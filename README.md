# CSMID — CS2 Market Intelligence Dataset

An automated system that tracks Counter-Strike 2 skin prices from the
Steam Community Market over time, storing them in a cloud Postgres
database (Supabase) for later feature engineering and ML-driven
buy/sell analysis.

**Status:** Active data collection. The system discovers and prices
skins on a schedule; analytics/ML are a later phase once enough price
history has accumulated (see Roadmap).

---

## How data actually moves through this project

There are currently **two separate collection paths** in this repo —
worth understanding both since they don't share the same code:

### Path A — Cloud (GitHub Actions, unattended)
```text
.github/workflows/discovery.yml  (weekly, Sun 00:00 UTC)
        │
        ▼
run_discovery.py → discoverer.py → ScrapingAnt → Steam Market search
        │
        ▼
DatabaseManager.insert_tracked_item()  →  tracked_items table (Supabase)
        │
        │   (separately, every 6h)
        ▼
.github/workflows/scraper.yaml
        │
        ▼
src/main.py → src/scraper.py → ScrapingAnt → Steam priceoverview
        │
        ▼
DatabaseManager.insert_price()  →  market_history table (Supabase)
        │
        ▼
src/notifier.py → ntfy.sh → phone push notification

        (run manually, not yet on the cron above)
        ▼
src/analytics.py  →  calculate_market_metrics()
        │
        ▼
DIP/SPIKE signal detection (24h % change + 7-day SMA deviation)
        │
        ▼
src/notifier.py → ntfy.sh → phone push notification
```

### Path B — Local (manual / long-running on your machine)
```text
scheduler/daily_collect.py  (while True loop, backs off on 429)
        │
        ▼
src/collection_manager.py → collect_queue() → collect_skin()
        │
        ▼
src/scraper.py.fetch_price()   ← NOTE: different method than Path A calls
        │
        ▼
DatabaseManager  →  Supabase
```

**These two paths call the scraper differently** — Path A's
`src/main.py` calls `scraper.get_price(appid=..., market_hash_name=...)`,
while Path B's `collection_manager.py` calls `scraper.fetch_price(skin_name)`.
Only `get_price()` currently exists on `SteamMarketScraper`, so Path B
will fail at that call until reconciled. Documented here as-is per
current code; not something this README fixes.

---

## Repository Structure

```text
CSMID/
│
├── .github/workflows/
│   ├── discovery.yml          # Weekly: runs run_discovery.py (cron: 0 0 * * 0)
│   └── scraper.yaml           # Every 6h: runs `python -m src.main` (cron: 0 */6 * * *)
│
├── src/
│   ├── main.py                 # Cloud price-scraper entrypoint (Path A) — loops tracked_items
│   ├── analytics.py            # Signal detection: 24h % change + true 7-day SMA deviation → DIP/SPIKE alerts
│   ├── collection_manager.py   # Local queue-driven collector (Path B) — batching, resume, backoff signal
│   ├── scraper.py              # Steam priceoverview client, routed through ScrapingAnt (residential proxy)
│   ├── database.py             # DatabaseManager — psycopg2 client for Supabase (market_history, tracked_items)
│   ├── proxy_manager.py        # Local HTTP proxy pool manager (loaded but not currently used by scraper.py)
│   ├── notifier.py             # ntfy.sh push notification client
│   ├── config.py               # Local paths (legacy — used by the original SQLite-era tooling below)
│   └── diagnose_steam.py       # Standalone script for empirically testing safe request spacing against Steam
│
├── discoverer.py                # SteamMarketDiscoverer — pages Steam's market search via ScrapingAnt
├── run_discovery.py             # Path A entrypoint: discovers skins, adds to tracked_items, sends notification
├── init_supabase.py             # One-off: initializes Supabase tables
├── migrate_to_supabase.py       # One-off: migrates data into Supabase
├── purge_nulls.py               # Maintenance: cleans null/invalid rows
├── update_proxies.py            # Maintenance: refreshes proxies.txt / _proxies.txt
├── proxies.txt / _proxies.txt   # Local proxy pool lists (used by proxy_manager.py, currently unused by scraper.py)
│
├── scheduler/                   # Path B — local long-running collector
│   ├── daily_collect.py         # Main loop: calls collection_manager, backs off 90min on rate limit
│   ├── collection_queue.py      # Slices master catalog into fixed-size batches (earlier prototype)
│   ├── manager.py               # Prints next queue batch (earlier prototype, not wired to Path B directly)
│   └── state.py                 # Load/save queue_state.json
│
├── tools/                       # Catalog-building pipeline (feeds watchlists, used by both paths' watchlist files)
│   ├── import_master_catalog.py # data/raw_catalog/*.json → data/master/master_skins.csv
│   ├── generate_watchlists.py   # master_skins.csv → per-category watchlist .txt files
│   ├── download_catalog.py      # Framework for pulling the raw skin catalog (source TBD)
│   └── test_manager.py          # Manual smoke test for CollectionManager
│
├── generate_watchlist.py        # Root-level variant: adds wear-condition suffixes → all_weapons_with_wears.txt
│
├── data/
│   ├── raw_catalog/             # Raw skin catalog JSON (source for the importer)
│   ├── master/master_skins.csv  # Deduplicated catalog: weapon, skin_name, market_hash_name, rarity, etc.
│   ├── watchlists/               # all_weapons.txt, all_weapons_with_wears.txt, rifles.txt, smgs.txt,
│   │                              # pistols.txt, heavy.txt, cases.txt, knives.txt, gloves.txt, core.txt
│   ├── processed/                # Dataset exports
│   ├── raw/                      # Reserved for raw scrape output
│   ├── source/                   # skins_source.csv
│   └── backups/
│
├── docs/                        # Handover_V0.5.txt, Handover_V0.6.txt — project history/context notes
├── tests/                       # pytest suite
├── requirements.txt
└── README.md
```

---

## Why ScrapingAnt instead of a direct request

Steam's Community Market blocks sustained unauthenticated request
sequences (HTTP 429), which was confirmed through direct testing
(`src/diagnose_steam.py`). This project's earlier local-only version
worked around it using the system `curl` binary (a TLS-fingerprinting
workaround); the current cloud version instead routes every request
through **ScrapingAnt**, using its residential proxy pool and a
`Referer` header that mimics arriving from Steam's own market page.

---

## Prerequisites

- Python 3.11+
- A [Supabase](https://supabase.com) project (free tier Postgres database)
- A [ScrapingAnt](https://scrapingant.com) API key
- The [ntfy](https://ntfy.sh) app (iOS/Android) with a topic name of your choosing, for push notifications

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
```

> `requirements.txt` currently lists `requests` twice (an older entry
> plus a newer block) alongside `beautifulsoup4`, `pytest`,
> `psycopg2-binary`, and `pandas` (needed by `src/analytics.py`).
> Functional as-is, just not deduplicated.

### Environment variables

Set these locally (e.g. in a `.env` file, or exported in your shell)
and as **GitHub repository secrets** (`Settings → Secrets and
variables → Actions`) for the cloud workflows:

| Variable | Purpose |
|---|---|
| `SUPABASE_DB_URL` | Postgres connection string for `market_history` / `tracked_items` |
| `NTFY_TOPIC` | Your private ntfy.sh topic name, for push notifications |

`SCRAPINGANT_API_KEY` — currently hardcoded directly in `src/scraper.py`
and `discoverer.py` rather than read from an environment variable.
Documented here as-is; planned to move to a secret later.

---

## Running locally

**Discover new skins and add them to tracking:**
```bash
python run_discovery.py
```

**Update prices for everything currently tracked (one pass):**
```bash
python -m src.main
```

**Run the local long-lived scheduler** (Path B — loops indefinitely,
processes the watchlist in batches, backs off 90+ minutes on a 429):
```bash
python scheduler/daily_collect.py
```

**Rebuild the master catalog / watchlists**, if the raw catalog changes:
```bash
python tools/import_master_catalog.py
python tools/generate_watchlists.py
```

---

## Cloud automation (GitHub Actions)

Once `SUPABASE_DB_URL` and `NTFY_TOPIC` are added as repository
secrets, two workflows run unattended:

- **`discovery.yml`** — every Sunday at 00:00 UTC, scans up to 500
  popular market items and adds any newly seen skins to `tracked_items`,
  then sends a push-notification summary.
- **`scraper.yaml`** — every 6 hours, fetches current prices for every
  active row in `tracked_items` and appends them to `market_history`,
  skipping any skin already scraped in the last 12 hours.

---

## Analytics engine — signal detection

`src/analytics.py` scans the last 14 days of `market_history` per skin
and flags two signal types:

- **DIP** (potential buy) — price dropped ≥8% in the last 24h, **or**
  sits ≥10% below its trailing 7-day simple moving average.
- **SPIKE** (potential sell) — price rose ≥10% in the last 24h, **or**
  sits ≥12% above its trailing 7-day SMA.

Column names (`skin_name`/`market_hash_name`, `lowest_price`/
`median_price`/etc.) are auto-detected from whatever's actually in the
table, so it tolerates schema changes without code edits. Flagged
skins are pushed to your phone via `ntfy`, top 5 summarized per run.

Run it manually:
```bash
python -m src.analytics
```

**Not yet on a schedule** — `scraper.yaml` only runs the price
collector (`src/main.py`) every 6 hours; analytics isn't chained after
it yet. Wiring that in is the natural next step once you're ready.

---

Documented for transparency, not addressed by this README:

- **Rate-limit handling in `src/scraper.py` retries on HTTP 429**
  instead of aborting immediately — repeated hits to an active block
  have empirically been shown (locally, via `diagnose_steam.py`-style
  testing) to extend rather than resolve it.
- **Two independent collection paths** (cloud vs. local scheduler) use
  different scraper method signatures (`get_price` vs `fetch_price`);
  only `get_price` currently exists.
- **`SUPABASE_DB_URL` and the ScrapingAnt API key have hardcoded
  fallback/default values** in source (`src/database.py`,
  `discoverer.py`, `src/scraper.py`). Planned to move to
  environment-variable-only once the current 3-month data collection
  run is complete.
- `src/proxy_manager.py` and `proxies.txt`/`_proxies.txt` are loaded
  but not currently used for actual requests (ScrapingAnt handles
  proxying instead).
- `tools/generate_watchlists.py` and the root-level
  `generate_watchlist.py` overlap in purpose (category watchlists vs.
  wear-condition watchlists) and aren't yet consolidated.
- `data/master/master_skins.csv` has no price data, so "all skins" and
  "cheap skins" are the same set today — filtering is by weapon type
  only, not value or rarity.

---

## Roadmap

- [x] Skin discovery via Steam Market search (ScrapingAnt-routed)
- [x] Scheduled price collection → Supabase
- [x] Push notifications on discovery runs
- [x] Cloud automation via GitHub Actions (no always-on PC required)
- [x] Analytics engine — DIP/SPIKE signal detection (24h % change + 7-day SMA)
- [ ] Wire `src/analytics.py` into the scraper cron (currently manual-only)
- [ ] Reconcile the two collection paths into one
- [ ] Move all secrets to environment-variable-only
- [ ] Volatility-aware scraping (frequent for volatile items, sparse for stable ones)
- [ ] Buy/sell signal notifications beyond DIP/SPIKE (e.g. incorporating patch-note/news events)