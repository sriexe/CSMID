import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import text

# Native database & tracking engine dependencies
from src.scraper import SteamMarketScraper
from src.database import SessionLocal, MarketHistory, Skin, get_or_create_skin, insert_market_history
from scheduler.state import load_state, save_state

logger = logging.getLogger("csmid.collection_manager")

class CollectionManager:
    def __init__(self):
        try:
            self.scraper = SteamMarketScraper()
            logger.info("SteamMarketScraper engine successfully initialized.")
        except Exception as e:
            logger.error(f"Failed to instantiate SteamMarketScraper engine: {e}")
            self.scraper = None

        self.session = SessionLocal()
        
    def get_recently_collected_names(self, since_hours=20) -> set:
        """Queries MarketHistory for skins successfully updated within the window to skip them."""
        time_threshold = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        
        try:
            recent_records = (
                self.session.query(MarketHistory.market_hash_name)
                .filter(MarketHistory.collected_at_utc >= time_threshold)
                .filter(MarketHistory.success == True)
                .all()
            )
            names_set = {record[0] for record in recent_records}
            return names_set
        except Exception as e:
            logger.error(f"Database query failed in get_recently_collected_names: {e}")
            return set()

    def _store_record(self, record_data):
        """
        Inserts the scraped observation into the database using native helpers.
        Handles both dictionary formats and raw class objects defensively.
        """
        try:
            if isinstance(record_data, dict):
                market_hash_name = record_data.get("market_hash_name")
            else:
                market_hash_name = getattr(record_data, "market_hash_name", None)

            if not market_hash_name:
                raise ValueError("Scraped payload is missing a valid 'market_hash_name' property.")

            skin = get_or_create_skin(self.session, market_hash_name)
            insert_market_history(self.session, skin, record_data)
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error(f"Failed to commit market record to database: {e}")
            raise e

    def collect_skin(self, skin_name: str) -> int:
        """
        Collects a single skin. 
        Returns 0 on success, 2 on HTTP 429, 1 on other errors.
        """
        if not self.scraper:
            logger.error(f"Scraper core is uninitialized. Skipping active call for: {skin_name}")
            return 1

        logger.info(f"Scraping skin data for: {skin_name}")
        try:
            result = self.scraper.fetch_price(skin_name) 
            
            if not result:
                logger.error(f"Scraper returned empty payload response for {skin_name}")
                return 1

            # --- DEFENSIVE DATA EXTRACTION LAYER ---
            # Handles both standard dicts and RawMarketRecord custom objects seamlessly
            if isinstance(result, dict):
                status_code = result.get("status_code")
                success = result.get("success")
                data = result.get("data")
            else:
                status_code = getattr(result, "status_code", None)
                success = getattr(result, "success", None)
                # Fallback to the object itself if it doesn't wrap data inside an attribute
                data = getattr(result, "data", result)

            if status_code == 429:
                logger.error(f"Rate limited while scraping {skin_name}")
                return 2
                
            if success or (success is None and data):
                self._store_record(data)
                logger.info(f"Successfully recorded price for {skin_name}")
                return 0
                
            return 1
            
        except Exception as e:
            logger.error(f"Unexpected error collecting skin {skin_name}: {e}")
            return 1

    def collect_queue(self, watchlist_path: str, resume: bool = False, since_hours: int = 20) -> int:
        """
        Reads the target watchlist, checks the skip list (DB), slices the batch 
        using queue_state.json, and runs the collection engine.
        """
        try:
            with open(watchlist_path, "r", encoding="utf-8") as f:
                all_skins = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            logger.error(f"Watchlist file not found: {watchlist_path}")
            return 1

        skip_names = set()
        if resume:
            skip_names = self.get_recently_collected_names(since_hours=since_hours)
            logger.info(f"Resume active: Skipping {len(skip_names)} skins collected in past {since_hours} hours.")

        state = load_state()
        start_idx = state["current_index"]
        batch_size = state["batch_size"]
        
        if start_idx >= len(all_skins):
            logger.info("Reached the end of the watchlist. Resetting queue index to 0.")
            start_idx = 0

        end_idx = min(start_idx + batch_size, len(all_skins))
        target_batch = all_skins[start_idx:end_idx]
        
        logger.info(f"Processing queue batch: Index {start_idx} to {end_idx} (Total skins: {len(all_skins)})")

        for current_idx, skin in enumerate(target_batch, start=start_idx):
            if skin in skip_names:
                logger.info(f"Skipping (Already fresh in DB): {skin}")
                continue
                
            exit_code = self.collect_skin(skin)
            
            if exit_code == 2:
                save_state(
                    current_index=current_idx, 
                    batch_size=batch_size, 
                    last_skin=skin, 
                    status="RATE_LIMITED"
                )
                return 2 
                
            if exit_code != 0:
                logger.warning(f"Failed to scrape {skin}, moving on...")

        new_start_index = end_idx
        status = "COMPLETED" if new_start_index >= len(all_skins) else "RUNNING"
        
        save_state(
            current_index=new_start_index, 
            batch_size=batch_size, 
            last_skin=target_batch[-1] if target_batch else None, 
            status=status
        )
        
        return 0