import os
import json
import logging
from datetime import datetime

# Setup basic logging if not already initialized elsewhere
logger = logging.getLogger("scheduler.state")

STATE_FILE = os.path.join("scheduler", "queue_state.json")

DEFAULT_STATE = {
    "current_index": 0,
    "batch_size": 120,
    "last_skin": None,
    "last_run": None,
    "status": "INITIALIZED"  # Statuses: INITIALIZED, RUNNING, COMPLETED, RATE_LIMITED
}

def load_state(filepath=STATE_FILE) -> dict:
    """
    Loads the queue state from a JSON file. 
    Returns defaults if the file doesn't exist or is corrupted.
    """
    if not os.path.exists(filepath):
        encoding = "utf-8"
        logger.info(f"State file '{filepath}' not found. Initializing with defaults.")
        return DEFAULT_STATE.copy()
        
    try:
        with open(filepath, "r") as f:
            state = json.load(f)
            
        # Ensure any missing keys get populated with defaults (schema protection)
        updated_state = DEFAULT_STATE.copy()
        updated_state.update(state)
        return updated_state
        
    except json.JSONDecodeError:
        logger.error(f"State file '{filepath}' is corrupted. Falling back to defaults to prevent crash.")
        return DEFAULT_STATE.copy()
    except Exception as e:
        logger.error(f"Unexpected error loading state: {e}")
        return DEFAULT_STATE.copy()

def save_state(current_index: int, batch_size: int, last_skin: str = None, status: str = "RUNNING", filepath=STATE_FILE):
    """
    Persists the current queue execution state to disk.
    Automatically captures the current timestamp.
    """
    state_data = {
        "current_index": current_index,
        "batch_size": batch_size,
        "last_skin": last_skin,
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status
    }
    
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=4)
        logger.debug(f"State saved successfully: Index {current_index}, Status: {status}")
        
    except Exception as e:
        logger.error(f"Failed to save state file: {e}")