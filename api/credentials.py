"""Blueprint for Account Credential REST APIs."""

from flask import Blueprint, request, jsonify
from config import DB_PATH, CREDENTIAL_ENCRYPTION_KEY
from services.crypto_service import CryptoService
from services.credential_service import CredentialService
from api.auth import require_auth

credentials_bp = Blueprint("credentials", __name__)
crypto = CryptoService(CREDENTIAL_ENCRYPTION_KEY)
cred_svc = CredentialService(DB_PATH, crypto)

# ── Validation constants ────────────────────────────────────────────────
VALID_CREDENTIAL_TYPES = {"cookie", "oauth_token", "username_password", "session", "api_key"}


@credentials_bp.route("/api/accounts/<int:account_id>/credentials", methods=["POST"])
@require_auth
def add_credential(account_id):
    """Add a credential to an account."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("credential_type") or not data.get("credential_data"):
            return jsonify({"error": "credential_type and credential_data are required"}), 400

        if data["credential_type"] not in VALID_CREDENTIAL_TYPES:
            return jsonify({"error": "invalid credential_type"}), 400
        if not isinstance(data["credential_data"], dict):
            return jsonify({"error": "credential_data must be a JSON object"}), 400

        cred_id = cred_svc.create(
            account_id=account_id,
            credential_type=data["credential_type"],
            credential_data=data["credential_data"],
            expires_at=data.get("expires_at"),
            notes=data.get("notes", ""),
        )
        cred = cred_svc.get(cred_id)
        return jsonify(cred), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@credentials_bp.route("/api/accounts/<int:account_id>/credentials", methods=["GET"])
@require_auth
def list_credentials(account_id):
    """List credentials for an account (masked)."""
    try:
        items = cred_svc.get_active_for_account(account_id)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@credentials_bp.route("/api/credentials/<int:cred_id>", methods=["GET"])
@require_auth
def get_credential(cred_id):
    """Get a single credential detail (masked)."""
    try:
        cred = cred_svc.get(cred_id)
        if cred is None:
            return jsonify({"error": "credential not found"}), 404
        return jsonify(cred), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@credentials_bp.route("/api/credentials/<int:cred_id>", methods=["PUT"])
@require_auth
def update_credential(cred_id):
    """Update a credential."""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400

        existing = cred_svc.get(cred_id)
        if existing is None:
            return jsonify({"error": "credential not found"}), 404

        cred_svc.update(cred_id, data)
        updated = cred_svc.get(cred_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@credentials_bp.route("/api/credentials/<int:cred_id>", methods=["DELETE"])
@require_auth
def delete_credential(cred_id):
    """Delete a credential."""
    try:
        ok = cred_svc.delete(cred_id)
        if not ok:
            return jsonify({"error": "credential not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@credentials_bp.route("/api/credentials/<int:cred_id>/validate", methods=["POST"])
@require_auth
def validate_credential(cred_id):
    """Validate a credential (marks as valid)."""
    try:
        existing = cred_svc.get(cred_id)
        if existing is None:
            return jsonify({"error": "credential not found"}), 404
        result = cred_svc.validate(cred_id)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@credentials_bp.route("/api/credentials/<int:cred_id>/refresh", methods=["POST"])
@require_auth
def refresh_credential(cred_id):
    """Refresh a credential token/cookie."""
    try:
        existing = cred_svc.get(cred_id)
        if existing is None:
            return jsonify({"error": "credential not found"}), 404
        result = cred_svc.refresh(cred_id)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@credentials_bp.route("/api/credentials/expiring", methods=["GET"])
@require_auth
def list_expiring_credentials():
    """List credentials expiring within N hours."""
    try:
        hours = request.args.get("hours", 24, type=int)
        items = cred_svc.list_expiring(hours=hours)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
