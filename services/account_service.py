"""
Services for AccountGroup and Account CRUD operations.
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


# ── AccountGroupService ─────────────────────────────────────────────────

class AccountGroupService:
    """CRUD for the `account_groups` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new account group and return its id."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                """
                INSERT INTO account_groups (name, description)
                VALUES (?, ?)
                """,
                (
                    data.get("name", ""),
                    data.get("description", ""),
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, group_id: int) -> Optional[dict]:
        """Return a single account group dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM account_groups WHERE id = ?", (group_id,)
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row)
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(self) -> List[dict]:
        """Return all account groups."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM account_groups ORDER BY id DESC"
            ).fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            conn.close()

    # -- update ----------------------------------------------------------------

    def update(self, group_id: int, data: dict) -> bool:
        """Update mutable fields of an account group. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            sets: List[str] = []
            params: list = []

            simple_fields = ["name", "description"]
            for field in simple_fields:
                if field in data:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            if not sets:
                return False

            params.append(group_id)

            cur = conn.execute(
                f"UPDATE account_groups SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, group_id: int) -> bool:
        """Delete an account group. Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM account_groups WHERE id = ?", (group_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


# ── AccountService ──────────────────────────────────────────────────────

class AccountService:
    """CRUD + pause/resume for the `accounts` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new account and return its id."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            cur = conn.execute(
                """
                INSERT INTO accounts
                    (platform, handle, display_name, group_id,
                     status, daily_limit, hourly_limit,
                     last_success_at, executor_account_ref,
                     proxy_id, login_status, last_login_at,
                     last_login_check_at, login_fail_count,
                     risk_score, fingerprint_config, notes,
                     cookie_updated_at, warming_stage, warming_started_at,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("platform", ""),
                    data.get("handle", ""),
                    data.get("display_name", ""),
                    data.get("group_id"),
                    data.get("status", "active"),
                    data.get("daily_limit", 10),
                    data.get("hourly_limit", 3),
                    data.get("last_success_at"),
                    data.get("executor_account_ref", ""),
                    data.get("proxy_id"),
                    data.get("login_status", "unknown"),
                    data.get("last_login_at"),
                    data.get("last_login_check_at"),
                    data.get("login_fail_count", 0),
                    data.get("risk_score", 0.0),
                    json.dumps(data.get("fingerprint_config", {})),
                    data.get("notes", ""),
                    data.get("cookie_updated_at"),
                    data.get("warming_stage", 0),
                    data.get("warming_started_at"),
                    now,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, account_id: int) -> Optional[dict]:
        """Return a single account dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row)
        finally:
            conn.close()

    # -- get_with_details ------------------------------------------------------

    def get_with_details(self, account_id: int) -> Optional[dict]:
        """Return account with login status, credential summary, and proxy assignment."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if row is None:
                return None
            acct = _row_to_dict(row)
            if acct.get("fingerprint_config"):
                try:
                    acct["fingerprint_config"] = json.loads(acct["fingerprint_config"])
                except (json.JSONDecodeError, TypeError):
                    pass
            # Login status
            ls = conn.execute(
                "SELECT * FROM account_login_status WHERE account_id = ?", (account_id,)
            ).fetchone()
            acct["login_status_detail"] = _row_to_dict(ls) if ls else None
            # Credential summary
            cred = conn.execute(
                "SELECT credential_type, validation_status, COUNT(*) as cnt FROM account_credentials WHERE account_id = ? AND is_active = 1 GROUP BY credential_type, validation_status",
                (account_id,),
            ).fetchall()
            acct["credentials_summary"] = [_row_to_dict(r) for r in cred]
            # Proxy assignment
            proxy = conn.execute(
                """SELECT apa.*, p.host, p.port, p.proxy_type, p.status as proxy_status
                   FROM account_proxy_assignments apa
                   LEFT JOIN proxies p ON apa.proxy_id = p.id
                   WHERE apa.account_id = ? AND apa.is_active = 1 LIMIT 1""",
                (account_id,),
            ).fetchone()
            acct["proxy_assignment"] = _row_to_dict(proxy) if proxy else None
            return acct
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(
        self,
        platform: Optional[str] = None,
        group_id: Optional[int] = None,
        status: Optional[str] = None,
        login_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        """Return accounts, optionally filtered by platform / group_id / status / login_status."""
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM accounts WHERE 1=1"
            params: list = []

            if platform is not None:
                query += " AND platform = ?"
                params.append(platform)
            if group_id is not None:
                query += " AND group_id = ?"
                params.append(group_id)
            if status is not None:
                query += " AND status = ?"
                params.append(status)
            if login_status is not None:
                query += " AND login_status = ?"
                params.append(login_status)

            query += " ORDER BY id DESC"
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            conn.close()

    # -- update ----------------------------------------------------------------

    def update(self, account_id: int, data: dict) -> bool:
        """Update mutable fields of an account. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            sets: List[str] = []
            params: list = []

            simple_fields = [
                "platform", "handle", "display_name", "group_id",
                "status", "daily_limit", "hourly_limit",
                "last_success_at", "executor_account_ref",
                "proxy_id", "login_status", "last_login_at",
                "last_login_check_at", "login_fail_count",
                "risk_score", "notes", "cookie_updated_at",
                "warming_stage", "warming_started_at",
            ]
            for field in simple_fields:
                if field in data:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            if "fingerprint_config" in data:
                sets.append("fingerprint_config = ?")
                params.append(json.dumps(data["fingerprint_config"]) if isinstance(data["fingerprint_config"], dict) else data["fingerprint_config"])

            if not sets:
                return False

            sets.append("updated_at = ?")
            params.append(_now())
            params.append(account_id)

            cur = conn.execute(
                f"UPDATE accounts SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- pause -----------------------------------------------------------------

    def pause(self, account_id: int) -> bool:
        """Set account status to 'paused'. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE accounts SET status = ?, updated_at = ? WHERE id = ?",
                ("paused", _now(), account_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- resume ----------------------------------------------------------------

    def resume(self, account_id: int) -> bool:
        """Set account status to 'active'. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE accounts SET status = ?, updated_at = ? WHERE id = ?",
                ("active", _now(), account_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, account_id: int) -> bool:
        """Delete an account. Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM accounts WHERE id = ?", (account_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
