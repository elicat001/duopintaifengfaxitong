import os
import pytest
from datetime import datetime, timedelta

from models.database import init_database, get_connection
from models.schemas import (
    ContentItem,
    ContentStatus,
    PerformanceRecord,
    Frequency,
    ScoreResult,
)
from agents.content_manager import ContentManager
from agents.performance_tracker import PerformanceTracker
from agents.scheduler import Scheduler


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_database(path)
    return path


def _add_content_with_performance(db_path, title, likes, comments, shares, views):
    """Helper: add content, record performance, return content_id."""
    cm = ContentManager(db_path)
    pt = PerformanceTracker(db_path)
    content_id = cm.add_content(ContentItem(title=title, body=f"Body of {title}", status=ContentStatus.ACTIVE))
    pt.record_performance(
        PerformanceRecord(
            content_id=content_id,
            likes=likes,
            comments=comments,
            shares=shares,
            views=views,
        )
    )
    return content_id


class TestGetDueContents:
    def test_returns_due_content(self, db_path):
        cid = _add_content_with_performance(db_path, "Due Item", 10, 5, 2, 100)
        # Set next_publish_at to the past so it's due
        conn = get_connection(db_path)
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE schedule_plans SET next_publish_at = ? WHERE content_id = ?",
            (past, cid),
        )
        conn.commit()
        conn.close()

        scheduler = Scheduler(db_path)
        due = scheduler.get_due_contents()
        assert len(due) == 1
        assert due[0].content_id == cid

    def test_excludes_paused(self, db_path):
        cid = _add_content_with_performance(db_path, "Paused Item", 0, 0, 0, 0)
        conn = get_connection(db_path)
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE schedule_plans SET next_publish_at = ?, frequency = ? WHERE content_id = ?",
            (past, "paused", cid),
        )
        conn.commit()
        conn.close()

        scheduler = Scheduler(db_path)
        due = scheduler.get_due_contents()
        assert len(due) == 0

    def test_excludes_future(self, db_path):
        cid = _add_content_with_performance(db_path, "Future Item", 10, 5, 2, 100)
        conn = get_connection(db_path)
        future = (datetime.now() + timedelta(days=10)).isoformat()
        conn.execute(
            "UPDATE schedule_plans SET next_publish_at = ? WHERE content_id = ?",
            (future, cid),
        )
        conn.commit()
        conn.close()

        scheduler = Scheduler(db_path)
        due = scheduler.get_due_contents()
        assert len(due) == 0


class TestExecutePublish:
    def test_publish_updates_plan(self, db_path):
        cid = _add_content_with_performance(db_path, "Publish Me", 10, 5, 2, 100)
        conn = get_connection(db_path)
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE schedule_plans SET next_publish_at = ? WHERE content_id = ?",
            (past, cid),
        )
        conn.commit()
        conn.close()

        scheduler = Scheduler(db_path)
        due = scheduler.get_due_contents()
        assert len(due) == 1

        success = scheduler.execute_publish(due[0])
        assert success is True

        # Verify publish_count incremented
        conn = get_connection(db_path)
        row = conn.execute(
            "SELECT * FROM schedule_plans WHERE content_id = ?", (cid,)
        ).fetchone()
        conn.close()
        assert row["publish_count"] == 1
        assert row["last_published_at"] is not None


class TestUpdatePlanFromScore:
    def test_updates_score_and_frequency(self, db_path):
        cid = _add_content_with_performance(db_path, "Score Update", 10, 5, 2, 100)
        scheduler = Scheduler(db_path)

        result = ScoreResult(
            content_id=cid, score=85.0, recommended_frequency=Frequency.HIGH
        )
        scheduler.update_plan_from_score(result)

        conn = get_connection(db_path)
        row = conn.execute(
            "SELECT * FROM schedule_plans WHERE content_id = ?", (cid,)
        ).fetchone()
        conn.close()

        assert row["score"] == 85.0
        assert row["frequency"] == "high"
        assert row["next_publish_at"] is not None


class TestRunCycle:
    def test_full_cycle(self, db_path):
        # Add high-performing content (due for publish)
        cid1 = _add_content_with_performance(
            db_path, "High Perf", 500, 100, 50, 10000
        )
        # Add low-performing content
        cid2 = _add_content_with_performance(db_path, "Low Perf", 0, 0, 0, 5)

        # Set both as due
        conn = get_connection(db_path)
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        conn.execute(
            "UPDATE schedule_plans SET next_publish_at = ?", (past,)
        )
        conn.commit()
        conn.close()

        scheduler = Scheduler(db_path)
        stats = scheduler.run_cycle()

        assert stats["published"] == 2
        assert stats["rescheduled"] + stats["paused"] == 2

        # Verify high-perf content is not paused
        conn = get_connection(db_path)
        row1 = conn.execute(
            "SELECT * FROM schedule_plans WHERE content_id = ?", (cid1,)
        ).fetchone()
        conn.close()
        assert row1["frequency"] != "paused"
        assert row1["score"] > 0

    def test_empty_cycle(self, db_path):
        scheduler = Scheduler(db_path)
        stats = scheduler.run_cycle()
        assert stats["published"] == 0
        assert stats["rescheduled"] == 0
        assert stats["paused"] == 0
