import logging
import requests
import numpy as np
from typing import List, Dict, Any, Optional, Tuple

from src.database import DatabaseManager
from src.env import NTFY_TOPIC, NTFY_SERVER

# Setup localized logger
logger = logging.getLogger("CSMID.analytics")


# =====================================================================
# 1. ANOMALY FILTERING ENGINE
# =====================================================================

class AnomalyFilter:
    """
    Guards price history and incoming signals against single bad data points,
    scraping glitches, currency formatting errors, and market outliers.
    """

    def __init__(
        self,
        max_pct_deviation: float = 0.40,  # Max 40% jump/drop relative to rolling median
        z_score_threshold: float = 3.0,   # Standard deviation threshold
        min_history_length: int = 3       # Min records required for statistical evaluation
    ):
        self.max_pct_deviation = max_pct_deviation
        self.z_score_threshold = z_score_threshold
        self.min_history_length = min_history_length

    def is_valid_price(self, price: Optional[float]) -> bool:
        """Sanity check: price must be a positive non-zero number."""
        return price is not None and isinstance(price, (int, float)) and price > 0.0

    def evaluate_point(
        self, 
        current_price: float, 
        history_prices: List[float]
    ) -> Tuple[bool, str]:
        """
        Evaluates whether current_price is an anomaly based on history_prices.
        Returns: (is_anomaly: bool, reason: str)
        """
        # 1. Zero/Negative/Null check
        if not self.is_valid_price(current_price):
            return True, f"Invalid or non-positive price value ({current_price})"

        # Filter out non-positive entries from history
        valid_history = [p for p in history_prices if self.is_valid_price(p)]

        # If insufficient historical depth, pass validation by default
        if len(valid_history) < self.min_history_length:
            return False, "Insufficient history depth for anomaly comparison"

        # 2. Rolling Median Deviation Test (Resilient to past outliers)
        median_price = float(np.median(valid_history))
        if median_price > 0:
            pct_change = abs(current_price - median_price) / median_price
            if pct_change > self.max_pct_deviation:
                return (
                    True, 
                    f"Deviates by {pct_change * 100:.1f}% from rolling median (${median_price:.2f})"
                )

        # 3. Z-Score Deviation Test (For items with >= 5 historical records)
        if len(valid_history) >= 5:
            mean = float(np.mean(valid_history))
            std = float(np.std(valid_history))
            if std > 0:
                z_score = abs(current_price - mean) / std
                if z_score > self.z_score_threshold:
                    return (
                        True, 
                        f"Z-score ({z_score:.2f}) exceeds threshold ({self.z_score_threshold})"
                    )

        return False, "Normal price point"

    def sanitize_series(self, price_series: List[float]) -> List[float]:
        """
        Removes single isolated bad data points from a historical price list.
        """
        clean_series: List[float] = []
        for price in price_series:
            if not self.is_valid_price(price):
                continue
            
            # Evaluate against validated history
            if len(clean_series) >= self.min_history_length:
                is_anomaly, _ = self.evaluate_point(price, clean_series[-10:])
                if is_anomaly:
                    logger.debug(f"Filtering historical anomaly point: ${price:.2f}")
                    continue
            
            clean_series.append(price)
            
        return clean_series


# =====================================================================
# 2. NOTIFICATION DISPATCHER
# =====================================================================

def send_ntfy_alert(title: str, message: str, priority: str = "default", tags: str = "chart_with_downwards_trend") -> None:
    """Dispatches push notifications via ntfy.sh."""
    if not NTFY_TOPIC:
        logger.warning("NTFY_TOPIC environment variable is not set. Skipping push notification.")
        return

    url = f"{NTFY_SERVER.rstrip('/')}/{NTFY_TOPIC}"
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags
    }

    try:
        res = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
        if res.status_code == 200:
            logger.info(f"📲 Alert sent via ntfy: '{title}'")
        else:
            logger.error(f"Failed to send ntfy alert: HTTP {res.status_code}")
    except Exception as e:
        logger.error(f"Error sending ntfy notification: {e}")


# =====================================================================
# 3. ANALYTICS PIPELINE ENTRY POINT
# =====================================================================

def run_and_notify_analytics(price_drop_threshold_pct: float = 0.08) -> None:
    """
    Main analytics workflow:
    1. Fetches recent price records from Supabase for all active items.
    2. Runs AnomalyFilter to guard against single bad data points.
    3. Calculates price trends and drop metrics on sanitized data.
    4. Triggers ntfy push notifications for genuine price drops.
    """
    logger.info("--- Running CSMID Market Analytics Engine ---")
    
    db = DatabaseManager()
    filter_engine = AnomalyFilter(max_pct_deviation=0.40, z_score_threshold=3.0)
    
    try:
        active_items = db.get_active_targets()
        if not active_items:
            logger.info("No active items found in target list.")
            return

        alerts_triggered = 0

        for skin_name in active_items:
            # Fetch recent price logs (newest first)
            history = db.get_price_history(skin_name, limit=20)
            if not history or len(history) < 2:
                continue

            # Extract prices sequentially (oldest to newest for analysis)
            raw_prices = [record.get("lowest_price", 0.0) for record in reversed(history)]
            
            latest_price = raw_prices[-1]
            past_prices = raw_prices[:-1]

            # --- ANOMALY CHECK ON LATEST DATA POINT ---
            is_anomaly, reason = filter_engine.evaluate_point(latest_price, past_prices)
            
            if is_anomaly:
                logger.warning(
                    f"⚠️ [ANOMALY SUPPRESSED] {skin_name} @ ${latest_price:.2f} — Reason: {reason}. Skipping alert."
                )
                continue

            # --- SANITIZE HISTORICAL SERIES ---
            clean_past_prices = filter_engine.sanitize_series(past_prices)
            if not clean_past_prices:
                continue

            # --- METRICS & SIGNAL DETECTION ---
            reference_price = float(np.median(clean_past_prices[-5:]))  # Median of last 5 clean readings
            
            if reference_price > 0:
                drop_pct = (reference_price - latest_price) / reference_price

                # Check if current price is a valid drop exceeding threshold
                if drop_pct >= price_drop_threshold_pct:
                    alerts_triggered += 1
                    title = f"🚨 Price Drop: {skin_name}"
                    message = (
                        f"{skin_name} dropped by {drop_pct * 100:.1f}%!\n"
                        f"Current Price: ${latest_price:.2f}\n"
                        f"Previous Median: ${reference_price:.2f}"
                    )
                    logger.info(f"🎯 Signal Detected: {skin_name} dropped {drop_pct * 100:.1f}%")
                    send_ntfy_alert(title, message, priority="high", tags="warning,moneybag")

        logger.info(f"🏁 Analytics completed. {alerts_triggered} alert(s) dispatched.")

    except Exception as e:
        logger.error(f"Error executing analytics engine: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_and_notify_analytics()