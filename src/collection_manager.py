import os
import sys
import json
import time
import random
import logging
import traceback
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 🔍 DIAGNOSTIC IMPORT SYSTEM: Exposes hidden internal dependency bugs
try:
    from src.scraper import SteamMarketScraper
    from src.database import DatabaseManager 
except ImportError as e:
    logger.warning(f"Could not import via absolute 'src.' path: {e}. Attempting direct relative imports...")
    try:
        from scraper import SteamMarketScraper
        from database import DatabaseManager
    except ImportError as e2:
        logger.critical("❌ CRITICAL IMPORT FAILURE: Scraper or Database files failed to load entirely.")
        logger.critical("Below is the underlying error stack trace detailing what went wrong (e.g., missing pip libraries):")
        logger.critical("\n" + "="*60 + "\n" + traceback.format_exc() + "="*60)
        sys.exit("\nExecution halted: Fix the missing modules or syntax errors listed above to continue.")

class CollectionManager:
    def __init__(self, state_file_path="queue_state.json"):
        self.state_file_path = state_file_path
        self.scraper = None
        self.db = None
        
        # Initialize the web scraper interface securely
        try:
            self.scraper = SteamMarketScraper()
        except Exception as e:
            logger.error(f"Failed to initialize SteamMarketScraper instance: {e}")

        # Initialize the database manager interface securely
        try:
            self.db = DatabaseManager()
        except Exception as e:
            logger.error(f"Failed to initialize DatabaseManager instance: {e}")

    def load_queue_state(self) -> dict:
        """Loads current progress metadata. Returns default configuration if state is missing."""
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading queue state file: {e}")
        
        return {
            "current_index": 0,
            "batch_size": 120,
            "last_skin": None,
            "status": "IDLE"
        }

    def save_queue_state(self, state: dict):
        """Saves current engine progress safely."""
        try:
            with open(self.state_file_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Error writing queue state file: {e}")

    def _is_recently_scraped(self, skin_name: str, since_hours: int) -> bool:
        """Queries the Supabase cloud database to see if a skin has been parsed recently."""
        if not self.db:
            return False
            
        try:
            # 1. First Choice: Use the robust built-in method in database.py if it exists
            if hasattr(self.db, "is_recently_scraped"):
                return self.db.is_recently_scraped(skin_name, since_hours)
            
            # 2. Second Choice: Check fallback naming
            if hasattr(self.db, "is_skin_fresh"):
                return self.db.is_skin_fresh(skin_name, since_hours)
                
            # 3. Dynamic Postgres Fallback: Direct query with proper syntax
            conn = getattr(self.db, "conn", None) or getattr(self.db, "connection", None)
            if conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM market_history 
                            WHERE skin_name = %s 
                            AND scraped_at > NOW() - (%s * INTERVAL '1 hour')
                        );
                        """, 
                        (skin_name, int(since_hours))
                    )
                    row = cursor.fetchone()
                    return row[0] if row else False
                    
        except Exception as e:
            logger.debug(f"Could not determine database history for '{skin_name}': {e}")
        
        return False

    def _store_record(self, data):
        """Pushes successfully scraped information to the database."""
        if not self.db:
            logger.warning(f"Fallback Storage: No database connection, logging raw: {data}")
            return

        # 1. Attempt to use database.py's insert_price
        if hasattr(self.db, "insert_price"):
            try:
                self.db.insert_price(data)
                return
            except Exception as e:
                logger.error(f"Failed to insert skin data using insert_price: {e}")

        # 2. Fallback: Attempt to use insert_market_data directly
        if hasattr(self.db, "insert_market_data"):
            try:
                # Extract clean variables from scraper dict format
                skin_name = data.get("skin_name") or data.get("market_hash_name")
                lowest_price = data.get("lowest_price")
                median_price = data.get("median_price")
                volume = data.get("volume")
                
                self.db.insert_market_data(skin_name, lowest_price, median_price, volume)
                return
            except Exception as e:
                logger.error(f"Failed to insert skin data using insert_market_data: {e}")
                
        logger.info(f"Fallback Storage: Standard insertion failed, logging raw: {data}")

    def collect_batch(self, skin_names: list[str], since_hours: int = 20) -> dict:
        """Compatibility wrapper for older batch-style callers."""
        if not skin_names:
            return {"processed": 0, "successes": 0, "failures": 0, "skipped": 0, "rate_limited": 0}

        results = {
            "processed": 0,
            "successes": 0,
            "failures": 0,
            "skipped": 0,
            "rate_limited": 0,
        }

        for skin_name in skin_names:
            if self._is_recently_scraped(skin_name, since_hours):
                results["skipped"] += 1
                continue

            status_code = self.collect_skin(skin_name)
            results["processed"] += 1
            if status_code == 0:
                results["successes"] += 1
            elif status_code == 2:
                results["rate_limited"] += 1
                results["failures"] += 1
            else:
                results["failures"] += 1

        return results

    def collect_skin(self, skin_name: str) -> int:
        """
        Scrapes a single item.
        Returns:
            0: Clean success.
            2: Active HTTP 429 (Rate Limit detected).
            1: Minor skip-worthy execution error.
        """
        if not self.scraper:
            logger.error(f"Scraper core is uninitialized. skipping collection: {skin_name}")
            return 1

        logger.info(f"Scraping skin data for: {skin_name}")
        try:
            result = self.scraper.fetch_price(skin_name) 
            
            if not result:
                logger.error(f"Scraper returned empty payload response for {skin_name}")
                return 1

            if isinstance(result, dict):
                status_code = result.get("status_code")
                success = result.get("success")
                data = result.get("data")
            else:
                status_code = getattr(result, "status_code", None)
                success = getattr(result, "success", None)
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
            error_msg = str(e)
            
            # Catch core connection exceptions that mention rate constraints
            if "429" in error_msg or "rate limited" in error_msg.lower():
                logger.error(f"Rate limit exception intercepted for {skin_name}: {error_msg}")
                return 2
                
            logger.error(f"Unexpected error collecting skin {skin_name}: {e}")
            return 1

    def collect_queue(self, watchlist_path: str, resume: bool = True, since_hours: int = 20) -> int:
        """
        Processes queue chunks safely.
        Returns:
            0: Clean run completion.
            2: Rate limiting triggered (Back off).
            1: Unhandled errors.
        """
        if not os.path.exists(watchlist_path):
            logger.error(f"Watchlist file not found: {watchlist_path}")
            return 1
            
        with open(watchlist_path, "r", encoding="utf-8") as f:
            all_skins = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            
        if not all_skins:
            logger.warning(f"Target watchlist contains no entries: {watchlist_path}")
            return 0

        state = self.load_queue_state() if resume else {
            "current_index": 0,
            "batch_size": 120,
            "last_skin": None,
            "status": "RUNNING"
        }
        
        start_idx = state.get("current_index", 0)
        batch_size = state.get("batch_size", 120)
        
        if start_idx >= len(all_skins):
            logger.info("Index out of list bounds. Resetting pipeline index to 0.")
            start_idx = 0
            
        end_idx = min(start_idx + batch_size, len(all_skins))
        skins_to_process = all_skins[start_idx:end_idx]
        
        logger.info(f"Starting pipeline chunk from index {start_idx} to {end_idx} of {len(all_skins)} total skins.")
        
        state["status"] = "RUNNING"
        self.save_queue_state(state)

        for offset, skin_name in enumerate(skins_to_process):
            current_skin_index = start_idx + offset
            
            # 🛡️ THE DEDUPLICATION SHIELD
            if self._is_recently_scraped(skin_name, since_hours):
                logger.info(f"⏭️ [SKIP] {skin_name} (scraped within last {since_hours} hours)")
                state["current_index"] = current_skin_index + 1
                state["last_skin"] = skin_name
                self.save_queue_state(state)
                continue
                
            status_code = self.collect_skin(skin_name)
            
            if status_code == 2:
                state["status"] = "RATE_LIMITED"
                state["current_index"] = current_skin_index 
                state["last_skin"] = skin_name
                self.save_queue_state(state)
                logger.warning(f"Scheduler aborting. Process halted at index {current_skin_index} ({skin_name})")
                return 2
                
            if status_code == 0:
                state["current_index"] = current_skin_index + 1
                state["last_skin"] = skin_name
                self.save_queue_state(state)
            else:
                logger.warning(f"Error handling skin {skin_name}. Progressing index forward.")
                state["current_index"] = current_skin_index + 1
                state["last_skin"] = skin_name
                self.save_queue_state(state)

            # 🎲 HUMAN-LIKE JITTER DELAY
            if offset < len(skins_to_process) - 1:
                base_delay = 15.0
                jitter = random.uniform(0.0, 10.0)
                total_sleep = base_delay + jitter
                logger.info(f"Waiting {total_sleep:.2f}s before next request... (Jitter: +{jitter:.2f}s)")
                time.sleep(total_sleep)

        logger.info(f"Successfully processed batch up to index {end_idx}.")
        
        if end_idx >= len(all_skins):
            logger.info("Entire watchlist cleared. Resetting loop indexes to 0.")
            state["current_index"] = 0
            state["status"] = "COMPLETED"
        else:
            state["status"] = "IDLE"
            
        self.save_queue_state(state)
        return 0