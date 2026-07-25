"""
src/forecaster.py — Gated Baseline Price Forecaster for CSMID

This module extracts time-series features from Supabase price history,
refuses to forecast skins below a configurable data-sufficiency gate,
and provides a defensible baseline model (weighted trend / persistence)
that produces real forecasts once enough data accumulates.

No forecasting library dependency — pure stdlib + numpy + pandas.
"""

import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("CSMID.forecaster")


# =====================================================================
# 1. CONFIGURATION & DATA-SUFFICIENCY GATE
# =====================================================================

class ForecastConfig:
    """Holds all tunable parameters for the forecasting pipeline."""

    # Minimum number of data points required to produce a forecast
    MIN_DATA_POINTS: int = 10

    # Minimum number of distinct days covered (prevents clustering bias)
    MIN_DISTINCT_DAYS: int = 5

    # Forecast horizon in hours (default: next scrape interval ≈ 12h)
    HORIZON_HOURS: int = 12

    # Trend window: how many recent points to use for trend extrapolation
    TREND_WINDOW: int = 5

    # Volume-weight factor for trend (0 = ignore volume, 1 = full weighting)
    VOLUME_WEIGHT: float = 0.3

    # Mean-reversion strength (0 = pure trend, 1 = pure mean reversion)
    MEAN_REVERSION_STRENGTH: float = 0.35

    # Confidence decay per forecast step (for multi-step forecasts)
    CONFIDENCE_DECAY: float = 0.85


# =====================================================================
# 2. FEATURE EXTRACTION
# =====================================================================

class PriceFeatureExtractor:
    """
    Transforms raw price history records into a feature vector suitable
    for the baseline forecaster. Extracts trend, volatility, momentum,
    and volume features.
    """

    @staticmethod
    def records_to_dataframe(records: List[Dict[str, Any]]) -> pd.DataFrame:
        """Convert database records to a clean, sorted DataFrame."""
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df["scraped_at"] = pd.to_datetime(df["scraped_at"], utc=True)
        df = df.sort_values("scraped_at").reset_index(drop=True)

        # Use lowest_price as primary signal; fall back to median_price
        if "lowest_price" in df.columns:
            df["price"] = df["lowest_price"].fillna(df.get("median_price"))
        else:
            df["price"] = df["median_price"]

        df = df.dropna(subset=["price"])
        df["price"] = df["price"].astype(float)
        df = df[df["price"] > 0].reset_index(drop=True)

        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)

        return df

    @staticmethod
    def extract_features(df: pd.DataFrame, config: ForecastConfig) -> Dict[str, Any]:
        """
        Extract a feature dictionary from a sorted price DataFrame.

        Returns an empty dict if insufficient data.
        """
        if len(df) < config.MIN_DATA_POINTS:
            return {}

        # Distinct days check
        if "scraped_at" in df.columns:
            distinct_days = df["scraped_at"].dt.date.nunique()
            if distinct_days < config.MIN_DISTINCT_DAYS:
                return {}

        prices = df["price"].values
        n = len(prices)

        # Core statistics
        current_price = float(prices[-1])
        mean_price = float(np.mean(prices))
        std_price = float(np.std(prices))
        median_price = float(np.median(prices))

        # Trend: linear regression slope over recent window
        tw = min(config.TREND_WINDOW, n)
        recent = prices[-tw:]
        if len(recent) >= 2:
            x = np.arange(len(recent), dtype=float)
            slope = float(np.polyfit(x, recent, 1)[0])
        else:
            slope = 0.0

        # Momentum: % change over last 3 points
        if n >= 3:
            momentum = (prices[-1] - prices[-3]) / prices[-3] if prices[-3] > 0 else 0.0
        else:
            momentum = 0.0

        # Volatility: coefficient of variation
        cv = std_price / mean_price if mean_price > 0 else 0.0

        # Volume trend (if available)
        vol_trend = 0.0
        if "volume" in df.columns and df["volume"].sum() > 0:
            tw_v = min(tw, n)
            recent_vol = df["volume"].values[-tw_v:]
            valid_vol = recent_vol[recent_vol > 0]
            if len(valid_vol) >= 2:
                vol_x = np.arange(len(valid_vol), dtype=float)
                vol_trend = float(np.polyfit(vol_x, valid_vol.astype(float), 1)[0])

        # Time features
        time_span_hours = 0.0
        if "scraped_at" in df.columns and len(df) >= 2:
            time_span = df["scraped_at"].iloc[-1] - df["scraped_at"].iloc[0]
            time_span_hours = time_span.total_seconds() / 3600.0

        avg_interval_hours = time_span_hours / (n - 1) if n > 1 else 0.0

        return {
            "current_price": current_price,
            "mean_price": mean_price,
            "median_price": median_price,
            "std_price": std_price,
            "cv": cv,
            "slope": slope,
            "momentum": float(momentum),
            "volume_trend": vol_trend,
            "n_points": n,
            "distinct_days": df["scraped_at"].dt.date.nunique() if "scraped_at" in df.columns else n,
            "time_span_hours": time_span_hours,
            "avg_interval_hours": avg_interval_hours,
        }


# =====================================================================
# 3. GATED BASELINE FORECASTER
# =====================================================================

class BaselineForecaster:
    """
    A defensible, simple forecasting model that blends:
    - Persistence (current price holds)
    - Linear trend extrapolation (from recent window)
    - Mean reversion (price drifts toward historical median)

    The blend weights are configurable. This is NOT a black-box ML model —
    every component is interpretable and the data-sufficiency gate ensures
    we never forecast from noise.
    """

    def __init__(self, config: Optional[ForecastConfig] = None):
        self.config = config or ForecastConfig()

    def can_forecast(self, features: Dict[str, Any]) -> bool:
        """Return True if the feature set passes the data-sufficiency gate."""
        return bool(features)  # Empty dict means gate not passed

    def _forecast_persistence(self, price: float) -> float:
        """Persistence model: price stays the same."""
        return price

    def _forecast_trend(self, features: Dict[str, Any]) -> float:
        """Linear trend extrapolation over the forecast horizon."""
        avg_interval = features["avg_interval_hours"]
        if avg_interval <= 0:
            return features["current_price"]

        # Number of intervals in the forecast horizon
        steps = self.config.HORIZON_HOURS / avg_interval
        return features["current_price"] + features["slope"] * steps

    def _forecast_mean_reversion(self, features: Dict[str, Any]) -> float:
        """Drift current price toward the historical median."""
        current = features["current_price"]
        target = features["median_price"]
        strength = self.config.MEAN_REVERSION_STRENGTH
        return current + strength * (target - current)

    def _forecast_volume_adjusted(self, features: Dict[str, Any], base: float) -> float:
        """
        Adjust the base forecast using volume trend as a signal.
        Rising volume on a rising trend = stronger trend.
        Rising volume on a falling trend = stronger decline.
        """
        if features["volume_trend"] == 0 or features["current_price"] == 0:
            return base

        # Normalize volume trend relative to current price
        vol_signal = (features["volume_trend"] / max(features["current_price"], 0.01))
        adjustment = vol_signal * self.config.VOLUME_WEIGHT * features["current_price"]
        return base + adjustment

    def forecast(self, features: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Produce a forecast if data passes the gate.

        Returns:
            Dict with keys:
                predicted_price, direction, confidence, components, features
            or None if data is insufficient.
        """
        if not self.can_forecast(features):
            return None

        current = features["current_price"]

        # Three base forecasts
        f_persist = self._forecast_persistence(current)
        f_trend = self._forecast_trend(features)
        f_revert = self._forecast_mean_reversion(features)

        # Blend: weight by volatility (high CV → trust mean reversion more)
        cv = features["cv"]
        cv_clamped = min(cv, 0.3) / 0.3  # Normalize to [0, 1]

        w_persist = 0.30 + cv_clamped * 0.10  # 30-40%
        w_trend = 0.35 - cv_clamped * 0.15    # 20-35%
        w_revert = 0.35 + cv_clamped * 0.05   # 35-40%

        # Ensure weights sum to 1
        total = w_persist + w_trend + w_revert
        w_persist /= total
        w_trend /= total
        w_revert /= total

        blended = w_persist * f_persist + w_trend * f_trend + w_revert * f_revert

        # Volume adjustment
        predicted = self._forecast_volume_adjusted(features, blended)

        # Ensure price doesn't go below 0.01
        predicted = max(predicted, 0.01)

        # Direction
        pct_change = (predicted - current) / current if current > 0 else 0.0
        if pct_change > 0.02:
            direction = "UP"
        elif pct_change < -0.02:
            direction = "DOWN"
        else:
            direction = "FLAT"

        # Confidence: based on data depth and volatility
        depth_score = min(features["n_points"] / 30.0, 1.0)  # Max at 30 points
        stability_score = 1.0 - min(cv / 0.2, 1.0)  # Lower CV = higher confidence
        confidence = float(0.3 * depth_score + 0.4 * stability_score + 0.3 * 0.5)
        confidence = round(min(max(confidence, 0.0), 1.0), 3)

        return {
            "predicted_price": round(float(predicted), 4),
            "direction": direction,
            "confidence": confidence,
            "pct_change": round(float(pct_change * 100), 2),
            "horizon_hours": self.config.HORIZON_HOURS,
            "components": {
                "persistence": round(float(f_persist), 4),
                "trend": round(float(f_trend), 4),
                "mean_reversion": round(float(f_revert), 4),
                "weights": {
                    "persistence": round(w_persist, 3),
                    "trend": round(w_trend, 3),
                    "mean_reversion": round(w_revert, 3),
                },
            },
            "features": features,
        }


# =====================================================================
# 4. HIGH-LEVEL FORECAST PIPELINE
# =====================================================================

def generate_forecasts(
    records_by_skin: Dict[str, List[Dict[str, Any]]],
    config: Optional[ForecastConfig] = None,
) -> Dict[str, Any]:
    """
    Run the forecaster across all skins and return results.

    Args:
        records_by_skin: {skin_name: [record_dict, ...]}
        config: Optional ForecastConfig override

    Returns:
        Dict with 'forecasts' (per-skin results) and 'summary' (aggregate stats).
    """
    cfg = config or ForecastConfig()
    extractor = PriceFeatureExtractor()
    forecaster = BaselineForecaster(cfg)

    forecasts = {}
    gated_out = []
    errors = []

    for skin_name, records in records_by_skin.items():
        try:
            df = extractor.records_to_dataframe(records)
            features = extractor.extract_features(df, cfg)

            if not features:
                gated_out.append({
                    "skin_name": skin_name,
                    "n_points": len(df),
                    "reason": "Insufficient data (need {} points, {} days; got {} points, {} days)".format(
                        cfg.MIN_DATA_POINTS,
                        cfg.MIN_DISTINCT_DAYS,
                        len(df),
                        df["scraped_at"].dt.date.nunique() if len(df) > 0 else 0,
                    ),
                })
                continue

            result = forecaster.forecast(features)
            if result is None:
                gated_out.append({
                    "skin_name": skin_name,
                    "n_points": features.get("n_points", 0),
                    "reason": "Forecaster rejected (internal gate)",
                })
            else:
                result["skin_name"] = skin_name
                forecasts[skin_name] = result

        except Exception as exc:
            errors.append({"skin_name": skin_name, "error": str(exc)})
            logger.error("Forecast error for %s: %s", skin_name, exc)

    # Summary statistics
    summary = {
        "total_skins": len(records_by_skin),
        "forecasted": len(forecasts),
        "gated_out": len(gated_out),
        "errors": len(errors),
        "min_data_points_required": cfg.MIN_DATA_POINTS,
        "horizon_hours": cfg.HORIZON_HOURS,
    }

    return {
        "forecasts": forecasts,
        "gated_out": gated_out,
        "errors": errors,
        "summary": summary,
        "config": {
            "min_data_points": cfg.MIN_DATA_POINTS,
            "min_distinct_days": cfg.MIN_DISTINCT_DAYS,
            "horizon_hours": cfg.HORIZON_HOURS,
            "trend_window": cfg.TREND_WINDOW,
            "mean_reversion_strength": cfg.MEAN_REVERSION_STRENGTH,
            "volume_weight": cfg.VOLUME_WEIGHT,
        },
    }
