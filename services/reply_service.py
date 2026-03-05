"""
Services for ReplyCampaign, ReplyTask, and ReplyLog CRUD operations.
Includes state-machines for campaign and task lifecycle transitions.
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


# ── JSON field helpers ───────────────────────────────────────────────────

_CAMPAIGN_JSON_FIELDS = ("keywords", "exclude_keywords", "schedule_windows")
_TASK_JSON_FIELDS = ("reply_content_alternatives",)


def _serialize_json_fields(data: dict, fields: tuple) -> dict:
    """Serialize list/dict values to JSON strings for storage."""
    out = dict(data)
    for f in fields:
        if f in out and not isinstance(out[f], str):
            out[f] = json.dumps(out[f], ensure_ascii=False)
    return out


def _deserialize_json_fields(d: dict, fields: tuple) -> dict:
    """Deserialize JSON string values back to Python objects."""
    for f in fields:
        if isinstance(d.get(f), str):
            try:
                d[f] = json.loads(d[f])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ── State machine definitions ──────────────────────────────────────────

CAMPAIGN_TRANSITIONS = {
    "draft":     {"active", "cancelled"},
    "active":    {"paused", "completed", "failed"},
    "paused":    {"active", "cancelled"},
    "completed": {"active"},
    "failed":    {"active", "cancelled"},
}

REPLY_TASK_TRANSITIONS = {
    "pending":    {"generating", "ready", "skipped", "cancelled"},
    "generating": {"ready", "failed"},
    "ready":      {"executing", "cancelled"},
    "executing":  {"verifying", "failed"},
    "verifying":  {"success", "failed"},
    "failed":     {"pending"},
    "skipped":    set(),
    "cancelled":  set(),
    "success":    set(),
}


# ── ReplyCampaignService ────────────────────────────────────────────────

class ReplyCampaignService:
    """CRUD + state-machine for the `reply_campaigns` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new reply campaign and return its id."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            d = _serialize_json_fields(data, _CAMPAIGN_JSON_FIELDS)
            cur = conn.execute(
                """
                INSERT INTO reply_campaigns
                    (name, campaign_type, platform, account_id, status,
                     keywords, exclude_keywords,
                     target_post_count, max_replies_per_run,
                     schedule_type, schedule_windows,
                     min_interval_minutes, max_interval_minutes,
                     max_replies_per_hour, max_replies_per_day, cooldown_minutes,
                     ai_config_key, reply_tone, reply_language,
                     reply_max_length, custom_instructions,
                     warmup_enabled, warmup_browse_count,
                     min_read_seconds, max_read_seconds,
                     typing_speed_min, typing_speed_max,
                     total_discovered, total_replied, total_failed,
                     next_run_at, error_message,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    d.get("name", ""),
                    d.get("campaign_type", "keyword"),
                    d.get("platform", ""),
                    d.get("account_id"),
                    d.get("status", "draft"),
                    d.get("keywords", "[]"),
                    d.get("exclude_keywords", "[]"),
                    d.get("target_post_count", 10),
                    d.get("max_replies_per_run", 5),
                    d.get("schedule_type", "immediate"),
                    d.get("schedule_windows", "[]"),
                    d.get("min_interval_minutes", 15),
                    d.get("max_interval_minutes", 60),
                    d.get("max_replies_per_hour", 3),
                    d.get("max_replies_per_day", 15),
                    d.get("cooldown_minutes", 30),
                    d.get("ai_config_key", "default"),
                    d.get("reply_tone", "friendly"),
                    d.get("reply_language", "zh"),
                    d.get("reply_max_length", 200),
                    d.get("custom_instructions", ""),
                    d.get("warmup_enabled", 1),
                    d.get("warmup_browse_count", 3),
                    d.get("min_read_seconds", 5),
                    d.get("max_read_seconds", 30),
                    d.get("typing_speed_min", 30),
                    d.get("typing_speed_max", 80),
                    d.get("total_discovered", 0),
                    d.get("total_replied", 0),
                    d.get("total_failed", 0),
                    d.get("next_run_at"),
                    d.get("error_message", ""),
                    now,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, campaign_id: int) -> Optional[dict]:
        """Return a single campaign dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM reply_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if row is None:
                return None
            d = _row_to_dict(row)
            return _deserialize_json_fields(d, _CAMPAIGN_JSON_FIELDS)
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(
        self,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        account_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[dict]:
        """Return campaigns, optionally filtered by status / platform / account_id."""
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM reply_campaigns WHERE 1=1"
            params: list = []

            if status is not None:
                query += " AND status = ?"
                params.append(status)
            if platform is not None:
                query += " AND platform = ?"
                params.append(platform)
            if account_id is not None:
                query += " AND account_id = ?"
                params.append(account_id)

            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                results.append(_deserialize_json_fields(d, _CAMPAIGN_JSON_FIELDS))
            return results
        finally:
            conn.close()

    # -- update ----------------------------------------------------------------

    def update(self, campaign_id: int, data: dict) -> bool:
        """Update mutable fields of a campaign. Returns True if updated."""
        conn = get_connection(self.db_path)
        try:
            d = _serialize_json_fields(data, _CAMPAIGN_JSON_FIELDS)
            d["updated_at"] = _now()

            # Build dynamic SET clause from provided keys
            set_parts = []
            params = []
            for key, value in d.items():
                set_parts.append(f"{key} = ?")
                params.append(value)

            if not set_parts:
                return False

            params.append(campaign_id)
            cur = conn.execute(
                f"UPDATE reply_campaigns SET {', '.join(set_parts)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, campaign_id: int) -> bool:
        """Delete a campaign and its related reply_tasks and reply_logs. Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            # Delete logs for all tasks in this campaign
            conn.execute(
                """
                DELETE FROM reply_logs WHERE reply_task_id IN
                    (SELECT id FROM reply_tasks WHERE campaign_id = ?)
                """,
                (campaign_id,),
            )
            conn.execute(
                "DELETE FROM reply_tasks WHERE campaign_id = ?", (campaign_id,)
            )
            cur = conn.execute(
                "DELETE FROM reply_campaigns WHERE id = ?", (campaign_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- transition (state machine) --------------------------------------------

    def transition(self, campaign_id: int, new_status: str) -> bool:
        """Attempt a state-machine transition for the given campaign.

        * Validates the transition against CAMPAIGN_TRANSITIONS.
        * Uses atomic UPDATE WHERE status=current to prevent race conditions.
        * Automatically updates ``updated_at``.

        Returns True if the transition was applied, False otherwise.
        """
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM reply_campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
            if row is None:
                return False

            campaign = _row_to_dict(row)
            current_status = campaign["status"]

            # Check if transition is legal
            allowed = CAMPAIGN_TRANSITIONS.get(current_status)
            if allowed is None or new_status not in allowed:
                return False

            now = _now()

            # Atomic: only update if status hasn't changed since we read it
            cur = conn.execute(
                """
                UPDATE reply_campaigns
                SET status = ?,
                    updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (new_status, now, campaign_id, current_status),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- increment_counters ----------------------------------------------------

    def increment_counters(
        self,
        campaign_id: int,
        discovered: int = 0,
        replied: int = 0,
        failed: int = 0,
    ):
        """SQL-level increment of campaign counters."""
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                UPDATE reply_campaigns
                SET discovered_count = discovered_count + ?,
                    replied_count    = replied_count + ?,
                    failed_count     = failed_count + ?,
                    updated_at       = ?
                WHERE id = ?
                """,
                (discovered, replied, failed, _now(), campaign_id),
            )
            conn.commit()
        finally:
            conn.close()

    # -- update_next_run -------------------------------------------------------

    def update_next_run(self, campaign_id: int, next_run_at: str):
        """Set next_run_at for a campaign."""
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                """
                UPDATE reply_campaigns
                SET next_run_at = ?,
                    updated_at  = ?
                WHERE id = ?
                """,
                (next_run_at, _now(), campaign_id),
            )
            conn.commit()
        finally:
            conn.close()


# ── ReplyTaskService ─────────────────────────────────────────────────────

class ReplyTaskService:
    """CRUD + state-machine for the `reply_tasks` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new reply task and return its id."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            d = _serialize_json_fields(data, _TASK_JSON_FIELDS)
            cur = conn.execute(
                """
                INSERT INTO reply_tasks
                    (campaign_id, account_id, platform, post_url,
                     post_author, post_title, post_content,
                     post_media_type, post_likes, post_comments,
                     reply_content, reply_content_alternatives,
                     selected_alternative, scheduled_at,
                     state, attempt_count, max_attempts,
                     reply_post_url, reply_screenshot,
                     last_error_code, last_error_message,
                     ai_tokens_used,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    d.get("campaign_id"),
                    d.get("account_id"),
                    d.get("platform", ""),
                    d.get("post_url", ""),
                    d.get("post_author", ""),
                    d.get("post_title", ""),
                    d.get("post_content", ""),
                    d.get("post_media_type", ""),
                    d.get("post_likes", 0),
                    d.get("post_comments", 0),
                    d.get("reply_content", ""),
                    d.get("reply_content_alternatives", "[]"),
                    d.get("selected_alternative", 0),
                    d.get("scheduled_at"),
                    d.get("state", "pending"),
                    d.get("attempt_count", 0),
                    d.get("max_attempts", 3),
                    d.get("reply_post_url", ""),
                    d.get("reply_screenshot", ""),
                    d.get("last_error_code", ""),
                    d.get("last_error_message", ""),
                    d.get("ai_tokens_used", 0),
                    now,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- batch_create ----------------------------------------------------------

    def batch_create(self, tasks: List[dict]) -> List[int]:
        """Create multiple reply tasks in a single transaction.

        Returns a list of newly created task ids.
        """
        conn = get_connection(self.db_path)
        try:
            now = _now()
            created_ids: List[int] = []

            for data in tasks:
                d = _serialize_json_fields(data, _TASK_JSON_FIELDS)
                cur = conn.execute(
                    """
                    INSERT INTO reply_tasks
                        (campaign_id, account_id, platform, post_url,
                         post_author, post_title, post_content,
                         post_media_type, post_likes, post_comments,
                         reply_content, reply_content_alternatives,
                         selected_alternative, scheduled_at,
                         state, attempt_count, max_attempts,
                         reply_post_url, reply_screenshot,
                         last_error_code, last_error_message,
                         ai_tokens_used,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        d.get("campaign_id"),
                        d.get("account_id"),
                        d.get("platform", ""),
                        d.get("post_url", ""),
                        d.get("post_author", ""),
                        d.get("post_title", ""),
                        d.get("post_content", ""),
                        d.get("post_media_type", ""),
                        d.get("post_likes", 0),
                        d.get("post_comments", 0),
                        d.get("reply_content", ""),
                        d.get("reply_content_alternatives", "[]"),
                        d.get("selected_alternative", 0),
                        d.get("scheduled_at"),
                        d.get("state", "pending"),
                        d.get("attempt_count", 0),
                        d.get("max_attempts", 3),
                        d.get("reply_post_url", ""),
                        d.get("reply_screenshot", ""),
                        d.get("last_error_code", ""),
                        d.get("last_error_message", ""),
                        d.get("ai_tokens_used", 0),
                        now,
                        now,
                    ),
                )
                created_ids.append(cur.lastrowid)

            conn.commit()
            return created_ids
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, task_id: int) -> Optional[dict]:
        """Return a single task dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM reply_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return None
            d = _row_to_dict(row)
            return _deserialize_json_fields(d, _TASK_JSON_FIELDS)
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(
        self,
        state: Optional[str] = None,
        campaign_id: Optional[int] = None,
        account_id: Optional[int] = None,
        platform: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[dict]:
        """Return tasks, optionally filtered by state / campaign_id / account_id / platform."""
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM reply_tasks WHERE 1=1"
            params: list = []

            if state is not None:
                query += " AND state = ?"
                params.append(state)
            if campaign_id is not None:
                query += " AND campaign_id = ?"
                params.append(campaign_id)
            if account_id is not None:
                query += " AND account_id = ?"
                params.append(account_id)
            if platform is not None:
                query += " AND platform = ?"
                params.append(platform)

            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                results.append(_deserialize_json_fields(d, _TASK_JSON_FIELDS))
            return results
        finally:
            conn.close()

    # -- update ----------------------------------------------------------------

    def update(self, task_id: int, data: dict) -> bool:
        """Update mutable fields of a task. Returns True if updated."""
        conn = get_connection(self.db_path)
        try:
            d = _serialize_json_fields(data, _TASK_JSON_FIELDS)
            d["updated_at"] = _now()

            set_parts = []
            params = []
            for key, value in d.items():
                set_parts.append(f"{key} = ?")
                params.append(value)

            if not set_parts:
                return False

            params.append(task_id)
            cur = conn.execute(
                f"UPDATE reply_tasks SET {', '.join(set_parts)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, task_id: int) -> bool:
        """Delete a task and its related reply_logs. Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            conn.execute("DELETE FROM reply_logs WHERE reply_task_id = ?", (task_id,))
            cur = conn.execute(
                "DELETE FROM reply_tasks WHERE id = ?", (task_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- transition (state machine) --------------------------------------------

    def transition(self, task_id: int, new_state: str) -> bool:
        """Attempt a state-machine transition for the given task.

        * Validates the transition against REPLY_TASK_TRANSITIONS.
        * For ``failed -> pending`` also increments attempt_count.
        * Uses atomic UPDATE WHERE state=current to prevent race conditions.
        * Automatically updates ``updated_at``.

        Returns True if the transition was applied, False otherwise.
        """
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM reply_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return False

            task = _row_to_dict(row)
            current_state = task["state"]

            # Check if transition is legal
            allowed = REPLY_TASK_TRANSITIONS.get(current_state)
            if allowed is None or new_state not in allowed:
                return False

            now = _now()

            # Special handling: retry (failed -> pending) increments attempt_count
            if current_state == "failed" and new_state == "pending":
                cur = conn.execute(
                    """
                    UPDATE reply_tasks
                    SET state = ?,
                        attempt_count = attempt_count + 1,
                        updated_at = ?
                    WHERE id = ? AND state = ? AND attempt_count < max_attempts
                    """,
                    (new_state, now, task_id, current_state),
                )
            else:
                # Atomic: only update if state hasn't changed since we read it
                cur = conn.execute(
                    """
                    UPDATE reply_tasks
                    SET state = ?,
                        updated_at = ?
                    WHERE id = ? AND state = ?
                    """,
                    (new_state, now, task_id, current_state),
                )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- get_next_ready --------------------------------------------------------

    def get_next_ready(self, limit: int = 5) -> List[dict]:
        """Return tasks that are ready to execute.

        Selects tasks WHERE state='ready' AND (scheduled_at IS NULL OR
        scheduled_at <= datetime('now')), ordered by scheduled_at ASC.
        """
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM reply_tasks
                WHERE state = 'ready'
                  AND (scheduled_at IS NULL OR scheduled_at <= datetime('now'))
                ORDER BY scheduled_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                results.append(_deserialize_json_fields(d, _TASK_JSON_FIELDS))
            return results
        finally:
            conn.close()

    # -- check_duplicate -------------------------------------------------------

    def check_duplicate(self, account_id: int, post_url: str) -> bool:
        """Check if a reply_task exists for this account+url with an active state.

        Returns True if a duplicate exists (state not in failed/cancelled/skipped).
        """
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM reply_tasks
                WHERE account_id = ?
                  AND post_url = ?
                  AND state NOT IN ('failed', 'cancelled', 'skipped')
                """,
                (account_id, post_url),
            ).fetchone()
            return row["cnt"] > 0 if row else False
        finally:
            conn.close()

    # -- get_stats -------------------------------------------------------------

    def get_stats(self, campaign_id: Optional[int] = None) -> dict:
        """Return counts by state.

        Returns dict like {total, pending, generating, ready, executing,
        verifying, success, failed, skipped, cancelled}.
        """
        conn = get_connection(self.db_path)
        try:
            query = "SELECT state, COUNT(*) AS cnt FROM reply_tasks"
            params: list = []

            if campaign_id is not None:
                query += " WHERE campaign_id = ?"
                params.append(campaign_id)

            query += " GROUP BY state"

            rows = conn.execute(query, params).fetchall()

            stats = {
                "total": 0,
                "pending": 0,
                "generating": 0,
                "ready": 0,
                "executing": 0,
                "verifying": 0,
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "cancelled": 0,
            }
            for row in rows:
                d = _row_to_dict(row)
                state = d["state"]
                count = d["cnt"]
                stats[state] = count
                stats["total"] += count

            return stats
        finally:
            conn.close()


# ── ReplyLogService ──────────────────────────────────────────────────────

class ReplyLogService:
    """CRUD for the `reply_logs` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- add -------------------------------------------------------------------

    def add(self, data: dict) -> int:
        """Insert a new reply-log entry and return its id.

        The ``raw`` field is serialised to JSON if it is a dict.
        """
        conn = get_connection(self.db_path)
        try:
            raw_value = data.get("raw")
            if isinstance(raw_value, dict):
                raw_value = json.dumps(raw_value, ensure_ascii=False)
            elif raw_value is None:
                raw_value = "{}"

            now = _now()
            cur = conn.execute(
                """
                INSERT INTO reply_logs
                    (reply_task_id, step, status, error_code, message, raw, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("reply_task_id") or data.get("task_id"),
                    data.get("step", "reply"),
                    data.get("status", "ok"),
                    data.get("error_code", ""),
                    data.get("message", ""),
                    raw_value,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- list_by_task ----------------------------------------------------------

    def list_by_task(self, task_id: int) -> List[dict]:
        """Return all log entries for a given task, ordered by creation time."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM reply_logs WHERE reply_task_id = ? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                # Deserialise raw back to dict
                if isinstance(d.get("raw"), str):
                    try:
                        d["raw"] = json.loads(d["raw"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(d)
            return results
        finally:
            conn.close()

    # -- list_by_campaign ------------------------------------------------------

    def list_by_campaign(self, campaign_id: int, limit: int = 100) -> List[dict]:
        """Return log entries for all tasks in a campaign, ordered by id ASC."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT rl.* FROM reply_logs rl
                JOIN reply_tasks rt ON rl.reply_task_id = rt.id
                WHERE rt.campaign_id = ?
                ORDER BY rl.id ASC
                LIMIT ?
                """,
                (campaign_id, limit),
            ).fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                if isinstance(d.get("raw"), str):
                    try:
                        d["raw"] = json.loads(d["raw"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(d)
            return results
        finally:
            conn.close()
