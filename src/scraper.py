import logging
from typing import Optional

logger = logging.getLogger("CSMID.scraper")


class SteamMarketScraper:
    """Lightweight compatibility scraper used when the full scraper module is unavailable."""

    def __init__(self, currency: int = 1, min_request_interval: float = 4.0, max_retries: int = 3, timeout: float = 10.0):
        self.currency = currency
        self.min_request_interval = min_request_interval
        self.max_retries = max_retries
        self.timeout = timeout

    def get_price(self, appid: int, market_hash_name: str) -> Optional[dict]:
        logger.warning("Scraper backend not available; returning no price data for %s", market_hash_name)
        return None

    def _get_with_retries(self, appid: int, market_hash_name: str) -> dict:
        raise RuntimeError("Scraper backend not available")
