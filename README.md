# CSMID — CS2 Market Intelligence Engine

An automated system that tracks Counter-Strike 2 skin prices from the
Steam Community Market, stores them in Supabase (Postgres), detects
buy/sell signals, and pushes alerts to your phone via ntfy.

**Status:** Active data collection, running unattended on a twice-daily
GitHub Actions schedule.

---

## Architecture

Everything now runs through one unified entrypoint:

```text
.github/workflows/pipeline.yml   (cron: 00:00 & 12:00 UTC, or manual dispatch)
        │
        ▼
python -m src.main   →   run_pipeline(mode, limit, dry_run, ignore_cache)
        │
        ├── SCRAPE PHASE (mode: "all" or "scrape")
        │       │
        │       ▼
        │   DatabaseManager.get_active_targets()  (tracked_items table)
        │       │
        │       ▼
        │   SteamMarketScraper.get_price()
        │       │
        │       ▼
        │   Multi-tier proxy cascade:
        │   ScrapingAnt → ScraperAPI → ZenRows → ScrapingBee → direct
        │       │
        │       ▼
        │   DatabaseManager.insert_price()  →  market_history table
        │
        └── ANALYTICS PHASE (mode: "all" or "analytics")
                │
                ▼
            calculate_market_metrics() — 14-day query, true 7-day SMA
                │
                ▼
            DIP/SPIKE signal detection
                │
                ▼
            send_push_notification() → ntfy.sh → phone
```

A separate, older local path (`scheduler/daily_collect.py` →
`src/collection_manager.py`) still exists in the repo but is **not
currently functional** — see Known Issues.

Skin discovery (finding new items to track) is handled by
`run_discovery.py` + `discoverer.py`, but is currently **manual-only**
— see Known Issues.

---

## Repository Structure

```text
CSMID/
│
├── .github/workflows/
│   └── pipeline.yml            # Twice-daily: scrape + analytics, unified
│
├── src/
│   ├── main.py                  # Unified CLI entrypoint — run_pipeline()
│   ├── analytics.py              # Signal detection — calculate_market_metrics(), run_and_notify_analytics()
│   ├── scraper.py                # SteamMarketScraper — multi-tier proxy cascade, get_price()
│   ├── database.py               # DatabaseManager — psycopg2 client for Supabase
│   ├── env.py                    # Environment variable loading (.env locally, GitHub Secrets in cloud)
│   ├── notifier.py               # ntfy.sh push notification client
│   ├── proxy_manager.py          # Local HTTP proxy pool manager (currently unused by scraper.py)
│   ├── collection_manager.py     # Local queue-driven collector — currently broken, see Known Issues
│   ├── config.py                 # Legacy local paths (pre-cloud tooling)
│   └── diagnose_steam.py         # Standalone script for empirically testing safe request spacing
│
├── discoverer.py                 # SteamMarketDiscoverer — pages Steam's market search via ScrapingAnt
├── run_discovery.py              # Discovery entrypoint — manual only, see Known Issues
├── init_supabase.py              # One-off: initializes Supabase tables
├── migrate_to_supabase.py        # One-off: migrates data into Supabase
├── purge_nulls.py                # Maintenance: cleans null/invalid rows
├── update_proxies.py             # Maintenance: refreshes proxies.txt / _proxies.txt
│
├── scheduler/                    # Older local collection path — not currently wired to a working scraper call
│   ├── daily_collect.py
│   ├── collection_queue.py
│   ├── manager.py
│   └── state.py
│
├── tools/                        # Catalog-building pipeline (feeds watchlists)
│   ├── import_master_catalog.py  # data/raw_catalog/*.json → data/master/master_skins.csv
│   ├── generate_watchlists.py    # master_skins.csv → per-category watchlist .txt files
│   ├── download_catalog.py
│   └── test_manager.py
│
├── generate_watchlist.py         # Root-level variant: adds wear-condition suffixes
│
├── data/
│   ├── raw_catalog/              # Raw skin catalog JSON
│   ├── master/master_skins.csv   # Deduplicated catalog: weapon, skin_name, rarity, etc.
│   ├── watchlists/                # Generated category watchlists
│   ├── processed/ raw/ source/ backups/
│
├── docs/                          # Handover_V0.5.txt, Handover_V0.6.txt — project history
├── tests/                         # pytest suite (conftest, database, env)
├── .env.example                   # Template for local environment variables
├── requirements.txt
└── README.md
```

---

## Environment Variables

Set locally via `.env` (see `.env.example`) and as **GitHub repository
secrets** (`Settings → Secrets and variables → Actions`) for the cloud
pipeline:

| Variable | Required | Purpose |
|---|---|---|
| `SUPABASE_URL` | Yes | Supabase project REST API URL |
| `SUPABASE_KEY` | Yes | Supabase anon/public key |
| `SUPABASE_DB_URL` | Yes | Direct Postgres connection string |
| `NTFY_TOPIC` | Yes | Your ntfy.sh topic name |
| `NTFY_SERVER` | No | Custom ntfy server (defaults to `https://ntfy.sh`) |
| `SCRAPINGANT_API_KEY` | No | Tier 1 proxy provider |
| `SCRAPERAPI_KEY` | No | Tier 2 proxy provider (fallback) |
| `ZENROWS_API_KEY` | No | Tier 3 proxy provider (fallback) |
| `SCRAPINGBEE_API_KEY` | No | Tier 4 proxy provider (fallback) |

The scraper tries providers in order and falls through to the next
(then to a direct request) if one is missing or fails. `src/database.py`
and `src/env.py` fail loudly (raise, rather than silently falling back
to a default) if `SUPABASE_DB_URL` isn't set.

---

## Setup

```bash
git clone https://github.com/sriexe/CSMID.git
cd CSMID

python -m venv .venv
# Windows
.venv\Scripts\activate
# Mac/Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # then fill in your real values
```

---

## Running locally

The unified CLI supports flags built specifically for local testing
without spending API credits or needing full credentials:

```bash
# Fast dry-run on 2 sample items, no DB writes, no ntfy alerts
python -m src.main --dry-run --limit 2

# Full run: scrape every tracked item, then run analytics
python -m src.main

# Analytics only, against existing data
python -m src.main --mode analytics

# Force a fresh scrape, bypassing the 12h recency check
python -m src.main --mode scrape --limit 1 --ignore-cache
```

**Discover new skins** (not currently scheduled — run manually):
```bash
python run_discovery.py
```

**Rebuild the master catalog / watchlists**, if the raw catalog changes:
```bash
python tools/import_master_catalog.py
python tools/generate_watchlists.py
```

---

## Cloud automation

`pipeline.yml` runs `python -m src.main` (default `mode="all"`) twice
daily — 00:00 and 12:00 UTC — scraping every active `tracked_items` row
and running analytics/alerts immediately after, in one job. Trigger it
manually anytime from the Actions tab (`workflow_dispatch`).

---

## Analytics engine — signal detection

`src/analytics.py` scans the last 14 days of `market_history` per skin
and flags two signal types:

- **DIP** (potential buy) — price dropped ≥8% in the last 24h, **or**
  sits ≥10% below its trailing **7-day** simple moving average
  (correctly windowed to 7 days, not the full 14-day query range).
- **SPIKE** (potential sell) — price rose ≥10% in the last 24h, **or**
  sits ≥12% above its trailing 7-day SMA.

Column names (`skin_name`/`market_hash_name`, `lowest_price`/
`median_price`/etc.) are auto-detected from whatever's actually in the
table. Flagged skins are pushed to your phone via ntfy.

---

## Known issues / current limitations

- **Skin discovery is no longer scheduled.** `discovery.yml` was
  removed; `run_discovery.py` still works but must be run manually, or
  `tracked_items` will never pick up newly popular skins on its own.
- **The local scheduler path is broken.** `src/collection_manager.py`
  calls `self.scraper.fetch_price(skin_name)`, but `SteamMarketScraper`
  only defines `get_price(appid, market_hash_name)` — no `fetch_price`
  method exists. `scheduler/daily_collect.py` will fail immediately if
  run. The cloud pipeline (`pipeline.yml` → `src/main.py`) is the
  actively maintained path; this local path hasn't been updated to
  match and is effectively dead code right now.
- **Old commits still contain the original hardcoded credentials**
  in git history (the strings themselves, not live in any current
  file). Both the Supabase DB password and the ScrapingAnt key have
  since been rotated, so the historical exposure no longer grants
  access to anything live — but the strings remain visible to anyone
  browsing old commits on GitHub.
- `src/proxy_manager.py` and `proxies.txt`/`_proxies.txt` are loaded
  but not currently used by `scraper.py` — the proxy providers above
  handle proxying instead.
- `tools/generate_watchlists.py` and the root-level
  `generate_watchlist.py` overlap in purpose and aren't consolidated.
- `data/master/master_skins.csv` has no price data, so "all skins" and
  "cheap skins" are the same set — filtering is by weapon type only.

---

## Roadmap

- [x] Skin discovery via Steam Market search (ScrapingAnt-routed)
- [x] Scheduled price collection → Supabase
- [x] Push notifications on discovery/analytics runs
- [x] Cloud automation via GitHub Actions
- [x] Analytics engine — DIP/SPIKE signal detection (24h % change + true 7-day SMA)
- [x] Unified `src/main.py` CLI with `--mode`/`--limit`/`--dry-run`/`--ignore-cache`
- [x] Multi-tier proxy fallback chain
- [x] Secrets moved to environment variables / GitHub Secrets
- [x] Immediate abort on HTTP 429 (no more retry-into-block)

**Next up:**
- [ ] Anomaly filtering in `src/analytics.py` — guard signals against
      single bad data points before relying on them further
- [ ] Restore scheduled skin discovery (or fold it into `pipeline.yml`)
- [ ] Fix or retire the local scheduler path (`collection_manager.py`
      / `scheduler/`) — currently broken and unmaintained
- [ ] Database RPCs (read-only Supabase SQL functions) for the
      friend's frontend — build when he's ready to start
- [ ] Volatility-aware scraping (frequent for volatile items, sparse for stable ones)
- [ ] Buy/sell signal notifications incorporating patch-note/news events

**Optional, no dependency — build anytime:**
- [ ] Portfolio P&L tracking (new, independent `user_inventory` table)

**Deliberately deferred — phase 3+:**
- [ ] Multi-marketplace arbitrage (CSFloat/Skinport, etc.)