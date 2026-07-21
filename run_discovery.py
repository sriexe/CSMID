import logging
from src.database import DatabaseManager
from discoverer import SteamMarketDiscoverer
from src.notifier import send_push_notification

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CSMID.run_discovery")

def notify_discovery_results(new_skins_added):
    """Sends a push notification to your phone with sample items."""
    if not new_skins_added:
        send_push_notification(
            title="🔍 Weekly Discovery Complete",
            message="Checked Steam catalog. No new skins were added today (checklist is up to date)."
        )
        return

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

def main():
    db = DatabaseManager()
    discoverer = SteamMarketDiscoverer()
    
    max_items_to_search = 500
    new_skins_added = []
    
    logger.info("Starting automated human-like item discovery loop...")
    
    for item_batch in discoverer.discover_popular_skins(max_items=max_items_to_search, items_per_page=100):
        logger.info(f"Processing batch of {len(item_batch)} items fetched from market page...")
        
        for skin_name in item_batch:
            # Insert into database and collect added skin names
            is_new = db.insert_tracked_item(skin_name, appid=730)
            # If your DB method returns True for new items, or collect all scanned items:
            new_skins_added.append(skin_name)
            
    db.close()
    logger.info(f"🏁 Item catalog updated successfully! Processed {len(new_skins_added)} total skins.")

    # 📱 SEND PUSH NOTIFICATION HERE
    notify_discovery_results(new_skins_added)

if __name__ == "__main__":
    main()