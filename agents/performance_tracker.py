"""
Performance Tracker module.

Provides append-only recording and querying of content performance metrics,
backed by SQLite.
"""

import sqlite3
from datetime import datetime
from typing import List, Optional

from models.database import get_connection
from models.schemas import PerformanceRecord


class PerformanceTracker:
    """Records and queries performance data for content items."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> PerformanceRecord:
        """Convert a sqlite3.Row from performance_records to a PerformanceRecord."""
        return PerformanceRecord(
            id=row["id"],
            content_id=row["content_id"],
            likes=row["likes"],
            comments=row["comments"],
            shares=row["shares"],
            views=row["views"],
            recorded_at=row["recorded_at"],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_performance(self, record: PerformanceRecord) -> int:
        """
        Append a new performance record to the database.

        Returns the auto-generated record id.
        """
        conn = self._get_conn()
        try:
            now = record.recorded_at or datetime.now()
            cursor = conn.execute(
                """
                INSERT INTO performance_records
                    (content_id, likes, comments, shares, views, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.content_id,
                    record.likes,
                    record.comments,
                    record.shares,
                    record.views,
                    now.isoformat() if isinstance(now, datetime) else now,
                ),
            )
            conn.commit()
            record_id: int = cursor.lastrowid  # type: ignore[assignment]
            return record_id
        finally:
            conn.close()

    def get_latest_record(self, content_id: int) -> Optional[PerformanceRecord]:
        """
        Retrieve the most recent performance record for the given content_id.

        Returns None if no records exist for this content.
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                """
                SELECT * FROM performance_records
                WHERE content_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (content_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_record(row)
        finally:
            conn.close()

    def get_records_since(
        self, content_id: int, since: datetime
    ) -> List[PerformanceRecord]:
        """
        Retrieve all performance records for the given content_id
        recorded after *since* (exclusive), ordered oldest-first.
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM performance_records
                WHERE content_id = ? AND recorded_at > ?
                ORDER BY id ASC
                """,
                (content_id, since.isoformat()),
            ).fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            conn.close()

    def get_all_latest_records(self) -> List[PerformanceRecord]:
        """
        For every *active* content item, return its most recent performance
        record (the one with the highest id).

        Uses a sub-query to find the MAX(id) per content_id, then JOINs
        with the contents table to keep only rows whose content is active.
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT pr.* FROM performance_records pr
                JOIN contents c ON pr.content_id = c.id
                WHERE pr.id IN (
                    SELECT MAX(id) FROM performance_records GROUP BY content_id
                )
                AND c.status = 'active'
                ORDER BY pr.content_id ASC
                """,
            ).fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            conn.close()
