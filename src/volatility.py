import logging
import numpy as np
from typing import List, Tuple, Any

logger = logging.getLogger("CSMID.volatility")


class VolatilityManager:
    """
    Evaluates price volatility using the Coefficient of Variation (CV = std / mean)
    and determines dynamic scraping intervals to optimize API usage.
    """

    # Tier thresholds and minimum scrape interval (in hours)
    TIER_INTERVALS = {
        "HIGH": 6,     # Volatile / New items: scrape every 6h (every run)
        "MEDIUM": 24,  # Moderate volatility: scrape once per day
        "LOW": 72,     # Stable baseline: scrape once every 3 days
    }

    def __init__(self, high_threshold: float = 0.05, low_threshold: float = 0.02):
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold

    def calculate_tier(self, history_prices: List[Any]) -> Tuple[str, float, int]:
        """
        Calculates Coefficient of Variation (CV) from historical prices.

        Returns:
            Tuple[tier_name (str), cv_score (float), required_interval_hours (int)]
        """
        valid_prices = []
        for p in history_prices:
            try:
                val = float(p)
                if val > 0:
                    valid_prices.append(val)
            except (ValueError, TypeError):
                continue

        # Cold-Start rule: New items or sparse history (< 3 records) default to HIGH priority
        if len(valid_prices) < 3:
            return "HIGH", 0.0, self.TIER_INTERVALS["HIGH"]

        mean = float(np.mean(valid_prices))
        std = float(np.std(valid_prices))

        if mean == 0:
            return "HIGH", 0.0, self.TIER_INTERVALS["HIGH"]

        cv = std / mean

        if cv >= self.high_threshold:
            tier = "HIGH"
        elif cv >= self.low_threshold:
            tier = "MEDIUM"
        else:
            tier = "LOW"

        interval = self.TIER_INTERVALS[tier]
        return tier, cv, interval


def get_scrape_interval_for_item(skin_name: str, db: Any) -> Tuple[str, float, int]:
    """
    Queries database for recent price history of skin_name and returns:
    (tier_name, cv_score, required_interval_hours)
    """
    prices = []
    try:
        if hasattr(db, "get_price_history"):
            records = db.get_price_history(skin_name, limit=15)
        elif hasattr(db, "get_recent_prices"):
            records = db.get_recent_prices(skin_name, limit=15)
        else:
            records = []

        for r in records:
            if isinstance(r, dict):
                p = r.get("lowest_price") or r.get("price")
            elif isinstance(r, (int, float)):
                p = r
            else:
                p = getattr(r, "lowest_price", None)
            
            if p is not None:
                prices.append(p)
    except Exception as e:
        logger.debug(f"Could not fetch price history for {skin_name}: {e}")
        prices = []

    vm = VolatilityManager()
    return vm.calculate_tier(prices)