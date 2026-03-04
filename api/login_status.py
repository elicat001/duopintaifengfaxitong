"""Blueprint for Account Login Status REST APIs."""

import logging

from flask import Blueprint, request, jsonify
from config import DB_PATH
from services.login_status_service import LoginStatusService
from api.auth import require_auth

logger = logging.getLogger(__name__)

login_status_bp = Blueprint("login_status", __name__)
login_svc = LoginStatusService(DB_PATH)


@login_status_bp.route("/api/accounts/<int:account_id>/login-status", methods=["GET"])
@require_auth
def get_login_status(account_id):
    """Get login status for an account."""
    try:
        status = login_svc.get_or_create(account_id)
        return jsonify(status), 200
    except Exception as e:
        logger.exception("Unexpected error in login_status API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@login_status_bp.route("/api/accounts/<int:account_id>/login-status/check", methods=["POST"])
@require_auth
def trigger_login_check(account_id):
    """Record a manual login check attempt."""
    try:
        data = request.get_json(force=True) or {}
        result = login_svc.record_attempt(
            account_id=account_id,
            action=data.get("action", "login_check"),
            status=data.get("status", "success"),
            failure_reason=data.get("failure_reason", ""),
            ip_used=data.get("ip_used", ""),
            duration_ms=data.get("duration_ms", 0),
            response_code=data.get("response_code"),
            response_snippet=data.get("response_snippet", ""),
        )
        # Update state if provided
        if data.get("new_state"):
            login_svc.update_state(account_id, data["new_state"],
                                   reason=data.get("failure_reason", ""))
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Unexpected error in login_status API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@login_status_bp.route("/api/accounts/<int:account_id>/login-logs", methods=["GET"])
@require_auth
def get_login_logs(account_id):
    """Get login attempt logs for an account."""
    try:
        limit = request.args.get("limit", 50, type=int)
        logs = login_svc.get_logs(account_id, limit=limit)
        return jsonify(logs), 200
    except Exception as e:
        logger.exception("Unexpected error in login_status API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@login_status_bp.route("/api/login-status/summary", methods=["GET"])
@require_auth
def login_status_summary():
    """Get summary stats (counts by state)."""
    try:
        stats = login_svc.get_summary_stats()
        return jsonify(stats), 200
    except Exception as e:
        logger.exception("Unexpected error in login_status API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@login_status_bp.route("/api/login-status/failing", methods=["GET"])
@require_auth
def list_failing_accounts():
    """List all accounts with login failures."""
    try:
        items = login_svc.list_failing()
        return jsonify(items), 200
    except Exception as e:
        logger.exception("Unexpected error in login_status API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@login_status_bp.route("/api/login-status/needing-check", methods=["GET"])
@require_auth
def list_needing_check():
    """List accounts needing login re-check."""
    try:
        items = login_svc.list_needing_check()
        return jsonify(items), 200
    except Exception as e:
        logger.exception("Unexpected error in login_status API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@login_status_bp.route("/api/login-status/check-all", methods=["POST"])
@require_auth
def check_all_logins():
    """Trigger batch login check (records attempts for accounts needing check)."""
    try:
        needing = login_svc.list_needing_check()
        results = []
        for item in needing[:10]:  # Limit batch size
            result = login_svc.record_attempt(
                account_id=item["account_id"],
                action="auto_check",
                status="success",
            )
            results.append(result)
        return jsonify({"checked": len(results), "results": results}), 200
    except Exception as e:
        logger.exception("Unexpected error in login_status API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500
