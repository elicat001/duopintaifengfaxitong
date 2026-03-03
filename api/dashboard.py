"""
Blueprint for Dashboard, Stats, and Auth Token APIs.
"""

from flask import Blueprint, request, jsonify
from config import DB_PATH, ADMIN_USERNAME, ADMIN_PASSWORD
from models.database import get_connection
from api.auth import generate_token, require_auth

dashboard_bp = Blueprint("dashboard", __name__)


# ── helpers ──────────────────────────────────────────────────────────────


_ALLOWED_GROUP_BY = {
    ("contents", "status"),
    ("accounts", "status"),
    ("accounts", "platform"),
    ("accounts", "login_status"),
    ("jobs", "state"),
}


def _count_group_by(conn, table: str, column: str) -> dict:
    """Run SELECT <column>, COUNT(*) FROM <table> GROUP BY <column> and
    return {value: count, ...}.  Only whitelisted table/column pairs allowed."""
    if (table, column) not in _ALLOWED_GROUP_BY:
        raise ValueError(f"Disallowed group-by: {table}.{column}")
    # table/column are from the whitelist above, safe to interpolate
    rows = conn.execute(
        f"SELECT [{column}], COUNT(*) AS cnt FROM [{table}] GROUP BY [{column}]"
    ).fetchall()
    return {row[column]: row["cnt"] for row in rows}


def _get_stats(conn) -> dict:
    """Build the full stats dictionary from the database."""
    total_contents = conn.execute(
        "SELECT COUNT(*) AS cnt FROM contents"
    ).fetchone()["cnt"]
    contents_by_status = _count_group_by(conn, "contents", "status")

    total_accounts = conn.execute(
        "SELECT COUNT(*) AS cnt FROM accounts"
    ).fetchone()["cnt"]
    accounts_by_status = _count_group_by(conn, "accounts", "status")
    accounts_by_platform = _count_group_by(conn, "accounts", "platform")

    total_jobs = conn.execute(
        "SELECT COUNT(*) AS cnt FROM jobs"
    ).fetchone()["cnt"]
    jobs_by_state = _count_group_by(conn, "jobs", "state")

    total_policies = conn.execute(
        "SELECT COUNT(*) AS cnt FROM policies"
    ).fetchone()["cnt"]

    # Accounts by login_status
    accounts_by_login_status = _count_group_by(conn, "accounts", "login_status")

    # Accounts with active proxy assignments
    accounts_with_proxy = conn.execute(
        "SELECT COUNT(DISTINCT account_id) AS cnt FROM account_proxy_assignments WHERE is_active = 1"
    ).fetchone()["cnt"]

    # Accounts with active credentials
    accounts_with_credentials = conn.execute(
        "SELECT COUNT(DISTINCT account_id) AS cnt FROM account_credentials WHERE is_active = 1"
    ).fetchone()["cnt"]

    return {
        "total_contents": total_contents,
        "contents_by_status": contents_by_status,
        "total_accounts": total_accounts,
        "accounts_by_status": accounts_by_status,
        "accounts_by_platform": accounts_by_platform,
        "accounts_by_login_status": accounts_by_login_status,
        "accounts_with_proxy": accounts_with_proxy,
        "accounts_with_credentials": accounts_with_credentials,
        "total_jobs": total_jobs,
        "jobs_by_state": jobs_by_state,
        "total_policies": total_policies,
    }


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


# ── Dashboard ────────────────────────────────────────────────────────────


@dashboard_bp.route("/api/dashboard", methods=["GET"])
@require_auth
def dashboard():
    """Return aggregated dashboard data: stats, recent jobs, recent contents."""
    try:
        conn = get_connection(DB_PATH)
        try:
            stats = _get_stats(conn)

            recent_jobs = conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT 20"
            ).fetchall()
            recent_jobs = [_row_to_dict(r) for r in recent_jobs]

            recent_contents = conn.execute(
                "SELECT * FROM contents ORDER BY id DESC LIMIT 10"
            ).fetchall()
            recent_contents = [_row_to_dict(r) for r in recent_contents]
        finally:
            conn.close()

        return jsonify({
            "stats": stats,
            "recent_jobs": recent_jobs,
            "recent_contents": recent_contents,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Stats (simplified) ──────────────────────────────────────────────────


@dashboard_bp.route("/api/stats", methods=["GET"])
@require_auth
def stats():
    """Return only the stats object (no recent lists)."""
    try:
        conn = get_connection(DB_PATH)
        try:
            result = _get_stats(conn)
        finally:
            conn.close()

        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Auth Token ──────────────────────────────────────────────────────────


@dashboard_bp.route("/api/auth/token", methods=["POST"])
def auth_token():
    """Generate a JWT token. Simplified: only admin/admin is accepted."""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400

        username = data.get("username", "")
        password = data.get("password", "")

        if username != ADMIN_USERNAME or password != ADMIN_PASSWORD:
            return jsonify({"error": "invalid credentials"}), 401

        token = generate_token(user_id=1, role="admin")
        return jsonify({"token": token, "user": {"id": 1, "username": "admin", "role": "admin"}}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
