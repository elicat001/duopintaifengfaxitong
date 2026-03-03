"""Blueprint for Account Health and Warming REST APIs."""

from flask import Blueprint, request, jsonify
from config import DB_PATH
from services.account_health_service import AccountHealthService
from api.auth import require_auth

account_health_bp = Blueprint("account_health", __name__)
health_svc = AccountHealthService(DB_PATH)


@account_health_bp.route("/api/accounts/<int:account_id>/health", methods=["GET"])
@require_auth
def get_account_health(account_id):
    """Get full health dashboard for an account."""
    try:
        dashboard = health_svc.get_health_dashboard(account_id)
        if "error" in dashboard:
            return jsonify(dashboard), 404
        return jsonify(dashboard), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@account_health_bp.route("/api/accounts/health/overview", methods=["GET"])
@require_auth
def health_overview():
    """Get system-wide health overview."""
    try:
        stats = health_svc.get_overview_stats()
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@account_health_bp.route("/api/accounts/health/at-risk", methods=["GET"])
@require_auth
def list_at_risk():
    """List at-risk accounts."""
    try:
        threshold = request.args.get("threshold", type=float)
        items = health_svc.list_at_risk(threshold=threshold)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@account_health_bp.route("/api/accounts/<int:account_id>/warming/advance", methods=["POST"])
@require_auth
def advance_warming(account_id):
    """Advance warming stage for an account."""
    try:
        result = health_svc.advance_warming(account_id)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@account_health_bp.route("/api/accounts/<int:account_id>/warming", methods=["GET"])
@require_auth
def get_warming_status(account_id):
    """Get warming workflow status."""
    try:
        status = health_svc.get_warming_status(account_id)
        if "error" in status:
            return jsonify(status), 404
        return jsonify(status), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@account_health_bp.route("/api/accounts/health/recompute", methods=["POST"])
@require_auth
def recompute_risk_scores():
    """Batch recompute all account risk scores."""
    try:
        result = health_svc.compute_all_risk_scores()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
