import sqlite3
import psycopg2
from datetime import datetime

# 🔑 Paste your connection string here (replace YOUR_ACTUAL_PASSWORD_HERE with your password)
SUPABASE_URL = "***REMOVED***"
SQLITE_DB_PATH = "csmid.db"

def migrate():
    print("🔄 Connecting to databases...")
    local_conn = sqlite3.connect(SQLITE_DB_PATH)
    local_cursor = local_conn.cursor()

    cloud_conn = psycopg2.connect(SUPABASE_URL)
    cloud_cursor = cloud_conn.cursor()
    print("✅ Connected to both local SQLite and Cloud Supabase!")

    # 1. Inspect local SQLite columns
    local_cursor.execute("PRAGMA table_info(market_history);")
    columns_info = local_cursor.fetchall()
    sqlite_columns = [col[1] for col in columns_info]
    print(f"📋 Detected SQLite columns: {sqlite_columns}")

    # 2. Automatically map columns
    # Find skin name column
    skin_col = None
    for col in ['market_hash_name', 'skin_name', 'name']:
        if col in sqlite_columns:
            skin_col = col
            break
    if not skin_col:
        raise ValueError(f"❌ Could not find skin name column. Available columns: {sqlite_columns}")

    # Find timestamp column
    time_col = None
    for col in ['timestamp', 'created_at', 'scraped_at', 'date', 'datetime']:
        if col in sqlite_columns:
            time_col = col
            break

    lowest_price_col = 'lowest_price' if 'lowest_price' in sqlite_columns else None
    median_price_col = 'median_price' if 'median_price' in sqlite_columns else None
    volume_col = 'volume' if 'volume' in sqlite_columns else None

    # 3. Create the table on Supabase (Postgres)
    print("🛠️ Making sure market_history table exists on Supabase...")
    create_table_query = """
    CREATE TABLE IF NOT EXISTS market_history (
        id SERIAL PRIMARY KEY,
        skin_name VARCHAR(255) NOT NULL,
        lowest_price NUMERIC(10, 2),
        median_price NUMERIC(10, 2),
        volume INTEGER,
        scraped_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """
    cloud_cursor.execute(create_table_query)
    cloud_conn.commit()

    # 4. Build dynamic query based on what columns actually exist
    select_fields = [skin_col]
    insert_fields = ['skin_name']
    placeholders = ['%s']

    if lowest_price_col:
        select_fields.append(lowest_price_col)
        insert_fields.append('lowest_price')
        placeholders.append('%s')
    if median_price_col:
        select_fields.append(median_price_col)
        insert_fields.append('median_price')
        placeholders.append('%s')
    if volume_col:
        select_fields.append(volume_col)
        insert_fields.append('volume')
        placeholders.append('%s')
    if time_col:
        select_fields.append(time_col)
        insert_fields.append('scraped_at')
        placeholders.append('%s')

    select_query = f"SELECT {', '.join(select_fields)} FROM market_history;"
    insert_query = f"INSERT INTO market_history ({', '.join(insert_fields)}) VALUES ({', '.join(placeholders)});"

    print(f"🔍 Mapping columns:")
    print(f"   SQLite:  {select_fields}")
    print(f"   Supabase: {insert_fields}")

    # 5. Fetch SQLite data
    print("📥 Fetching local SQLite data...")
    local_cursor.execute(select_query)
    rows = local_cursor.fetchall()
    total_rows = len(rows)
    print(f"📦 Found {total_rows} rows to migrate.")

    if total_rows == 0:
        print("⚠️ No data found in SQLite to migrate!")
        return

    # 6. Bulk insert into Supabase
    print("🚀 Pushing data to Supabase...")
    chunk_size = 500
    for i in range(0, total_rows, chunk_size):
        chunk = rows[i:i + chunk_size]
        cloud_cursor.executemany(insert_query, chunk)
        cloud_conn.commit()
        print(f"   Uploaded {min(i + chunk_size, total_rows)}/{total_rows} rows...")

    print("🎉 MIGRATION SUCCESSFUL! All data is now live on Supabase.")
    local_conn.close()
    cloud_conn.close()

if __name__ == "__main__":
    migrate()