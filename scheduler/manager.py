from scheduler.state import load_state, save_state

def process_next_batch():
    # 1. Load the state safely (never throws FileNotFoundError now)
    state = load_state()
    
    idx = state["current_index"]
    size = state["batch_size"]
    
    # ... your logic to grab skins from idx to (idx + size) ...
    
    try:
        # Simulate or execute collection
        # If it hits a 429 inside the batch loop:
        # save_state(current_index=new_idx, batch_size=size, last_skin=current_skin, status="RATE_LIMITED")
        
        # If it finishes cleanly:
        save_state(
            current_index=idx + size, 
            batch_size=size, 
            last_skin="AK-47 | Redline", 
            status="COMPLETED"
        )
    except Exception:
        save_state(current_index=idx, batch_size=size, status="FAILED")