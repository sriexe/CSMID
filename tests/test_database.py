import sqlite3

import pytest

import config
import database


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    database.init_db()
    yield db_path


def test_insert_and_fetch_record() -> None:
    record_id = database.insert_record(
        source="test",
        title="Example",
        url="https://example.com",
        raw_data='{"title": "Example"}',
    )

    records = database.fetch_records(limit=1)
    assert len(records) == 1
    assert records[0]["id"] == record_id
    assert records[0]["title"] == "Example"
