"""
Blueprint for Content, Asset, and Variant REST APIs.
"""

from flask import Blueprint, request, jsonify
from config import DB_PATH
from services.content_service import ContentService, AssetService, VariantService
from api.auth import require_auth

contents_bp = Blueprint("contents", __name__)
cs = ContentService(DB_PATH)
asset_svc = AssetService(DB_PATH)
variant_svc = VariantService(DB_PATH)

# ── Validation constants ────────────────────────────────────────────────
VALID_CONTENT_TYPES = {"image_single", "image_carousel", "video"}
VALID_CONTENT_STATUSES = {"draft", "pending_review", "approved", "rejected", "archived"}


# ── Content API ──────────────────────────────────────────────────────────


@contents_bp.route("/api/contents", methods=["POST"])
@require_auth
def create_content():
    """Create a new content item."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("title"):
            return jsonify({"error": "title is required"}), 400

        content_type = data.get("content_type", "image_single")
        if content_type not in VALID_CONTENT_TYPES:
            return jsonify({"error": "invalid content_type"}), 400
        title = data.get("title", "").strip()
        if not title or len(title) > 500:
            return jsonify({"error": "title required, max 500 chars"}), 400

        content_id = cs.create(data)
        content = cs.get(content_id)
        return jsonify(content), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/contents", methods=["GET"])
@require_auth
def list_contents():
    """List contents with optional filters."""
    try:
        status = request.args.get("status")
        topic = request.args.get("topic")
        content_type = request.args.get("content_type")
        limit = min(request.args.get("limit", 50, type=int), 500)
        offset = request.args.get("offset", 0, type=int)

        items = cs.list_all(status=status, topic=topic, content_type=content_type,
                            limit=limit, offset=offset)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/contents/<int:content_id>", methods=["GET"])
@require_auth
def get_content(content_id):
    """Get a single content item."""
    try:
        content = cs.get(content_id)
        if content is None:
            return jsonify({"error": "content not found"}), 404
        return jsonify(content), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/contents/<int:content_id>", methods=["PUT"])
@require_auth
def update_content(content_id):
    """Update a content item."""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400

        # Check existence first
        existing = cs.get(content_id)
        if existing is None:
            return jsonify({"error": "content not found"}), 404

        cs.update(content_id, data)
        updated = cs.get(content_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/contents/<int:content_id>/review", methods=["POST"])
@require_auth
def review_content(content_id):
    """Review a content item (approve / reject)."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("status"):
            return jsonify({"error": "status is required"}), 400

        status = data["status"]
        if status not in ("approved", "rejected"):
            return jsonify({"error": "status must be 'approved' or 'rejected'"}), 400

        notes = data.get("notes", "")
        ok = cs.review(content_id, status, notes)
        if not ok:
            return jsonify({"error": "content not found"}), 404

        updated = cs.get(content_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/contents/<int:content_id>", methods=["DELETE"])
@require_auth
def delete_content(content_id):
    """Delete a content item."""
    try:
        ok = cs.delete(content_id)
        if not ok:
            return jsonify({"error": "content not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Asset API ────────────────────────────────────────────────────────────


@contents_bp.route("/api/assets", methods=["POST"])
@require_auth
def create_asset():
    """Create a new asset record."""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400

        asset_id = asset_svc.create(data)
        asset = asset_svc.get(asset_id)
        return jsonify(asset), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/assets", methods=["GET"])
@require_auth
def list_assets():
    """List all assets."""
    try:
        items = asset_svc.list_all()
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/assets/<int:asset_id>", methods=["GET"])
@require_auth
def get_asset(asset_id):
    """Get a single asset."""
    try:
        asset = asset_svc.get(asset_id)
        if asset is None:
            return jsonify({"error": "asset not found"}), 404
        return jsonify(asset), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/assets/<int:asset_id>", methods=["DELETE"])
@require_auth
def delete_asset(asset_id):
    """Delete an asset."""
    try:
        ok = asset_svc.delete(asset_id)
        if not ok:
            return jsonify({"error": "asset not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Variant API ──────────────────────────────────────────────────────────


@contents_bp.route("/api/contents/<int:content_id>/variants", methods=["POST"])
@require_auth
def create_variant(content_id):
    """Create a variant for a given content item."""
    try:
        # Verify the parent content exists
        content = cs.get(content_id)
        if content is None:
            return jsonify({"error": "content not found"}), 404

        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400

        data["content_id"] = content_id
        variant_id = variant_svc.create(data)
        variant = variant_svc.get(variant_id)
        return jsonify(variant), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/contents/<int:content_id>/variants", methods=["GET"])
@require_auth
def list_variants(content_id):
    """List all variants belonging to a content item."""
    try:
        # Verify the parent content exists
        content = cs.get(content_id)
        if content is None:
            return jsonify({"error": "content not found"}), 404

        items = variant_svc.list_by_content(content_id)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/variants/<int:variant_id>", methods=["GET"])
@require_auth
def get_variant(variant_id):
    """Get a single variant."""
    try:
        variant = variant_svc.get(variant_id)
        if variant is None:
            return jsonify({"error": "variant not found"}), 404
        return jsonify(variant), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/variants/<int:variant_id>/status", methods=["PUT"])
@require_auth
def update_variant_status(variant_id):
    """Update the status of a variant (ready / blocked)."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("status"):
            return jsonify({"error": "status is required"}), 400

        status = data["status"]
        if status not in ("ready", "blocked"):
            return jsonify({"error": "status must be 'ready' or 'blocked'"}), 400

        ok = variant_svc.update_status(variant_id, status)
        if not ok:
            return jsonify({"error": "variant not found"}), 404

        updated = variant_svc.get(variant_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@contents_bp.route("/api/variants/<int:variant_id>", methods=["DELETE"])
@require_auth
def delete_variant(variant_id):
    """Delete a variant."""
    try:
        ok = variant_svc.delete(variant_id)
        if not ok:
            return jsonify({"error": "variant not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
