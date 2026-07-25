"""
tests/test_prediction_report.py — Tests for report formatting modules.
"""

import os
import sys
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.prediction_report import (
    format_forecast_report,
    format_forecast_summary_ntfy,
    format_backtest_report,
    format_forecast_markdown,
    format_backtest_markdown,
)


# =====================================================================
# FORECAST REPORT TESTS
# =====================================================================

class TestFormatForecastReport:

    def test_empty_forecasts_message(self):
        """When no forecasts exist, report should say so."""
        results = {
            "summary": {"total_skins": 5, "forecasted": 0, "gated_out": 5, "errors": 0},
            "forecasts": {},
            "gated_out": [{"skin_name": "X", "n_points": 3, "reason": "test"}],
            "errors": [],
            "config": {"horizon_hours": 12, "min_data_points": 10, "min_distinct_days": 5},
        }
        report = format_forecast_report(results)
        assert "No skins have enough data" in report
        assert "GATED OUT" in report

    def test_forecasts_present_in_report(self):
        """When forecasts exist, they should appear in the report."""
        results = {
            "summary": {"total_skins": 3, "forecasted": 2, "gated_out": 1, "errors": 0},
            "forecasts": {
                "Skin A": {
                    "skin_name": "Skin A",
                    "predicted_price": 1.25,
                    "direction": "UP",
                    "confidence": 0.7,
                    "pct_change": 5.0,
                    "horizon_hours": 12,
                    "components": {"weights": {"trend": 0.3, "mean_reversion": 0.4, "persistence": 0.3}},
                    "features": {"current_price": 1.19},
                },
                "Skin B": {
                    "skin_name": "Skin B",
                    "predicted_price": 2.10,
                    "direction": "FLAT",
                    "confidence": 0.4,
                    "pct_change": 0.5,
                    "horizon_hours": 12,
                    "components": {"weights": {"trend": 0.25, "mean_reversion": 0.5, "persistence": 0.25}},
                    "features": {"current_price": 2.09},
                },
            },
            "gated_out": [{"skin_name": "Skin C", "n_points": 2, "reason": "need 10"}],
            "errors": [],
            "config": {"horizon_hours": 12, "min_data_points": 10, "min_distinct_days": 5},
        }
        report = format_forecast_report(results)
        assert "Skin A" in report
        assert "Skin B" in report
        assert "Skin C" in report
        assert "$1.25" in report or "1.25" in report
        assert "UP" in report

    def test_report_sorted_by_confidence(self):
        """Higher confidence forecasts should appear first."""
        results = {
            "summary": {"total_skins": 2, "forecasted": 2, "gated_out": 0, "errors": 0},
            "forecasts": {
                "Low": {
                    "skin_name": "Low",
                    "predicted_price": 1.0,
                    "direction": "FLAT",
                    "confidence": 0.3,
                    "pct_change": 0.0,
                    "horizon_hours": 12,
                    "components": {"weights": {"trend": 0.3, "mean_reversion": 0.4, "persistence": 0.3}},
                    "features": {"current_price": 1.0},
                },
                "High": {
                    "skin_name": "High",
                    "predicted_price": 2.0,
                    "direction": "UP",
                    "confidence": 0.9,
                    "pct_change": 3.0,
                    "horizon_hours": 12,
                    "components": {"weights": {"trend": 0.3, "mean_reversion": 0.4, "persistence": 0.3}},
                    "features": {"current_price": 1.94},
                },
            },
            "gated_out": [],
            "errors": [],
            "config": {"horizon_hours": 12, "min_data_points": 10, "min_distinct_days": 5},
        }
        report = format_forecast_report(results)
        high_pos = report.index("High")
        low_pos = report.index("Low")
        assert high_pos < low_pos


class TestFormatNtfySummary:

    def test_no_forecasts_message(self):
        results = {"summary": {"gated_out": 5, "forecasted": 0}, "forecasts": {}}
        msg = format_forecast_summary_ntfy(results)
        assert "No forecasts" in msg

    def test_only_flat_signals(self):
        results = {
            "summary": {"gated_out": 0, "forecasted": 2},
            "forecasts": {
                "A": {"pct_change": 1.0, "skin_name": "A", "confidence": 0.5,
                       "predicted_price": 1.01, "features": {"current_price": 1.0}, "direction": "FLAT"},
                "B": {"pct_change": -0.5, "skin_name": "B", "confidence": 0.4,
                       "predicted_price": 0.995, "features": {"current_price": 1.0}, "direction": "FLAT"},
            },
        }
        msg = format_forecast_summary_ntfy(results)
        assert "FLAT" in msg

    def test_actionable_signals_formatted(self):
        results = {
            "summary": {"gated_out": 10, "forecasted": 5},
            "forecasts": {
                "X": {"pct_change": 8.5, "skin_name": "X", "confidence": 0.8,
                      "predicted_price": 1.085, "features": {"current_price": 1.0}, "direction": "UP"},
            },
        }
        msg = format_forecast_summary_ntfy(results)
        assert "X" in msg
        assert "8.5" in msg
        assert "10 gated out" in msg


class TestFormatBacktestReport:

    def test_empty_backtest_message(self):
        results = {"aggregate": {}, "results": [], "skipped": []}
        report = format_backtest_report(results)
        assert "No skins had sufficient data" in report

    def test_backtest_with_results(self):
        results = {
            "aggregate": {
                "n_skins_evaluated": 2,
                "n_skins_skipped": 1,
                "total_predictions": 30,
                "mean_mape_pct": 5.2,
                "median_mape_pct": 4.8,
                "mean_bias_pct": 0.3,
                "median_bias_pct": 0.1,
                "mean_direction_accuracy": 0.65,
            },
            "results": [
                {
                    "skin_name": "Skin A",
                    "n_predictions": 15,
                    "metrics": {"mape_pct": 3.0, "bias_pct": 0.1, "direction_accuracy": 0.7, "median_abs_error_pct": 2.5, "rmse_pct": 3.5},
                },
                {
                    "skin_name": "Skin B",
                    "n_predictions": 15,
                    "metrics": {"mape_pct": 7.4, "bias_pct": 0.5, "direction_accuracy": 0.6, "median_abs_error_pct": 6.0, "rmse_pct": 8.0},
                },
            ],
            "skipped": [{"skin_name": "Skin C", "n_points": 3, "reason": "insufficient"}],
        }
        report = format_backtest_report(results)
        assert "Skin A" in report
        assert "Skin B" in report
        assert "Skin C" in report
        assert "MAPE" in report
        assert "dir accuracy" in report or "Direction accuracy" in report


class TestMarkdownReports:

    def test_forecast_markdown_basic(self):
        results = {
            "summary": {"total_skins": 1, "forecasted": 1, "gated_out": 0, "errors": 0},
            "forecasts": {
                "Test": {"skin_name": "Test", "predicted_price": 1.5, "direction": "UP",
                         "confidence": 0.7, "pct_change": 5.0, "horizon_hours": 12,
                         "components": {"weights": {"trend": 0.3, "mean_reversion": 0.4, "persistence": 0.3}},
                         "features": {"current_price": 1.43}},
            },
            "gated_out": [],
            "config": {"horizon_hours": 12, "min_data_points": 10, "min_distinct_days": 5},
        }
        md = format_forecast_markdown(results)
        assert "# CSMID Forecast Report" in md
        assert "| Skin |" in md
        assert "Test" in md

    def test_backtest_markdown_basic(self):
        results = {
            "aggregate": {"n_skins_evaluated": 1, "n_skins_skipped": 0, "total_predictions": 10,
                          "mean_mape_pct": 5.0, "median_mape_pct": 4.5, "mean_bias_pct": 0.2,
                          "median_bias_pct": 0.1, "mean_direction_accuracy": 0.7},
            "results": [
                {"skin_name": "S1", "n_predictions": 10,
                 "metrics": {"mape_pct": 5.0, "bias_pct": 0.2, "direction_accuracy": 0.7,
                             "median_abs_error_pct": 4.0, "rmse_pct": 6.0}},
            ],
            "skipped": [],
        }
        md = format_backtest_markdown(results)
        assert "# CSMID Walk-Forward Backtest Report" in md
        assert "| Skin |" in md

    def test_backtest_markdown_no_data(self):
        results = {"aggregate": {}, "results": [], "skipped": []}
        md = format_backtest_markdown(results)
        assert "No skins had sufficient data" in md
