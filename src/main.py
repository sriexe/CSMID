import time
import logging

# Import your classes (Ensure the file names match your actual structure)
from csmid.scraper import SteamMarketScraper
from database import DatabaseManager  

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("CSMID.bulk_scraper")

def run_bulk_scrape():
    # Initialize the Scraper and Database
    scraper = SteamMarketScraper(min_request_interval=4.0)
    db = DatabaseManager()

    # Define the list of items you want to track
    target_skins = [
        "Clutch Case",
        "Dreams & Nightmares Case",
        "AK-47 | Redline (Field-Tested)",
        "AWP | Asiimov (Field-Tested)",
        "Desert Eagle | Printstream (Minimal Wear)",
        "M4A1-S | Printstream (Field-Tested)"
    ]

    logger.info(f"Starting bulk scrape for {len(target_skins)} items...")

    for skin_name in target_skins:
        logger.info(f"--- Processing: {skin_name} ---")
        
        # 1. Check if it was already scraped recently (Saves API credits!)
        # Using a 12-hour threshold so it updates twice a day
        if db.is_recently_scraped(skin_name, hours_threshold=12):
            logger.info(f"⏭️ Skipped {skin_name}: Already scraped recently.")
            continue
            
        # 2. Scrape the data from Steam via Proxy
        price_data = scraper.get_price(appid=730, market_hash_name=skin_name)
        
        # 3. Save to Supabase
        if price_data:
            # Inject the skin name into the dict so your DatabaseManager can read it
            price_data["skin_name"] = skin_name 
            
            db.insert_price(price_data)
            logger.info(f"✅ Saved new price for {skin_name} to Supabase.")
        else:
            logger.error(f"❌ Failed to scrape {skin_name}")
            
        # 4. Safe delay to prevent proxy rate-limiting
        time.sleep(2)
        
    # Clean up the DB connection when finished
    db.close()
    logger.info("Bulk scrape complete!")

if __name__ == "__main__":
    run_bulk_scrape()