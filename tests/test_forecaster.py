"""
tests/test_forecaster.py — Unit tests for the gated forecaster pipeline.

Tests cover:
- Feature extraction and data-sufficiency gate
- Baseline forecaster blend logic
- Multi-skin forecast pipeline (with gating)
- Edge cases (empty data, single point, NaN prices)
"""

import os
import sys
import pytest
import numpy as np
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.forecaster import (
    ForecastConfig,
    PriceFeatureExtractor,
    BaselineForecaster,
    generate_forecasts,
)


# =====================================================================
# HELPERS
# =====================================================================

def _make_records(
    skin_name: str,
    base_price: float,
    n_points: int,
    price_noise: float = 0.02,
    volume: int = 100,
    start_days_ago: int = 30,
    interval_hours: float = 12.0,
):
    """Generate synthetic price records for testing."""
    np.random.seed(42)
    records = []
    for i in range(n_points):
        noise = 1.0 + np.random.normal(0, price_noise)
        # Add slight upward drift
        trend = 1.0 + (i * 0.005)
        price = base_price * trend * noise
        ts = datetime.now(timezone.utc) - timedelta(days=start_days_ago, hours=interval_hours * (n_points - 1 - i))
        records.append({
            "skin_name": skin_name,
            "hash_name": skin_name,
            "lowest_price": round(price, 4),
            "median_price": round(price * 1.01, 4),
            "volume": volume + np.random.randint(-20, 20),
            "scraped_at": ts.isoformat(),
        })
    return records


# =====================================================================
# FEATURE EXTRACTION TESTS
# =====================================================================

class TestPriceFeatureExtractor:
    """Test the feature extraction and data-sufficiency gate."""

    def test_empty_records_returns_empty_df(self):
        """Empty input should return empty DataFrame."""
        df = PriceFeatureExtractor.records_to_dataframe([])
        assert df.empty

    def test_records_to_dataframe_sorts_chronologically(self):
        """Records should be sorted by scraped_at ascending."""
        records = _make_records("Test Skin", 1.0, 5, start_days_ago=10, interval_hours=12.0)
        df = PriceFeatureExtractor.records_to_dataframe(records)
        timestamps = pd.to_datetime(df["scraped_at"]) if "scraped_at" in df.columns else None
        if timestamps is not None:
            assert timestamps.is_monotonic_increasing

    def test_records_to_dataframe_fills_missing_lowest_price(self):
        """If lowest_price is None, should fall back to median_price."""
        records = [
            {
                "hash_name": "Test",
                "lowest_price": None,
                "median_price": 1.5,
                "volume": 50,
                "scraped_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            },
            {
                "hash_name": "Test",
                "lowest_price": 1.4,
                "median_price": 1.45,
                "volume": 55,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            },
        ]
        df = PriceFeatureExtractor.records_to_dataframe(records)
        assert len(df) == 2
        # First record should have price=1.5 (fallback to median)
        assert df.iloc[0]["price"] == 1.5

    def test_extract_features_below_gate_returns_empty(self):
        """Features below minimum data points should return empty dict."""
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 10
        records = _make_records("Test Skin", 1.0, 5, start_days_ago=10, interval_hours=12.0)
        df = PriceFeatureExtractor.records_to_dataframe(records)
        features = PriceFeatureExtractor.extract_features(df, config)
        assert features == {}

    def test_extract_features_passes_gate(self):
        """Features above minimum data points should return non-empty dict."""
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 2
        records = _make_records("Test Skin", 1.0, 15, start_days_ago=30, interval_hours=12.0)
        df = PriceFeatureExtractor.records_to_dataframe(records)
        features = PriceFeatureExtractor.extract_features(df, config)
        assert features != {}
        assert "current_price" in features
        assert "mean_price" in features
        assert "std_price" in features
        assert "slope" in features
        assert "momentum" in features
        assert "cv" in features
        assert features["n_points"] == 15

    def test_extract_features_price_range_sane(self):
        """Extracted price features should be in a reasonable range."""
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 2
        records = _make_records("AWP Skin", 50.0, 20, price_noise=0.05, start_days_ago=30, interval_hours=12.0)
        df = PriceFeatureExtractor.records_to_dataframe(records)
        features = PriceFeatureExtractor.extract_features(df, config)
        # Current price should be roughly $50 ± noise + trend
        assert 30.0 < features["current_price"] < 80.0
        assert features["std_price"] > 0
        assert features["cv"] >= 0

    def test_all_nan_prices_returns_empty(self):
        """If all prices are None/NaN, should return empty features."""
        records = [
            {
                "hash_name": "Test",
                "lowest_price": None,
                "median_price": None,
                "volume": 0,
                "scraped_at": (datetime.now(timezone.utc) - timedelta(days=i)).isoformat(),
            }
            for i in range(15, 0, -1)
        ]
        df = PriceFeatureExtractor.records_to_dataframe(records)
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 2
        features = PriceFeatureExtractor.extract_features(df, config)
        assert features == {}


# =====================================================================
# BASELINE FORECASTER TESTS
# =====================================================================

class TestBaselineForecaster:
    """Test the baseline forecaster model logic."""

    def test_can_forecast_false_for_empty(self):
        """Empty features dict should fail the gate."""
        forecaster = BaselineForecaster()
        assert forecaster.can_forecast({}) is False

    def test_can_forecast_true_for_valid(self):
        """Non-empty features should pass the gate."""
        features = {
            "current_price": 1.0,
            "mean_price": 1.0,
            "median_price": 1.0,
            "std_price": 0.1,
            "cv": 0.1,
            "slope": 0.001,
            "momentum": 0.02,
            "volume_trend": 0.0,
            "n_points": 20,
            "distinct_days": 10,
            "time_span_hours": 120.0,
            "avg_interval_hours": 6.0,
        }
        forecaster = BaselineForecaster()
        assert forecaster.can_forecast(features) is True

    def test_forecast_returns_dict_with_expected_keys(self):
        """Forecast output should have the expected structure."""
        features = {
            "current_price": 1.5,
            "mean_price": 1.4,
            "median_price": 1.45,
            "std_price": 0.15,
            "cv": 0.1,
            "slope": 0.002,
            "momentum": 0.01,
            "volume_trend": 5.0,
            "n_points": 20,
            "distinct_days": 10,
            "time_span_hours": 120.0,
            "avg_interval_hours": 6.0,
        }
        forecaster = BaselineForecaster()
        result = forecaster.forecast(features)
        assert result is not None
        assert "predicted_price" in result
        assert "direction" in result
        assert "confidence" in result
        assert "pct_change" in result
        assert "components" in result
        assert "features" in result

    def test_forecast_price_never_negative(self):
        """Predicted price should always be positive."""
        features = {
            "current_price": 0.05,
            "mean_price": 0.06,
            "median_price": 0.055,
            "std_price": 0.01,
            "cv": 0.18,
            "slope": -0.005,
            "momentum": -0.1,
            "volume_trend": -10.0,
            "n_points": 15,
            "distinct_days": 8,
            "time_span_hours": 96.0,
            "avg_interval_hours": 7.0,
        }
        forecaster = BaselineForecaster()
        result = forecaster.forecast(features)
        assert result["predicted_price"] > 0

    def test_persistence_forecast_returns_current_price(self):
        """Persistence model should return the current price unchanged."""
        forecaster = BaselineForecaster()
        assert forecaster._forecast_persistence(42.5) == 42.5

    def test_mean_reversion_drifts_toward_median(self):
        """Mean reversion should move price toward the median."""
        features = {
            "current_price": 10.0,
            "median_price": 5.0,
            "mean_price": 6.0,
        }
        forecaster = BaselineForecaster(ForecastConfig())
        result = forecaster._forecast_mean_reversion(features)
        # With strength 0.35, should move 35% toward median: 10 - 0.35*(10-5) = 8.25
        assert 7.0 < result < 9.5

    def test_forecast_direction_classification(self):
        """Direction should be UP, DOWN, or FLAT based on pct_change threshold."""
        features = {
            "current_price": 1.0,
            "mean_price": 1.0,
            "median_price": 1.0,
            "std_price": 0.0,
            "cv": 0.0,
            "slope": 0.1,  # Strong upward trend
            "momentum": 0.05,
            "volume_trend": 0.0,
            "n_points": 20,
            "distinct_days": 10,
            "time_span_hours": 120.0,
            "avg_interval_hours": 6.0,
        }
        forecaster = BaselineForecaster()
        result = forecaster.forecast(features)
        assert result["direction"] == "UP"

    def test_forecast_no_data_returns_none(self):
        """Should return None when features is empty."""
        forecaster = BaselineForecaster()
        assert forecaster.forecast({}) is None


# =====================================================================
# MULTI-SKIN PIPELINE TESTS
# =====================================================================

class TestGenerateForecasts:
    """Test the high-level forecast pipeline across multiple skins."""

    def test_all_skins_below_gate(self):
        """When all skins have insufficient data, none should be forecasted."""
        records_by_skin = {
            "Skin A": _make_records("Skin A", 1.0, 3, start_days_ago=5),
            "Skin B": _make_records("Skin B", 2.0, 5, start_days_ago=5),
        }
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 10
        config.MIN_DISTINCT_DAYS = 5
        results = generate_forecasts(records_by_skin, config)
        assert results["summary"]["forecasted"] == 0
        assert results["summary"]["gated_out"] == 2
        assert results["summary"]["total_skins"] == 2

    def test_some_skins_pass_gate(self):
        """Skins with enough data should be forecasted; others gated out."""
        records_by_skin = {
            "Skin A": _make_records("Skin A", 1.0, 3, start_days_ago=5),
            "Skin B": _make_records("Skin B", 2.0, 15, start_days_ago=30, interval_hours=12.0),
        }
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 10
        config.MIN_DISTINCT_DAYS = 5
        results = generate_forecasts(records_by_skin, config)
        assert results["summary"]["forecasted"] == 1
        assert results["summary"]["gated_out"] == 1

    def test_empty_input_returns_zero_counts(self):
        """Empty input should return zero forecasts and zero gated."""
        results = generate_forecasts({})
        assert results["summary"]["total_skins"] == 0
        assert results["summary"]["forecasted"] == 0
        assert results["summary"]["gated_out"] == 0

    def test_forecast_results_have_skin_name(self):
        """Each forecast result should include the skin name."""
        records_by_skin = {
            "Test Skin": _make_records("Test Skin", 5.0, 15, start_days_ago=30, interval_hours=12.0),
        }
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 3
        results = generate_forecasts(records_by_skin, config)
        assert "Test Skin" in results["forecasts"]
        assert results["forecasts"]["Test Skin"]["skin_name"] == "Test Skin"

    def test_config_passed_through(self):
        """Config values should appear in the results."""
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 8
        config.HORIZON_HOURS = 24
        results = generate_forecasts({}, config)
        assert results["config"]["min_data_points"] == 8
        assert results["config"]["horizon_hours"] == 24


# =====================================================================
# EDGE CASE TESTS
# =====================================================================

class TestEdgeCases:
    """Test edge cases and robustness."""

    def test_single_data_point_gated(self):
        """A single data point should not produce a forecast."""
        records = [{
            "hash_name": "Lone Skin",
            "lowest_price": 1.0,
            "median_price": 1.0,
            "volume": 100,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }]
        records_by_skin = {"Lone Skin": records}
        results = generate_forecasts(records_by_skin)
        assert results["summary"]["gated_out"] == 1

    def test_identical_prices_zero_cv(self):
        """If all prices are truly identical, CV should be 0 (stable = HIGH tier)."""
        # Generate records with exactly the same price each time
        now = datetime.now(timezone.utc)
        records = [
            {
                "hash_name": "Stable Skin",
                "lowest_price": 1.0,
                "median_price": 1.0,
                "volume": 100,
                "scraped_at": (now - timedelta(hours=12 * (14 - i))).isoformat(),
            }
            for i in range(15)
        ]
        df = PriceFeatureExtractor.records_to_dataframe(records)
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 3
        features = PriceFeatureExtractor.extract_features(df, config)
        assert features["cv"] == 0.0

    def test_zero_price_filtered_out(self):
        """Zero prices should be filtered out during feature extraction."""
        now = datetime.now(timezone.utc)
        # Mostly zeros, but enough non-zero to potentially pass gate
        records = [
            {
                "hash_name": "Test",
                "lowest_price": 0.0 if i % 3 != 0 else float(i),
                "median_price": 0.0 if i % 3 != 0 else float(i) * 1.01,
                "volume": 50,
                "scraped_at": (now - timedelta(hours=12 * (14 - i))).isoformat(),
            }
            for i in range(15)
        ]

        df = PriceFeatureExtractor.records_to_dataframe(records)
        # All zero prices should have been dropped
        zero_count = (df["price"] == 0.0).sum()
        assert zero_count == 0
        # Remaining valid prices should be positive
        assert (df["price"] > 0).all()


# Need pandas import for the test helper
import pandas as pd
