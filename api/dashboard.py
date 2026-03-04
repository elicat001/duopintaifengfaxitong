"""
Blueprint for Dashboard, Stats, and Auth Token APIs.
"""

import logging
import time

from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from config import DB_PATH, ADMIN_USERNAME, ADMIN_PASSWORD
from models.database import get_connection
from api.auth import generate_token, require_auth

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)

# ── Password hash (computed once at import time) ─────────────────────────
_ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)

# ── In-memory rate limiter for login ─────────────────────────────────────
_LOGIN_RATE_LIMIT = {}          # IP -> (fail_count, first_fail_time)
_MAX_LOGIN_FAILURES = 5
_RATE_LIMIT_WINDOW = 15 * 60   # 15 minutes in seconds


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
        logger.exception("dashboard error")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("stats error")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


# ── Auth Token ──────────────────────────────────────────────────────────


@dashboard_bp.route("/api/auth/token", methods=["POST"])
def auth_token():
    """Generate a JWT token. Simplified: only admin/admin is accepted."""
    try:
        client_ip = request.remote_addr or "unknown"

        # ── Rate-limit check ────────────────────────────────────────
        now = time.time()
        if client_ip in _LOGIN_RATE_LIMIT:
            fail_count, first_fail_time = _LOGIN_RATE_LIMIT[client_ip]
            if now - first_fail_time > _RATE_LIMIT_WINDOW:
                # Window expired, reset
                del _LOGIN_RATE_LIMIT[client_ip]
            elif fail_count >= _MAX_LOGIN_FAILURES:
                remaining = int(_RATE_LIMIT_WINDOW - (now - first_fail_time))
                logger.warning("Rate limit hit for IP %s, %d seconds remaining", client_ip, remaining)
                return jsonify({"error": f"登录尝试过多，请在{remaining}秒后重试"}), 429

        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400

        username = data.get("username", "")
        password = data.get("password", "")

        if username != ADMIN_USERNAME or not check_password_hash(_ADMIN_PASSWORD_HASH, password):
            # Record failed attempt
            if client_ip in _LOGIN_RATE_LIMIT:
                fail_count, first_fail_time = _LOGIN_RATE_LIMIT[client_ip]
                _LOGIN_RATE_LIMIT[client_ip] = (fail_count + 1, first_fail_time)
            else:
                _LOGIN_RATE_LIMIT[client_ip] = (1, now)
            logger.warning("Failed login attempt for user '%s' from IP %s", username, client_ip)
            return jsonify({"error": "invalid credentials"}), 401

        # Successful login — clear any rate-limit tracking for this IP
        _LOGIN_RATE_LIMIT.pop(client_ip, None)

        token = generate_token(user_id=1, role="admin")
        return jsonify({"token": token, "user": {"id": 1, "username": "admin", "role": "admin"}}), 200
    except Exception as e:
        logger.exception("auth_token error")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500
