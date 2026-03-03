"""
Services for Policy CRUD operations.
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


def _deserialize_policy(d: dict) -> dict:
    """Deserialize JSON fields and convert enabled from INTEGER to bool."""
    d["posting_windows"] = json.loads(d.get("posting_windows") or "[]")
    d["topic_mix"] = json.loads(d.get("topic_mix") or "{}")
    d["enabled"] = d.get("enabled", 1) == 1
    return d


# ── PolicyService ───────────────────────────────────────────────────────

class PolicyService:
    """CRUD + toggle for the `policies` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new policy and return its id."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            posting_windows = json.dumps(data.get("posting_windows") or [])
            topic_mix = json.dumps(data.get("topic_mix") or {})
            enabled = 1 if data.get("enabled", True) else 0

            cur = conn.execute(
                """
                INSERT INTO policies
                    (name, scope_type, scope_id, platform,
                     posting_windows, max_per_day, max_per_hour,
                     min_interval_minutes, min_stagger_minutes,
                     cooldown_days, topic_mix, enabled,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("name", ""),
                    data.get("scope_type", "group"),
                    data.get("scope_id", ""),
                    data.get("platform", "instagram"),
                    posting_windows,
                    data.get("max_per_day", 10),
                    data.get("max_per_hour", 3),
                    data.get("min_interval_minutes", 30),
                    data.get("min_stagger_minutes", 5),
                    data.get("cooldown_days", 7),
                    topic_mix,
                    enabled,
                    now,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, policy_id: int) -> Optional[dict]:
        """Return a single policy dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM policies WHERE id = ?", (policy_id,)
            ).fetchone()
            if row is None:
                return None
            d = _row_to_dict(row)
            return _deserialize_policy(d)
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(
        self,
        platform: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> List[dict]:
        """Return policies, optionally filtered by platform / scope_type / scope_id."""
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM policies WHERE 1=1"
            params: list = []

            if platform is not None:
                query += " AND platform = ?"
                params.append(platform)
            if scope_type is not None:
                query += " AND scope_type = ?"
                params.append(scope_type)
            if scope_id is not None:
                query += " AND scope_id = ?"
                params.append(scope_id)

            query += " ORDER BY id DESC"

            rows = conn.execute(query, params).fetchall()
            results: List[dict] = []
            for row in rows:
                d = _row_to_dict(row)
                results.append(_deserialize_policy(d))
            return results
        finally:
            conn.close()

    # -- update ----------------------------------------------------------------

    def update(self, policy_id: int, data: dict) -> bool:
        """Update mutable fields of a policy. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            sets: List[str] = []
            params: list = []

            simple_fields = [
                "name", "scope_type", "scope_id", "platform",
                "max_per_day", "max_per_hour",
                "min_interval_minutes", "min_stagger_minutes",
                "cooldown_days",
            ]
            for field in simple_fields:
                if field in data:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            # JSON fields
            if "posting_windows" in data:
                sets.append("posting_windows = ?")
                params.append(json.dumps(data["posting_windows"] or []))
            if "topic_mix" in data:
                sets.append("topic_mix = ?")
                params.append(json.dumps(data["topic_mix"] or {}))

            # enabled: bool -> INTEGER
            if "enabled" in data:
                sets.append("enabled = ?")
                params.append(1 if data["enabled"] else 0)

            if not sets:
                return False

            sets.append("updated_at = ?")
            params.append(_now())
            params.append(policy_id)

            cur = conn.execute(
                f"UPDATE policies SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, policy_id: int) -> bool:
        """Delete a policy. Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM policies WHERE id = ?", (policy_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- toggle ----------------------------------------------------------------

    def toggle(self, policy_id: int, enabled: bool) -> bool:
        """Enable or disable a policy. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE policies SET enabled = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, _now(), policy_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
