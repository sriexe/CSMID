"""
tests/test_backtest.py — Unit tests for the walk-forward backtest framework.

Tests cover:
- Backtest on synthetic data with known properties
- Warmup period enforcement
- Insufficient data handling
- Aggregate metric computation
"""

import os
import sys
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.backtest import WalkForwardBacktester, run_backtest
from src.forecaster import ForecastConfig, PriceFeatureExtractor, BaselineForecaster


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
    trend: float = 0.005,
):
    """Generate synthetic price records with optional trend."""
    np.random.seed(42)
    records = []
    for i in range(n_points):
        noise = 1.0 + np.random.normal(0, price_noise)
        trend_factor = 1.0 + (i * trend)
        price = base_price * trend_factor * noise
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
# WALK-FORWARD BACKTESTER TESTS
# =====================================================================

class TestWalkForwardBacktester:

    def test_backtest_insufficient_data_returns_none(self):
        """Skin with fewer points than warmup + 1 should be skipped."""
        records = _make_records("Tiny Skin", 1.0, 5, start_days_ago=10)
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 3
        config.MIN_DISTINCT_DAYS = 2
        backtester = WalkForwardBacktester(config=config, warmup_periods=10)
        result = backtester.backtest_skin("Tiny Skin", records)
        assert result is None

    def test_backtest_produces_predictions(self):
        """Skin with enough data should produce predictions."""
        records = _make_records("Rich Skin", 5.0, 30, start_days_ago=60, interval_hours=12.0)
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 3
        backtester = WalkForwardBacktester(config=config, warmup_periods=10)
        result = backtester.backtest_skin("Rich Skin", records)
        assert result is not None
        assert result["skin_name"] == "Rich Skin"
        assert result["n_predictions"] > 0
        assert len(result["predictions"]) == result["n_predictions"]

    def test_backtest_predictions_have_required_fields(self):
        """Each prediction should have timestamp, predicted, actual, pct_error, direction_predicted."""
        records = _make_records("Test Skin", 2.0, 25, start_days_ago=50, interval_hours=12.0)
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 3
        backtester = WalkForwardBacktester(config=config, warmup_periods=10)
        result = backtester.backtest_skin("Test Skin", records)
        assert result is not None
        for pred in result["predictions"]:
            assert "predicted" in pred
            assert "actual" in pred
            assert "pct_error" in pred
            assert "direction_predicted" in pred
            assert pred["predicted"] > 0
            assert pred["actual"] > 0

    def test_backtest_metrics_computed(self):
        """Metrics dict should contain MAPE, median error, RMSE, direction accuracy, bias."""
        records = _make_records("Metric Skin", 3.0, 30, start_days_ago=60, interval_hours=12.0)
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 3
        backtester = WalkForwardBacktester(config=config, warmup_periods=10)
        result = backtester.backtest_skin("Metric Skin", records)
        assert result is not None
        m = result["metrics"]
        assert "mape_pct" in m
        assert "median_abs_error_pct" in m
        assert "rmse_pct" in m
        assert "direction_accuracy" in m
        assert "bias_pct" in m
        assert 0 <= m["direction_accuracy"] <= 1
        assert m["mape_pct"] >= 0

    def test_backtest_step_size_reduces_predictions(self):
        """Larger step size should produce fewer predictions."""
        records = _make_records("Step Skin", 4.0, 30, start_days_ago=60, interval_hours=12.0)
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 3

        bt1 = WalkForwardBacktester(config=config, warmup_periods=10, step_size=1)
        bt2 = WalkForwardBacktester(config=config, warmup_periods=10, step_size=3)

        r1 = bt1.backtest_skin("Step Skin", records)
        r2 = bt2.backtest_skin("Step Skin", records)

        assert r1 is not None
        assert r2 is not None
        assert r1["n_predictions"] > r2["n_predictions"]


class TestBacktestAll:

    def test_backtest_all_mixed_data(self):
        """Mix of skins with enough and insufficient data."""
        records_by_skin = {
            "Skin A": _make_records("Skin A", 1.0, 30, start_days_ago=60, interval_hours=12.0),
            "Skin B": _make_records("Skin B", 2.0, 5, start_days_ago=10),
            "Skin C": _make_records("Skin C", 3.0, 20, start_days_ago=40, interval_hours=12.0),
        }
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 3

        results = run_backtest(records_by_skin, config=config, warmup_periods=10)
        assert "results" in results
        assert "aggregate" in results
        assert "skipped" in results
        assert len(results["results"]) == 2  # A and C
        assert len(results["skipped"]) == 1  # B

    def test_backtest_all_empty_input(self):
        """Empty input should return zero results."""
        results = run_backtest({})
        assert results["aggregate"] == {}
        assert len(results["results"]) == 0

    def test_backtest_all_aggregate_has_sensible_values(self):
        """Aggregate metrics should be in reasonable ranges."""
        records_by_skin = {
            f"Skin_{i}": _make_records(f"Skin_{i}", float(i + 1), 25, start_days_ago=50, interval_hours=12.0)
            for i in range(5)
        }
        config = ForecastConfig()
        config.MIN_DATA_POINTS = 5
        config.MIN_DISTINCT_DAYS = 3

        results = run_backtest(records_by_skin, config=config, warmup_periods=10)
        agg = results["aggregate"]
        assert agg["n_skins_evaluated"] == 5
        assert agg["total_predictions"] > 0
        assert agg["mean_mape_pct"] >= 0
        assert 0 <= agg["mean_direction_accuracy"] <= 1
