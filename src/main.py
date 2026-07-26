import os
import sys
import time
import logging
import argparse
from typing import Optional
import numpy as np

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scraper import SteamMarketScraper
from src.database import DatabaseManager
from src.analytics import run_and_notify_analytics
from src.env import SUPABASE_URL, SUPABASE_KEY
from src.volatility import get_scrape_interval_for_item

# Prediction pipeline imports
from src.forecaster import ForecastConfig, generate_forecasts
from src.backtest import run_backtest, WalkForwardBacktester
from src.prediction_report import (
    format_forecast_report,
    format_forecast_summary_ntfy,
    format_backtest_report,
    format_forecast_markdown,
    format_backtest_markdown,
)

# Neural forecaster imports (optional — requires torch)
try:
    from src.neural_forecaster import (
        NeuralForecasterWrapper,
        train_neural_model,
        NeuralDataAdapter,
        INPUT_DIM as NEURAL_INPUT_DIM,
    )
    HAS_NEURAL = True
except ImportError:
    HAS_NEURAL = False

# Optional import for Discovery Phase
try:
    from run_discovery import run_discovery
except ImportError:
    run_discovery = None

try:
    from supabase import create_client
except ImportError:  # pragma: no cover - optional dependency in some environments
    create_client = None

supabase = None
if create_client and SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CSMID.main")

# Default items used for local dry-run testing if no DB is connected
SAMPLE_TARGETS = [
    "Recoil Case",
    "Revolution Case",
    "Dreams & Nightmares Case"
]


def run_pipeline(
    mode: str = "all",
    limit: Optional[int] = None,
    dry_run: bool = False,
    ignore_cache: bool = False,
    forecast_config: Optional[ForecastConfig] = None,
    backtest_warmup: int = 10,
    output_format: str = "text",
    use_neural: bool = False,
    train_epochs: int = 50,
    train_lr: float = 1e-3,
) -> None:
    """
    Unified CLI pipeline runner with Volatility-Aware Scraping and Prediction.

    :param mode: 'all' (scrape + analytics), 'scrape' (only scrape),
                 'analytics' (only analytics), 'discovery' (only discovery),
                 'predict' (forecast from current data),
                 'backtest' (walk-forward backtest),
                 'train' (train neural model on all historical data),
                 'all+predict' (scrape + analytics + forecast)
    :param limit: Max number of items to process (great for local testing)
    :param dry_run: If True, skips DB writes and alert notifications
    :param ignore_cache: If True, bypasses the dynamic recency check
    :param forecast_config: Optional ForecastConfig override for prediction tuning
    :param backtest_warmup: Min data points before first prediction in backtest
    :param output_format: 'text' or 'markdown' for report output
    :param use_neural: If True, use neural forecaster (falls back to baseline if no checkpoint)
    :param train_epochs: Number of epochs for neural training
    :param train_lr: Learning rate for neural training
    """
    scraper = SteamMarketScraper(min_request_interval=4.0)
    db: Optional[DatabaseManager] = None

    # ------------------------------------------------------------------
    # 0. DISCOVERY PHASE
    # ------------------------------------------------------------------
    if mode == "discovery":
        logger.info(f"--- Starting Skin Discovery Phase (Dry Run: {dry_run}) ---")
        if dry_run:
            logger.info("[Dry Run] Skipping database updates for newly discovered skins.")
        elif run_discovery:
            run_discovery()
            logger.info("Skin discovery complete. Tracked items updated in Supabase.")
        else:
            logger.error("Could not import 'run_discovery' from src.run_discovery.")
        return

    # ------------------------------------------------------------------
    # 1. SCRAPE PHASE (Volatility-Aware)
    # ------------------------------------------------------------------
    if mode in ("all", "scrape", "all+predict"):
        logger.info(f"--- Starting Scraper Phase (Mode: {mode}, Limit: {limit}, Dry Run: {dry_run}) ---")

        target_skins = []

        if not dry_run:
            try:
                db = DatabaseManager()
                target_skins = db.get_active_targets()
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                logger.info("Tip: Use --dry-run for local testing without database credentials.")
                return

        # Fallback to sample items in dry-run mode if no targets loaded
        if dry_run and not target_skins:
            logger.info("DRY RUN MODE: Using sample items for local testing...")
            target_skins = SAMPLE_TARGETS

        if not target_skins:
            logger.warning("No active items found in the tracked_items table! Run python -m src.main --mode discovery first.")
            if db:
                db.close()
            return

        # Apply item limit for testing
        if limit and limit > 0:
            target_skins = target_skins[:limit]
            logger.info(f"Local test limit applied: processing {len(target_skins)} item(s).")

        logger.info(f"Processing {len(target_skins)} item(s)...")

        for skin_name in target_skins:
            logger.info(f"--- Processing: {skin_name} ---")

            # Volatility-aware cache threshold unless bypassed
            if not dry_run and not ignore_cache and db:
                tier, cv, required_hours = get_scrape_interval_for_item(skin_name, db)
                if db.is_recently_scraped(skin_name, hours_threshold=required_hours):
                    logger.info(f"Skipped {skin_name} [{tier} tier, CV: {cv:.3f}]: Scraped within last {required_hours}h.")
                    continue
                else:
                    logger.info(f"Evaluated {skin_name} [{tier} tier, CV: {cv:.3f}]: Interval threshold {required_hours}h reached.")

            # Scrape price data using residential proxy chain
            price_data = scraper.get_price(appid=730, market_hash_name=skin_name)

            if price_data:
                logger.info(f"Scraped {skin_name}: ${price_data.get('lowest_price', 0.0)}")

                if dry_run:
                    logger.info(f"[Dry Run] Parsed payload for {skin_name}: {price_data}")
                elif db:
                    price_data["skin_name"] = skin_name
                    db.insert_price(price_data)
                    logger.info(f"Logged fresh prices for {skin_name} into Supabase")
            else:
                logger.error(f"Failed to reach Steam backend for {skin_name}")

            time.sleep(2)  # Safe breathing window for proxy rotation

        if db:
            db.close()
        logger.info("Historical price log run completed.")

    # ------------------------------------------------------------------
    # 2. ANALYTICS & ALERT PHASE
    # ------------------------------------------------------------------
    if mode in ("all", "analytics", "all+predict"):
        logger.info("--- Starting Analytics Phase ---")
        if dry_run:
            logger.info("DRY RUN MODE: Skipping live analytics DB queries and ntfy alerts.")
        else:
            run_and_notify_analytics()

    # ------------------------------------------------------------------
    # 3. PREDICTION PHASE
    # ------------------------------------------------------------------
    if mode in ("predict", "all+predict"):
        logger.info("--- Starting Prediction Phase ---")

        if dry_run:
            logger.info("DRY RUN MODE: Skipping live prediction DB queries.")
            logger.info("  (Prediction requires live data; use --mode predict without --dry-run)")
            return

        try:
            db = DatabaseManager()
            active_items = db.get_active_targets()

            if not active_items:
                logger.info("No active items found for forecasting.")
                db.close()
                return

            if limit and limit > 0:
                active_items = active_items[:limit]

            # Collect all price history in one pass
            records_by_skin = {}
            for skin_name in active_items:
                records = db.get_price_history(skin_name=skin_name, limit=200)
                if records:
                    records_by_skin[skin_name] = records

            db.close()

            if not records_by_skin:
                logger.info("No price history found in database for any tracked item.")
                return

            # Choose forecaster
            if use_neural and HAS_NEURAL:
                logger.info("Using neural forecaster (falls back to baseline if no checkpoint)")
                wrapper = NeuralForecasterWrapper(config=forecast_config)
                backtester = WalkForwardBacktester(neural_forecaster=wrapper)

                forecasts = {}
                gated_out = []
                errors = []
                extractor = wrapper.adapter

                for skin_name, records in records_by_skin.items():
                    try:
                        feat_dict = extractor.records_to_features(records)
                        if feat_dict is None:
                            gated_out.append({
                                "skin_name": skin_name,
                                "n_points": len(records),
                                "reason": "Insufficient data for neural forecaster",
                            })
                            continue

                        # --- Promotion Gate via Walk-Forward Backtest ---
                        backtest_res = backtester.backtest_skin(skin_name, records)
                        neural_promoted = False
                        mape_imp = 0.0

                        if backtest_res and "comparison" in backtest_res:
                            neural_promoted = backtest_res["comparison"].get("neural_promoted", False)
                            mape_imp = backtest_res["comparison"].get("mape_improvement") or 0.0

                        if neural_promoted:
                            logger.info(f"🏆 Neural model PROMOTED for {skin_name}: MAPE improved by {mape_imp:.2f}%")
                            is_experimental = False
                        else:
                            logger.info(f"🧪 Neural model EXPERIMENTAL for {skin_name}: Failed to beat baseline MAPE.")
                            is_experimental = True

                        # Build features & generate forecast
                        features = _features_from_dict(feat_dict, forecast_config)
                        result = wrapper.forecast(features)

                        if result is None:
                            gated_out.append({
                                "skin_name": skin_name,
                                "n_points": feat_dict["n_points"],
                                "reason": f"Below {wrapper.min_data_points}-point gate",
                            })
                        else:
                            result["skin_name"] = skin_name
                            result["is_experimental"] = is_experimental
                            result["source"] = "baseline" if is_experimental else "neural"
                            forecasts[skin_name] = result

                    except Exception as exc:
                        errors.append({"skin_name": skin_name, "error": str(exc)})
                        logger.error("Neural forecast error for %s: %s", skin_name, exc)

                results = {
                    "forecasts": forecasts,
                    "gated_out": gated_out,
                    "errors": errors,
                    "summary": {
                        "total_skins": len(records_by_skin),
                        "forecasted": len(forecasts),
                        "gated_out": len(gated_out),
                        "errors": len(errors),
                        "min_data_points_required": wrapper.min_data_points,
                        "horizon_hours": 12,
                    },
                    "config": {
                        "model": "neural_tcn_gru" if wrapper._has_model else "baseline_fallback",
                        "min_data_points": wrapper.min_data_points,
                        "horizon_hours": 12,
                    },
                }
            else:
                results = generate_forecasts(records_by_skin, config=forecast_config)

            report = format_forecast_report(results)
            print(report)

            # Also produce ntfy-eligible summary
            if not dry_run:
                ntfy_msg = format_forecast_summary_ntfy(results)
                try:
                    from src.analytics import send_ntfy_alert
                    send_ntfy_alert(
                        title="CSMID Forecast Update",
                        message=ntfy_msg,
                        priority="default",
                        tags="bar_chart,game",
                    )
                except Exception as e:
                    logger.warning("Failed to send forecast notification: %s", e)

        except Exception as exc:
            logger.error("Prediction phase failed: %s", exc)

    # ------------------------------------------------------------------
    # 4. NEURAL TRAINING PHASE
    # ------------------------------------------------------------------
    if mode == "train":
        if not HAS_NEURAL:
            logger.error("Neural forecaster not available. Install torch: pip install torch")
            return

        logger.info("--- Starting Neural Model Training Phase ---")

        if dry_run:
            logger.info("DRY RUN MODE: Skipping neural training.")
            return

        try:
            db = DatabaseManager()
            active_items = db.get_active_targets()

            if not active_items:
                logger.info("No active items for training.")
                db.close()
                return

            if limit and limit > 0:
                active_items = active_items[:limit]

            # Collect full price history for all skins
            records_by_skin = {}
            for skin_name in active_items:
                records = db.get_price_history(skin_name=skin_name, limit=1000)
                if records:
                    records_by_skin[skin_name] = records

            db.close()

            if not records_by_skin:
                logger.info("No price history found for training.")
                return

            logger.info("Training data: %d skins with price history", len(records_by_skin))

            result = train_neural_model(
                records_by_skin,
                epochs=train_epochs,
                learning_rate=train_lr,
            )
            print(f"\nTraining result: {result}")

        except Exception as exc:
            logger.error("Training phase failed: %s", exc)

    # ------------------------------------------------------------------
    # 5. BACKTEST PHASE
    # ------------------------------------------------------------------
    if mode == "backtest":
        logger.info("--- Starting Backtest Phase ---")

        if dry_run:
            logger.info("DRY RUN MODE: Skipping live backtest DB queries.")
            return

        try:
            db = DatabaseManager()
            active_items = db.get_active_targets()

            if not active_items:
                logger.info("No active items found for backtesting.")
                db.close()
                return

            if limit and limit > 0:
                active_items = active_items[:limit]

            records_by_skin = {}
            for skin_name in active_items:
                records = db.get_price_history(skin_name=skin_name, limit=1000)
                if records:
                    records_by_skin[skin_name] = records

            db.close()

            if not records_by_skin:
                logger.info("No price history found in database for backtesting.")
                return

            # Attach neural forecaster if requested
            neural_wrapper = None
            if use_neural:
                if HAS_NEURAL:
                    logger.info("Enabling Neural Forecaster for walk-forward comparison...")
                    neural_wrapper = NeuralForecasterWrapper(config=forecast_config)
                else:
                    logger.warning("Neural flag set but PyTorch is unavailable. Falling back to baseline backtest.")

            # Run walk-forward backtest
            results = run_backtest(
                records_by_skin, 
                warmup_periods=backtest_warmup, 
                neural_forecaster=neural_wrapper
            )
            report = format_backtest_report(results)
            print(report)

            # Save report
            md_path = os.path.join(ROOT_DIR, "data", "backtest_report.md")
            os.makedirs(os.path.dirname(md_path), exist_ok=True)
            with open(md_path, "w") as f:
                f.write(format_backtest_markdown(results))
            logger.info(f"Backtest Markdown report saved to: {md_path}")

        except Exception as exc:
            logger.error("Backtest phase failed: %s", exc)


def _features_from_dict(
    feat_dict: dict,
    config: ForecastConfig,
) -> dict:
    """Build a BaselineForecaster-compatible features dict from neural adapter output."""
    try:
        extractor = __import__("src.forecaster", fromlist=["PriceFeatureExtractor"]).PriceFeatureExtractor()
        prices = feat_dict.get("feature_matrix", [])
        n = len(prices)
        current_price = float(prices[-1, 0]) if n > 0 else 0.0
        mean_price = float(np.mean(prices[:, 0])) if n > 0 else current_price
        median_price = float(np.median(prices[:, 0])) if n > 0 else current_price
        std_price = float(np.std(prices[:, 0])) if n > 0 else 0.0
        cv = std_price / mean_price if mean_price > 0 else 0.0

        # Slope from last 5 prices
        recent_prices = prices[-min(5, n):, 0]
        if len(recent_prices) >= 2:
            x = np.arange(len(recent_prices), dtype=float)
            slope = float(np.polyfit(x, recent_prices, 1)[0])
        else:
            slope = 0.0

        # Momentum
        momentum = float(prices[-1, 3]) if n > 0 and len(prices[0]) > 3 else 0.0

        # Volume trend
        vol_trend = 0.0
        if n > 1 and len(prices[0]) > 8:
            recent_vol = prices[-min(5, n):, 8]
            valid = recent_vol[recent_vol > 0]
            if len(valid) >= 2:
                vx = np.arange(len(valid), dtype=float)
                vol_trend = float(np.polyfit(vx, valid, 1)[0])

        # Time features
        avg_interval = float(np.mean(prices[:, 9])) if n > 0 else 12.0

        return {
            "current_price": current_price,
            "mean_price": mean_price,
            "median_price": median_price,
            "std_price": std_price,
            "cv": cv,
            "slope": slope,
            "momentum": momentum,
            "volume_trend": vol_trend,
            "n_points": feat_dict.get("n_points", n),
            "distinct_days": feat_dict.get("n_points", n),
            "time_span_hours": avg_interval * (n - 1) if n > 1 else 0.0,
            "avg_interval_hours": avg_interval,
        }
    except Exception:
        # Fallback: construct minimal features
        return {
            "current_price": 0.0,
            "mean_price": 0.0,
            "median_price": 0.0,
            "std_price": 0.0,
            "cv": 0.0,
            "slope": 0.0,
            "momentum": 0.0,
            "volume_trend": 0.0,
            "n_points": feat_dict.get("n_points", 0),
            "distinct_days": feat_dict.get("n_points", 0),
            "time_span_hours": 0.0,
            "avg_interval_hours": 12.0,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CSMID Market Scraper, Analytics & Prediction Pipeline")
    parser.add_argument(
        "--mode",
        choices=["all", "scrape", "analytics", "discovery", "predict", "backtest",
                 "train", "all+predict"],
        default="all",
        help="Pipeline phase to execute (default: all)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of items to scrape (useful for fast local testing)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without connecting to Supabase or firing ntfy alerts"
    )
    parser.add_argument(
        "--ignore-cache",
        action="store_true",
        help="Ignore volatility intervals and force a fresh scrape"
    )
    parser.add_argument(
        "--min-data-points",
        type=int,
        default=10,
        help="Minimum data points required for forecasting (default: 10)"
    )
    parser.add_argument(
        "--horizon-hours",
        type=int,
        default=12,
        help="Forecast horizon in hours (default: 12)"
    )
    parser.add_argument(
        "--backtest-warmup",
        type=int,
        default=10,
        help="Min data points before first prediction in backtest (default: 10)"
    )
    parser.add_argument(
        "--output-format",
        choices=["text", "markdown"],
        default="text",
        help="Output format for reports (default: text)"
    )
    parser.add_argument(
        "--neural",
        action="store_true",
        help="Use neural forecaster instead of baseline (requires torch)"
    )
    parser.add_argument(
        "--train-epochs",
        type=int,
        default=50,
        help="Number of training epochs for neural model (default: 50)"
    )
    parser.add_argument(
        "--train-lr",
        type=float,
        default=1e-3,
        help="Learning rate for neural training (default: 0.001)"
    )

    args = parser.parse_args()

    # Build config from CLI args
    fc = ForecastConfig()
    fc.MIN_DATA_POINTS = args.min_data_points
    fc.HORIZON_HOURS = args.horizon_hours

    run_pipeline(
        mode=args.mode,
        limit=args.limit,
        dry_run=args.dry_run,
        ignore_cache=args.ignore_cache,
        forecast_config=fc,
        backtest_warmup=args.backtest_warmup,
        output_format=args.output_format,
        use_neural=args.neural,
        train_epochs=args.train_epochs,
        train_lr=args.train_lr,
    )