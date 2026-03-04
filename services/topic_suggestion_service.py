"""
Service for TopicSuggestion CRUD and analytics.
"""

import json
from datetime import datetime
from typing import Optional, List

from models.database import get_connection


# ── helpers ──────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict, deserialising JSON fields."""
    if row is None:
        return {}
    d = dict(row)
    for field in ("keywords", "suggested_tags", "suggested_platforms"):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _now() -> str:
    return datetime.now().isoformat()


# ── TopicSuggestionService ─────────────────────────────────────────────

class TopicSuggestionService:
    """CRUD + analytics for the `topic_suggestions` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new topic suggestion and return its id."""
        conn = get_connection(self.db_path)
        try:
            now = _now()

            keywords = data.get("keywords", [])
            if not isinstance(keywords, str):
                keywords = json.dumps(keywords, ensure_ascii=False)

            suggested_tags = data.get("suggested_tags", [])
            if not isinstance(suggested_tags, str):
                suggested_tags = json.dumps(suggested_tags, ensure_ascii=False)

            suggested_platforms = data.get("suggested_platforms", [])
            if not isinstance(suggested_platforms, str):
                suggested_platforms = json.dumps(suggested_platforms, ensure_ascii=False)

            cur = conn.execute(
                """
                INSERT INTO topic_suggestions
                    (topic, description, reasoning, source_type,
                     source_trend_id, keywords, suggested_tags,
                     suggested_content_type, suggested_platforms,
                     score, historical_performance, trend_relevance,
                     freshness_score, status, used_content_id,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("topic", ""),
                    data.get("description", ""),
                    data.get("reasoning", ""),
                    data.get("source_type", "ai"),
                    data.get("source_trend_id"),
                    keywords,
                    suggested_tags,
                    data.get("suggested_content_type", "image_single"),
                    suggested_platforms,
                    data.get("score", 0.0),
                    data.get("historical_performance", 0.0),
                    data.get("trend_relevance", 0.0),
                    data.get("freshness_score", 0.0),
                    data.get("status", "pending"),
                    data.get("used_content_id"),
                    now,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, suggestion_id: int) -> Optional[dict]:
        """Return a single topic suggestion dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM topic_suggestions WHERE id = ?", (suggestion_id,)
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row)
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(
        self,
        status: Optional[str] = None,
        sort_by: str = "score",
        limit: int = 50,
    ) -> List[dict]:
        """Return topic suggestions, optionally filtered by status and sorted."""
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM topic_suggestions WHERE 1=1"
            params: list = []

            if status is not None:
                query += " AND status = ?"
                params.append(status)

            # Whitelist valid sort columns to prevent SQL injection
            allowed_sorts = {
                "score", "historical_performance", "trend_relevance",
                "freshness_score", "created_at", "id",
            }
            if sort_by not in allowed_sorts:
                sort_by = "score"

            query += f" ORDER BY {sort_by} DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            conn.close()

    # -- update_status ---------------------------------------------------------

    def update_status(self, suggestion_id: int, status: str) -> bool:
        """Update the status of a topic suggestion. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE topic_suggestions SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), suggestion_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- mark_used -------------------------------------------------------------

    def mark_used(self, suggestion_id: int, content_id: int) -> bool:
        """Mark a suggestion as used and link it to the produced content.

        Sets status='used' and used_content_id=content_id.
        Returns True if a row was updated.
        """
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                """
                UPDATE topic_suggestions
                SET status = 'used', used_content_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (content_id, _now(), suggestion_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, suggestion_id: int) -> bool:
        """Delete a topic suggestion. Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM topic_suggestions WHERE id = ?", (suggestion_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- get_stats -------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return counts of topic suggestions grouped by status."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM topic_suggestions GROUP BY status"
            ).fetchall()
            counts = {row["status"]: row["cnt"] for row in rows}
            total = sum(counts.values())
            return {
                "total": total,
                "pending": counts.get("pending", 0),
                "accepted": counts.get("accepted", 0),
                "rejected": counts.get("rejected", 0),
                "used": counts.get("used", 0),
            }
        finally:
            conn.close()

    # -- analyze_top_topics ----------------------------------------------------

    def analyze_top_topics(self) -> List[dict]:
        """Query metrics + contents + jobs to find the top-performing topics.

        Returns up to 20 topics sorted by average likes descending, each
        containing: topic, avg_views, avg_likes, avg_comments, avg_shares, cnt.

        Falls back to content-based analysis (without metrics) when no
        performance data is available.
        """
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT c.topic,
                       AVG(m.views)    AS avg_views,
                       AVG(m.likes)    AS avg_likes,
                       AVG(m.comments) AS avg_comments,
                       AVG(m.shares)   AS avg_shares,
                       COUNT(*)        AS cnt
                FROM contents c
                JOIN jobs j    ON j.content_id = c.id
                JOIN metrics m ON m.job_id = j.id
                WHERE j.state = 'success' AND c.topic != ''
                GROUP BY c.topic
                ORDER BY avg_likes DESC
                LIMIT 20
                """
            ).fetchall()
            results = [dict(row) for row in rows]

            # Fallback: when no metrics data, derive suggestions from contents
            if not results:
                rows = conn.execute(
                    """
                    SELECT c.topic,
                           0 AS avg_views,
                           0 AS avg_likes,
                           0 AS avg_comments,
                           0 AS avg_shares,
                           COUNT(*) AS cnt
                    FROM contents c
                    WHERE c.topic IS NOT NULL AND c.topic != ''
                    GROUP BY c.topic
                    ORDER BY cnt DESC
                    LIMIT 20
                    """
                ).fetchall()
                results = [dict(row) for row in rows]

            return results
        finally:
            conn.close()
