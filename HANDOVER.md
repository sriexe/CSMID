# CSMID — Prediction Pipeline Handover Document

**Project:** CSMID (Counter-Strike 2 Market Intelligence Engine)
**Date:** July 25, 2026
**Status:** Prediction pipeline built, tested, deployed, and wired into CI/CD

---

## 1. What Was Built

A **gated prediction pipeline** that runs on top of the existing scrape + analytics pipeline. It was designed with an explicit data-sufficiency gate so that no skin gets a forecast until it has accumulated enough real price history to produce something meaningful.

### Three New Source Modules

| File | Lines | Purpose |
|------|-------|---------|
| `src/forecaster.py` | ~380 | Feature extraction, data gate, and baseline blend model |
| `src/backtest.py` | ~235 | Walk-forward validation framework |
| `src/prediction_report.py` | ~310 | Text, Markdown, and ntfy report formatters |

### Updated Files

| File | Change |
|------|--------|
| `src/main.py` | Added `--mode predict`, `--mode backtest`, `--mode all+predict`, plus CLI flags |
| `.github/workflows/pipeline.yml` | Added forecast step (runs after every scrape cycle) + optional backtest toggle |
| `README.md` | Updated architecture, running commands, prediction section, roadmap |
| `tests/test_forecaster.py` | 20 unit tests |
| `tests/test_backtest.py` | 10 unit tests |
| `tests/test_prediction_report.py` | 12 unit tests |

---

## 2. Architecture: How Prediction Fits In

```
┌─────────────────────────────────────────────────────────────────┐
│                    GITHUB ACTIONS (2x daily)                     │
│                                                                 │
│  1. Skin Discovery (Sundays / manual toggle)                     │
│         ↓                                                       │
│  2. Scrape (volatility-aware, tiered intervals)                  │
│         ↓                                                       │
│  3. Analytics (anomaly detection, DIP/SPIKE signals, ntfy)       │
│         ↓                                                       │
│  4. FORECAST  ← NEW: runs after every scrape + analytics cycle   │
│         ↓                                                       │
│  5. BACKTEST (manual toggle only, via workflow_dispatch)         │
└─────────────────────────────────────────────────────────────────┘
```

The prediction phase:
1. Pulls all price history for active tracked skins from Supabase
2. Extracts features (trend, momentum, volatility, volume)
3. Runs each skin through the **data-sufficiency gate** (10 points / 5 days)
4. For skins that pass, produces a blended forecast (persistence + trend + mean reversion)
5. Formats results and pushes actionable signals to **ntfy**

---

## 3. The Forecaster — Design Decisions

### Data-Sufficiency Gate

The model **refuses to forecast** any skin that doesn't meet the minimum threshold. This is the single most important design decision — it prevents the pipeline from producing confident-sounding garbage on 3-4 data points.

| Parameter | Default | Rationale |
|-----------|---------|-----------|
| `MIN_DATA_POINTS` | 10 | Need enough points for a meaningful trend line |
| `MIN_DISTINCT_DAYS` | 5 | Prevents clustering bias (e.g., 10 points all on 2 days) |
| `HORIZON_HOURS` | 12 | Matches the default scrape interval |

### The Model: Why Not ML?

The baseline is a **weighted blend of three interpretable components:**

| Component | Weight Range | What It Does |
|-----------|-------------|--------------|
| **Persistence** | 30–40% | "Price stays the same" — the safest bet |
| **Trend** | 20–35% | Linear extrapolation from the last 5 points |
| **Mean Reversion** | 35–40% | Drifts toward the historical median |

Weights are **volatility-adaptive**: high CV (volatile skins) shifts weight toward mean reversion; low CV (stable skins) trusts the trend more.

### Feature Extraction

From each skin's price history, the pipeline extracts:

| Feature | Method |
|---------|--------|
| `current_price` | Last observed `lowest_price` (falls back to `median_price`) |
| `mean_price`, `median_price`, `std_price` | Standard statistics |
| `cv` | Coefficient of variation (std / mean) — drives weight blending |
| `slope` | Linear regression over the last `TREND_WINDOW` (5) points |
| `momentum` | % change over last 3 observations |
| `volume_trend` | Linear slope of volume over recent window |
| `avg_interval_hours` | Time between observations (used to scale trend to horizon) |

### Confidence Scoring

```
confidence = 0.3 * depth_score + 0.4 * stability_score + 0.3 * 0.5

depth_score     = min(n_points / 30.0, 1.0)    # Max at 30 data points
stability_score = 1.0 - min(cv / 0.2, 1.0)     # Lower CV = higher confidence
```

Range: 0.15 (worst) to 1.0 (best). Scales gracefully as data accumulates.

### Swappable Model Interface

The `BaselineForecaster` class exposes a clean `.forecast(features) -> dict` interface. When you want to swap in ARIMA, Prophet, or an LSTM, you replace the class — everything else (feature extraction, gating, reporting, CLI, CI/CD) stays the same.

---

## 4. The Backtest Framework

### Walk-Forward Validation

This is the gold standard for time-series evaluation. For each skin:

```
For t in [warmup, ..., len(data) - 1]:
    features = extract(data[:t])       # only past data — no peeking
    prediction = forecaster.forecast(features)
    actual = data[t]["price"]          # the held-out truth
    record(prediction, actual)
```

### Metrics Reported

| Metric | Description |
|--------|-------------|
| **MAPE** | Mean Absolute Percentage Error |
| **Median Absolute Error** | More robust than mean for skewed errors |
| **RMSE** | Root Mean Square Error (penalizes large outliers) |
| **Direction Accuracy** | % of time the predicted direction matches reality |
| **Bias** | Mean signed error — positive = systematic over-prediction |

### Output

- Console report (human-readable text)
- Markdown report saved to `data/backtest_report.md`
- ntfy summary for actionable signals only (±2% threshold)

---

## 5. How to Run It

### CLI Commands

```bash
# Forecast only (pulls current Supabase data, runs forecaster)
python -m src.main --mode predict

# Forecast with custom parameters
python -m src.main --mode predict --min-data-points 15 --horizon-hours 24

# Walk-forward backtest
python -m src.main --mode backtest

# Backtest with custom warmup
python -m src.main --mode backtest --backtest-warmup 15

# Full pipeline + forecast in one shot
python -m src.main --mode all+predict

# Dry run (no DB, no ntfy)
python -m src.main --mode predict --dry-run

# Limit to first N skins (fast local testing)
python -m src.main --mode predict --limit 5
```

### GitHub Actions (CI/CD)

The workflow now has **4 manual inputs** on the Actions tab:

| Input | Type | Default | Effect |
|-------|------|---------|--------|
| `run_discovery` | boolean | false | Trigger skin discovery |
| `run_backtest` | boolean | false | Run walk-forward backtest after forecast |
| `forecast_min_data_points` | string | (empty = use default 10) | Override the data gate threshold |
| `forecast_horizon_hours` | string | (empty = use default 12) | Override the forecast horizon |

The **forecast step runs automatically** after every scheduled scrape + analytics cycle (00:00 and 12:00 UTC). The backtest step is **manual only** — toggle it from the Actions tab when you want to validate model quality.

---

## 6. Notifications

Forecasts that show **meaningful predicted moves** (≥2% change) are pushed to your ntfy topic:

```
UP Kilowatt Case: $0.3500 -> $0.3850 (+10.0%, conf=0.42)
DOWN Recoil Case: $0.8200 -> $0.7800 (-4.9%, conf=0.55)

3 forecasted | 47 gated out
```

Skins that are still below the data gate are **not** included in the ntfy alert — they're just logged locally. This keeps your phone quiet until there's something worth looking at.

---

## 7. Current State of the Data

| Metric | Value |
|--------|-------|
| Total price history rows | ~800 |
| Unique skins with history | 324 |
| Date range | July 16 – July 25 (9 days) |
| Most-covered skin | 7 data points |
| Skins above forecast gate | 0 (none have 10+ points / 5+ days yet) |

This is expected and correct. The pipeline is **ready** — it just needs time to accumulate data. Each scrape cycle adds 50 new observations (one per tracked skin). Within **5–7 days**, the most-active skins will cross the gate and start producing real forecasts automatically.

---

## 8. What's Next (Suggested Order)

| Priority | Task | Notes |
|----------|------|-------|
| 1 | **Wait for data to accumulate** | ~5-7 days until first real forecasts appear |
| 2 | **Tune the model** | Once you have 30+ points per skin, validate against backtest results and adjust weights |
| 3 | **Lower the gate** | If 10 points / 5 days proves too conservative, reduce to 8 / 4 |
| 4 | **Add a better model** | Swap `BaselineForecaster` for Prophet or ARIMA — same interface, zero pipeline changes |
| 5 | **Portfolio P&L tracking** | Track hypothetical buy/sell positions based on forecast signals |
| 6 | **Multi-marketplace arbitrage** | Add CSFloat / Skinport as additional data sources |
| 7 | **Event-aware signals** | Incorporate patch notes, major announcements, or case drop changes into the forecast |

---

## 9. Key Files Reference

```
csmid/
├── src/
│   ├── main.py              # Unified CLI — all modes (scrape, analytics, predict, backtest)
│   ├── forecaster.py        # Feature extraction + gated baseline model
│   ├── backtest.py          # Walk-forward validation framework
│   ├── prediction_report.py # Text, Markdown, and ntfy report formatters
│   ├── scraper.py           # Steam Market scraping (existing)
│   ├── database.py          # Supabase read/write (existing)
│   ├── analytics.py         # Anomaly detection + DIP/SPIKE signals (existing)
│   ├── volatility.py        # CV-based tier classification (existing)
│   ├── config.py            # Configuration constants (existing)
│   ├── env.py               # Environment variable loading (existing)
│   └── notifier.py          # ntfy push notifications (existing)
├── tests/
│   ├── test_forecaster.py   # 20 tests — features, gating, model, edge cases
│   ├── test_backtest.py     # 10 tests — walk-forward, aggregation, insufficient data
│   └── test_prediction_report.py  # 12 tests — text, ntfy, markdown formatting
├── .github/workflows/
│   └── pipeline.yml         # CI/CD — scrape → analytics → forecast (+ optional backtest)
├── data/
│   └── backtest_report.md   # Generated by --mode backtest
├── requirements.txt
└── README.md
```

---

## 10. Dependencies

**No new Python packages were added.** The prediction pipeline uses only:

- `numpy` (already in requirements.txt)
- `pandas` (already in requirements.txt)
- Python stdlib (`logging`, `datetime`, `typing`, `argparse`)

---

## 11. Test Results

```
tests/test_forecaster.py         20 passed
tests/test_backtest.py           10 passed
tests/test_prediction_report.py  12 passed
────────────────────────────────────────
Total: 42 passed, 0 failed
```

---

## 12. Design Principles

1. **Honest over impressive.** The gate ensures we never forecast from noise. Better to say "not enough data" than to produce a confident wrong number.
2. **Interpretable over black-box.** Every component of the blend model is explainable. Weights shift based on observable volatility, not learned parameters.
3. **Swappable, not fragile.** The forecaster is a class with a contract (`.forecast(features)`). Replacing it requires zero changes to the pipeline, CLI, reports, or CI/CD.
4. **Automatic, not manual.** Forecasts run on every scrape cycle. Skins cross the gate automatically as data accumulates. No human intervention needed.
5. **Quiet until useful.** ntfy alerts only fire when there's a meaningful predicted move (≥2%). Your phone stays silent when nothing is worth acting on.
