"""
Content Manager module.

Provides CRUD operations for content items, backed by SQLite.
When a new content item is added, a default SchedulePlan is created automatically.
"""

import sqlite3
from datetime import datetime
from typing import List, Optional

from models.database import get_connection
from models.schemas import ContentItem, ContentStatus, Frequency


class ContentManager:
    """Manages content lifecycle: creation, retrieval, update, and deletion."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    @staticmethod
    def _row_to_content_item(row: sqlite3.Row) -> ContentItem:
        """Convert a sqlite3.Row from the contents table to a ContentItem."""
        return ContentItem(
            id=row["id"],
            title=row["title"],
            body=row["body"],
            content_type=row["content_type"],
            status=ContentStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_content(self, item: ContentItem) -> int:
        """
        Insert a new content item and create a default schedule plan for it.

        Returns the auto-generated content_id.
        """
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                """
                INSERT INTO contents (title, body, content_type, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item.title,
                    item.body,
                    item.content_type,
                    item.status.value,
                    now,
                    now,
                ),
            )
            content_id: int = cursor.lastrowid  # type: ignore[assignment]

            # Create a default schedule plan
            conn.execute(
                """
                INSERT INTO schedule_plans (content_id, score, frequency, next_publish_at, updated_at)
                VALUES (?, 0.0, ?, ?, ?)
                """,
                (
                    content_id,
                    Frequency.NORMAL.value,
                    now,
                    now,
                ),
            )

            conn.commit()
            return content_id
        finally:
            conn.close()

    def get_content(self, content_id: int) -> Optional[ContentItem]:
        """Retrieve a single content item by its id, or None if not found."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM contents WHERE id = ?", (content_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_content_item(row)
        finally:
            conn.close()

    def list_contents(
        self, status: Optional[ContentStatus] = None
    ) -> List[ContentItem]:
        """
        List all content items, optionally filtered by status.
        """
        conn = self._get_conn()
        try:
            if status is not None:
                rows = conn.execute(
                    "SELECT * FROM contents WHERE status = ? ORDER BY id",
                    (status.value,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM contents ORDER BY id"
                ).fetchall()
            return [self._row_to_content_item(r) for r in rows]
        finally:
            conn.close()

    def update_status(self, content_id: int, status: ContentStatus) -> bool:
        """
        Update the status of a content item.

        Returns True if a row was updated, False if the content_id was not found.
        """
        conn = self._get_conn()
        try:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                "UPDATE contents SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, content_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_content(self, content_id: int) -> bool:
        """
        Delete a content item and its associated schedule plan.

        Returns True if the content existed and was deleted, False otherwise.
        """
        conn = self._get_conn()
        try:
            # Delete the schedule plan first (foreign-key child)
            conn.execute(
                "DELETE FROM schedule_plans WHERE content_id = ?",
                (content_id,),
            )
            # Delete the content itself
            cursor = conn.execute(
                "DELETE FROM contents WHERE id = ?", (content_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
