import sqlite3
import os

# 1. Look for any database files in your project directory
db_files = [f for f in os.listdir('.') if f.endswith('.db') or f.endswith('.sqlite') or f.endswith('.sqlite3')]

# Also look inside a 'data' folder if it exists
if os.path.exists('data'):
    db_files += [os.path.join('data', f) for f in os.listdir('data') if f.endswith('.db') or f.endswith('.sqlite') or f.endswith('.sqlite3')]

if not db_files:
    print("❌ No SQLite database file (.db or .sqlite) detected in the root or 'data' folder.")
    print("If you are using PostgreSQL or MySQL, please run the SQL command in your database client instead!")
    exit(1)

# 2. Clean up the found databases
for db_path in db_files:
    print(f"🧹 Connecting to database: {db_path}...")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Execute the delete statement
        cursor.execute("DELETE FROM market_history WHERE lowest_price IS NULL AND median_price IS NULL;")
        rows_deleted = cursor.rowcount
        
        conn.commit()
        conn.close()
        print(f"✅ Success! Deleted {rows_deleted} empty placeholder rows from '{db_path}'.")
    except Exception as e:
        print(f"❌ Failed to process '{db_path}': {e}")