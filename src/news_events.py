"""
src/news_events.py — Patch Notes & News Event Ingestion Engine for CSMID

Polls Valve Steam News API for CS2, categorizes update events, identifies
affected item categories/weapons, and computes signal modulation factors.
"""

import re
import logging
import requests
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger("CSMID.news")

STEAM_NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v0002/"
CS2_APP_ID = 730

# Known high-impact keywords mapped to market categories
EVENT_RULES = {
    "WEAPON_REBALANCE": {
        "keywords": [r"\bnerf\b", r"\bbuff\b", r"recoil", r"accuracy", r"damage", r"rate of fire", r"silencer"],
        "impact_score": 0.8,
        "cooldown_hours": 48,
    },
    "ECONOMY_TRADE_RULES": {
        "keywords": [r"trade up", r"covert", r"marketable", r"tradable", r"armory", r"key", r"rental"],
        "impact_score": 1.0,  # Extreme market volatility
        "cooldown_hours": 72,
    },
    "DROP_POOL_CHANGE": {
        "keywords": [r"active duty", r"discontinued", r"rare drop", r"case", r"collection"],
        "impact_score": 0.9,
        "cooldown_hours": 96,
    },
    "MAJOR_ESPORTS": {
        "keywords": [r"major", r"sticker", r"capsule", r"souvenir", r"pick'em", r"pass"],
        "impact_score": 0.6,
        "cooldown_hours": 24,
    }
}


class PatchNoteIngestor:
    """Fetches, parses, and classifies official CS2 update news."""

    def __init__(self):
        self.seen_hashes = set()

    def fetch_latest_news(self, count: int = 5) -> List[Dict[str, Any]]:
        """Fetch latest news items from Steam API for CS2."""
        params = {
            "appid": CS2_APP_ID,
            "count": count,
            "maxlength": 1000,
            "format": "json"
        }
        try:
            resp = requests.get(STEAM_NEWS_URL, params=params, timeout=10)
            resp.raise_for_status()
            news_items = resp.json().get("appnews", {}).get("newsitems", [])
            return news_items
        except Exception as exc:
            logger.error("Failed to fetch Steam News: %s", exc)
            return []

    def classify_news_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Classify event impact and extract target weapon/item tags."""
        title = item.get("title", "")
        contents = item.get("contents", "")
        full_text = f"{title}\n{contents}".lower()

        # Compute content hash to prevent duplicate processing
        item_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
        if item_hash in self.seen_hashes:
            return None
        self.seen_hashes.add(item_hash)

        matched_categories = []
        max_impact = 0.0

        for cat, rule in EVENT_RULES.items():
            for kw in rule["keywords"]:
                if re.search(kw, full_text):
                    matched_categories.append(cat)
                    max_impact = max(max_impact, rule["impact_score"])
                    break

        if not matched_categories:
            return None

        # Basic entity extraction for weapons
        weapons = ["awp", "m4a1-s", "m4a4", "ak-47", "usps", "glock", "deagle", "mp9"]
        affected_weapons = [w for w in weapons if w in full_text]

        return {
            "id": item.get("gid"),
            "title": title,
            "url": item.get("url"),
            "date": datetime.fromtimestamp(item.get("date", 0)).isoformat(),
            "categories": matched_categories,
            "max_impact": max_impact,
            "affected_weapons": affected_weapons,
            "snippet": contents[:200] + "..." if len(contents) > 200 else contents
        }


class EventDrivenSignalModifier:
    """Adjusts baseline / neural forecaster signals based on active news events."""

    @staticmethod
    def adjust_signal(
        base_signal: Dict[str, Any],
        active_events: List[Dict[str, Any]],
        skin_name: str
    ) -> Dict[str, Any]:
        """
        Overlays active patch note events onto standard buy/sell signals.
        """
        skin_lower = skin_name.lower()
        adjusted = dict(base_signal)
        adjusted["news_warning"] = False
        adjusted["news_action_override"] = None

        for event in active_events:
            # Check if this skin matches an affected weapon or category
            weapon_match = any(w in skin_lower for w in event.get("affected_weapons", []))
            is_economy = "ECONOMY_TRADE_RULES" in event.get("categories", [])
            is_case = "DROP_POOL_CHANGE" in event.get("categories", []) and "case" in skin_lower

            if weapon_match or is_economy or is_case:
                adjusted["news_warning"] = True
                impact = event["max_impact"]

                # High impact updates increase risk and pause speculative BUY signals
                if impact >= 0.8 and adjusted.get("direction") == "BUY":
                    adjusted["news_action_override"] = "HOLD_NEWS_VOLATILITY"
                    adjusted["recommendation"] = (
                        f"PAUSE BUY: Recent patch ({event['title']}) creates high market volatility."
                    )
                elif is_case and "DROP_POOL_CHANGE" in event.get("categories", []):
                    adjusted["news_action_override"] = "URGENT_REVIEW"
                    adjusted["recommendation"] = (
                        f"ATTENTION: Potential drop pool shift detected in patch notes."
                    )

        return adjusted