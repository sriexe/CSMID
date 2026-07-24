import os
import sys
import logging
from typing import List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.database import DatabaseManager

# Modular import handling for discoverer
try:
    from discoverer import SteamMarketDiscoverer
except ImportError:
    from discoverer import SteamMarketDiscoverer

# Modular import handling for push notification engine
try:
    from src.notifier import send_push_notification
except ImportError:
    try:
        from src.analytics import send_ntfy_alert as send_push_notification
    except ImportError:
        def send_push_notification(title: str, message: str, priority: str = "default"):
            logging.getLogger("CSMID.run_discovery").warning(f"[Mock Push] {title}: {message}")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CSMID.run_discovery")


def notify_discovery_results(new_skins_added: List[str]) -> None:
    """Sends a push notification summarizing newly tracked items."""
    if not new_skins_added:
        send_push_notification(
            title="🔍 Discovery Complete",
            message="Checked Steam catalog. No new skins were added today (tracked items are up to date)."
        )
        return

    count = len(new_skins_added)
    head_samples = new_skins_added[:3]
    tail_samples = new_skins_added[-2:] if count > 3 else []

    sample_text = "\n• " + "\n• ".join(head_samples)
    if tail_samples:
        sample_text += "\n...\n• " + "\n• ".join(tail_samples)

    msg = f"Added {count} new skin(s) to tracking!\n\nSamples:{sample_text}"
    
    send_push_notification(
        title=f"🎉 Discovery: +{count} New Skins Tracked!",
        message=msg,
        priority="high"
    )


def run_discovery(max_items: int = 500) -> List[str]:
    """
    Main entry point for discovery logic.
    Searches popular market listings, inserts new entries into DB,
    and sends a summary push notification.
    """
    db = DatabaseManager()
    discoverer = SteamMarketDiscoverer()
    new_skins_added: List[str] = []
    
    logger.info("Starting automated human-like item discovery loop...")
    
    try:
        for item_batch in discoverer.discover_popular_skins(max_items=max_items, items_per_page=100):
            logger.info(f"Processing batch of {len(item_batch)} items fetched from market page...")
            
            for skin_name in item_batch:
                # Insert into database and only record items that were genuinely new
                is_new = db.insert_tracked_item(skin_name, appid=730)
                if is_new:
                    new_skins_added.append(skin_name)
                    
    except Exception as e:
        logger.error(f"Error encountered during discovery loop: {e}")
    finally:
        db.close()

    logger.info(f"🏁 Item catalog updated successfully! Added {len(new_skins_added)} new skins.")

    # Send push notification summary
    notify_discovery_results(new_skins_added)
    return new_skins_added


def main():
    run_discovery()


if __name__ == "__main__":
    main()