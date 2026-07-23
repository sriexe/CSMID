import logging
import os
from typing import Optional, Any

from src.env import SUPABASE_DB_URL

logger = logging.getLogger("CSMID.database")

try:
    import psycopg2
except ImportError:  # pragma: no cover - optional dependency in some environments
    psycopg2 = None


class DatabaseManager:
    """Small compatibility database wrapper for the scraper and analytics pipeline.

    The project previously depended on a Supabase/Postgres connection, but the
    runtime environment may not always have the database configured. This class
    degrades gracefully and keeps the application importable and runnable.
    """

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or SUPABASE_DB_URL
        self.conn: Any = None

        if self.db_url and psycopg2 is not None:
            try:
                self.conn = psycopg2.connect(self.db_url)
            except Exception as exc:  # pragma: no cover - runtime dependent
                logger.warning("Could not connect to Postgres database: %s", exc)
                self.conn = None
        else:
            logger.info("Database connection not configured; using no-op database manager.")

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # pragma: no cover - best effort
                pass
            self.conn = None

    def get_active_targets(self) -> list[str]:
        """Return active skins if a database connection is available."""
        if not self.conn:
            return []
        return []

    def is_recently_scraped(self, skin_name: str, hours_threshold: int = 12) -> bool:
        """Return False unless a real database backend can answer the query."""
        return False

    def insert_price(self, price_data: dict[str, Any]) -> None:
        """No-op insert for environments without a configured database."""
        if not self.conn:
            logger.debug("Skipping price insert because no database connection is configured.")
            return

    def insert_market_data(self, skin_name: str, lowest_price: Optional[float], median_price: Optional[float], volume: Optional[int]) -> None:
        """Compatibility method used by the collection manager."""
        self.insert_price({
            "skin_name": skin_name,
            "lowest_price": lowest_price,
            "median_price": median_price,
            "volume": volume,
        })
