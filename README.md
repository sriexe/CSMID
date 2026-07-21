# CSMID — Counter-Strike Market Intelligence Dataset

A local Python pipeline that collects CS2 skin price history from the
Steam Community Market and stores it in SQLite, as the foundation for
later feature engineering and an ML-based buy/sell recommendation
engine.

Right now this is a **data collection project**, not yet a prediction
engine. The immediate goal is to build up a clean historical price
dataset (multiple snapshots per skin over time); analytics and ML are
planned once there's enough history to make them meaningful.

---

## Project Structure

```text
CSMID/
│
├── src/
│   ├── main.py                # CLI entry point (collect, list)
│   ├── collection_manager.py  # Core collection logic: fetch, store, batch, resume
│   ├── scraper.py             # Steam Community Market client (shells out to curl)
│   ├── database.py            # SQLAlchemy models + SQLite connection (skins, market_history)
│   ├── config.py              # Paths: DB location, data dirs, default watchlist
│   └── diagnose_steam.py      # Standalone diagnostic script for probing Steam's rate limits
│
├── scheduler/
│   ├── daily_collect.py       # Long-running loop: runs collection on a schedule, backs off on 429s
│   ├── manager.py             # Prints the next queue batch (prototype, not yet wired to collection)
│   ├── collection_queue.py    # Slices the master catalog into fixed-size batches
│   ├── state.py                # Load/save queue_state.json
│   └── queue_state.json       # Persisted queue position (current_index, batch_size)
│
├── tools/
│   ├── import_master_catalog.py    # raw_catalog/*.json -> data/master/master_skins.csv
│   ├── generate_watchlists.py      # master_skins.csv -> per-category watchlist .txt files
│   ├── download_catalog.py         # Framework for pulling the raw skin catalog (source TBD)
│   └── test_manager.py             # Quick manual smoke test for CollectionManager
│
├── data/
│   ├── raw_catalog/           # Raw skin catalog JSON (source data for the importer)
│   ├── master/
│   │   └── master_skins.csv   # Deduplicated catalog: weapon, skin_name, market_hash_name, rarity, etc.
│   ├── watchlists/            # Generated: all_weapons.txt, rifles.txt, smgs.txt, pistols.txt, heavy.txt
│   │                          # (+ legacy manually-maintained watchlists: core.txt, cases.txt, knives.txt, gloves.txt)
│   ├── processed/             # Dataset exports for handoff (see tools/export_dataset.py)
│   ├── raw/                   # Reserved for raw scrape output
│   └── backups/               # Reserved for DB backups
│
├── tests/                     # pytest suite (scraper, database)
├── docs/
├── requirements.txt
├── csmid.db                   # SQLite database (created on first run, gitignored)
└── README.md
```

---

## Architecture

```text
Steam Community Market (priceoverview endpoint)
        │
        ▼
scraper.py            (curl subprocess — see "Why curl" below)
        │
        ▼
collection_manager.py (throttling, storage, resume, batch orchestration)
        │
        ▼
database.py            (SQLAlchemy → SQLite: skins, market_history)
        │
        ▼
tools/export_dataset.py  (flat CSV export for downstream analytics/ML)
```

The catalog side is a separate pipeline that feeds watchlists into the
collector above:

```text
data/raw_catalog/*.json
        │
        ▼
tools/import_master_catalog.py
        │
        ▼
data/master/master_skins.csv   (1157 unique weapon skins)
        │
        ▼
tools/generate_watchlists.py
        │
        ▼
data/watchlists/*.txt  →  used by `collect --watchlist NAME`
```

---

## Why curl instead of `requests`

The scraper shells out to the system `curl` binary rather than using
Python's `requests` library. This was confirmed empirically: `requests`
gets blocked (HTTP 429) by Steam's Akamai-fronted bot detection almost
immediately, while `curl` hitting the exact same URL from the same IP
at the same moment succeeds reliably. The leading explanation is
TLS/HTTP client fingerprinting rather than headers or IP reputation
(both were tested and ruled out first). See the module docstring in
`src/scraper.py` for details.

**This means `curl` must be available on PATH.** It ships by default
on Windows 10/11 and most Linux/macOS systems; check with
`curl --version`.

---

## Setup

Requires Python 3.11+ and `curl` on PATH.

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

No external accounts, API keys, or `.env` file are needed — this
project only talks to Steam's public, unauthenticated
`priceoverview` endpoint and stores everything locally in SQLite.

---

## Usage

**Collect prices for a specific category:**
```bash
python src/main.py collect --watchlist rifles
python src/main.py collect --watchlist smgs
python src/main.py collect --watchlist pistols
python src/main.py collect --watchlist heavy
python src/main.py collect --watchlist all_weapons
```

**Collect a single skin:**
```bash
python src/main.py collect --skin "AK-47 | Slate (Minimal Wear)"
```

**Resume after a rate-limit stop** (skips skins already collected
within the lookback window instead of re-fetching them):
```bash
python src/main.py collect --watchlist all_weapons --resume --since-hours 20
```

**View recently collected records:**
```bash
python src/main.py list --limit 20
python src/main.py list --skin "AK-47 | Slate (Minimal Wear)"
```

**Regenerate watchlists** after updating the master catalog:
```bash
python tools/generate_watchlists.py
```

---

## Automated / scheduled collection

`scheduler/daily_collect.py` runs collection in a long-lived local
loop (not GitHub Actions/cloud — this runs on your own machine):

```bash
python scheduler/daily_collect.py
```

It runs `collect --watchlist all_weapons --resume` once, then:
- if it finishes cleanly, sleeps ~24h before running again,
- if Steam returns a 429, backs off (starting at 90 minutes, doubling
  on consecutive rate limits, capped at 8h) before retrying — rather
  than retrying blindly, which was confirmed to extend the block
  rather than recover from it.

The `scheduler/collection_queue.py` + `manager.py` + `state.py` set is
a separate, earlier prototype for batch-based (rather than
watchlist-based) collection with persisted queue position — currently
not wired into the main collection path.

---

## Known constraints

- **Steam rate limits aggressively** for sustained, unauthenticated
  request sequences. There's no confirmed safe request volume or
  cooldown duration — `src/diagnose_steam.py` exists specifically to
  probe this empirically rather than relying on assumed numbers.
- **No price data currently informs the master catalog.** Every skin
  in `master_skins.csv` (all rarities, all price tiers) is collected
  equally — filtering happens by weapon type only, not by value.
- This runs **locally**, on-demand or via the scheduler script above.
  There is currently no cloud/CI automation.

---

## Roadmap

- [x] SQLite + SQLAlchemy storage
- [x] curl-based scraper (bypasses `requests` 429s)
- [x] Master catalog (1157 skins) + category watchlists
- [x] CLI collection with `--watchlist` / `--resume`
- [x] Rate-limit-aware backoff in the daily scheduler
- [ ] Finish wiring the queue-based batch prototype (or retire it in
      favor of the watchlist-based flow, once one approach proves out)
- [ ] Dataset export for handoff to collaborator (analytics/ML)
- [ ] Feature engineering (moving averages, RSI, volatility, etc.)
- [ ] ML models + buy/sell recommendation engine