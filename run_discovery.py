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
    
    
# At the end of your discovery function in run_discovery.py
from src.notifier import send_push_notification

def notify_discovery_results(new_skins_added):
    if not new_skins_added:
        send_push_notification(
            title="🔍 Weekly Discovery Complete",
            message="Checked Steam catalog. No new skins were added today (checklist is up to date)."
        )
        return

    # Grab sample data (Head & Tail)
    count = len(new_skins_added)
    head_samples = new_skins_added[:3]
    tail_samples = new_skins_added[-2:] if count > 3 else []

    sample_text = "\n• " + "\n• ".join(head_samples)
    if tail_samples:
        sample_text += "\n...\n• " + "\n• ".join(tail_samples)

    msg = f"Added {count} new skins to tracking!\n\nSamples:{sample_text}"
    
    send_push_notification(
        title=f"🎉 Discovery: +{count} New Skins Tracked!",
        message=msg,
        priority="high"
    )