"""
Unit tests for the ContentManager module.

Each test gets a fresh temporary SQLite database with tables already created.
"""

import os
import tempfile

import pytest

from agents.content_manager import ContentManager
from models.database import get_connection, init_database
from models.schemas import ContentItem, ContentStatus


@pytest.fixture()
def db_path(tmp_path):
    """Create a temporary database file and initialise the schema."""
    path = str(tmp_path / "test.db")
    init_database(path)
    return path


@pytest.fixture()
def manager(db_path):
    """Return a ContentManager wired to the temporary database."""
    return ContentManager(db_path)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_item(**overrides) -> ContentItem:
    defaults = {
        "title": "Test Title",
        "body": "Test body content.",
        "content_type": "article",
        "status": ContentStatus.ACTIVE,
    }
    defaults.update(overrides)
    return ContentItem(**defaults)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

class TestAddAndGetContent:
    """test_add_and_get_content"""

    def test_add_returns_positive_id(self, manager):
        item = _make_item()
        content_id = manager.add_content(item)
        assert isinstance(content_id, int)
        assert content_id > 0

    def test_get_returns_matching_item(self, manager):
        item = _make_item(title="My Article", body="Hello world")
        content_id = manager.add_content(item)

        fetched = manager.get_content(content_id)
        assert fetched is not None
        assert fetched.id == content_id
        assert fetched.title == "My Article"
        assert fetched.body == "Hello world"
        assert fetched.content_type == "article"
        assert fetched.status == ContentStatus.ACTIVE

    def test_get_nonexistent_returns_none(self, manager):
        assert manager.get_content(9999) is None

    def test_add_creates_default_schedule_plan(self, manager, db_path):
        item = _make_item()
        content_id = manager.add_content(item)

        # Verify directly in the database that a schedule_plans row exists
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM schedule_plans WHERE content_id = ?",
                (content_id,),
            ).fetchone()
            assert row is not None
            assert row["frequency"] == "normal"
            assert row["score"] == 0.0
            assert row["next_publish_at"] is not None
        finally:
            conn.close()


class TestListContentsFilterByStatus:
    """test_list_contents_filter_by_status"""

    def test_list_all(self, manager):
        manager.add_content(_make_item(title="A"))
        manager.add_content(_make_item(title="B"))
        manager.add_content(_make_item(title="C", status=ContentStatus.PAUSED))

        items = manager.list_contents()
        assert len(items) == 3

    def test_filter_active(self, manager):
        manager.add_content(_make_item(title="Active1"))
        manager.add_content(_make_item(title="Paused1", status=ContentStatus.PAUSED))

        active_items = manager.list_contents(status=ContentStatus.ACTIVE)
        assert len(active_items) == 1
        assert active_items[0].title == "Active1"

    def test_filter_paused(self, manager):
        manager.add_content(_make_item(title="Active1"))
        manager.add_content(_make_item(title="Paused1", status=ContentStatus.PAUSED))

        paused_items = manager.list_contents(status=ContentStatus.PAUSED)
        assert len(paused_items) == 1
        assert paused_items[0].title == "Paused1"

    def test_filter_returns_empty_when_no_match(self, manager):
        manager.add_content(_make_item(title="Active1"))
        retired_items = manager.list_contents(status=ContentStatus.RETIRED)
        assert retired_items == []


class TestUpdateStatus:
    """test_update_status"""

    def test_update_existing(self, manager):
        content_id = manager.add_content(_make_item())
        result = manager.update_status(content_id, ContentStatus.PAUSED)
        assert result is True

        updated = manager.get_content(content_id)
        assert updated is not None
        assert updated.status == ContentStatus.PAUSED

    def test_update_nonexistent_returns_false(self, manager):
        result = manager.update_status(9999, ContentStatus.RETIRED)
        assert result is False

    def test_update_preserves_other_fields(self, manager):
        content_id = manager.add_content(
            _make_item(title="Original", body="Keep me")
        )
        manager.update_status(content_id, ContentStatus.RETIRED)

        item = manager.get_content(content_id)
        assert item is not None
        assert item.title == "Original"
        assert item.body == "Keep me"
        assert item.status == ContentStatus.RETIRED


class TestDeleteContent:
    """test_delete_content"""

    def test_delete_existing(self, manager):
        content_id = manager.add_content(_make_item())
        result = manager.delete_content(content_id)
        assert result is True

        # Content should no longer be retrievable
        assert manager.get_content(content_id) is None

    def test_delete_nonexistent_returns_false(self, manager):
        result = manager.delete_content(9999)
        assert result is False

    def test_delete_removes_schedule_plan(self, manager, db_path):
        content_id = manager.add_content(_make_item())

        # Confirm schedule plan exists
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM schedule_plans WHERE content_id = ?",
                (content_id,),
            ).fetchone()
            assert row is not None
        finally:
            conn.close()

        # Delete the content
        manager.delete_content(content_id)

        # Confirm schedule plan is also removed
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM schedule_plans WHERE content_id = ?",
                (content_id,),
            ).fetchone()
            assert row is None
        finally:
            conn.close()

    def test_delete_does_not_affect_other_items(self, manager):
        id1 = manager.add_content(_make_item(title="Keep"))
        id2 = manager.add_content(_make_item(title="Delete"))

        manager.delete_content(id2)

        assert manager.get_content(id1) is not None
        assert manager.get_content(id2) is None
