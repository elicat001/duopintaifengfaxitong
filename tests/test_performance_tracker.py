"""
Unit tests for the PerformanceTracker module.

Each test gets a fresh temporary SQLite database with tables already created.
"""

from datetime import datetime, timedelta

import pytest

from agents.performance_tracker import PerformanceTracker
from models.database import get_connection, init_database
from models.schemas import PerformanceRecord


@pytest.fixture()
def db_path(tmp_path):
    """Create a temporary database file and initialise the schema."""
    path = str(tmp_path / "test.db")
    init_database(path)
    return path


@pytest.fixture()
def tracker(db_path):
    """Return a PerformanceTracker wired to the temporary database."""
    return PerformanceTracker(db_path)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _insert_content(db_path: str, title: str = "Test", status: str = "active") -> int:
    """Insert a content row directly and return its id."""
    conn = get_connection(db_path)
    try:
        now = datetime.now().isoformat()
        cursor = conn.execute(
            """
            INSERT INTO contents (title, body, content_type, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, "body", "article", status, now, now),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def _make_record(content_id: int, **overrides) -> PerformanceRecord:
    defaults = {
        "content_id": content_id,
        "likes": 10,
        "comments": 2,
        "shares": 1,
        "views": 100,
    }
    defaults.update(overrides)
    return PerformanceRecord(**defaults)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestRecordAndGetLatest:
    """test_record_and_get_latest"""

    def test_record_returns_positive_id(self, tracker, db_path):
        cid = _insert_content(db_path)
        record = _make_record(cid)
        record_id = tracker.record_performance(record)
        assert isinstance(record_id, int)
        assert record_id > 0

    def test_get_latest_returns_most_recent(self, tracker, db_path):
        cid = _insert_content(db_path)

        tracker.record_performance(_make_record(cid, likes=5))
        tracker.record_performance(_make_record(cid, likes=20))

        latest = tracker.get_latest_record(cid)
        assert latest is not None
        assert latest.content_id == cid
        assert latest.likes == 20

    def test_recorded_at_is_populated(self, tracker, db_path):
        cid = _insert_content(db_path)
        tracker.record_performance(_make_record(cid))

        latest = tracker.get_latest_record(cid)
        assert latest is not None
        assert latest.recorded_at is not None

    def test_record_with_explicit_timestamp(self, tracker, db_path):
        cid = _insert_content(db_path)
        ts = datetime(2025, 6, 15, 12, 0, 0)
        tracker.record_performance(_make_record(cid, recorded_at=ts))

        latest = tracker.get_latest_record(cid)
        assert latest is not None
        # The stored timestamp should match the provided one
        assert "2025-06-15" in str(latest.recorded_at)


class TestGetRecordsSince:
    """test_get_records_since"""

    def test_returns_records_after_cutoff(self, tracker, db_path):
        cid = _insert_content(db_path)

        t1 = datetime(2025, 1, 1, 10, 0, 0)
        t2 = datetime(2025, 1, 2, 10, 0, 0)
        t3 = datetime(2025, 1, 3, 10, 0, 0)

        tracker.record_performance(_make_record(cid, likes=1, recorded_at=t1))
        tracker.record_performance(_make_record(cid, likes=2, recorded_at=t2))
        tracker.record_performance(_make_record(cid, likes=3, recorded_at=t3))

        cutoff = datetime(2025, 1, 1, 12, 0, 0)
        records = tracker.get_records_since(cid, cutoff)

        assert len(records) == 2
        assert records[0].likes == 2
        assert records[1].likes == 3

    def test_returns_empty_when_none_after_cutoff(self, tracker, db_path):
        cid = _insert_content(db_path)
        t1 = datetime(2025, 1, 1, 10, 0, 0)
        tracker.record_performance(_make_record(cid, recorded_at=t1))

        cutoff = datetime(2025, 12, 31, 23, 59, 59)
        records = tracker.get_records_since(cid, cutoff)
        assert records == []

    def test_returns_empty_for_nonexistent_content(self, tracker):
        records = tracker.get_records_since(9999, datetime(2020, 1, 1))
        assert records == []


class TestGetAllLatestRecords:
    """test_get_all_latest_records"""

    def test_returns_latest_for_each_active_content(self, tracker, db_path):
        cid1 = _insert_content(db_path, title="Active1", status="active")
        cid2 = _insert_content(db_path, title="Active2", status="active")

        # Two records for content 1 -- should only get the latest
        tracker.record_performance(_make_record(cid1, likes=1))
        tracker.record_performance(_make_record(cid1, likes=10))

        # One record for content 2
        tracker.record_performance(_make_record(cid2, likes=50))

        results = tracker.get_all_latest_records()
        assert len(results) == 2

        by_cid = {r.content_id: r for r in results}
        assert by_cid[cid1].likes == 10
        assert by_cid[cid2].likes == 50

    def test_excludes_non_active_content(self, tracker, db_path):
        cid_active = _insert_content(db_path, title="Active", status="active")
        cid_paused = _insert_content(db_path, title="Paused", status="paused")
        cid_retired = _insert_content(db_path, title="Retired", status="retired")

        tracker.record_performance(_make_record(cid_active, likes=5))
        tracker.record_performance(_make_record(cid_paused, likes=15))
        tracker.record_performance(_make_record(cid_retired, likes=25))

        results = tracker.get_all_latest_records()
        assert len(results) == 1
        assert results[0].content_id == cid_active
        assert results[0].likes == 5

    def test_returns_empty_when_no_records(self, tracker):
        results = tracker.get_all_latest_records()
        assert results == []


class TestGetLatestRecordNonexistent:
    """test_get_latest_record_nonexistent"""

    def test_returns_none_for_missing_content(self, tracker):
        result = tracker.get_latest_record(9999)
        assert result is None

    def test_returns_none_for_content_with_no_records(self, tracker, db_path):
        cid = _insert_content(db_path)
        result = tracker.get_latest_record(cid)
        assert result is None
