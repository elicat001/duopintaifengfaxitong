"""AES-256-GCM encryption service for sensitive credential data."""

import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


class CryptoService:
    """Encrypt/decrypt sensitive data using AES-256-GCM."""

    def __init__(self, master_key: str):
        # Derive a 32-byte AES-256 key from the master key using PBKDF2.
        # NOTE: Changing key derivation invalidates all previously encrypted data.
        # In development, recreate the DB after this change.
        salt = b"inswuxianfa-credential-salt-v1"
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
        self._key = kdf.derive(master_key.encode("utf-8"))

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext string. Returns base64-encoded nonce+ciphertext."""
        nonce = os.urandom(12)
        aesgcm = AESGCM(self._key)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("utf-8")

    def decrypt(self, encrypted_b64: str) -> str:
        """Decrypt base64-encoded blob back to plaintext string."""
        raw = base64.b64decode(encrypted_b64)
        nonce = raw[:12]
        ct = raw[12:]
        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(nonce, ct, None).decode("utf-8")

    def encrypt_json(self, data: dict) -> str:
        """Serialize dict to JSON, then encrypt."""
        return self.encrypt(json.dumps(data, ensure_ascii=False))

    def decrypt_json(self, encrypted_b64: str) -> dict:
        """Decrypt and parse JSON back to dict."""
        return json.loads(self.decrypt(encrypted_b64))
