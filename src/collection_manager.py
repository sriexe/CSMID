import logging
from datetime import datetime
from src.scraper import SteamMarketScraper  # Adjust import based on your exact layout
from src.database import SessionLocal   # Adjust import based on your exact layout
from scheduler.state import load_state, save_state
from datetime import datetime, timedelta ,timezone
from sqlalchemy import text

logger = logging.getLogger("csmid.collection_manager")

# Native imports directly from your database.py layer
from src.database import SessionLocal, MarketHistory, Skin, get_or_create_skin, insert_market_history
from scheduler.state import load_state, save_state

logger = logging.getLogger("csmid.collection_manager")

class CollectionManager:
    def __init__(self):
        self.scraper = None # Assuming your scraper initialization happens here
        # Instantiate your native session factory
        self.session = SessionLocal()
        
    def get_recently_collected_names(self, since_hours=20) -> set:
        """Queries MarketHistory for skins successfully updated within the window to skip them."""
        time_threshold = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        
        try:
            # Query the market_history table for entries within our time window
            recent_records = (
                self.session.query(MarketHistory.market_hash_name)
                .filter(MarketHistory.collected_at_utc >= time_threshold)
                .filter(MarketHistory.success == True)
                .all()
            )
            
            # Extract names out of the query tuples into a lightning-fast lookup set
            names_set = {record[0] for record in recent_records}
            return names_set
            
        except Exception as e:
            logger.error(f"Database query failed in get_recently_collected_names: {e}")
            return set()

    def _store_record(self, record_data):
        """
        Inserts the scraped observation into the database using native helpers.
        Expects record_data to be an object or dictionary matching your scraper schema.
        """
        try:
            # 1. Ensure the parent skin exists in the static metadata table
            skin = get_or_create_skin(self.session, record_data.market_hash_name)
            
            # 2. Use your native insert_market_history helper to append the time-series row
            insert_market_history(self.session, skin, record_data)
            
            # 3. Commit the transaction safely
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
        logger.info(f"Scraping skin data for: {skin_name}")
        try:
            # Call your curl-based scraper
            result = self.scraper.fetch_price(skin_name) 
            
            if result.get("status_code") == 429:
                logger.error(f"Rate limited while scraping {skin_name}")
                return 2
                
            if result.get("success"):
                self._store_record(result["data"])
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
        # 1. Load the watchlist skins
        try:
            with open(watchlist_path, "r", encoding="utf-8") as f:
                all_skins = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            logger.error(f"Watchlist file not found: {watchlist_path}")
            return 1

        # 2. Handle skip logic if resume mode is active
        skip_names = set()
        if resume:
            skip_names = self.get_recently_collected_names(since_hours=since_hours)
            logger.info(f"Resume active: Skipping {len(skip_names)} skins collected in past {since_hours} hours.")

        # 3. Load our persistent state tracking
        state = load_state()
        start_idx = state["current_index"]
        batch_size = state["batch_size"]
        
        # If we reached the end of the file in a previous run, wrap around or stop
        if start_idx >= len(all_skins):
            logger.info("Reached the end of the watchlist. Resetting queue index to 0.")
            start_idx = 0

        end_idx = min(start_idx + batch_size, len(all_skins))
        target_batch = all_skins[start_idx:end_idx]
        
        logger.info(f"Processing queue batch: Index {start_idx} to {end_idx} (Total skins: {len(all_skins)})")

        # 4. Process the slice
        for current_idx, skin in enumerate(target_batch, start=start_idx):
            if skin in skip_names:
                logger.info(f"Skipping (Already fresh in DB): {skin}")
                continue
                
            # Process the individual skin
            exit_code = self.collect_skin(skin)
            
            # If we hit a 429 rate limit, stop the queue immediately and save state
            if exit_code == 2:
                save_state(
                    current_index=current_idx, 
                    batch_size=batch_size, 
                    last_skin=skin, 
                    status="RATE_LIMITED"
                )
                return 2  # Bubble up the 429 exit code to the scheduler
                
            if exit_code != 0:
                logger.warning(f"Failed to scrape {skin}, moving on...")

        # 5. Finished the batch cleanly
        new_start_index = end_idx
        status = "COMPLETED" if new_start_index >= len(all_skins) else "RUNNING"
        
        save_state(
            current_index=new_start_index, 
            batch_size=batch_size, 
            last_skin=target_batch[-1] if target_batch else None, 
            status=status
        )
        
        return 0