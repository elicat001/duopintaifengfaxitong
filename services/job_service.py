"""
Services for Job, JobLog, and Metric CRUD operations.
Includes a state-machine for job lifecycle transitions.
"""

import json
import uuid
from datetime import datetime
from typing import Optional, List

from models.database import get_connection


# ── helpers ──────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row) if row else {}


def _now() -> str:
    return datetime.now().isoformat()


# ── State machine definition ────────────────────────────────────────────

# Maps current_state -> set of allowed next states
VALID_TRANSITIONS = {
    "draft":             {"queued", "cancelled"},
    "queued":            {"preparing", "cancelled", "account_paused"},
    "preparing":         {"publishing", "failed_retryable", "cancelled"},
    "publishing":        {"verifying", "failed_retryable", "cancelled"},
    "verifying":         {"success", "failed_retryable", "needs_review"},
    "failed_retryable":  {"queued"},
    "needs_review":      {"queued", "cancelled", "failed_final"},
    "account_paused":    {"queued", "cancelled"},
}


# ── JobService ──────────────────────────────────────────────────────────

class JobService:
    """CRUD + state-machine for the `jobs` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new job and return its id.

        If `idempotency_key` is not provided in *data*, a uuid4 is generated
        automatically.
        """
        conn = get_connection(self.db_path)
        try:
            now = _now()
            idempotency_key = data.get("idempotency_key") or str(uuid.uuid4())
            cur = conn.execute(
                """
                INSERT INTO jobs
                    (account_id, content_id, variant_id, scheduled_at,
                     state, attempt_count, max_attempts, next_run_at,
                     platform_post_id, platform_post_url,
                     idempotency_key,
                     last_error_code, last_error_message,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("account_id"),
                    data.get("content_id"),
                    data.get("variant_id"),
                    data.get("scheduled_at"),
                    data.get("state", "draft"),
                    data.get("attempt_count", 0),
                    data.get("max_attempts", 5),
                    data.get("next_run_at"),
                    data.get("platform_post_id", ""),
                    data.get("platform_post_url", ""),
                    idempotency_key,
                    data.get("last_error_code", ""),
                    data.get("last_error_message", ""),
                    now,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, job_id: int) -> Optional[dict]:
        """Return a single job dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row)
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(
        self,
        state: Optional[str] = None,
        account_id: Optional[int] = None,
        content_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[dict]:
        """Return jobs, optionally filtered by state / account_id / content_id."""
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM jobs WHERE 1=1"
            params: list = []

            if state is not None:
                query += " AND state = ?"
                params.append(state)
            if account_id is not None:
                query += " AND account_id = ?"
                params.append(account_id)
            if content_id is not None:
                query += " AND content_id = ?"
                params.append(content_id)

            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, job_id: int) -> bool:
        """Delete a job and its related records (cascade). Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            conn.execute("DELETE FROM job_logs WHERE job_id = ?", (job_id,))
            conn.execute("DELETE FROM metrics WHERE job_id = ?", (job_id,))
            cur = conn.execute(
                "DELETE FROM jobs WHERE id = ?", (job_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- batch_create ----------------------------------------------------------

    def batch_create(
        self,
        content_id: int,
        account_ids: list,
        variant_id: int = None,
        scheduled_at: str = None,
        initial_state: str = "draft",
    ) -> List[int]:
        """Create one job per account in a single transaction.

        Returns a list of newly created job ids.
        """
        conn = get_connection(self.db_path)
        try:
            now = _now()
            created_ids: List[int] = []

            next_run_at = now if initial_state == "queued" else None

            for acct_id in account_ids:
                idempotency_key = str(uuid.uuid4())
                cur = conn.execute(
                    """
                    INSERT INTO jobs
                        (account_id, content_id, variant_id, scheduled_at,
                         state, attempt_count, max_attempts, next_run_at,
                         platform_post_id, platform_post_url,
                         idempotency_key,
                         last_error_code, last_error_message,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        acct_id,
                        content_id,
                        variant_id,
                        scheduled_at,
                        initial_state,
                        0,
                        5,
                        next_run_at,
                        "",
                        "",
                        idempotency_key,
                        "",
                        "",
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

    # -- transition (state machine) --------------------------------------------

    def transition(self, job_id: int, new_state: str) -> bool:
        """Attempt a state-machine transition for the given job.

        * Validates the transition against VALID_TRANSITIONS.
        * For ``failed_retryable -> queued`` also checks attempt_count < max_attempts
          and increments attempt_count.
        * Automatically updates ``updated_at`` and ``next_run_at``.
        * Uses atomic UPDATE WHERE state=current to prevent race conditions.

        Returns True if the transition was applied, False otherwise.
        """
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return False

            job = _row_to_dict(row)
            current_state = job["state"]

            # Check if transition is legal
            allowed = VALID_TRANSITIONS.get(current_state)
            if allowed is None or new_state not in allowed:
                return False

            now = _now()

            # Determine next_run_at: set to now when moving into queued
            next_run_at = job.get("next_run_at")
            if new_state == "queued":
                next_run_at = now

            # Special handling: retry (failed_retryable -> queued)
            # Use SQL-level increment to avoid race condition on attempt_count
            if current_state == "failed_retryable" and new_state == "queued":
                cur = conn.execute(
                    """
                    UPDATE jobs
                    SET state = ?,
                        attempt_count = attempt_count + 1,
                        next_run_at = ?,
                        updated_at = ?
                    WHERE id = ? AND state = ? AND attempt_count < max_attempts
                    """,
                    (new_state, next_run_at, now, job_id, current_state),
                )
            else:
                # Atomic: only update if state hasn't changed since we read it
                cur = conn.execute(
                    """
                    UPDATE jobs
                    SET state = ?,
                        next_run_at = ?,
                        updated_at = ?
                    WHERE id = ? AND state = ?
                    """,
                    (new_state, next_run_at, now, job_id, current_state),
                )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- cancel ----------------------------------------------------------------

    def cancel(self, job_id: int) -> bool:
        """Cancel a job (transition to 'cancelled').

        Only valid from states that list 'cancelled' as an allowed target.
        """
        return self.transition(job_id, "cancelled")

    # -- retry -----------------------------------------------------------------

    def retry(self, job_id: int) -> bool:
        """Retry a failed job (failed_retryable -> queued).

        Increments attempt_count; fails if max_attempts reached.
        """
        return self.transition(job_id, "queued")


# ── JobLogService ───────────────────────────────────────────────────────

class JobLogService:
    """CRUD for the `job_logs` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- add -------------------------------------------------------------------

    def add(self, data: dict) -> int:
        """Insert a new job-log entry and return its id.

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
                INSERT INTO job_logs
                    (job_id, step, status, error_code, message, raw, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("job_id"),
                    data.get("step", "publish"),
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

    # -- list_by_job -----------------------------------------------------------

    def list_by_job(self, job_id: int) -> List[dict]:
        """Return all log entries for a given job, ordered by creation time."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM job_logs WHERE job_id = ? ORDER BY id ASC",
                (job_id,),
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


# ── MetricService ───────────────────────────────────────────────────────

class MetricService:
    """CRUD for the `metrics` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- record ----------------------------------------------------------------

    def record(self, data: dict) -> int:
        """Insert a new metrics snapshot and return its id.

        The ``extra`` field is serialised to JSON if it is a dict.
        """
        conn = get_connection(self.db_path)
        try:
            extra_value = data.get("extra")
            if isinstance(extra_value, dict):
                extra_value = json.dumps(extra_value, ensure_ascii=False)
            elif extra_value is None:
                extra_value = "{}"

            now = _now()
            cur = conn.execute(
                """
                INSERT INTO metrics
                    (job_id, platform_post_id, captured_at,
                     views, likes, comments, shares, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("job_id"),
                    data.get("platform_post_id", ""),
                    data.get("captured_at", now),
                    data.get("views", 0),
                    data.get("likes", 0),
                    data.get("comments", 0),
                    data.get("shares", 0),
                    extra_value,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get_latest ------------------------------------------------------------

    def get_latest(self, job_id: int) -> Optional[dict]:
        """Return the most recent metrics snapshot for a given job, or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM metrics WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            d = _row_to_dict(row)
            if isinstance(d.get("extra"), str):
                try:
                    d["extra"] = json.loads(d["extra"])
                except (json.JSONDecodeError, TypeError):
                    pass
            return d
        finally:
            conn.close()

    # -- list_by_job -----------------------------------------------------------

    def list_by_job(self, job_id: int) -> List[dict]:
        """Return all metrics snapshots for a given job, oldest first."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM metrics WHERE job_id = ? ORDER BY id ASC",
                (job_id,),
            ).fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                if isinstance(d.get("extra"), str):
                    try:
                        d["extra"] = json.loads(d["extra"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(d)
            return results
        finally:
            conn.close()
