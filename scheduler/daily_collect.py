import sys
import os
import time
import logging
from datetime import datetime, timedelta

# Ensure the project root directory is in the Python path so imports resolve correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.collection_manager import CollectionManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scheduler.log"),
        logging.StreamHandler()
    ]
)

# Configuration constants
WATCHLIST_NAME = "all_weapons"
WATCHLIST_PATH = f"data/watchlists/{WATCHLIST_NAME}.txt"
RESUME_MODE = True
SINCE_HOURS = 20

RATE_LIMIT_BACKOFF_MINUTES = 60
STANDARD_COOLDOWN_MINUTES = 10

def main():
    logging.info("Native Intelligent Scheduler started.")
    
    # Initialize the manager once, keeping its state and sessions alive natively
    try:
        manager = CollectionManager()
    except Exception as e:
        logging.critical(f"Failed to initialize CollectionManager: {e}")
        sys.exit(1)
    
    while True:
        logging.info(f"Starting native queue collection for watchlist: {WATCHLIST_NAME}")
        
        try:
            # Call the manager method directly in-process
            status_code = manager.collect_queue(
                watchlist_path=WATCHLIST_PATH,
                resume=RESUME_MODE,
                since_hours=SINCE_HOURS
            )
            
        except Exception as e:
            logging.error(f"Unhandled exception during collection loop: {e}")
            status_code = 1  # Treat as general error
            
        # Branch on native return codes
        if status_code == 0:
            logging.info(f"Batch completed cleanly. Engine resting for {STANDARD_COOLDOWN_MINUTES} minutes.")
            time.sleep(STANDARD_COOLDOWN_MINUTES * 60)
            
        elif status_code == 2:
            resume_time = datetime.now() + timedelta(minutes=RATE_LIMIT_BACKOFF_MINUTES)
            logging.error("HTTP 429 Rate Limit hit natively.")
            logging.info(f"Cooling down for {RATE_LIMIT_BACKOFF_MINUTES} minutes. Next attempt at: {resume_time.strftime('%H:%M:%S')}")
            time.sleep(RATE_LIMIT_BACKOFF_MINUTES * 60)
            
        else:
            logging.error(f"Collection manager returned error status: {status_code}. Retrying in 5 minutes.")
            time.sleep(5 * 60)

if __name__ == "__main__":
    main()