import time
import json
import random
import logging
import requests
from typing import List, Generator, Optional, Dict, Any

from src.env import (
    SCRAPINGANT_API_KEY,
    SCRAPERAPI_KEY,
    ZENROWS_API_KEY,
    SCRAPINGBEE_API_KEY,
)

logger = logging.getLogger("CSMID.discoverer")


class SteamMarketDiscoverer:
    """
    Scans the Steam Community Market listings to automatically 
    discover valid skin hash names by leveraging multi-provider proxy rotation.
    """
    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://steamcommunity.com/market/search?appid=730",
        })

    def _fetch_via_scraperapi(self, target_url: str) -> Optional[dict]:
        if not SCRAPERAPI_KEY:
            return None
        logger.info("Attempting fetch via ScraperAPI...")
        try:
            params = {"api_key": SCRAPERAPI_KEY, "url": target_url}
            res = requests.get("https://api.scraperapi.com", params=params, timeout=self.timeout)
            if res.status_code == 200:
                return res.json()
            logger.warning(f"ScraperAPI returned HTTP {res.status_code}")
        except Exception as e:
            logger.warning(f"ScraperAPI failed: {e}")
        return None

    def _fetch_via_scrapingbee(self, target_url: str) -> Optional[dict]:
        if not SCRAPINGBEE_API_KEY:
            return None
        logger.info("Attempting fetch via ScrapingBee...")
        try:
            params = {"api_key": SCRAPINGBEE_API_KEY, "url": target_url, "render_js": "false"}
            res = requests.get("https://api.scrapingbee.com/v1/", params=params, timeout=self.timeout)
            if res.status_code == 200:
                return res.json()
            logger.warning(f"ScrapingBee returned HTTP {res.status_code}")
        except Exception as e:
            logger.warning(f"ScrapingBee failed: {e}")
        return None

    def _fetch_via_zenrows(self, target_url: str) -> Optional[dict]:
        if not ZENROWS_API_KEY:
            return None
        logger.info("Attempting fetch via ZenRows...")
        try:
            params = {"apikey": ZENROWS_API_KEY, "url": target_url}
            res = requests.get("https://api.zenrows.com/v1/", params=params, timeout=self.timeout)
            if res.status_code == 200:
                return res.json()
            logger.warning(f"ZenRows returned HTTP {res.status_code}")
        except Exception as e:
            logger.warning(f"ZenRows failed: {e}")
        return None

    def _fetch_via_scrapingant(self, target_url: str) -> Optional[dict]:
        if not SCRAPINGANT_API_KEY:
            return None
        logger.info("Attempting fetch via ScrapingAnt...")
        try:
            params = {"x-api-key": SCRAPINGANT_API_KEY, "url": target_url, "browser": "false"}
            res = requests.get("https://api.scrapingant.com/v2/general", params=params, timeout=self.timeout)
            if res.status_code == 200:
                wrapper = res.json()
                if "content" in wrapper:
                    return json.loads(wrapper["content"])
                return wrapper
            logger.warning(f"ScrapingAnt returned HTTP {res.status_code}")
        except Exception as e:
            logger.warning(f"ScrapingAnt failed: {e}")
        return None

    def _fetch_payload(self, target_url: str) -> Optional[dict]:
        """Tries each proxy provider in sequence until one succeeds."""
        providers = [
            self._fetch_via_scraperapi,
            self._fetch_via_scrapingbee,
            self._fetch_via_zenrows,
            self._fetch_via_scrapingant,
        ]

        for fetch_func in providers:
            data = fetch_func(target_url)
            if data and isinstance(data, dict) and "results" in data:
                return data

        return None

    def discover_popular_skins(self, max_items: int = 500, items_per_page: int = 100) -> Generator[List[str], None, None]:
        start_offset = 0
        
        while start_offset < max_items:
            logger.info(f"Browsing Steam Market page (Items {start_offset} to {start_offset + items_per_page})...")
            
            target_steam_url = (
                f"https://steamcommunity.com/market/search/render/"
                f"?query=&start={start_offset}&count={items_per_page}"
                f"&search_descriptions=0&sort_column=popular&sort_dir=desc"
                f"&appid=730&norender=1"
            )

            steam_data = self._fetch_payload(target_steam_url)

            if not steam_data:
                logger.error("All proxy providers failed or returned invalid data from Steam.")
                break

            raw_results = steam_data.get("results", [])
            if not raw_results:
                logger.info("Reached the end of available search pages.")
                break

            batch_names = [item["hash_name"] for item in raw_results if "hash_name" in item]
            yield batch_names

            total_listings = steam_data.get("total_count", max_items)
            if start_offset + items_per_page >= total_listings:
                break

            start_offset += items_per_page

            human_delay = random.uniform(3.0, 6.0)
            logger.info(f"Waiting {human_delay:.1f}s before next page query...")
            time.sleep(human_delay)