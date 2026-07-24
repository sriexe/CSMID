import logging
import os
from typing import Optional, Any, List, Dict

from src.env import SUPABASE_DB_URL

logger = logging.getLogger("CSMID.database")

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - optional dependency in some environments
    psycopg2 = None


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

        -- Add missing columns if tracked_items pre-existed with an older schema
        ALTER TABLE tracked_items ADD COLUMN IF NOT EXISTS hash_name TEXT;
        ALTER TABLE tracked_items ADD COLUMN IF NOT EXISTS item_type TEXT DEFAULT 'skin';
        ALTER TABLE tracked_items ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

        -- Relax NOT NULL constraint on legacy skin_name column if present
        DO $$ 
        BEGIN 
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='tracked_items' AND column_name='skin_name'
            ) THEN 
                ALTER TABLE tracked_items ALTER COLUMN skin_name DROP NOT NULL;
            END IF; 
        END $$;

        -- Ensure UNIQUE constraint on hash_name for ON CONFLICT upsert queries
        DO $$ 
        BEGIN 
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'tracked_items_hash_name_key'
            ) THEN 
                ALTER TABLE tracked_items ADD CONSTRAINT tracked_items_hash_name_key UNIQUE (hash_name);
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
        SELECT 1 FROM price_history
        WHERE hash_name = %s 
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
        INSERT INTO price_history (hash_name, lowest_price, median_price, volume)
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
        query = "SELECT id, hash_name, lowest_price, median_price, volume, scraped_at FROM price_history"
        conditions = []
        params = []

        if target_name:
            conditions.append("hash_name = %s")
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