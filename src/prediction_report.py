"""
src/prediction_report.py — Formatted prediction & backtest reports

Generates human-readable text reports and optional Markdown summaries
for both live forecasts and walk-forward backtest results.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger("CSMID.prediction_report")


# =====================================================================
# 1. LIVE FORECAST REPORT
# =====================================================================

def format_forecast_report(results: Dict[str, Any]) -> str:
    """
    Format a live forecast pipeline result into a readable text report.

    Args:
        results: Output from forecaster.generate_forecasts()

    Returns:
        Multi-line formatted string suitable for logging or ntfy.
    """
    summary = results["summary"]
    forecasts = results["forecasts"]
    gated_out = results["gated_out"]
    config_info = results["config"]

    lines = []
    lines.append("=" * 60)
    lines.append("  CSMID FORECAST REPORT")
    lines.append(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("=" * 60)
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    lines.append(f"  Total tracked skins:  {summary['total_skins']}")
    lines.append(f"  Forecasted:           {summary['forecasted']}")
    lines.append(f"  Gated out (insufficient data): {summary['gated_out']}")
    lines.append(f"  Errors:               {summary['errors']}")
    lines.append(f"  Horizon:              {config_info['horizon_hours']}h")
    lines.append(f"  Min data required:    {config_info['min_data_points']} points / {config_info['min_distinct_days']} days")
    lines.append("")

    if not forecasts:
        lines.append("  No skins have enough data for forecasting yet.")
        if gated_out:
            lines.append("")
            lines.append("GATED OUT (nearest to threshold):")
            sorted_gated = sorted(gated_out, key=lambda x: x["n_points"], reverse=True)[:10]
            for item in sorted_gated:
                lines.append(f"  - {item['skin_name']}: {item['n_points']} pts — {item['reason']}")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    # Forecasts sorted by confidence descending
    sorted_forecasts = sorted(
        forecasts.values(),
        key=lambda x: x["confidence"],
        reverse=True,
    )

    lines.append("FORECASTS (sorted by confidence)")
    lines.append("-" * 60)

    for fc in sorted_forecasts:
        direction_icon = {"UP": "+", "DOWN": "-", "FLAT": "~"}.get(fc["direction"], "?")
        lines.append(f"  {fc['skin_name']}")
        lines.append(f"    Current:  ${fc['features']['current_price']:.4f}")
        lines.append(f"    Predicted: ${fc['predicted_price']:.4f}  [{direction_icon}{abs(fc['pct_change']):.2f}%]")
        lines.append(f"    Direction: {fc['direction']}  |  Confidence: {fc['confidence']:.3f}")
        lines.append(f"    Horizon:   {fc['horizon_hours']}h")
        lines.append(f"    Model blend: trend={fc['components']['weights']['trend']:.0%}, "
                     f"revert={fc['components']['weights']['mean_reversion']:.0%}, "
                     f"persist={fc['components']['weights']['persistence']:.0%}")
        lines.append("")

    # Gated out
    if gated_out:
        lines.append("")
        lines.append(f"GATED OUT ({len(gated_out)} skins — insufficient data)")
        lines.append("-" * 60)
        sorted_gated = sorted(gated_out, key=lambda x: x["n_points"], reverse=True)[:15]
        for item in sorted_gated:
            lines.append(f"  - {item['skin_name']}: {item['n_points']} pts")
        if len(gated_out) > 15:
            lines.append(f"  ... and {len(gated_out) - 15} more")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def format_forecast_summary_ntfy(results: dict) -> str:
    """Format short summary for ntfy notifications (filters out experimental/unpromoted forecasts)."""
    forecasts = results.get("forecasts", {})
    
    # Filter out experimental predictions
    promoted_forecasts = {
        skin: f for skin, f in forecasts.items() 
        if not f.get("is_experimental", False)
    }
    
    summary = results.get("summary", {})
    total = summary.get("total_skins", 0)
    gated_out = summary.get("gated_out", 0)
    promoted_count = len(promoted_forecasts)

    if not forecasts:
        return f"📊 CSMID Forecast: No forecasts yet ({gated_out} gated out, not enough data)."

    if not promoted_forecasts:
        return (
            f"📊 CSMID Forecast: 0/{total} skins promoted. "
            f"({gated_out} gated out, not enough data yet)."
        )

    lines = [
        f"📊 CSMID Forecast ({promoted_count}/{total} Promoted, "
        f"{gated_out} gated out):"
    ]
    emoji_by_direction = {"UP": "📈", "DOWN": "📉", "FLAT": "➡️"}
    for skin, f in promoted_forecasts.items():
        curr = f.get("features", {}).get("current_price", 0.0)
        pred = f.get("predicted_price", 0.0)
        pct = f.get("pct_change", 0.0)
        direction = f.get("direction", "FLAT")
        emoji = emoji_by_direction.get(direction, "➡️")
        lines.append(f"{emoji} {skin} [{direction}]: ${curr:.2f} ➔ ${pred:.2f} ({pct:+.1f}%)")

    return "\n".join(lines)


# =====================================================================
# 2. BACKTEST REPORT
# =====================================================================

def format_backtest_report(results: Dict[str, Any]) -> str:
    """
    Format a walk-forward backtest result into a readable text report.

    Args:
        results: Output from backtest.run_backtest()

    Returns:
        Multi-line formatted string.
    """
    aggregate = results["aggregate"]
    per_skin = results["results"]
    skipped = results["skipped"]

    lines = []
    lines.append("=" * 60)
    lines.append("  CSMID WALK-FORWARD BACKTEST REPORT")
    lines.append(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("=" * 60)
    lines.append("")

    if not aggregate:
        lines.append("  No skins had sufficient data for backtesting.")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    # Aggregate metrics
    lines.append("AGGREGATE METRICS")
    lines.append(f"  Skins evaluated:    {aggregate['n_skins_evaluated']}")
    lines.append(f"  Skins skipped:      {aggregate['n_skins_skipped']}")
    lines.append(f"  Total predictions:  {aggregate['total_predictions']}")
    lines.append(f"  Mean MAPE:          {aggregate['mean_mape_pct']:.2f}%")
    lines.append(f"  Median MAPE:        {aggregate['median_mape_pct']:.2f}%")
    lines.append(f"  Mean bias:          {aggregate['mean_bias_pct']:+.2f}%")
    lines.append(f"  Median bias:        {aggregate['median_bias_pct']:+.2f}%")
    lines.append(f"  Mean dir accuracy:  {aggregate['mean_direction_accuracy']:.1%}")
    lines.append("")

    # Per-skin results sorted by MAPE (best first)
    if per_skin:
        lines.append("PER-SKIN RESULTS (sorted by MAPE, best first)")
        lines.append("-" * 60)

        sorted_skins = sorted(per_skin, key=lambda x: x["metrics"]["mape_pct"])
        for s in sorted_skins:
            m = s["metrics"]
            lines.append(f"  {s['skin_name']}")
            lines.append(f"    Predictions: {s['n_predictions']}")
            lines.append(f"    MAPE:        {m['mape_pct']:.2f}%")
            lines.append(f"    Bias:        {m['bias_pct']:+.2f}%")
            lines.append(f"    Dir acc:     {m['direction_accuracy']:.1%}")
            lines.append("")

    # Skipped skins
    if skipped:
        lines.append(f"SKIPPED ({len(skipped)} skins)")
        lines.append("-" * 60)
        for s in skipped[:10]:
            reason = s.get("error", s.get("reason", "unknown"))
            lines.append(f"  - {s['skin_name']}: {reason}")
        if len(skipped) > 10:
            lines.append(f"  ... and {len(skipped) - 10} more")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


# =====================================================================
# 3. MARKDOWN REPORT (for documentation / sharing)
# =====================================================================

def format_forecast_markdown(results: Dict[str, Any]) -> str:
    """Generate a Markdown-formatted forecast report."""
    summary = results["summary"]
    forecasts = results["forecasts"]
    gated_out = results["gated_out"]

    lines = []
    lines.append("# CSMID Forecast Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Horizon:** {results['config']['horizon_hours']}h")
    lines.append(f"**Min data required:** {results['config']['min_data_points']} points / {results['config']['min_distinct_days']} days")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total tracked skins | {summary['total_skins']} |")
    lines.append(f"| Forecasted | {summary['forecasted']} |")
    lines.append(f"| Gated out | {summary['gated_out']} |")
    lines.append(f"| Errors | {summary['errors']} |")
    lines.append("")

    if forecasts:
        lines.append("## Forecasts")
        lines.append("")
        lines.append("| Skin | Current | Predicted | Direction | Change | Confidence |")
        lines.append("|------|---------|-----------|-----------|--------|------------|")
        sorted_fc = sorted(forecasts.values(), key=lambda x: x["confidence"], reverse=True)
        for fc in sorted_fc:
            lines.append(
                f"| {fc['skin_name']} | ${fc['features']['current_price']:.4f} "
                f"| ${fc['predicted_price']:.4f} | {fc['direction']} "
                f"| {fc['pct_change']:+.2f}% | {fc['confidence']:.3f} |"
            )
        lines.append("")

    if gated_out:
        lines.append(f"## Gated Out ({len(gated_out)} skins)")
        lines.append("")
        sorted_gated = sorted(gated_out, key=lambda x: x["n_points"], reverse=True)
        for item in sorted_gated[:20]:
            lines.append(f"- **{item['skin_name']}**: {item['n_points']} points — {item['reason']}")
        if len(gated_out) > 20:
            lines.append(f"- ... and {len(gated_out) - 20} more")
        lines.append("")

    return "\n".join(lines)


def format_backtest_markdown(results: Dict[str, Any]) -> str:
    """Generate a Markdown-formatted backtest report."""
    aggregate = results["aggregate"]
    per_skin = results["results"]

    lines = []
    lines.append("# CSMID Walk-Forward Backtest Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    if not aggregate:
        lines.append("No skins had sufficient data for backtesting.")
        return "\n".join(lines)

    lines.append("## Aggregate Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Skins evaluated | {aggregate['n_skins_evaluated']} |")
    lines.append(f"| Skins skipped | {aggregate['n_skins_skipped']} |")
    lines.append(f"| Total predictions | {aggregate['total_predictions']} |")
    lines.append(f"| Mean MAPE | {aggregate['mean_mape_pct']:.2f}% |")
    lines.append(f"| Median MAPE | {aggregate['median_mape_pct']:.2f}% |")
    lines.append(f"| Mean bias | {aggregate['mean_bias_pct']:+.2f}% |")
    lines.append(f"| Mean direction accuracy | {aggregate['mean_direction_accuracy']:.1%} |")
    lines.append("")

    if per_skin:
        lines.append("## Per-Skin Results")
        lines.append("")
        lines.append("| Skin | Predictions | MAPE | Bias | Dir Accuracy |")
        lines.append("|------|-------------|------|------|--------------|")
        sorted_skins = sorted(per_skin, key=lambda x: x["metrics"]["mape_pct"])
        for s in sorted_skins:
            m = s["metrics"]
            lines.append(
                f"| {s['skin_name']} | {s['n_predictions']} "
                f"| {m['mape_pct']:.2f}% | {m['bias_pct']:+.2f}% "
                f"| {m['direction_accuracy']:.1%} |"
            )
        lines.append("")

    return "\n".join(lines)