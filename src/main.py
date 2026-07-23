import os
import sys
import time
import logging

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scraper import SteamMarketScraper
from src.database import DatabaseManager
from src.analytics import run_and_notify_analytics
from src.env import SUPABASE_URL, SUPABASE_KEY

try:
    from supabase import create_client
except ImportError:  # pragma: no cover - optional dependency in some environments
    create_client = None

supabase = None
if create_client and SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CSMID.main")

def run_bulk_scrape():
    scraper = SteamMarketScraper(min_request_interval=4.0)
    db = DatabaseManager()

    # 1. Automatically pull the dynamic target list from your Supabase control panel
    target_skins = db.get_active_targets()
    
    if not target_skins:
        logger.warning("No active items found in the tracked_items table! Run run_discovery.py first.")
        db.close()
        return

    logger.info(f"Starting tracking run for {len(target_skins)} items loaded from Supabase...")

    for skin_name in target_skins:
        logger.info(f"--- Processing: {skin_name} ---")
        
        # 2. Check if it was already updated recently (Saves ScrapingAnt credits)
        if db.is_recently_scraped(skin_name, hours_threshold=12):
            logger.info(f"⏭️ Skipped {skin_name}: Already up to date.")
            continue
            
        # 3. Scrape price data using residential proxies
        price_data = scraper.get_price(appid=730, market_hash_name=skin_name)
        
        # 4. Save clean data straight to your ledger
        if price_data:
            price_data["skin_name"] = skin_name 
            db.insert_price(price_data)
            logger.info(f"✅ Logged fresh prices for {skin_name}")
        else:
            logger.error(f"❌ Failed to reach Steam backend for {skin_name}")
            
        time.sleep(2) # Safe breathing window for proxy rotation
        
    db.close()
    logger.info("🏁 Historical price log run completed successfully.")

    # 📊 5. TRIGGER ANALYTICS & MARKET SIGNAL ALERTS HERE
    run_and_notify_analytics()

if __name__ == "__main__":
    run_bulk_scrape()