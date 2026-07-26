"""
src/backtest.py — Walk-Forward Backtest Framework for CSMID

Provides a rigorous walk-forward validation harness comparing baseline
and neural forecasters. Splits historical data into training windows,
evaluates both models on held-out future observations, and computes
head-to-head accuracy metrics including MAPE, RMSE, and Direction Accuracy.

A neural model is strictly flagged as `neural_promoted = True` ONLY if it
outperforms the parameter-free baseline in MAPE on identical evaluation steps.
"""

import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional

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
    Walk-forward validation engine for head-to-head model comparison.

    For each skin:
        For t in [warmup, ..., len(data) - 1]:
            df_past = data[:t]
            features = extract(df_past)
            pred_baseline = baseline.forecast(features)
            pred_neural   = neural.forecast(df_past)
            actual        = data[t]["price"]
            record_errors(pred_baseline, pred_neural, actual)

    Returns per-skin comparative metrics and global aggregate statistics.
    """

    def __init__(
        self,
        forecaster: Optional[BaselineForecaster] = None,
        neural_forecaster: Optional[Any] = None,
        config: Optional[ForecastConfig] = None,
        warmup_periods: int = 15,
        step_size: int = 1,
    ):
        self.baseline_forecaster = forecaster or BaselineForecaster(config)
        self.neural_forecaster = neural_forecaster
        self.config = config or self.baseline_forecaster.config
        self.extractor = PriceFeatureExtractor()
        self.warmup_periods = warmup_periods
        self.step_size = step_size

    def backtest_skin(
        self,
        skin_name: str,
        records: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Run head-to-head walk-forward backtest on a single skin's history.

        Returns:
            Dict containing baseline metrics, neural metrics, and promotion status.
        """
        df = self.extractor.records_to_dataframe(records)
        if len(df) < self.warmup_periods + 1:
            logger.info(
                "Backtest skipped %s: only %d points (need %d)",
                skin_name, len(df), self.warmup_periods + 1,
            )
            return None

        prices = df["price"].values
        predictions_base = []
        predictions_neural = []

        # Walk forward step-by-step
        for t in range(self.warmup_periods, len(prices) - 1, self.step_size):
            df_past = df.iloc[:t]
            actual = float(prices[t])
            last_price = float(df_past["price"].iloc[-1])

            # 1. Evaluate Baseline Model
            features = self.extractor.extract_features(df_past, self.config)
            if not features:
                continue

            forecast_base = self.baseline_forecaster.forecast(features)
            if forecast_base is None:
                continue

            pred_base = float(forecast_base["predicted_price"])
            err_base = ((pred_base - actual) / actual) * 100 if actual != 0 else 0.0
            
            # Direction check: did baseline correctly predict price move sign?
            actual_move = actual - last_price
            pred_move_base = pred_base - last_price
            dir_correct_base = 1.0 if np.sign(actual_move) == np.sign(pred_move_base) else 0.0

            predictions_base.append({
                "predicted": pred_base,
                "actual": actual,
                "pct_error": err_base,
                "dir_correct": dir_correct_base,
                "direction": forecast_base.get("direction", "NEUTRAL"),
            })

            # 2. Evaluate Neural Model (if provided & operational)
            if self.neural_forecaster is not None:
                try:
                    neural_res = None
                    if hasattr(self.neural_forecaster, "forecast"):
                        neural_res = self.neural_forecaster.forecast(df_past)
                    elif hasattr(self.neural_forecaster, "predict"):
                        neural_res = self.neural_forecaster.predict(df_past)

                    if neural_res is not None:
                        pred_neural = float(
                            neural_res["predicted_price"]
                            if isinstance(neural_res, dict)
                            else neural_res
                        )
                        err_neural = ((pred_neural - actual) / actual) * 100 if actual != 0 else 0.0
                        
                        pred_move_neural = pred_neural - last_price
                        dir_correct_neural = 1.0 if np.sign(actual_move) == np.sign(pred_move_neural) else 0.0

                        predictions_neural.append({
                            "predicted": pred_neural,
                            "actual": actual,
                            "pct_error": err_neural,
                            "dir_correct": dir_correct_neural,
                        })
                except Exception as exc:
                    logger.debug("Neural prediction step failed at t=%d for %s: %s", t, skin_name, exc)

        if not predictions_base:
            return None

        # Compute Baseline Metrics
        base_pct_errors = np.array([p["pct_error"] for p in predictions_base])
        base_abs_errors = np.abs(base_pct_errors)
        base_mape = float(np.nanmean(base_abs_errors)) if len(base_abs_errors) > 0 else 0.0
        base_rmse = float(np.sqrt(np.nanmean(base_pct_errors ** 2))) if len(base_pct_errors) > 0 else 0.0
        base_dir_acc = float(np.nanmean([p["dir_correct"] for p in predictions_base]) * 100.0) if len(predictions_base) > 0 else 0.0

        # Compute Neural Metrics (if evaluated)
        neural_mape = float("inf")
        neural_rmse = float("inf")
        neural_dir_acc = 0.0
        neural_eval_count = len(predictions_neural)

        if neural_eval_count > 0 and neural_eval_count == len(predictions_base):
            neur_pct_errors = np.array([p["pct_error"] for p in predictions_neural])
            neur_abs_errors = np.abs(neur_pct_errors)
            neural_mape = float(np.nanmean(neur_abs_errors))
            neural_rmse = float(np.sqrt(np.nanmean(neur_pct_errors ** 2)))
            neural_dir_acc = float(np.nanmean([p["dir_correct"] for p in predictions_neural]) * 100.0)

        # Promotion Gate: Neural MUST exist, pass all steps, and achieve LOWER MAPE than Baseline
        neural_promoted = (
            self.neural_forecaster is not None
            and neural_eval_count == len(predictions_base)
            and neural_mape < base_mape
        )

        base_metrics_dict = {
            "mape_pct": round(base_mape, 2),
            "rmse_pct": round(base_rmse, 2),
            "bias_pct": round(float(np.nanmean(base_pct_errors)), 2),
            "direction_accuracy": round(base_dir_acc, 2),
        }

        neural_metrics_dict = {
            "evaluations": neural_eval_count,
            "mape_pct": round(neural_mape, 2) if neural_mape != float("inf") else None,
            "rmse_pct": round(neural_rmse, 2) if neural_rmse != float("inf") else None,
            "direction_accuracy": round(neural_dir_acc, 2) if neural_eval_count > 0 else None,
        } if self.neural_forecaster else None

        return {
            "skin_name": skin_name,
            "n_evaluations": len(predictions_base),
            "n_predictions": len(predictions_base),  # Alias for backward compatibility
            "baseline_metrics": base_metrics_dict,
            "metrics": base_metrics_dict,            # Alias for backward compatibility
            "neural_metrics": neural_metrics_dict,
            "comparison": {
                "neural_promoted": neural_promoted,
                "mape_improvement": round(base_mape - neural_mape, 2) if neural_mape != float("inf") else None,
                "baseline_direction_acc": round(base_dir_acc, 2),
                "neural_direction_acc": round(neural_dir_acc, 2) if neural_eval_count > 0 else None,
            }
        }

    def backtest_all(
        self,
        records_by_skin: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        Run walk-forward backtest across all skins.
        """
        results = []
        skipped = []
        promoted_count = 0

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
                    if result["comparison"]["neural_promoted"]:
                        promoted_count += 1
            except Exception as exc:
                logger.error("Backtest error for %s: %s", skin_name, exc)
                skipped.append({
                    "skin_name": skin_name,
                    "error": str(exc),
                })

        # Global aggregate stats
        aggregate = {}
        if results:
            base_mapes = [r["baseline_metrics"]["mape_pct"] for r in results]
            base_dirs = [r["baseline_metrics"]["direction_accuracy"] for r in results]
            total_evals = sum(r["n_evaluations"] for r in results)

            mean_mape = round(float(np.mean(base_mapes)), 2)
            mean_dir_acc = round(float(np.mean(base_dirs)), 2)

            aggregate = {
                "n_skins_evaluated": len(results),
                "total_skins_evaluated": len(results),      # Alias
                "n_skins_skipped": len(skipped),
                "total_evaluations": total_evals,
                "total_predictions": total_evals,             # Alias
                "baseline_mean_mape_pct": mean_mape,
                "mean_mape_pct": mean_mape,                   # Alias
                "baseline_mean_direction_accuracy": mean_dir_acc,
                "mean_direction_accuracy": mean_dir_acc,      # Alias
                "neural_promotions": promoted_count,
                "promoted_skins_count": promoted_count,       # Alias
            }

        # Build dictionary map for skins lookup
        skins_dict = {r["skin_name"]: r for r in results}

        return {
            "results": results,
            "skins": skins_dict,
            "aggregate": aggregate,
            "skipped": skipped,
        }


# =====================================================================
# 2. CONVENIENCE FUNCTION
# =====================================================================

def run_backtest(
    records_by_skin: Dict[str, List[Dict[str, Any]]],
    config: Optional[ForecastConfig] = None,
    neural_forecaster: Optional[Any] = None,
    warmup_periods: int = 15,
) -> Dict[str, Any]:
    """
    High-level entry point for running a full comparative backtest.
    """
    cfg = config or ForecastConfig()
    backtester = WalkForwardBacktester(
        config=cfg,
        neural_forecaster=neural_forecaster,
        warmup_periods=warmup_periods,
    )
    return backtester.backtest_all(records_by_skin)