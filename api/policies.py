"""
Blueprint for Policy REST APIs.
"""

from flask import Blueprint, request, jsonify
from config import DB_PATH
from services.policy_service import PolicyService
from api.auth import require_auth

policies_bp = Blueprint("policies", __name__)
policy_svc = PolicyService(DB_PATH)


# ── Policy API ───────────────────────────────────────────────────────────


@policies_bp.route("/api/policies", methods=["POST"])
@require_auth
def create_policy():
    """Create a new policy."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("name"):
            return jsonify({"error": "name is required"}), 400

        policy_id = policy_svc.create(data)
        policy = policy_svc.get(policy_id)
        return jsonify(policy), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@policies_bp.route("/api/policies", methods=["GET"])
@require_auth
def list_policies():
    """List policies with optional filters."""
    try:
        platform = request.args.get("platform")
        scope_type = request.args.get("scope_type")
        scope_id = request.args.get("scope_id")

        items = policy_svc.list_all(
            platform=platform, scope_type=scope_type, scope_id=scope_id
        )
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@policies_bp.route("/api/policies/<int:policy_id>", methods=["GET"])
@require_auth
def get_policy(policy_id):
    """Get a single policy."""
    try:
        policy = policy_svc.get(policy_id)
        if policy is None:
            return jsonify({"error": "policy not found"}), 404
        return jsonify(policy), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@policies_bp.route("/api/policies/<int:policy_id>", methods=["PUT"])
@require_auth
def update_policy(policy_id):
    """Update a policy."""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400

        existing = policy_svc.get(policy_id)
        if existing is None:
            return jsonify({"error": "policy not found"}), 404

        policy_svc.update(policy_id, data)
        updated = policy_svc.get(policy_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@policies_bp.route("/api/policies/<int:policy_id>/toggle", methods=["POST"])
@require_auth
def toggle_policy(policy_id):
    """Enable or disable a policy."""
    try:
        data = request.get_json(force=True)
        if data is None or "enabled" not in data:
            return jsonify({"error": "enabled is required"}), 400

        ok = policy_svc.toggle(policy_id, bool(data["enabled"]))
        if not ok:
            return jsonify({"error": "policy not found"}), 404

        updated = policy_svc.get(policy_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@policies_bp.route("/api/policies/<int:policy_id>", methods=["DELETE"])
@require_auth
def delete_policy(policy_id):
    """Delete a policy."""
    try:
        ok = policy_svc.delete(policy_id)
        if not ok:
            return jsonify({"error": "policy not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
