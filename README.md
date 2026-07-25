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
        ├── SCRAPE PHASE (mode: "all", "scrape", or "all+predict")
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
        ├── ANALYTICS PHASE (mode: "all", "analytics", or "all+predict")
        │       │
        │       ▼
        │   calculate_market_metrics() — 14-day query, true 7-day SMA
        │       │
        │       ▼
        │   DIP/SPIKE signal detection
        │       │
        │       ▼
        │   send_push_notification() → ntfy.sh → phone
        │
        ├── PREDICTION PHASE (mode: "predict" or "all+predict")
        │       │
        │       ▼
        │   DatabaseManager.get_price_history()  (last 200 records per skin)
        │       │
        │       ▼
        │   PriceFeatureExtractor.extract_features()  → trend, volatility, momentum
        │       │
        │       ▼
        │   DATA SUFFICIENCY GATE (need ≥10 points across ≥5 days)
        │       │
        │       ├── FAIL → skin gated out, logged with reason
        │       │
        │       └── PASS → BaselineForecaster.forecast()
        │                       │
        │                       ▼
        │                   Blend: persistence + trend + mean-reversion
        │                       │
        │                       ▼
        │                   Confidence-scored forecast + ntfy summary
        │
        ├── NEURAL PREDICTION PHASE (mode: "predict" with --neural flag)
        │       │
        │       ▼
        │   NeuralForecasterWrapper — same .forecast() contract
        │       │
        │       ├── Checkpoint exists? → run neural model
        │       │       (SoftFocusGate → TCN → DilatedGRU → MultiHorizonHead)
        │       │
        │       └── No checkpoint? → fall back to BaselineForecaster
        │
        ├── NEURAL TRAINING PHASE (mode: "train", manual only)
        │       │
        │       ▼
        │   NeuralDataAdapter — Supabase records → tensors
        │       │
        │       ▼
        │   NeuralTrainer — walk-forward training with temperature annealing
        │       │
        │       ▼
        │   Checkpoint saved to data/models/neural_forecaster.pt
        │
        └── BACKTEST PHASE (mode: "backtest")
                │
                ▼
            WalkForwardBacktester — "predict the next point" repeatedly
                │
                ▼
            MAPE / RMSE / direction accuracy per skin + aggregate
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
│   └── pipeline.yml            # Twice-daily: scrape + analytics + forecast
│                               # Manual: discovery, neural training, backtest
│
├── src/
│   ├── main.py                  # Unified CLI entrypoint — run_pipeline()
│   ├── analytics.py              # Signal detection — calculate_market_metrics(), run_and_notify_analytics()
│   ├── scraper.py                # SteamMarketScraper — multi-tier proxy cascade, get_price()
│   ├── database.py               # DatabaseManager — psycopg2 client for Supabase
│   ├── env.py                    # Environment variable loading (.env locally, GitHub Secrets in cloud)
│   ├── notifier.py               # ntfy.sh push notification client
│   ├── volatility.py             # VolatilityManager — CV-based scrape interval tiers (HIGH/MEDIUM/LOW)
│   ├── forecaster.py             # Gated baseline forecaster — feature extraction + blend model
│   ├── neural_forecaster.py      # Neural TCN+DilatedGRU forecaster — full training pipeline
│   ├── backtest.py               # Walk-forward backtest framework — per-skin & aggregate metrics
│   ├── prediction_report.py      # Formatted text & Markdown reports for forecasts and backtests
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
│   ├── models/                    # Neural model checkpoints (neural_forecaster.pt)
│   ├── processed/ raw/ source/ backups/
│
├── docs/                          # Handover_V0.5.txt, Handover_V0.6.txt — project history
├── tests/                         # pytest suite (conftest, database, env, forecaster, backtest, prediction_report, neural_forecaster)
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

# Run forecasts (requires live DB connection)
python -m src.main --mode predict

# Run forecasts using the neural forecaster (falls back to baseline if no checkpoint)
python -m src.main --mode predict --neural

# Train the neural model on all historical data
python -m src.main --mode train

# Train with custom hyperparameters
python -m src.main --mode train --train-epochs 100 --train-lr 0.0005

# Run walk-forward backtest against all available history
python -m src.main --mode backtest

# Full pipeline + forecast in one shot
python -m src.main --mode all+predict

# Tune the forecast: require 20 points instead of 10, 24h horizon
python -m src.main --mode predict --min-data-points 20 --horizon-hours 24

# Backtest with a shorter warmup (for sparse data)
python -m src.main --mode backtest --backtest-warmup 5
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

**Manual workflow dispatch toggles:**

| Input | Type | Default | What it does |
|-------|------|---------|--------------|
| `run_discovery` | boolean | false | Runs skin discovery (also auto-runs Sundays) |
| `run_backtest` | boolean | false | Runs walk-forward backtest after forecast |
| `run_neural_training` | boolean | false | Installs PyTorch and trains the neural forecaster |
| `neural_epochs` | string | "" | Custom epoch count for neural training |
| `forecast_min_data_points` | string | "" | Override the minimum data points gate |
| `forecast_horizon_hours` | string | "" | Override the forecast horizon |

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

## Prediction pipeline — gated baseline forecaster

`src/forecaster.py` implements a transparent, interpretable forecasting
pipeline with a hard data-sufficiency gate:

**How it works:**

1. **Feature extraction** (`PriceFeatureExtractor`) — pulls trend slope,
   momentum, volatility (CV), volume trend, and time-series depth from
   each skin's price history.
2. **Data-sufficiency gate** — a skin must have ≥10 data points across
   ≥5 distinct days before any forecast is attempted. Skins below the
   threshold are logged and skipped (not guessed).
3. **Baseline blend model** (`BaselineForecaster`) — combines three
   interpretable components:
   - **Persistence** (30–40% weight): price stays where it is
   - **Trend extrapolation** (20–35% weight): linear slope from recent window
   - **Mean reversion** (35–40% weight): drift toward historical median
   - Blend weights shift based on volatility — stable items trust trend
     more, volatile items trust mean reversion more.
4. **Volume adjustment** — volume trend reinforces or dampens the
   direction signal.
5. **Confidence scoring** — based on data depth and volatility stability.

The model starts producing real forecasts automatically the moment each
skin crosses the data threshold — no rebuild needed.

**Walk-forward backtest** (`src/backtest.py`):

Repeatedly predicts the next data point using only history available at
that time, then compares to the actual observation. Reports MAPE,
median absolute error, RMSE, bias, and direction accuracy per skin and
in aggregate.

---

## Neural forecaster — TCN + DilatedGRU + Soft Focus

`src/neural_forecaster.py` implements an advanced time-series model that
extends the original college experiment architecture with production-grade
improvements. It's designed as a drop-in replacement for `BaselineForecaster`.

**Architecture:**

| Component | Role | Key improvement |
|-----------|------|-----------------|
| `SoftFocusGate` | Learns which timesteps matter | Hard binary mask → Gumbel-sigmoid (stable gradients) |
| `AdaptiveResidualBlock` | TCN residual block | Fixed dropout=0.5 → depth-adaptive (0.2–0.4) |
| `NeuralTCNEncoder` | Dilated causal convolutions | Configurable channels, receptive field = 15 |
| `DilatedGRUDecoder` | Skip-step GRU recurrence | Every-2nd-timestep processing for long-range |
| `TemporalPositionalEncoding` | Position + interval encoding | Handles irregular scrape intervals |
| `MultiHorizonHead` | Per-horizon predictions | Structured horizons [1h, 3h, 6h, 12h, 24h, 48h, 72h, 168h] with confidence |

**Integration:**

- `NeuralForecasterWrapper` exposes the same `.forecast(features)` contract as `BaselineForecaster`
- Falls back to baseline automatically when no checkpoint exists
- Data gate: requires ≥30 points (more conservative than baseline's 10)
- Training: `python -m src.main --mode train` pulls all history from Supabase

**When to use it:**
- Baseline model is the default — it works on sparse data
- Neural model becomes useful once skins have 60+ data points (~3 weeks)
- Run `--mode backtest` to compare neural vs baseline accuracy

**Dependencies:** PyTorch is optional — install with `pip install torch` when ready to train. The GitHub Actions workflow auto-installs it (CPU-only) when `run_neural_training` is toggled on.

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
- [x] Anomaly filtering in `src/analytics.py` — guard signals against noise
- [x] Restore scheduled skin discovery (or fold it into `pipeline.yml`)
- [x] Fix or retire the local scheduler path (`collection_manager.py`
      / `scheduler/`) — currently broken and unmaintained
- [x] Volatility-aware scraping (frequent for volatile items, sparse for stable ones)
- [x] Gated prediction pipeline with walk-forward backtest framework
      (baseline model, data-sufficiency gate, feature extraction)
- [x] Neural forecaster — TCN + DilatedGRU + Soft Focus (drop-in replacement)
- [x] Database RPCs (read-only Supabase SQL functions) for the
      friend's frontend — build when he's ready to start
- [ ] Buy/sell signal notifications incorporating patch-note/news events
- [ ] ~~Advanced model upgrade path (e.g., ARIMA, Prophet)~~ — replaced by neural forecaster

**Optional, no dependency — build anytime:**
- [ ] Portfolio P&L tracking (new, independent `user_inventory` table)

**Deliberately deferred — phase 3+:**
- [ ] Multi-marketplace arbitrage (CSFloat/Skinport, etc.)
