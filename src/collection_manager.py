"""
collection_manager.py

Owns all collection-related logic.

The CLI, scheduler, and future dashboard should all call this class
instead of implementing their own collection workflows.
"""

from datetime import datetime, timedelta, timezone

from database import (
    SessionLocal,
    get_or_create_skin,
    insert_market_history,
    MarketHistory,
)
from scraper import SteamMarketScraper, SteamMarketError, SteamRateLimitError


class CollectionManager:

    def __init__(self):
        self.scraper = SteamMarketScraper()

    def get_recently_collected_names(self, since_hours: float) -> set[str]:
        cutoff = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=since_hours)
        )

        session = SessionLocal()

        try:
            rows = (
                session.query(MarketHistory.market_hash_name)
                .filter(MarketHistory.collected_at_utc >= cutoff)
                .distinct()
                .all()
            )

            return {r[0] for r in rows}

        finally:
            session.close()

    def _store_record(self, session, market_hash_name, record):

        if not record.success:
            return "no_listing"

        skin = get_or_create_skin(session, market_hash_name)

        row = insert_market_history(
            session,
            skin,
            record
        )

        if row is None:
            return "skipped_duplicate"

        return "collected"

    def collect_batch(
        self,
        names,
        skip_names=None,
    ):

        skip_names = skip_names or set()

        to_fetch = [
            n
            for n in names
            if n not in skip_names
        ]

        already_skipped = len(names) - len(to_fetch)

        if already_skipped:
            print(
                f"ℹ️  Skipping {already_skipped} skin(s) already collected recently (--resume)."
            )

        print(f"Collecting {len(to_fetch)} skins...\n")

        session = SessionLocal()

        counts = {
            "collected": 0,
            "skipped_duplicate": 0,
            "no_listing": 0,
        }

        try:

            for name in to_fetch:

                try:
                    record = self.scraper.fetch_price(name)

                except SteamRateLimitError as exc:

                    print(f"\n❌ Rate limited on '{name}': {exc}")

                    print(f"Stopping batch early. Progress so far: {counts}")

                    session.commit()

                    return 1

                except SteamMarketError as exc:

                    print(f"⚠️ '{name}' failed: {exc}")

                    counts["no_listing"] += 1

                    continue

                status = self._store_record(
                    session,
                    name,
                    record,
                )

                counts[status] += 1

                symbol = {
                    "collected": "✅",
                    "skipped_duplicate": "ℹ️",
                    "no_listing": "⚠️",
                }[status]

                print(f"{symbol} {name}: {status}")

            session.commit()

        except Exception:
            session.rollback()
            raise

        finally:
            session.close()

        print(
            f"\nDone. "
            f"{counts['collected']} collected, "
            f"{counts['skipped_duplicate']} duplicates skipped, "
            f"{counts['no_listing']} had no listing/failed."
        )

        return 0