"""Service for managing encrypted account credentials."""

from datetime import datetime, timedelta
from typing import Optional, List

from models.database import get_connection
from services.crypto_service import CryptoService


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def _now() -> str:
    return datetime.now().isoformat()


def _mask_value(value: str, credential_type: str) -> str:
    """Mask sensitive credential values for API responses."""
    if not value:
        return ""
    if credential_type == "username_password":
        return "********"
    if len(value) <= 12:
        return value[:3] + "..."
    if credential_type in ("oauth_token", "api_key"):
        return value[:8] + "..." + value[-4:]
    # cookie / session — show first 10 chars
    return value[:10] + "..."


class CredentialService:
    """CRUD + validate/refresh for account_credentials table."""

    def __init__(self, db_path: str, crypto: CryptoService):
        self.db_path = db_path
        self.crypto = crypto

    def create(self, account_id: int, credential_type: str,
               credential_data: dict, expires_at: str = None, notes: str = "") -> int:
        """Encrypt and store a new credential. Returns id."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            encrypted = self.crypto.encrypt_json(credential_data)
            cur = conn.execute(
                """INSERT INTO account_credentials
                   (account_id, credential_type, credential_data_encrypted,
                    is_active, expires_at, last_refreshed_at, validation_status,
                    notes, created_at, updated_at)
                   VALUES (?, ?, ?, 1, ?, ?, 'unknown', ?, ?, ?)""",
                (account_id, credential_type, encrypted,
                 expires_at, now, notes, now, now),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get(self, credential_id: int, decrypt: bool = False) -> Optional[dict]:
        """Get a single credential. If decrypt=False, masks sensitive data."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM account_credentials WHERE id = ?",
                (credential_id,),
            ).fetchone()
            if row is None:
                return None
            d = _row_to_dict(row)
            if decrypt and d["credential_data_encrypted"]:
                try:
                    d["credential_data"] = self.crypto.decrypt_json(d["credential_data_encrypted"])
                except Exception:
                    d["credential_data"] = {}
            elif d["credential_data_encrypted"]:
                # Return masked preview
                try:
                    plain = self.crypto.decrypt_json(d["credential_data_encrypted"])
                    d["credential_data_preview"] = {
                        k: _mask_value(str(v), d["credential_type"])
                        for k, v in plain.items()
                    }
                except Exception:
                    d["credential_data_preview"] = {"error": "decryption_failed"}
            d.pop("credential_data_encrypted", None)
            return d
        finally:
            conn.close()

    def get_active_for_account(self, account_id: int) -> List[dict]:
        """Return all active credentials for an account (masked)."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """SELECT * FROM account_credentials
                   WHERE account_id = ? AND is_active = 1
                   ORDER BY created_at DESC""",
                (account_id,),
            ).fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                if d["credential_data_encrypted"]:
                    try:
                        plain = self.crypto.decrypt_json(d["credential_data_encrypted"])
                        d["credential_data_preview"] = {
                            k: _mask_value(str(v), d["credential_type"])
                            for k, v in plain.items()
                        }
                    except Exception:
                        d["credential_data_preview"] = {"error": "decryption_failed"}
                d.pop("credential_data_encrypted", None)
                results.append(d)
            return results
        finally:
            conn.close()

    def get_primary_for_account(self, account_id: int) -> Optional[dict]:
        """Return the most recent active credential for an account (decrypted)."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """SELECT * FROM account_credentials
                   WHERE account_id = ? AND is_active = 1
                   ORDER BY created_at DESC LIMIT 1""",
                (account_id,),
            ).fetchone()
            if row is None:
                return None
            d = _row_to_dict(row)
            if d["credential_data_encrypted"]:
                try:
                    d["credential_data"] = self.crypto.decrypt_json(d["credential_data_encrypted"])
                except Exception:
                    d["credential_data"] = {}
            d.pop("credential_data_encrypted", None)
            return d
        finally:
            conn.close()

    def update(self, credential_id: int, data: dict) -> bool:
        """Update credential fields. Re-encrypts if credential_data is provided."""
        conn = get_connection(self.db_path)
        try:
            sets = []
            params = []

            if "credential_data" in data:
                sets.append("credential_data_encrypted = ?")
                params.append(self.crypto.encrypt_json(data["credential_data"]))

            for field in ["credential_type", "is_active", "expires_at",
                          "validation_status", "notes"]:
                if field in data:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            if not sets:
                return False

            sets.append("updated_at = ?")
            params.append(_now())
            params.append(credential_id)

            cur = conn.execute(
                f"UPDATE account_credentials SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def deactivate(self, credential_id: int) -> bool:
        """Set is_active=0."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE account_credentials SET is_active = 0, updated_at = ? WHERE id = ?",
                (_now(), credential_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def delete(self, credential_id: int) -> bool:
        """Hard delete a credential."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM account_credentials WHERE id = ?",
                (credential_id,),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def validate(self, credential_id: int) -> dict:
        """Mark credential as validated (actual platform validation is external).
        Returns updated status."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            conn.execute(
                """UPDATE account_credentials
                   SET last_validated_at = ?, validation_status = 'valid', updated_at = ?
                   WHERE id = ?""",
                (now, now, credential_id),
            )
            conn.commit()
            return {"credential_id": credential_id, "validation_status": "valid",
                    "validated_at": now}
        finally:
            conn.close()

    def mark_invalid(self, credential_id: int, reason: str = "") -> bool:
        """Mark credential as invalid."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            cur = conn.execute(
                """UPDATE account_credentials
                   SET validation_status = 'invalid', last_validated_at = ?,
                       notes = CASE WHEN ? != '' THEN ? ELSE notes END,
                       updated_at = ?
                   WHERE id = ?""",
                (now, reason, reason, now, credential_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def mark_expired(self, credential_id: int) -> bool:
        """Mark credential as expired."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            cur = conn.execute(
                """UPDATE account_credentials
                   SET validation_status = 'expired', updated_at = ? WHERE id = ?""",
                (now, credential_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def refresh(self, credential_id: int) -> dict:
        """Mark credential as refreshed (actual refresh is external)."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            conn.execute(
                """UPDATE account_credentials
                   SET last_refreshed_at = ?, validation_status = 'valid', updated_at = ?
                   WHERE id = ?""",
                (now, now, credential_id),
            )
            conn.commit()
            return {"credential_id": credential_id, "refreshed_at": now}
        finally:
            conn.close()

    def list_expiring(self, hours: int = 24) -> List[dict]:
        """List credentials expiring within N hours."""
        conn = get_connection(self.db_path)
        try:
            cutoff = (datetime.now() + timedelta(hours=hours)).isoformat()
            rows = conn.execute(
                """SELECT * FROM account_credentials
                   WHERE is_active = 1 AND expires_at IS NOT NULL
                     AND expires_at <= ? AND expires_at > ?
                   ORDER BY expires_at ASC""",
                (cutoff, _now()),
            ).fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                d.pop("credential_data_encrypted", None)
                results.append(d)
            return results
        finally:
            conn.close()

    def count_by_account(self, account_id: int) -> dict:
        """Return credential counts by type and status for an account."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """SELECT credential_type, validation_status, COUNT(*) as cnt
                   FROM account_credentials
                   WHERE account_id = ? AND is_active = 1
                   GROUP BY credential_type, validation_status""",
                (account_id,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()
