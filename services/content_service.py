"""
Services for Content, Asset, and Variant CRUD operations.
"""

import json
from datetime import datetime
from typing import Optional, List

from models.database import get_connection


# ── helpers ──────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row) if row else {}


def _now() -> str:
    return datetime.now().isoformat()


# ── ContentService ───────────────────────────────────────────────────────

class ContentService:
    """CRUD + review workflow for the `contents` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new content row and return its id."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            tags = json.dumps(data.get("tags") or [])
            copyright_flags = json.dumps(data.get("copyright_flags") or {})

            cur = conn.execute(
                """
                INSERT INTO contents
                    (title, topic, language, content_type, status,
                     tags, copyright_flags, dedupe_hash, created_by,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("title", ""),
                    data.get("topic", ""),
                    data.get("language", "zh"),
                    data.get("content_type", "image_single"),
                    data.get("status", "draft"),
                    tags,
                    copyright_flags,
                    data.get("dedupe_hash", ""),
                    data.get("created_by"),
                    now,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, content_id: int) -> Optional[dict]:
        """Return a single content dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM contents WHERE id = ?", (content_id,)
            ).fetchone()
            if row is None:
                return None
            d = _row_to_dict(row)
            d["tags"] = json.loads(d.get("tags") or "[]")
            d["copyright_flags"] = json.loads(d.get("copyright_flags") or "{}")
            return d
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(
        self,
        status: Optional[str] = None,
        topic: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        """Return contents, optionally filtered by status / topic / content_type."""
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM contents WHERE 1=1"
            params: list = []

            if status is not None:
                query += " AND status = ?"
                params.append(status)
            if topic is not None:
                query += " AND topic = ?"
                params.append(topic)
            if content_type is not None:
                query += " AND content_type = ?"
                params.append(content_type)

            query += " ORDER BY id DESC"
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            results: List[dict] = []
            for row in rows:
                d = _row_to_dict(row)
                d["tags"] = json.loads(d.get("tags") or "[]")
                d["copyright_flags"] = json.loads(d.get("copyright_flags") or "{}")
                results.append(d)
            return results
        finally:
            conn.close()

    # -- update ----------------------------------------------------------------

    def update(self, content_id: int, data: dict) -> bool:
        """Update mutable fields of a content row. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            sets: List[str] = []
            params: list = []

            simple_fields = [
                "title", "topic", "language", "content_type",
                "status", "dedupe_hash", "created_by",
            ]
            for field in simple_fields:
                if field in data:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            # JSON fields
            if "tags" in data:
                sets.append("tags = ?")
                params.append(json.dumps(data["tags"] or []))
            if "copyright_flags" in data:
                sets.append("copyright_flags = ?")
                params.append(json.dumps(data["copyright_flags"] or {}))

            if not sets:
                return False

            sets.append("updated_at = ?")
            params.append(_now())
            params.append(content_id)

            cur = conn.execute(
                f"UPDATE contents SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- review ----------------------------------------------------------------

    def review(self, content_id: int, status: str, notes: str = "") -> bool:
        """
        Set content status for review workflow (e.g. approved / rejected).
        `notes` is stored in `copyright_flags.review_notes` for traceability.
        Returns True if a row was updated.
        """
        conn = get_connection(self.db_path)
        try:
            # Read current copyright_flags so we can merge review notes
            row = conn.execute(
                "SELECT copyright_flags FROM contents WHERE id = ?",
                (content_id,),
            ).fetchone()
            if row is None:
                return False

            flags = json.loads(row["copyright_flags"] or "{}")
            flags["review_notes"] = notes
            flags["reviewed_at"] = _now()

            cur = conn.execute(
                """
                UPDATE contents
                   SET status = ?, copyright_flags = ?, updated_at = ?
                 WHERE id = ?
                """,
                (status, json.dumps(flags), _now(), content_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, content_id: int) -> bool:
        """Delete a content row and all related records (cascade).
        Deletes: variants, jobs (and their job_logs/metrics),
        schedule_plans, performance_records, topic_suggestions,
        generation_tasks (and their generation_logs).
        Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            # Check existence first
            row = conn.execute(
                "SELECT id FROM contents WHERE id = ?", (content_id,)
            ).fetchone()
            if row is None:
                return False

            # Delete job_logs and metrics for jobs referencing this content
            job_ids = conn.execute(
                "SELECT id FROM jobs WHERE content_id = ?", (content_id,)
            ).fetchall()
            for job_row in job_ids:
                jid = job_row["id"]
                conn.execute("DELETE FROM job_logs WHERE job_id = ?", (jid,))
                conn.execute("DELETE FROM metrics WHERE job_id = ?", (jid,))

            # Delete jobs referencing this content
            conn.execute("DELETE FROM jobs WHERE content_id = ?", (content_id,))

            # Delete variants for this content
            conn.execute("DELETE FROM variants WHERE content_id = ?", (content_id,))

            # Delete schedule_plans for this content
            conn.execute("DELETE FROM schedule_plans WHERE content_id = ?", (content_id,))

            # Delete performance_records for this content
            conn.execute("DELETE FROM performance_records WHERE content_id = ?", (content_id,))

            # Delete generation_logs for generation_tasks referencing this content
            task_ids = conn.execute(
                "SELECT id FROM generation_tasks WHERE content_id = ?", (content_id,)
            ).fetchall()
            for task_row in task_ids:
                tid = task_row["id"]
                conn.execute("DELETE FROM generation_logs WHERE generation_task_id = ?", (tid,))

            # Delete generation_tasks referencing this content
            conn.execute("DELETE FROM generation_tasks WHERE content_id = ?", (content_id,))

            # Delete topic_suggestions that used this content
            conn.execute("DELETE FROM topic_suggestions WHERE used_content_id = ?", (content_id,))

            # Finally delete the content itself
            cur = conn.execute(
                "DELETE FROM contents WHERE id = ?", (content_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


# ── AssetService ─────────────────────────────────────────────────────────

class AssetService:
    """CRUD for the `assets` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        conn = get_connection(self.db_path)
        try:
            now = _now()
            meta = json.dumps(data.get("meta") or {})

            cur = conn.execute(
                """
                INSERT INTO assets
                    (asset_type, storage_url, sha256,
                     width, height, duration_sec, filesize_bytes,
                     meta, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("asset_type", "image"),
                    data.get("storage_url", ""),
                    data.get("sha256", ""),
                    data.get("width", 0),
                    data.get("height", 0),
                    data.get("duration_sec"),
                    data.get("filesize_bytes", 0),
                    meta,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, asset_id: int) -> Optional[dict]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM assets WHERE id = ?", (asset_id,)
            ).fetchone()
            if row is None:
                return None
            d = _row_to_dict(row)
            d["meta"] = json.loads(d.get("meta") or "{}")
            return d
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(self) -> List[dict]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM assets ORDER BY id DESC"
            ).fetchall()
            results: List[dict] = []
            for row in rows:
                d = _row_to_dict(row)
                d["meta"] = json.loads(d.get("meta") or "{}")
                results.append(d)
            return results
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, asset_id: int) -> bool:
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM assets WHERE id = ?", (asset_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


# ── VariantService ───────────────────────────────────────────────────────

class VariantService:
    """CRUD for the `variants` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        conn = get_connection(self.db_path)
        try:
            now = _now()
            hashtags = json.dumps(data.get("hashtags") or [])
            media_asset_ids = json.dumps(data.get("media_asset_ids") or [])

            cur = conn.execute(
                """
                INSERT INTO variants
                    (content_id, platform, caption, headline,
                     hashtags, cover_asset_id, media_asset_ids,
                     variant_fingerprint, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["content_id"],
                    data.get("platform"),
                    data.get("caption", ""),
                    data.get("headline", ""),
                    hashtags,
                    data.get("cover_asset_id"),
                    media_asset_ids,
                    data.get("variant_fingerprint", ""),
                    data.get("status", "ready"),
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, variant_id: int) -> Optional[dict]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM variants WHERE id = ?", (variant_id,)
            ).fetchone()
            if row is None:
                return None
            d = _row_to_dict(row)
            d["hashtags"] = json.loads(d.get("hashtags") or "[]")
            d["media_asset_ids"] = json.loads(d.get("media_asset_ids") or "[]")
            return d
        finally:
            conn.close()

    # -- list_by_content -------------------------------------------------------

    def list_by_content(self, content_id: int) -> List[dict]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM variants WHERE content_id = ? ORDER BY id DESC",
                (content_id,),
            ).fetchall()
            results: List[dict] = []
            for row in rows:
                d = _row_to_dict(row)
                d["hashtags"] = json.loads(d.get("hashtags") or "[]")
                d["media_asset_ids"] = json.loads(d.get("media_asset_ids") or "[]")
                results.append(d)
            return results
        finally:
            conn.close()

    # -- update_status ---------------------------------------------------------

    def update_status(self, variant_id: int, status: str) -> bool:
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE variants SET status = ? WHERE id = ?",
                (status, variant_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, variant_id: int) -> bool:
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM variants WHERE id = ?", (variant_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
