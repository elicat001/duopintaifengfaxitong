"""Simplified Cookie API — view and delete cookies per account."""

import logging

from flask import Blueprint, jsonify
from config import DB_PATH, CREDENTIAL_ENCRYPTION_KEY
from services.crypto_service import CryptoService
from services.credential_service import CredentialService
from api.auth import require_auth

logger = logging.getLogger(__name__)

credentials_bp = Blueprint("credentials", __name__)
crypto = CryptoService(CREDENTIAL_ENCRYPTION_KEY)
cred_svc = CredentialService(DB_PATH, crypto)


@credentials_bp.route("/api/accounts/<int:account_id>/cookies", methods=["GET"])
@require_auth
def get_cookie_status(account_id):
    """Check whether an account has saved cookies."""
    try:
        status = cred_svc.has_cookies(account_id)
        return jsonify(status), 200
    except Exception as e:
        logger.exception("Unexpected error in credentials API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@credentials_bp.route("/api/accounts/<int:account_id>/cookies", methods=["DELETE"])
@require_auth
def delete_cookies(account_id):
    """Delete all saved cookies for an account."""
    try:
        ok = cred_svc.delete_cookies(account_id)
        if not ok:
            return jsonify({"message": "该账号没有已保存的Cookie"}), 200
        return jsonify({"message": "Cookie已删除"}), 200
    except Exception as e:
        logger.exception("Unexpected error in credentials API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500
