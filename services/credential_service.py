"""Simplified cookie-only credential service.

Stores and retrieves encrypted cookies per account.
Each account has at most one active cookie record — saving new
cookies automatically deactivates the old ones.
"""

import logging
from datetime import datetime
from typing import Optional

from models.database import get_connection
from services.crypto_service import CryptoService

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().isoformat()


class CredentialService:
    """Save / load / delete cookies for accounts."""

    def __init__(self, db_path: str, crypto: CryptoService):
        self.db_path = db_path
        self.crypto = crypto

    def save_cookies(self, account_id: int, cookies: list,
                     source: str = "browser") -> int:
        """Encrypt and save cookies, replacing any previous ones.

        Returns the new credential row id.
        """
        conn = get_connection(self.db_path)
        try:
            now = _now()
            # Deactivate previous cookies for this account
            conn.execute(
                "UPDATE account_credentials SET is_active = 0, updated_at = ? "
                "WHERE account_id = ? AND is_active = 1",
                (now, account_id),
            )
            # Insert new
            encrypted = self.crypto.encrypt_json({
                "cookies": cookies,
                "source": source,
                "saved_at": now,
            })
            cur = conn.execute(
                """INSERT INTO account_credentials
                   (account_id, credential_type, credential_data_encrypted,
                    is_active, validation_status, notes, created_at, updated_at)
                   VALUES (?, 'cookie', ?, 1, 'valid', ?, ?, ?)""",
                (account_id, encrypted, f"来源: {source}", now, now),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_cookies(self, account_id: int) -> Optional[list]:
        """Return decrypted cookie list for an account, or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """SELECT credential_data_encrypted FROM account_credentials
                   WHERE account_id = ? AND is_active = 1
                   ORDER BY created_at DESC LIMIT 1""",
                (account_id,),
            ).fetchone()
            if not row or not row["credential_data_encrypted"]:
                return None
            try:
                data = self.crypto.decrypt_json(row["credential_data_encrypted"])
                return data.get("cookies", [])
            except Exception:
                logger.warning(
                    "Failed to decrypt cookies for account %d", account_id,
                    exc_info=True,
                )
                return None
        finally:
            conn.close()

    def has_cookies(self, account_id: int) -> dict:
        """Return cookie status: {has_cookies, cookie_count, updated_at}."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """SELECT credential_data_encrypted, updated_at
                   FROM account_credentials
                   WHERE account_id = ? AND is_active = 1
                   ORDER BY created_at DESC LIMIT 1""",
                (account_id,),
            ).fetchone()
            if not row or not row["credential_data_encrypted"]:
                return {"has_cookies": False, "cookie_count": 0, "updated_at": None}
            try:
                data = self.crypto.decrypt_json(row["credential_data_encrypted"])
                cookies = data.get("cookies", [])
                return {
                    "has_cookies": len(cookies) > 0,
                    "cookie_count": len(cookies),
                    "updated_at": row["updated_at"],
                }
            except Exception:
                return {"has_cookies": False, "cookie_count": 0, "updated_at": None}
        finally:
            conn.close()

    def delete_cookies(self, account_id: int) -> bool:
        """Delete all cookies for an account."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM account_credentials WHERE account_id = ?",
                (account_id,),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
