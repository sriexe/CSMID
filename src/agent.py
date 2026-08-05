"""
src/agent.py — CSMID Market Copilot Agent

Provides structured tools for an AI Chat Copilot to interact with Supabase,
evaluate model directional accuracy (90%+ thresholds), filter buy signals
by user budget, and remember specific skin watchlists (e.g. Glock-18 | Block-18).
"""

import os
import logging
from typing import List, Dict, Any, Optional
from supabase import create_client, Client

from src.forecaster import BaselineForecaster, PriceFeatureExtractor
from src.backtest import WalkForwardBacktester
from src.news_events import PatchNoteIngestor, EventDrivenSignalModifier

logger = logging.getLogger("CSMID.agent")


class CSMIDMarketAgent:
    """
    Tool provider for the conversational AI Copilot.
    """

    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase: Client = create_client(supabase_url, supabase_key)
        self.forecaster = BaselineForecaster()
        self.backtester = WalkForwardBacktester(forecaster=self.forecaster)
        self.news_ingestor = PatchNoteIngestor()

    # -----------------------------------------------------------------
    # TOOL 1: Watchlist & Single Skin Inspection (e.g., Glock-18 Block-18)
    # -----------------------------------------------------------------
    def inspect_skin(self, skin_name: str) -> Dict[str, Any]:
        """
        Fetches current market price, forecasted price, backtested direction
        accuracy, and active news events for a specific item.
        """
        res = self.supabase.table("price_records").select("*").eq("skin_name", skin_name).order("timestamp", desc=False).execute()
        records = res.data or []

        if not records:
            return {"error": f"No historical records found in Supabase for '{skin_name}'."}

        # 1. Compute historical accuracy via backtester
        backtest_res = self.backtester.backtest_skin(skin_name, records)
        metrics = backtest_res.get("baseline_metrics", {}) if backtest_res else {}

        # 2. Extract features and forecast
        extractor = PriceFeatureExtractor()
        df = extractor.records_to_dataframe(records)
        features = extractor.extract_features(df)
        forecast = self.forecaster.forecast(features) if features else {}

        # 3. Apply active news event overrides
        latest_news = self.news_ingestor.fetch_latest_news(count=3)
        active_events = [
            self.news_ingestor.classify_news_item(n)
            for n in latest_news if self.news_ingestor.classify_news_item(n) is not None
        ]
        adjusted = EventDrivenSignalModifier.adjust_signal(forecast, active_events, skin_name)

        curr_price = float(records[-1].get("price", 0.0))
        pred_price = float(forecast.get("predicted_price", curr_price))

        return {
            "skin_name": skin_name,
            "current_price": round(curr_price, 2),
            "predicted_price": round(pred_price, 2),
            "predicted_move": round(pred_price - curr_price, 2),
            "signal": adjusted.get("news_action_override") or adjusted.get("direction", "NEUTRAL"),
            "historical_direction_accuracy": f"{metrics.get('direction_accuracy', 0.0)}%",
            "news_warning": adjusted.get("news_warning", False),
            "summary": adjusted.get("recommendation", forecast.get("reasoning", ""))
        }

    # -----------------------------------------------------------------
    # TOOL 2: Budget-Aware Buy Recommendations
    # -----------------------------------------------------------------
    def recommend_buys_by_budget(self, max_budget_usd: float, top_n: int = 3) -> Dict[str, Any]:
        """
        Scans tracked market items, filters out items exceeding budget,
        and ranks candidate BUY signals by model direction accuracy and upside.
        """
        skins_res = self.supabase.table("price_records").select("skin_name").execute()
        tracked_skins = list(set(r["skin_name"] for r in (skins_res.data or [])))

        recommendations = []
        for skin in tracked_skins:
            info = self.inspect_skin(skin)
            if "error" in info:
                continue

            price = info["current_price"]
            sig = info["signal"]
            accuracy_val = float(info["historical_direction_accuracy"].replace("%", ""))

            # Must fit budget, be a BUY signal, and have no news hold
            if price <= max_budget_usd and sig == "BUY" and not info["news_warning"]:
                upside_pct = ((info["predicted_price"] - price) / price) * 100 if price > 0 else 0
                recommendations.append({
                    "skin_name": skin,
                    "price_usd": price,
                    "target_price_usd": info["predicted_price"],
                    "projected_gain_pct": round(upside_pct, 2),
                    "model_direction_accuracy": f"{accuracy_val}%",
                    "_sort_score": accuracy_val * upside_pct
                })

        # Rank by confidence-weighted return score
        recommendations.sort(key=lambda x: x["_sort_score"], reverse=True)
        for r in recommendations:
            r.pop("_sort_score", None)

        return {
            "budget_limit": f"${max_budget_usd:.2f}",
            "recommended_buys": recommendations[:top_n]
        }

    # -----------------------------------------------------------------
    # TOOL 3: High-Confidence Sell Triggers (90%+ Accuracy Items & Cases)
    # -----------------------------------------------------------------
    def check_high_confidence_sells(self, min_accuracy_pct: float = 90.0) -> Dict[str, Any]:
        """
        Identifies inventory items or cases where the model predicts a downward trend
        AND historical direction accuracy meets or exceeds the target threshold (e.g., 90%).
        """
        portfolio_res = self.supabase.table("user_portfolio").select("*").execute()
        user_portfolio = portfolio_res.data or []

        sell_triggers = []
        for item in user_portfolio:
            skin_name = item["skin_name"]
            info = self.inspect_skin(skin_name)
            if "error" in info:
                continue

            acc_val = float(info["historical_direction_accuracy"].replace("%", ""))
            
            # Check for high-accuracy SELL signal
            if acc_val >= min_accuracy_pct and info["signal"] in ["SELL", "HOLD_NEWS_VOLATILITY"]:
                sell_triggers.append({
                    "skin_name": skin_name,
                    "quantity_held": item.get("quantity", 1),
                    "cost_basis_usd": item.get("cost_basis"),
                    "current_price": info["current_price"],
                    "target_exit_price": info["predicted_price"],
                    "model_accuracy_confidence": f"{acc_val}%",
                    "action_required": "SELL_FOR_PROFIT" if info["current_price"] > item.get("cost_basis", 0) else "CUT_LOSS"
                })

        return {
            "accuracy_threshold": f"{min_accuracy_pct}%",
            "active_sell_alerts": sell_triggers
        }