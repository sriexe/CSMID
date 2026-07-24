import logging
import os
import time
import urllib.parse
from typing import Optional, Dict, Any
import requests

logger = logging.getLogger("CSMID.scraper")


class SteamMarketScraper:
    """Steam Market Price Scraper supporting ScraperAPI proxy and direct fallbacks."""

    def __init__(
        self, 
        currency: int = 1, 
        min_request_interval: float = 2.0, 
        max_retries: int = 3, 
        timeout: float = 10.0
    ):
        self.currency = currency
        self.min_request_interval = min_request_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.api_key = os.getenv("SCRAPERAPI_KEY") or os.getenv("SCRAPER_API_KEY")

    def _clean_price(self, val: Optional[str]) -> Optional[float]:
        """Convert string price like '$1,234.56' or '0,50€' into float."""
        if not val:
            return None
        try:
            cleaned = "".join([c for c in val if c.isdigit() or c in [".", ","]])
            if "," in cleaned and "." in cleaned:
                cleaned = cleaned.replace(",", "")
            elif "," in cleaned and "." not in cleaned:
                cleaned = cleaned.replace(",", ".")
            return float(cleaned)
        except Exception:
            return None

    def _clean_volume(self, val: Optional[str]) -> Optional[int]:
        """Convert string volume like '1,234' into integer."""
        if not val:
            return None
        try:
            cleaned = "".join([c for c in val if c.isdigit()])
            return int(cleaned) if cleaned else None
        except Exception:
            return None

    def get_price(self, appid: int, market_hash_name: str) -> Optional[Dict[str, Any]]:
        """Fetch and parse price overview for a given item."""
        encoded_name = urllib.parse.quote(market_hash_name)
        steam_url = (
            f"https://steamcommunity.com/market/priceoverview/"
            f"?currency={self.currency}&appid={appid}&market_hash_name={encoded_name}"
        )

        for attempt in range(1, self.max_retries + 1):
            try:
                if self.api_key:
                    params = {
                        "api_key": self.api_key,
                        "url": steam_url
                    }
                    res = requests.get("https://api.scraperapi.com", params=params, timeout=self.timeout)
                else:
                    headers = {
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Accept-Language": "en-US,en;q=0.9",
                    }
                    res = requests.get(steam_url, headers=headers, timeout=self.timeout)

                if res.status_code == 200:
                    data = res.json()
                    if data.get("success"):
                        lowest_price = self._clean_price(data.get("lowest_price"))
                        median_price = self._clean_price(data.get("median_price"))
                        volume = self._clean_volume(data.get("volume"))

                        return {
                            "skin_name": market_hash_name,
                            "hash_name": market_hash_name,
                            "lowest_price": lowest_price,
                            "median_price": median_price,
                            "volume": volume,
                            "raw": data,
                        }
                    else:
                        logger.warning("Steam API returned success=False for %s", market_hash_name)
                elif res.status_code == 429:
                    logger.warning("Rate limited by Steam (429) on attempt %d for %s", attempt, market_hash_name)
                    time.sleep(self.min_request_interval * attempt * 2)
                else:
                    logger.warning("HTTP %d for %s (attempt %d)", res.status_code, market_hash_name, attempt)

            except Exception as exc:
                logger.warning("Error fetching %s (attempt %d): %s", market_hash_name, attempt, exc)

            time.sleep(self.min_request_interval)

        logger.error("Failed to fetch price data for %s after %d retries.", market_hash_name, self.max_retries)
        return None