import os
import sys
import time
import logging
import argparse
from typing import Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scraper import SteamMarketScraper
from src.database import DatabaseManager
from src.analytics import run_and_notify_analytics
from src.env import SUPABASE_URL, SUPABASE_KEY
from src.volatility import get_scrape_interval_for_item

# Optional import for Discovery Phase
try:
    from run_discovery import run_discovery
except ImportError:
    run_discovery = None

try:
    from supabase import create_client
except ImportError:  # pragma: no cover - optional dependency in some environments
    create_client = None

supabase = None
if create_client and SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CSMID.main")

# Default items used for local dry-run testing if no DB is connected
SAMPLE_TARGETS = [
    "Recoil Case",
    "Revolution Case",
    "Dreams & Nightmares Case"
]


def run_pipeline(
    mode: str = "all",
    limit: Optional[int] = None,
    dry_run: bool = False,
    ignore_cache: bool = False
) -> None:
    """
    Unified CLI pipeline runner with Volatility-Aware Scraping.
    
    :param mode: 'all' (scrape + analytics), 'scrape' (only scrape), 'analytics' (only analytics), 'discovery' (only discovery)
    :param limit: Max number of items to process (great for local testing)
    :param dry_run: If True, skips DB writes and alert notifications
    :param ignore_cache: If True, bypasses the dynamic recency check
    """
    scraper = SteamMarketScraper(min_request_interval=4.0)
    db: Optional[DatabaseManager] = None

    # ------------------------------------------------------------------
    # 0. DISCOVERY PHASE
    # ------------------------------------------------------------------
    if mode == "discovery":
        logger.info(f"--- Starting Skin Discovery Phase (Dry Run: {dry_run}) ---")
        if dry_run:
            logger.info("🧪 [Dry Run] Skipping database updates for newly discovered skins.")
        elif run_discovery:
            run_discovery()
            logger.info("✅ Skin discovery complete. Tracked items updated in Supabase.")
        else:
            logger.error("Could not import 'run_discovery' from src.run_discovery.")
        return

    # ------------------------------------------------------------------
    # 1. SCRAPE PHASE (Volatility-Aware)
    # ------------------------------------------------------------------
    if mode in ("all", "scrape"):
        logger.info(f"--- Starting Scraper Phase (Mode: {mode}, Limit: {limit}, Dry Run: {dry_run}) ---")
        
        target_skins = []

        if not dry_run:
            try:
                db = DatabaseManager()
                target_skins = db.get_active_targets()
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
                logger.info("Tip: Use --dry-run for local testing without database credentials.")
                return

        # Fallback to sample items in dry-run mode if no targets loaded
        if dry_run and not target_skins:
            logger.info("🧪 DRY RUN MODE: Using sample items for local testing...")
            target_skins = SAMPLE_TARGETS

        if not target_skins:
            logger.warning("No active items found in the tracked_items table! Run python -m src.main --mode discovery first.")
            if db:
                db.close()
            return

        # Apply item limit for testing
        if limit and limit > 0:
            target_skins = target_skins[:limit]
            logger.info(f"Local test limit applied: processing {len(target_skins)} item(s).")

        logger.info(f"Processing {len(target_skins)} item(s)...")

        for skin_name in target_skins:
            logger.info(f"--- Processing: {skin_name} ---")

            # Volatility-aware cache threshold unless bypassed
            if not dry_run and not ignore_cache and db:
                tier, cv, required_hours = get_scrape_interval_for_item(skin_name, db)
                if db.is_recently_scraped(skin_name, hours_threshold=required_hours):
                    logger.info(f"⏭️ Skipped {skin_name} [{tier} tier, CV: {cv:.3f}]: Scraped within last {required_hours}h.")
                    continue
                else:
                    logger.info(f"📊 Evaluated {skin_name} [{tier} tier, CV: {cv:.3f}]: Interval threshold {required_hours}h reached.")

            # Scrape price data using residential proxy chain
            price_data = scraper.get_price(appid=730, market_hash_name=skin_name)

            if price_data:
                logger.info(f"✅ Scraped {skin_name}: ${price_data.get('lowest_price', 0.0)}")
                
                if dry_run:
                    logger.info(f"🧪 [Dry Run] Parsed payload for {skin_name}: {price_data}")
                elif db:
                    price_data["skin_name"] = skin_name
                    db.insert_price(price_data)
                    logger.info(f"💾 Logged fresh prices for {skin_name} into Supabase")
            else:
                logger.error(f"❌ Failed to reach Steam backend for {skin_name}")

            time.sleep(2)  # Safe breathing window for proxy rotation

        if db:
            db.close()
        logger.info("🏁 Historical price log run completed.")

    # ------------------------------------------------------------------
    # 2. ANALYTICS & ALERT PHASE
    # ------------------------------------------------------------------
    if mode in ("all", "analytics"):
        logger.info("--- Starting Analytics Phase ---")
        if dry_run:
            logger.info("🧪 DRY RUN MODE: Skipping live analytics DB queries and ntfy alerts.")
        else:
            run_and_notify_analytics()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CSMID Market Scraper & Analytics Pipeline")
    parser.add_argument(
        "--mode",
        choices=["all", "scrape", "analytics", "discovery"],
        default="all",
        help="Pipeline phase to execute (default: all)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of items to scrape (useful for fast local testing)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without connecting to Supabase or firing ntfy alerts"
    )
    parser.add_argument(
        "--ignore-cache",
        action="store_true",
        help="Ignore volatility intervals and force a fresh scrape"
    )

    args = parser.parse_args()
    run_pipeline(
        mode=args.mode,
        limit=args.limit,
        dry_run=args.dry_run,
        ignore_cache=args.ignore_cache
    )