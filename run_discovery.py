import logging
from src.database import DatabaseManager
from discoverer import SteamMarketDiscoverer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CSMID.run_discovery")

def main():
    db = DatabaseManager()
    discoverer = SteamMarketDiscoverer()
    
    # Configure how deep into the 'popular items' list you want to look (e.g., top 500 items)
    max_items_to_search = 500
    total_added = 0
    
    logger.info("Starting automated human-like item discovery loop...")
    
    # Pull items in blocks of 100 per page request
    for item_batch in discoverer.discover_popular_skins(max_items=max_items_to_search, items_per_page=100):
        logger.info(f"Processing batch of {len(item_batch)} items fetched from market page...")
        
        for skin_name in item_batch:
            db.insert_tracked_item(skin_name, appid=730)
            total_added += 1
            
    db.close()
    logger.info(f"🏁 Item catalog updated successfully! Processed {total_added} total skins into tracked_items.")

if __name__ == "__main__":
    main()