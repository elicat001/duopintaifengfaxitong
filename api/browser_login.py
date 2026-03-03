"""Browser Login API Blueprint."""

import base64
import logging
import os

from flask import Blueprint, jsonify, request
from api.auth import require_auth

logger = logging.getLogger(__name__)

browser_login_bp = Blueprint("browser_login", __name__)

# Lazy-initialized orchestrator singleton
_orchestrator = None
_init_lock = __import__("threading").Lock()


def _get_orchestrator():
    """Lazy-initialize the LoginOrchestrator singleton."""
    global _orchestrator
    if _orchestrator is not None:
        return _orchestrator

    with _init_lock:
        if _orchestrator is not None:
            return _orchestrator

        from config import (
            DB_PATH, CREDENTIAL_ENCRYPTION_KEY,
            BROWSER_HEADLESS, BROWSER_TIMEOUT_SECONDS,
            BROWSER_MAX_CONCURRENT, BROWSER_SCREENSHOT_DIR,
            BROWSER_USER_AGENTS,
        )
        from services.crypto_service import CryptoService
        from services.browser_service import BrowserService
        from services.credential_service import CredentialService
        from services.proxy_service import ProxyService
        from services.login_status_service import LoginStatusService
        from services.account_health_service import AccountHealthService
        from services.account_service import AccountService
        from services.login_orchestrator import LoginOrchestrator

        crypto = CryptoService(CREDENTIAL_ENCRYPTION_KEY)
        browser_config = {
            "headless": BROWSER_HEADLESS,
            "timeout": BROWSER_TIMEOUT_SECONDS,
            "max_concurrent": BROWSER_MAX_CONCURRENT,
            "screenshot_dir": BROWSER_SCREENSHOT_DIR,
            "user_agents": BROWSER_USER_AGENTS,
        }

        browser_svc = BrowserService(browser_config)
        browser_svc.start()

        _orchestrator = LoginOrchestrator(
            db_path=DB_PATH,
            browser_service=browser_svc,
            credential_service=CredentialService(DB_PATH, crypto),
            proxy_service=ProxyService(DB_PATH, crypto),
            login_status_service=LoginStatusService(DB_PATH),
            account_health_service=AccountHealthService(DB_PATH),
            account_service=AccountService(DB_PATH),
            crypto_service=crypto,
        )
        return _orchestrator


VALID_METHODS = {"cookie_import", "password_login", "qr_login"}


@browser_login_bp.route(
    "/api/accounts/<int:account_id>/browser-login", methods=["POST"]
)
@require_auth
def start_browser_login(account_id):
    """Start a browser login session for an account.

    Body: {
        "method": "cookie_import" | "password_login" | "qr_login",
        "cookie_data": {"cookies": [...]}  // for cookie_import only
    }
    Returns 202: {session_id, status, message}
    """
    try:
        data = request.get_json(force=True) or {}
        method = data.get("method", "cookie_import")

        if method not in VALID_METHODS:
            return jsonify({
                "error": f"无效的登录方式，必须是: {', '.join(VALID_METHODS)}"
            }), 400

        cookie_data = data.get("cookie_data") if method == "cookie_import" else None
        if method == "cookie_import" and not cookie_data:
            return jsonify({"error": "cookie_import 方式需要提供 cookie_data"}), 400

        orch = _get_orchestrator()
        result = orch.start_login(account_id, method, cookie_data=cookie_data)
        return jsonify(result), 202

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 429
    except Exception as e:
        logger.exception("start_browser_login error")
        return jsonify({"error": str(e)}), 500


@browser_login_bp.route(
    "/api/accounts/<int:account_id>/browser-login/status", methods=["GET"]
)
@require_auth
def get_login_session_status(account_id):
    """Poll the current/most recent login session status."""
    try:
        orch = _get_orchestrator()
        session = orch.get_session_status(account_id)
        if not session:
            return jsonify({"error": "没有找到登录会话"}), 404
        return jsonify(session), 200
    except Exception as e:
        logger.exception("get_login_session_status error")
        return jsonify({"error": str(e)}), 500


@browser_login_bp.route(
    "/api/accounts/<int:account_id>/browser-login/screenshot", methods=["GET"]
)
@require_auth
def get_login_screenshot(account_id):
    """Get the latest screenshot (CAPTCHA or QR code) as base64.

    Query params: type=captcha|qr|latest
    """
    try:
        orch = _get_orchestrator()
        session = orch.get_session_status(account_id)
        if not session:
            return jsonify({"error": "没有找到登录会话"}), 404

        screenshot_type = request.args.get("type", "latest")

        if screenshot_type == "qr":
            path = session.get("qr_code_path", "")
        elif screenshot_type == "captcha":
            path = session.get("screenshot_path", "")
        else:
            # Latest: prefer QR if waiting, else screenshot
            path = session.get("qr_code_path") or session.get("screenshot_path", "")

        if not path or not os.path.exists(path):
            return jsonify({"error": "暂无截图"}), 404

        with open(path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")

        return jsonify({
            "image": img_data,
            "format": "png",
            "session_status": session.get("status"),
            "progress_message": session.get("progress_message", ""),
        }), 200

    except Exception as e:
        logger.exception("get_login_screenshot error")
        return jsonify({"error": str(e)}), 500


@browser_login_bp.route(
    "/api/accounts/<int:account_id>/browser-login/captcha-solved",
    methods=["POST"],
)
@require_auth
def captcha_solved(account_id):
    """User signals that CAPTCHA was solved manually (in non-headless mode)."""
    try:
        orch = _get_orchestrator()
        # Update session status to indicate captcha was handled
        session = orch.get_session_status(account_id)
        if session and session.get("status") == "need_captcha":
            orch._update_session(
                session["id"], status="verifying",
                message="验证码已处理，正在验证..."
            )
        return jsonify({"message": "验证码处理信号已发送"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@browser_login_bp.route(
    "/api/accounts/<int:account_id>/browser-login/qr-scanned",
    methods=["POST"],
)
@require_auth
def qr_scanned(account_id):
    """User signals QR code was scanned."""
    try:
        orch = _get_orchestrator()
        session = orch.get_session_status(account_id)
        if session and session.get("status") == "waiting_qr_scan":
            orch._update_session(
                session["id"], status="verifying",
                message="二维码已扫描，正在确认登录..."
            )
        return jsonify({"message": "扫码确认信号已发送"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@browser_login_bp.route(
    "/api/accounts/<int:account_id>/browser-login/cancel",
    methods=["POST"],
)
@require_auth
def cancel_login(account_id):
    """Cancel an active login session."""
    try:
        orch = _get_orchestrator()
        orch.cancel_session(account_id)
        return jsonify({"message": "登录会话已取消"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@browser_login_bp.route("/api/browser-login/batch", methods=["POST"])
@require_auth
def batch_login():
    """Start login sessions for multiple accounts.

    Body: {
        "account_ids": [1, 2, 3],
        "method": "cookie_import" | "password_login" | "qr_login",
        "cookie_data": {...}  // for cookie_import only, same cookies for all
    }
    """
    try:
        data = request.get_json(force=True) or {}
        account_ids = data.get("account_ids", [])
        method = data.get("method", "cookie_import")
        cookie_data = data.get("cookie_data")

        if not account_ids:
            return jsonify({"error": "account_ids 不能为空"}), 400
        if method not in VALID_METHODS:
            return jsonify({"error": "无效的登录方式"}), 400
        if len(account_ids) > 20:
            return jsonify({"error": "批量登录最多支持20个账号"}), 400

        orch = _get_orchestrator()
        results = []
        for aid in account_ids:
            try:
                r = orch.start_login(aid, method, cookie_data=cookie_data)
                results.append({"account_id": aid, **r})
            except Exception as e:
                results.append({"account_id": aid, "error": str(e)})

        return jsonify({
            "results": results,
            "total": len(results),
            "started": sum(1 for r in results if "session_id" in r),
        }), 202

    except Exception as e:
        logger.exception("batch_login error")
        return jsonify({"error": str(e)}), 500
