"""Service for account login status tracking and login log management."""

import logging
from datetime import datetime
from typing import Optional, List

from models.database import get_connection

logger = logging.getLogger(__name__)


# Valid state transitions for the login status state machine.
# Each key maps to the set of states it is allowed to transition to.
VALID_TRANSITIONS = {
    "unknown": {"logging_in", "logged_out"},
    "logged_out": {"logging_in"},
    "logging_in": {"logged_in", "login_failed", "logged_out"},
    "logged_in": {"session_expired", "logged_out", "logging_in"},
    "login_failed": {"logging_in", "logged_out"},
    "session_expired": {"logging_in", "logged_out"},
    "suspended": {"logged_out"},
    "rate_limited": {"logging_in", "logged_out", "logged_in"},
}


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def _now() -> str:
    return datetime.now().isoformat()


def _validate_transition(current_state: str, new_state: str) -> bool:
    """Check whether a state transition is valid.

    Logs a warning for invalid transitions but returns False without raising,
    so callers can proceed (observability without brittleness).
    """
    allowed = VALID_TRANSITIONS.get(current_state)
    if allowed is None:
        logger.warning(
            "Login state transition from unrecognized state %r to %r "
            "(no transitions defined for source state)",
            current_state,
            new_state,
        )
        return False
    if new_state not in allowed:
        logger.warning(
            "Invalid login state transition from %r to %r "
            "(allowed targets: %s)",
            current_state,
            new_state,
            ", ".join(sorted(allowed)),
        )
        return False
    return True


class LoginStatusService:
    """Manages account_login_status and login_logs tables."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_or_create(self, account_id: int) -> dict:
        """Get login status for an account, creating a default row if none exists."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM account_login_status WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if row:
                return _row_to_dict(row)
            now = _now()
            conn.execute(
                """INSERT INTO account_login_status
                   (account_id, login_state, health_score, consecutive_failures,
                    total_login_attempts, total_login_successes,
                    check_interval_minutes, alert_sent, created_at, updated_at)
                   VALUES (?, 'unknown', 0.0, 0, 0, 0, 30, 0, ?, ?)""",
                (account_id, now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM account_login_status WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            return _row_to_dict(row)
        finally:
            conn.close()

    def update_state(self, account_id: int, new_state: str, reason: str = "") -> dict:
        """Transition login state, log the change, update accounts.login_status mirror."""
        conn = get_connection(self.db_path)
        try:
            self.get_or_create(account_id)
            row = conn.execute(
                "SELECT * FROM account_login_status WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            old_state = row["login_state"] if row else "unknown"

            # Validate the transition (warn on invalid, but still proceed)
            _validate_transition(old_state, new_state)

            now = _now()

            # Update login status
            updates = {"login_state": new_state, "last_state_change_at": now, "updated_at": now}
            if new_state in ("logged_in",):
                updates["consecutive_failures"] = 0
                updates["last_login_at"] = now
                updates["last_failure_reason"] = ""
                updates["alert_sent"] = 0
            elif new_state in ("expired", "need_captcha", "need_verify", "banned", "rate_limited", "logged_out"):
                cf = 0
                if row:
                    cf = (row["consecutive_failures"] or 0) + 1
                else:
                    cf = 1
                updates["consecutive_failures"] = cf
                updates["last_failure_reason"] = reason

            set_parts = [f"{k} = ?" for k in updates]
            params = list(updates.values()) + [account_id]
            conn.execute(
                f"UPDATE account_login_status SET {', '.join(set_parts)} WHERE account_id = ?",
                params,
            )

            # Mirror to accounts table
            conn.execute(
                "UPDATE accounts SET login_status = ?, updated_at = ? WHERE id = ?",
                (new_state, now, account_id),
            )

            # Log the state change
            conn.execute(
                """INSERT INTO login_logs
                   (account_id, action, status, previous_state, new_state,
                    failure_reason, created_at)
                   VALUES (?, 'state_change', ?, ?, ?, ?, ?)""",
                (account_id, "success" if new_state == "logged_in" else "failure",
                 old_state, new_state, reason, now),
            )
            conn.commit()

            return {"account_id": account_id, "previous_state": old_state,
                    "new_state": new_state, "reason": reason}
        finally:
            conn.close()

    def record_attempt(self, account_id: int, action: str = "login_check",
                       status: str = "success", failure_reason: str = "",
                       ip_used: str = "", duration_ms: int = 0,
                       response_code: int = None, response_snippet: str = "") -> dict:
        """Insert a login log entry and update counters.

        Health/risk scoring is NOT done here; use
        AccountHealthService.compute_risk_score() as the single source of truth.
        """
        conn = get_connection(self.db_path)
        try:
            self.get_or_create(account_id)
            now = _now()

            row = conn.execute(
                "SELECT * FROM account_login_status WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            old = _row_to_dict(row) if row else {}

            # Insert log
            conn.execute(
                """INSERT INTO login_logs
                   (account_id, action, status, failure_reason, ip_used,
                    response_code, response_snippet, duration_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (account_id, action, status, failure_reason, ip_used,
                 response_code, response_snippet[:500] if response_snippet else "", duration_ms, now),
            )

            # Update counters
            total_attempts = (old.get("total_login_attempts") or 0) + 1
            total_successes = (old.get("total_login_successes") or 0) + (1 if status == "success" else 0)
            cf = 0 if status == "success" else (old.get("consecutive_failures") or 0) + 1

            updates = {
                "total_login_attempts": total_attempts,
                "total_login_successes": total_successes,
                "consecutive_failures": cf,
                "last_login_check_at": now,
                "updated_at": now,
            }
            if status == "success":
                updates["last_login_at"] = now
                updates["last_failure_reason"] = ""
            else:
                updates["last_failure_reason"] = failure_reason

            set_parts = [f"{k} = ?" for k in updates]
            params = list(updates.values()) + [account_id]
            conn.execute(
                f"UPDATE account_login_status SET {', '.join(set_parts)} WHERE account_id = ?",
                params,
            )

            # Mirror key fields to accounts (including login_status sync)
            current_login_state = old.get("login_state", "unknown")
            conn.execute(
                """UPDATE accounts SET login_status = ?, last_login_at = ?,
                   last_login_check_at = ?, login_fail_count = ?, updated_at = ?
                   WHERE id = ?""",
                (current_login_state,
                 now if status == "success" else old.get("last_login_at"),
                 now, cf, now, account_id),
            )
            conn.commit()

            return {"account_id": account_id, "action": action, "status": status,
                    "consecutive_failures": cf}
        finally:
            conn.close()

    def compute_health_score(self, account_id: int) -> float:
        """Recompute health score by delegating to AccountHealthService.

        This method exists for backward compatibility.  The canonical risk
        scoring logic lives in AccountHealthService.compute_risk_score().
        """
        from services.account_health_service import AccountHealthService

        health_svc = AccountHealthService(self.db_path)
        return health_svc.compute_risk_score(account_id)

    def get_logs(self, account_id: int, limit: int = 50) -> List[dict]:
        """Return recent login logs for an account."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM login_logs WHERE account_id = ? ORDER BY created_at DESC LIMIT ?",
                (account_id, limit),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def list_all(self, login_state: str = None) -> List[dict]:
        """List all login statuses, optionally filtered by state."""
        conn = get_connection(self.db_path)
        try:
            query = """SELECT als.*, a.handle, a.platform, a.display_name
                       FROM account_login_status als
                       JOIN accounts a ON als.account_id = a.id
                       WHERE 1=1"""
            params = []
            if login_state:
                query += " AND als.login_state = ?"
                params.append(login_state)
            query += " ORDER BY als.consecutive_failures DESC, als.health_score ASC"
            rows = conn.execute(query, params).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def list_needing_check(self) -> List[dict]:
        """Find accounts whose login check is overdue."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """SELECT als.*, a.handle, a.platform, a.display_name
                   FROM account_login_status als
                   JOIN accounts a ON als.account_id = a.id
                   WHERE (als.last_login_check_at IS NULL
                     OR datetime(als.last_login_check_at, '+' || als.check_interval_minutes || ' minutes') < datetime('now'))
                   AND a.status != 'banned'
                   ORDER BY als.last_login_check_at ASC"""
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def list_failing(self) -> List[dict]:
        """List accounts with consecutive failures > 0."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """SELECT als.*, a.handle, a.platform, a.display_name
                   FROM account_login_status als
                   JOIN accounts a ON als.account_id = a.id
                   WHERE als.consecutive_failures > 0
                   ORDER BY als.consecutive_failures DESC"""
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_summary_stats(self) -> dict:
        """Count accounts by login_state."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT login_state, COUNT(*) as cnt FROM account_login_status GROUP BY login_state"
            ).fetchall()
            by_state = {r["login_state"]: r["cnt"] for r in rows}
            total = sum(by_state.values())
            return {"total": total, "by_state": by_state}
        finally:
            conn.close()

    def reset_alert(self, account_id: int) -> bool:
        """Mark alert as sent for an account."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE account_login_status SET alert_sent = 1, updated_at = ? WHERE account_id = ?",
                (_now(), account_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
