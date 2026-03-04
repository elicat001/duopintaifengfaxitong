"""Blueprint for Proxy Pool and Assignment REST APIs."""

import logging

from flask import Blueprint, request, jsonify
from config import DB_PATH, CREDENTIAL_ENCRYPTION_KEY
from services.crypto_service import CryptoService
from services.proxy_service import ProxyGroupService, ProxyService
from api.auth import require_auth

logger = logging.getLogger(__name__)

proxies_bp = Blueprint("proxies", __name__)
crypto = CryptoService(CREDENTIAL_ENCRYPTION_KEY)
group_svc = ProxyGroupService(DB_PATH)
proxy_svc = ProxyService(DB_PATH, crypto)

# ── Validation constants ────────────────────────────────────────────────
VALID_PROXY_TYPES = {"http", "https", "socks5"}
VALID_PROXY_STATUSES = {"active", "inactive", "failed", "testing"}


# ── Proxy Group API ─────────────────────────────────────────────────────

@proxies_bp.route("/api/proxy-groups", methods=["POST"])
@require_auth
def create_proxy_group():
    try:
        data = request.get_json(force=True)
        if not data or not data.get("name"):
            return jsonify({"error": "name is required"}), 400
        gid = group_svc.create(data)
        return jsonify(group_svc.get(gid)), 201
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxy-groups", methods=["GET"])
@require_auth
def list_proxy_groups():
    try:
        items = group_svc.list_all()
        return jsonify(items), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxy-groups/<int:gid>", methods=["PUT"])
@require_auth
def update_proxy_group(gid):
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body required"}), 400
        if not group_svc.get(gid):
            return jsonify({"error": "proxy group not found"}), 404
        group_svc.update(gid, data)
        return jsonify(group_svc.get(gid)), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxy-groups/<int:gid>", methods=["DELETE"])
@require_auth
def delete_proxy_group(gid):
    try:
        if not group_svc.delete(gid):
            return jsonify({"error": "proxy group not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


# ── Proxy API ────────────────────────────────────────────────────────────

@proxies_bp.route("/api/proxies", methods=["POST"])
@require_auth
def create_proxy():
    try:
        data = request.get_json(force=True)
        if not data or not data.get("host") or not data.get("port"):
            return jsonify({"error": "host and port are required"}), 400
        proxy_type = data.get("proxy_type", "http")
        if proxy_type not in VALID_PROXY_TYPES:
            return jsonify({"error": "invalid proxy_type"}), 400
        port = data.get("port", 0)
        if not isinstance(port, int) or port < 1 or port > 65535:
            return jsonify({"error": "port must be 1-65535"}), 400
        pid = proxy_svc.create(data)
        return jsonify(proxy_svc.get(pid)), 201
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxies", methods=["GET"])
@require_auth
def list_proxies():
    try:
        limit = min(request.args.get("limit", 50, type=int), 500)
        offset = request.args.get("offset", 0, type=int)
        items = proxy_svc.list_all(
            status=request.args.get("status"),
            proxy_type=request.args.get("proxy_type"),
            region=request.args.get("region"),
            group_id=request.args.get("group_id", type=int),
            limit=limit,
            offset=offset,
        )
        return jsonify(items), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxies/<int:pid>", methods=["GET"])
@require_auth
def get_proxy(pid):
    try:
        p = proxy_svc.get(pid)
        if not p:
            return jsonify({"error": "proxy not found"}), 404
        return jsonify(p), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxies/<int:pid>", methods=["PUT"])
@require_auth
def update_proxy(pid):
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body required"}), 400
        if not proxy_svc.get(pid):
            return jsonify({"error": "proxy not found"}), 404
        proxy_svc.update(pid, data)
        return jsonify(proxy_svc.get(pid)), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxies/<int:pid>", methods=["DELETE"])
@require_auth
def delete_proxy(pid):
    try:
        if not proxy_svc.delete(pid):
            return jsonify({"error": "proxy not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxies/<int:pid>/check", methods=["POST"])
@require_auth
def check_proxy(pid):
    try:
        result = proxy_svc.check_health(pid)
        if "error" in result and result["error"] == "proxy not found":
            return jsonify(result), 404
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxies/check-all", methods=["POST"])
@require_auth
def check_all_proxies():
    try:
        results = proxy_svc.check_all_health()
        return jsonify({"results": results, "total": len(results)}), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxies/<int:pid>/logs", methods=["GET"])
@require_auth
def get_proxy_logs(pid):
    try:
        limit = request.args.get("limit", 20, type=int)
        logs = proxy_svc.get_check_logs(pid, limit=limit)
        return jsonify(logs), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxies/stats", methods=["GET"])
@require_auth
def get_proxy_stats():
    try:
        stats = proxy_svc.get_stats()
        return jsonify(stats), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/proxies/import", methods=["POST"])
@require_auth
def import_proxies():
    try:
        data = request.get_json(force=True)
        if not data or not data.get("proxies"):
            return jsonify({"error": "proxies list is required"}), 400
        result = proxy_svc.import_bulk(data["proxies"])
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


# ── Account Proxy Assignment API ──────────────────────────────────────

@proxies_bp.route("/api/accounts/<int:account_id>/proxy-assignment", methods=["POST"])
@require_auth
def assign_proxy(account_id):
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body required"}), 400
        assignment_type = data.get("assignment_type", "direct")
        proxy_id = data.get("proxy_id")
        proxy_group_id = data.get("proxy_group_id")
        if assignment_type == "direct" and not proxy_id:
            return jsonify({"error": "proxy_id required for direct assignment"}), 400
        if assignment_type == "pool" and not proxy_group_id:
            return jsonify({"error": "proxy_group_id required for pool assignment"}), 400
        aid = proxy_svc.assign_to_account(
            account_id, proxy_id=proxy_id,
            proxy_group_id=proxy_group_id,
            assignment_type=assignment_type,
        )
        assignment = proxy_svc.get_assignment(account_id)
        return jsonify(assignment), 201
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/accounts/<int:account_id>/proxy-assignment", methods=["GET"])
@require_auth
def get_proxy_assignment(account_id):
    try:
        assignment = proxy_svc.get_assignment(account_id)
        if not assignment:
            return jsonify({"error": "no active proxy assignment"}), 404
        return jsonify(assignment), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@proxies_bp.route("/api/accounts/<int:account_id>/proxy-assignment", methods=["DELETE"])
@require_auth
def remove_proxy_assignment(account_id):
    try:
        ok = proxy_svc.remove_assignment(account_id)
        if not ok:
            return jsonify({"error": "no active assignment found"}), 404
        return jsonify({"message": "proxy assignment removed"}), 200
    except Exception as e:
        logger.exception("Unexpected error in proxies API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500
