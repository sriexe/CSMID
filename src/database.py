import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional, Any, List, Dict

from src import config  
from src.env import SUPABASE_DB_URL

logger = logging.getLogger("CSMID.database")

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - optional dependency in some environments
    psycopg2 = None


_sqlite_conn: Optional[sqlite3.Connection] = None


def init_db() -> sqlite3.Connection:
    """Initialize a lightweight SQLite database for local compatibility tests."""
    global _sqlite_conn
    db_path = Path(getattr(config, "DB_PATH", config.DATABASE_PATH))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _sqlite_conn = sqlite3.connect(db_path)
    _sqlite_conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _sqlite_conn.commit()
    return _sqlite_conn


def insert_record(source: str, title: str, url: str, raw_data: str) -> int:
    """Insert a record into the compatibility SQLite database."""
    conn = _sqlite_conn or init_db()
    cursor = conn.execute(
        "INSERT INTO records (source, title, url, raw_data) VALUES (?, ?, ?, ?)",
        (source, title, url, raw_data),
    )
    conn.commit()
    return int(cursor.lastrowid)


def fetch_records(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch records from the compatibility SQLite database."""
    conn = _sqlite_conn or init_db()
    rows = conn.execute(
        "SELECT id, source, title, url, raw_data, created_at FROM records ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": row[0],
            "source": row[1],
            "title": row[2],
            "url": row[3],
            "raw_data": row[4],
            "created_at": row[5],
        }
        for row in rows
    ]


class DatabaseManager:
    """Postgres / Supabase Direct database manager for the CSMID pipeline."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or SUPABASE_DB_URL
        self.conn: Any = None

        if self.db_url and psycopg2 is not None:
            try:
                self.conn = psycopg2.connect(self.db_url)
                self.conn.autocommit = True
                self._ensure_tables()
                logger.info("Successfully connected to Postgres database.")
            except Exception as exc:  # pragma: no cover
                logger.warning("Could not connect to Postgres database: %s", exc)
                self.conn = None
        else:
            logger.info("Database connection not configured; using no-op database manager.")

    def _ensure_tables(self) -> None:
        """Initializes required tables or updates existing schemas dynamically."""
        if not self.conn:
            return

        schema_sql = """
        CREATE TABLE IF NOT EXISTS tracked_items (
            id BIGSERIAL PRIMARY KEY,
            hash_name TEXT UNIQUE NOT NULL,
            item_type TEXT DEFAULT 'skin',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        ALTER TABLE tracked_items ADD COLUMN IF NOT EXISTS hash_name TEXT;
        ALTER TABLE tracked_items ADD COLUMN IF NOT EXISTS item_type TEXT DEFAULT 'skin';
        ALTER TABLE tracked_items ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='tracked_items' AND column_name='skin_name'
            ) THEN
                ALTER TABLE tracked_items ALTER COLUMN skin_name DROP NOT NULL;
            END IF;
        END $$;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'tracked_items_hash_name_key'
            ) THEN
                ALTER TABLE tracked_items ADD CONSTRAINT tracked_items_hash_name_key UNIQUE (hash_name);
            END IF;
        END $$;

        CREATE TABLE IF NOT EXISTS market_history (
            id BIGSERIAL PRIMARY KEY,
            skin_name TEXT NOT NULL,
            lowest_price NUMERIC(10, 2),
            median_price NUMERIC(10, 2),
            volume INT,
            scraped_at TIMESTAMPTZ DEFAULT NOW()
        );

        ALTER TABLE market_history ADD COLUMN IF NOT EXISTS skin_name TEXT;
        ALTER TABLE market_history ADD COLUMN IF NOT EXISTS lowest_price NUMERIC(10, 2);
        ALTER TABLE market_history ADD COLUMN IF NOT EXISTS median_price NUMERIC(10, 2);
        ALTER TABLE market_history ADD COLUMN IF NOT EXISTS volume INT;
        ALTER TABLE market_history ADD COLUMN IF NOT EXISTS scraped_at TIMESTAMPTZ;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns WHERE table_name='market_history' AND column_name='hash_name'
            ) THEN
                ALTER TABLE market_history ADD COLUMN hash_name TEXT;
            END IF;
        END $$;

        CREATE TABLE IF NOT EXISTS price_history (
            id BIGSERIAL PRIMARY KEY,
            hash_name TEXT NOT NULL,
            lowest_price NUMERIC(10, 2),
            median_price NUMERIC(10, 2),
            volume INT,
            scraped_at TIMESTAMPTZ DEFAULT NOW()
        );

        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name='market_history'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name='price_history'
            ) THEN
                INSERT INTO price_history (hash_name, lowest_price, median_price, volume, scraped_at)
                SELECT COALESCE(hash_name, skin_name, 'unknown'), lowest_price, median_price, volume, scraped_at
                FROM market_history
                WHERE NOT EXISTS (
                    SELECT 1 FROM price_history ph
                    WHERE ph.hash_name = COALESCE(market_history.hash_name, market_history.skin_name, 'unknown')
                      AND ph.scraped_at = market_history.scraped_at
                );
            END IF;
        END $$;
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(schema_sql)
        except Exception as exc:
            logger.error("Failed to initialize or align database tables: %s", exc)

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # pragma: no cover
                pass
            self.conn = None

    def insert_tracked_item(
        self, 
        hash_name: str, 
        item_type: str = "skin", 
        appid: int = 730, 
        **kwargs
    ) -> bool:
        """Insert or reactivate a skin hash_name in tracked_items."""
        if not self.conn:
            logger.debug("[No-Op] Simulated insert_tracked_item for: %s", hash_name)
            return True

        query = """
        INSERT INTO tracked_items (hash_name, item_type, is_active)
        VALUES (%s, %s, TRUE)
        ON CONFLICT (hash_name) DO UPDATE SET is_active = TRUE;
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (hash_name, item_type))
            return True
        except Exception as exc:
            logger.error("Failed to insert tracked item '%s': %s", hash_name, exc)
            return False

    def get_active_targets(self) -> list[str]:
        """Return active skin hash names from tracked_items."""
        if not self.conn:
            return []

        query = "SELECT hash_name FROM tracked_items WHERE is_active = TRUE ORDER BY id ASC;"
        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
                return [r[0] for r in rows]
        except Exception as exc:
            logger.error("Failed to fetch active targets: %s", exc)
            return []

    def is_recently_scraped(self, skin_name: str, hours_threshold: int = 12) -> bool:
        """Check if a skin has a price entry within the last N hours."""
        if not self.conn:
            return False

        query = """
        SELECT 1 FROM market_history
        WHERE skin_name = %s
          AND scraped_at >= NOW() - (INTERVAL '1 hour' * %s)
        LIMIT 1;
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (skin_name, hours_threshold))
                return cur.fetchone() is not None
        except Exception as exc:
            logger.error("Failed to check recent scrape status for '%s': %s", skin_name, exc)
            return False

    def insert_price(self, price_data: dict[str, Any]) -> None:
        """Insert price records into price_history."""
        if not self.conn:
            logger.debug("Skipping price insert because no database connection is configured.")
            return

        hash_name = price_data.get("skin_name") or price_data.get("hash_name")
        lowest_price = price_data.get("lowest_price")
        median_price = price_data.get("median_price")
        volume = price_data.get("volume")

        if not hash_name:
            return

        query = """
        INSERT INTO market_history (skin_name, lowest_price, median_price, volume)
        VALUES (%s, %s, %s, %s);
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (hash_name, lowest_price, median_price, volume))
        except Exception as exc:
            logger.error("Failed to insert price for '%s': %s", hash_name, exc)

    def insert_market_data(
        self, 
        skin_name: str, 
        lowest_price: Optional[float], 
        median_price: Optional[float], 
        volume: Optional[int]
    ) -> None:
        """Compatibility method used by collection manager."""
        self.insert_price({
            "skin_name": skin_name,
            "lowest_price": lowest_price,
            "median_price": median_price,
            "volume": volume,
        })

    def get_price_history(
        self, 
        hash_name: Optional[str] = None, 
        skin_name: Optional[str] = None, 
        days: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch historical price records from price_history table."""
        if not self.conn:
            return []

        target_name = hash_name or skin_name
        query = "SELECT id, skin_name AS hash_name, lowest_price, median_price, volume, scraped_at FROM market_history"
        conditions = []
        params = []

        if target_name:
            conditions.append("skin_name = %s")
            params.append(target_name)

        if days:
            conditions.append("scraped_at >= NOW() - (INTERVAL '1 day' * %s)")
            params.append(days)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY scraped_at ASC"

        if limit:
            query += " LIMIT %s"
            params.append(limit)

        query += ";"

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                if cur.description:
                    cols = [desc[0] for desc in cur.description]
                    return [dict(zip(cols, row)) for row in cur.fetchall()]
                return []
        except Exception as exc:
            logger.error("Failed to fetch price history: %s", exc)
            return []