"""
Blueprint for Account Group and Account REST APIs.
"""

import logging

from flask import Blueprint, request, jsonify
from config import DB_PATH
from services.account_service import AccountService, AccountGroupService
from api.auth import require_auth

logger = logging.getLogger(__name__)

accounts_bp = Blueprint("accounts", __name__)
group_svc = AccountGroupService(DB_PATH)
account_svc = AccountService(DB_PATH)

# ── Validation constants ────────────────────────────────────────────────
VALID_PLATFORMS = {"instagram", "tiktok", "youtube", "twitter", "facebook", "xiaohongshu", "weibo", "bilibili", "douyin"}
VALID_ACCOUNT_STATUSES = {"active", "paused", "banned", "warming", "login_expired", "need_verify", "rate_limited", "cooldown", "disabled"}


# ── Account Group API ────────────────────────────────────────────────────


@accounts_bp.route("/api/account-groups", methods=["POST"])
@require_auth
def create_account_group():
    """Create a new account group."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("name"):
            return jsonify({"error": "name is required"}), 400

        group_id = group_svc.create(data)
        group = group_svc.get(group_id)
        return jsonify(group), 201
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@accounts_bp.route("/api/account-groups", methods=["GET"])
@require_auth
def list_account_groups():
    """List all account groups."""
    try:
        items = group_svc.list_all()
        return jsonify(items), 200
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@accounts_bp.route("/api/account-groups/<int:group_id>", methods=["PUT"])
@require_auth
def update_account_group(group_id):
    """Update an account group."""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400

        existing = group_svc.get(group_id)
        if existing is None:
            return jsonify({"error": "account group not found"}), 404

        group_svc.update(group_id, data)
        updated = group_svc.get(group_id)
        return jsonify(updated), 200
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@accounts_bp.route("/api/account-groups/<int:group_id>", methods=["DELETE"])
@require_auth
def delete_account_group(group_id):
    """Delete an account group."""
    try:
        ok = group_svc.delete(group_id)
        if not ok:
            return jsonify({"error": "account group not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


# ── Account API ──────────────────────────────────────────────────────────


@accounts_bp.route("/api/accounts", methods=["POST"])
@require_auth
def create_account():
    """Create a new account."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("platform") or not data.get("handle"):
            return jsonify({"error": "platform and handle are required"}), 400

        if data["platform"] not in VALID_PLATFORMS:
            return jsonify({"error": f"invalid platform, must be one of: {', '.join(sorted(VALID_PLATFORMS))}"}), 400
        daily = data.get("daily_limit", 10)
        hourly = data.get("hourly_limit", 3)
        if not isinstance(daily, int) or daily < 0 or daily > 1000:
            return jsonify({"error": "daily_limit must be 0-1000"}), 400
        if not isinstance(hourly, int) or hourly < 0 or hourly > 100:
            return jsonify({"error": "hourly_limit must be 0-100"}), 400

        account_id = account_svc.create(data)
        account = account_svc.get(account_id)
        return jsonify(account), 201
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@accounts_bp.route("/api/accounts", methods=["GET"])
@require_auth
def list_accounts():
    """List accounts with optional filters."""
    try:
        platform = request.args.get("platform")
        if platform and platform not in VALID_PLATFORMS:
            return jsonify({"error": "invalid platform filter"}), 400
        status = request.args.get("status")
        if status and status not in VALID_ACCOUNT_STATUSES:
            return jsonify({"error": "invalid status filter"}), 400
        group_id = request.args.get("group_id", type=int)
        login_status = request.args.get("login_status")
        limit = min(request.args.get("limit", 50, type=int), 500)
        offset = request.args.get("offset", 0, type=int)

        items = account_svc.list_all(
            platform=platform, group_id=group_id, status=status,
            login_status=login_status, limit=limit, offset=offset,
        )
        return jsonify(items), 200
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@accounts_bp.route("/api/accounts/<int:account_id>", methods=["GET"])
@require_auth
def get_account(account_id):
    """Get a single account."""
    try:
        include = request.args.get("include")
        if include == "details":
            account = account_svc.get_with_details(account_id)
        else:
            account = account_svc.get(account_id)
        if account is None:
            return jsonify({"error": "account not found"}), 404
        return jsonify(account), 200
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@accounts_bp.route("/api/accounts/<int:account_id>", methods=["PUT"])
@require_auth
def update_account(account_id):
    """Update an account."""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400

        existing = account_svc.get(account_id)
        if existing is None:
            return jsonify({"error": "account not found"}), 404

        account_svc.update(account_id, data)
        updated = account_svc.get(account_id)
        return jsonify(updated), 200
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@accounts_bp.route("/api/accounts/<int:account_id>/pause", methods=["POST"])
@require_auth
def pause_account(account_id):
    """Pause an account."""
    try:
        ok = account_svc.pause(account_id)
        if not ok:
            return jsonify({"error": "account not found"}), 404

        updated = account_svc.get(account_id)
        return jsonify(updated), 200
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@accounts_bp.route("/api/accounts/<int:account_id>/resume", methods=["POST"])
@require_auth
def resume_account(account_id):
    """Resume an account."""
    try:
        ok = account_svc.resume(account_id)
        if not ok:
            return jsonify({"error": "account not found"}), 404

        updated = account_svc.get(account_id)
        return jsonify(updated), 200
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@accounts_bp.route("/api/accounts/<int:account_id>", methods=["DELETE"])
@require_auth
def delete_account(account_id):
    """Delete an account."""
    try:
        ok = account_svc.delete(account_id)
        if not ok:
            return jsonify({"error": "account not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        logger.exception("Unexpected error in accounts API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500
