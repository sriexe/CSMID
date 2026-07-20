import sqlite3
import os
from datetime import datetime

# 1. Locate the absolute directory of 'query_prices.py'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Go one folder up to find the root where csmid.db lives
# (Since the script is inside 'tests/', we use '..' to step up to 'CSMID/')
DB_FILE = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "steam_market.db"))

def get_item_price_history(item_name):
    """
    Queries the database to fetch and display the complete historical pricing
    records for a specific Steam market item.
    """
    # SQL query to join our tables and sort by date (oldest to newest)
    query = """
        SELECT 
            i.market_hash_name, 
            p.lowest_price, 
            p.volume, 
            p.recorded_at
        FROM price_history p
        JOIN items i ON p.item_id = i.id
        WHERE i.market_hash_name = ?
        ORDER BY p.recorded_at ASC
    """
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(query, (item_name,))
    records = cursor.fetchall()
    conn.close()
    
    if not records:
        print(f"\n❌ No historical data found in database for item: '{item_name}'")
        return
        
    print("\n" + "=" * 65)
    print(f"📊 PRICE HISTORY TIMELINE: {item_name}")
    print("=" * 65)
    print(f"{'Date & Time (UTC)':<22} | {'Lowest Price':<15} | {'Market Supply (Volume)':<15}")
    print("-" * 65)
    
    prices = []
    
    for row_name, price, volume, recorded_at in records:
        # Format the SQLite timestamp string into a cleaner readability format
        try:
            dt = datetime.strptime(recorded_at, "%Y-%m-%d %H:%M:%S")
            formatted_date = dt.strftime("%b %d, %Y %I:%M %p")
        except ValueError:
            formatted_date = recorded_at # Fallback if format differs
            
        # Format price with currency (or show 'N/A' if missing)
        price_display = f"₹ {price:,.2f}" if price is not None else "N/A"
        volume_display = f"{volume:,}" if volume is not None else "N/A"
        
        if price is not None:
            prices.append(price)
            
        print(f"{formatted_date:<22} | {price_display:<15} | {volume_display:<15}")
        
    print("=" * 65)
    
    # Calculate simple database stats if we have entries
    if prices:
        avg_price = sum(prices) / len(prices)
        max_price = max(prices)
        min_price = min(prices)
        print(f"📈 Total Entries: {len(prices)}")
        print(f"💰 Price Range:   ₹ {min_price:.2f} - ₹ {max_price:.2f}")
        print(f"🎯 Average Price:  ₹ {avg_price:.2f}")
        print("=" * 65 + "\n")

if __name__ == "__main__":
    # Test our query on one of the items parsed in the previous step
    target_item = "Dreams & Nightmares Case"
    get_item_price_history(target_item)