"""Browser Pool Management API endpoints."""

from flask import Blueprint, request, jsonify
from api.auth import require_auth
from config import DB_PATH

browser_pool_bp = Blueprint("browser_pool", __name__)


@browser_pool_bp.route("/api/browser-pool/status", methods=["GET"])
@require_auth
def pool_status():
    """Get browser pool status - active instances, idle instances, etc."""
    # Try to get pool from app context or create a status view
    from services.browser_profile_manager import BrowserProfileManager
    pm = BrowserProfileManager()
    profiles = pm.list_profiles()

    return jsonify({
        "total_profiles": len(profiles),
        "profiles": profiles,
    })


@browser_pool_bp.route("/api/browser-profiles", methods=["GET"])
@require_auth
def list_profiles():
    """List all browser profiles."""
    from services.browser_profile_manager import BrowserProfileManager
    pm = BrowserProfileManager()
    profiles = pm.list_profiles()
    return jsonify(profiles)


@browser_pool_bp.route("/api/browser-profiles/<int:account_id>", methods=["GET"])
@require_auth
def get_profile(account_id):
    """Get profile info for an account."""
    from services.browser_profile_manager import BrowserProfileManager
    pm = BrowserProfileManager()
    info = pm.get_profile_info(account_id)
    if not info:
        return jsonify({"error": "Profile not found"}), 404
    return jsonify(info)


@browser_pool_bp.route("/api/browser-profiles/<int:account_id>", methods=["POST"])
@require_auth
def create_profile(account_id):
    """Create or get a browser profile for an account."""
    from services.browser_profile_manager import BrowserProfileManager
    data = request.get_json(silent=True) or {}
    pm = BrowserProfileManager()
    result = pm.get_or_create_profile(account_id, platform=data.get("platform", ""))
    return jsonify(result)


@browser_pool_bp.route("/api/browser-profiles/<int:account_id>", methods=["DELETE"])
@require_auth
def delete_profile(account_id):
    """Delete a browser profile."""
    from services.browser_profile_manager import BrowserProfileManager
    pm = BrowserProfileManager()
    deleted = pm.delete_profile(account_id)
    if deleted:
        return jsonify({"message": "Profile deleted"})
    return jsonify({"error": "Profile not found"}), 404


@browser_pool_bp.route("/api/browser-profiles/cleanup", methods=["POST"])
@require_auth
def cleanup_profiles():
    """Clean up stale browser profiles."""
    data = request.get_json(silent=True) or {}
    max_age_days = data.get("max_age_days", 30)
    from services.browser_profile_manager import BrowserProfileManager
    pm = BrowserProfileManager()
    count = pm.cleanup_stale_profiles(max_age_days)
    return jsonify({"deleted_count": count})


@browser_pool_bp.route("/api/browser-pool/connect-cdp", methods=["POST"])
@require_auth
def connect_cdp():
    """Connect to a remote browser via CDP."""
    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id")
    cdp_url = data.get("cdp_url")

    if not account_id or not cdp_url:
        return jsonify({"error": "account_id and cdp_url required"}), 400

    # Store CDP config in database
    from models.database import get_connection
    from datetime import datetime
    conn = get_connection(DB_PATH)
    try:
        now = datetime.now().isoformat()
        # Upsert browser_profiles
        existing = conn.execute(
            "SELECT id FROM browser_profiles WHERE account_id = ?",
            (account_id,)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE browser_profiles
                SET cdp_url = ?, connection_mode = 'remote_cdp', updated_at = ?
                WHERE account_id = ?
            """, (cdp_url, now, account_id))
        else:
            conn.execute("""
                INSERT INTO browser_profiles
                    (account_id, cdp_url, connection_mode, profile_dir, created_at, updated_at)
                VALUES (?, ?, 'remote_cdp', '', ?, ?)
            """, (account_id, cdp_url, now, now))
        conn.commit()
        return jsonify({"message": f"CDP connection configured: {cdp_url}"})
    finally:
        conn.close()


@browser_pool_bp.route("/api/browser-pool/docker-status", methods=["GET"])
@require_auth
def docker_status():
    """Check Docker browser container status."""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=inswu-browser", "--format",
             "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=10
        )
        containers = []
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t")
                containers.append({
                    "name": parts[0] if len(parts) > 0 else "",
                    "status": parts[1] if len(parts) > 1 else "",
                    "ports": parts[2] if len(parts) > 2 else "",
                })
        return jsonify({"containers": containers, "docker_available": True})
    except Exception as e:
        return jsonify({"containers": [], "docker_available": False,
                        "error": str(e)})


@browser_pool_bp.route("/api/generic-tasks", methods=["POST"])
@require_auth
def create_generic_task():
    """Submit a generic task."""
    data = request.get_json(silent=True) or {}
    required = ["task_type", "account_id"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    from services.task_engine import GenericTaskEngine
    engine = GenericTaskEngine(DB_PATH)
    task_id = engine.submit_task(
        task_type=data["task_type"],
        account_id=data["account_id"],
        platform=data.get("platform", ""),
        params=data.get("params", {}),
        scheduled_at=data.get("scheduled_at"),
    )
    return jsonify({"id": task_id}), 201


@browser_pool_bp.route("/api/generic-tasks", methods=["GET"])
@require_auth
def list_generic_tasks():
    """List generic tasks."""
    task_type = request.args.get("task_type")
    state = request.args.get("state")
    account_id = request.args.get("account_id", type=int)
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    from services.task_engine import GenericTaskEngine
    engine = GenericTaskEngine(DB_PATH)
    tasks = engine.list_tasks(task_type, state, account_id, limit, offset)
    return jsonify(tasks)


@browser_pool_bp.route("/api/generic-tasks/<int:task_id>", methods=["GET"])
@require_auth
def get_generic_task(task_id):
    """Get a specific generic task."""
    from services.task_engine import GenericTaskEngine
    engine = GenericTaskEngine(DB_PATH)
    task = engine.get_task(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task)


@browser_pool_bp.route("/api/generic-tasks/<int:task_id>/execute", methods=["POST"])
@require_auth
def execute_generic_task(task_id):
    """Execute a generic task immediately."""
    from services.task_engine import GenericTaskEngine
    engine = GenericTaskEngine(DB_PATH)
    success = engine.execute_task(task_id)
    return jsonify({"success": success})


@browser_pool_bp.route("/api/generic-tasks/<int:task_id>/cancel", methods=["POST"])
@require_auth
def cancel_generic_task(task_id):
    """Cancel a generic task."""
    from services.task_engine import GenericTaskEngine
    engine = GenericTaskEngine(DB_PATH)
    success = engine.cancel_task(task_id)
    return jsonify({"success": success})


@browser_pool_bp.route("/api/task-handlers", methods=["GET"])
@require_auth
def list_task_handlers():
    """List registered task handlers."""
    from services.task_engine import TaskHandlerRegistry
    return jsonify(TaskHandlerRegistry.list_types())
