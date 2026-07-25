"""
src/backtest.py — Walk-Forward Backtest Framework for CSMID

Provides a rigorous walk-forward validation harness for the forecaster.
Splits historical data into training windows, trains (or in this case,
evaluates the parameter-free baseline), and measures prediction accuracy
on held-out future data — simulating exactly how the model would perform
in production.

No ML training is involved (the baseline is parameter-free), but the
framework is structured to accept any future model class that exposes
a .forecast(features) interface.
"""

import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional, Callable

from src.forecaster import (
    BaselineForecaster,
    ForecastConfig,
    PriceFeatureExtractor,
)

logger = logging.getLogger("CSMID.backtest")


# =====================================================================
# 1. WALK-FORWARD VALIDATION ENGINE
# =====================================================================

class WalkForwardBacktester:
    """
    Walk-forward validation: repeatedly "predict the next point" using
    only data available up to that point, then compare to the actual
    observation. This is the gold standard for time-series evaluation.

    For each skin:
        For t in [warmup, ..., len(data) - 1]:
            features = extract(data[:t])       # only past data
            prediction = forecaster.forecast(features)
            actual = data[t]["price"]          # the held-out truth
            record(prediction, actual)

    Returns per-skin error metrics and aggregate statistics.
    """

    def __init__(
        self,
        forecaster: Optional[BaselineForecaster] = None,
        config: Optional[ForecastConfig] = None,
        warmup_periods: int = 10,
        step_size: int = 1,
    ):
        self.forecaster = forecaster or BaselineForecaster(config)
        self.config = config or self.forecaster.config
        self.extractor = PriceFeatureExtractor()
        self.warmup_periods = warmup_periods
        self.step_size = step_size

    def backtest_skin(
        self,
        skin_name: str,
        records: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Run walk-forward backtest on a single skin's history.

        Returns:
            Dict with 'skin_name', 'metrics', 'predictions' list,
            or None if insufficient data.
        """
        df = self.extractor.records_to_dataframe(records)
        if len(df) < self.warmup_periods + 1:
            logger.info(
                "Backtest skipped %s: only %d points (need %d)",
                skin_name, len(df), self.warmup_periods + 1,
            )
            return None

        prices = df["price"].values
        predictions = []

        # Walk forward from warmup to the second-to-last point
        # (we need at least one actual to compare against)
        for t in range(self.warmup_periods, len(prices) - 1, self.step_size):
            # Build features from data[:t] only (no peeking)
            df_past = df.iloc[:t]
            features = self.extractor.extract_features(df_past, self.config)

            if not features:
                continue

            forecast_result = self.forecaster.forecast(features)
            if forecast_result is None:
                continue

            predicted = forecast_result["predicted_price"]
            actual = float(prices[t])
            pct_error = ((predicted - actual) / actual) * 100 if actual != 0 else 0.0

            predictions.append({
                "timestamp": str(df["scraped_at"].iloc[t].isoformat()) if "scraped_at" in df.columns else None,
                "predicted": round(predicted, 4),
                "actual": round(actual, 4),
                "pct_error": round(pct_error, 2),
                "direction_predicted": forecast_result["direction"],
            })

        if not predictions:
            return None

        # Compute metrics
        pct_errors = np.array([p["pct_error"] for p in predictions])
        abs_errors = np.abs(pct_errors)

        mape = float(np.nanmean(abs_errors)) if len(abs_errors) > 0 else 0.0
        median_abs_error = float(np.nanmedian(abs_errors)) if len(abs_errors) > 0 else 0.0
        rmse_pct = float(np.sqrt(np.nanmean(pct_errors ** 2))) if len(pct_errors) > 0 else 0.0

        # Direction accuracy
        directions_correct = 0
        for i, p in enumerate(predictions):
            if i + 1 < len(prices):
                actual_next = float(prices[
                    self.warmup_periods + (i * self.step_size) + 1
                ]) if self.warmup_periods + (i * self.step_size) + 1 < len(prices) else actual
                if actual > predictions[i]["actual"]:
                    actual_dir = "UP"
                elif actual < predictions[i]["actual"]:
                    actual_dir = "DOWN"
                else:
                    actual_dir = "FLAT"

                if p["direction_predicted"] == actual_dir or actual_dir == "FLAT":
                    directions_correct += 1

        dir_accuracy = directions_correct / len(predictions) if predictions else 0.0

        return {
            "skin_name": skin_name,
            "n_predictions": len(predictions),
            "metrics": {
                "mape_pct": round(mape, 2),
                "median_abs_error_pct": round(median_abs_error, 2),
                "rmse_pct": round(rmse_pct, 2),
                "direction_accuracy": round(dir_accuracy, 3),
                "bias_pct": round(float(np.nanmean(pct_errors)), 2),
            },
            "predictions": predictions,
        }

    def backtest_all(
        self,
        records_by_skin: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        Run walk-forward backtest across all skins.

        Returns:
            Dict with 'results' (per-skin), 'aggregate' (summary stats),
            and 'skipped' (skins with insufficient data).
        """
        results = []
        skipped = []

        for skin_name, records in records_by_skin.items():
            try:
                result = self.backtest_skin(skin_name, records)
                if result is None:
                    skipped.append({
                        "skin_name": skin_name,
                        "n_points": len(records),
                        "reason": "Insufficient data for backtest",
                    })
                else:
                    results.append(result)
            except Exception as exc:
                logger.error("Backtest error for %s: %s", skin_name, exc)
                skipped.append({
                    "skin_name": skin_name,
                    "error": str(exc),
                })

        # Aggregate metrics
        aggregate = {}
        if results:
            mapes = [r["metrics"]["mape_pct"] for r in results]
            biases = [r["metrics"]["bias_pct"] for r in results]
            dir_accs = [r["metrics"]["direction_accuracy"] for r in results]
            total_preds = sum(r["n_predictions"] for r in results)

            aggregate = {
                "n_skins_evaluated": len(results),
                "n_skins_skipped": len(skipped),
                "total_predictions": total_preds,
                "mean_mape_pct": round(float(np.mean(mapes)), 2),
                "median_mape_pct": round(float(np.median(mapes)), 2),
                "mean_bias_pct": round(float(np.mean(biases)), 2),
                "median_bias_pct": round(float(np.median(biases)), 2),
                "mean_direction_accuracy": round(float(np.mean(dir_accs)), 3),
            }

        return {
            "results": results,
            "aggregate": aggregate,
            "skipped": skipped,
        }


# =====================================================================
# 2. CONVENIENCE FUNCTION
# =====================================================================

def run_backtest(
    records_by_skin: Dict[str, List[Dict[str, Any]]],
    config: Optional[ForecastConfig] = None,
    warmup_periods: int = 10,
) -> Dict[str, Any]:
    """
    High-level entry point for running a full backtest.

    Args:
        records_by_skin: {skin_name: [record_dict, ...]}
        config: Optional ForecastConfig
        warmup_periods: Min history points before first prediction

    Returns:
        Backtest result dict with aggregate metrics and per-skin details.
    """
    cfg = config or ForecastConfig()
    backtester = WalkForwardBacktester(config=cfg, warmup_periods=warmup_periods)
    return backtester.backtest_all(records_by_skin)
