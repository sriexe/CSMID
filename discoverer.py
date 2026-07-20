import time
import random
import logging
import requests

logger = logging.getLogger("CSMID.discoverer")

class SteamMarketDiscoverer:
    """
    Scans the Steam Community Market listings to automatically 
    discover valid skin hash names by mimicking normal user browsing behavior.
    """
    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout
        self.api_key = "***REMOVED***"

    def discover_popular_skins(self, max_items: int = 500, items_per_page: int = 100):
        """
        Paginates through popular CS2 market pages.
        Yields batches of found market_hash_names to the caller.
        """
        start_offset = 0
        
        while start_offset < max_items:
            logger.info(f"Browsing Steam Market page (Items {start_offset} to {start_offset + items_per_page})...")
            
            # norender=1 tells Steam to give us raw JSON data, bypassing messy HTML parsing
            target_steam_url = (
                f"https://steamcommunity.com/market/search/render/"
                f"?query=&start={start_offset}&count={items_per_page}"
                f"&search_descriptions=0&sort_column=popular&sort_dir=desc"
                f"&appid=730&norender=1"
            )
            
            params = {
                "url": target_steam_url,
                "browser": "false",
                "proxy_type": "residential",  # Crucial for shuffling residential IPs
                "proxy_country": "US"
            }
            
            headers = {
                "x-api-key": self.api_key,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Referer": "https://steamcommunity.com/market/search?appid=730"  # Spoofs entry point
            }
            
            try:
                response = requests.get(
                    "https://api.scrapingant.com/v2/general", 
                    params=params, 
                    headers=headers, 
                    timeout=self.timeout + 15
                )
                
                if response.status_code != 200:
                    logger.error(f"Steam Search API returned error status: {response.status_code}")
                    break
                
                payload = response.json()
                if not payload.get("success") or "results" not in payload:
                    logger.warning("Steam indicated search request failure or returned empty payload.")
                    break
                
                raw_results = payload["results"]
                if not raw_results:
                    logger.info("Reached the end of available search pages.")
                    break
                
                # Extract clean hash names ready for our price scraper
                batch_names = [item["hash_name"] for item in raw_results if "hash_name" in item]
                yield batch_names
                
                # Prevent paging past absolute capacity limits
                total_listings = payload.get("total_count", max_items)
                if start_offset + items_per_page >= total_listings:
                    break
                
                # Advance page cursor
                start_offset += items_per_page
                
                # Human Jitter: Sleep a random window to look like someone checking listing entries
                human_delay = random.uniform(7.0, 14.0)
                logger.info(f"Simulating human processing. Deliberate wait for {human_delay:.1f}s...")
                time.sleep(human_delay)
                
            except Exception as err:
                logger.error(f"Network error during search automation sequence: {err}")
                break