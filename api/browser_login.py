"""Simplified Browser Login API.

Flow: start (open browser) → user logs in manually → complete (save cookies).
"""

import logging
from flask import Blueprint, jsonify
from api.auth import require_auth

logger = logging.getLogger(__name__)

browser_login_bp = Blueprint("browser_login", __name__)

# Lazy-initialized orchestrator
_orchestrator = None
_init_lock = __import__("threading").Lock()


def _get_orchestrator():
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
        from services.login_status_service import LoginStatusService
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
            login_status_service=LoginStatusService(DB_PATH),
            account_service=AccountService(DB_PATH),
        )
        return _orchestrator


@browser_login_bp.route(
    "/api/accounts/<int:account_id>/browser-login/start", methods=["POST"]
)
@require_auth
def start_browser_login(account_id):
    """Open a browser window to the platform's login page.

    The user logs in manually in the browser window.
    Returns 202: {session_id, status, message, login_url}
    """
    try:
        orch = _get_orchestrator()
        result = orch.open_browser(account_id)
        return jsonify(result), 202
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 429
    except Exception as e:
        logger.exception("start_browser_login error")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@browser_login_bp.route(
    "/api/accounts/<int:account_id>/browser-login/complete", methods=["POST"]
)
@require_auth
def complete_browser_login(account_id):
    """Extract cookies from the open browser and save them.

    Call this after the user has finished logging in manually.
    Returns: {success, message, cookie_count}
    """
    try:
        orch = _get_orchestrator()
        result = orch.complete_login(account_id)
        status_code = 200 if result["success"] else 400
        return jsonify(result), status_code
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("complete_browser_login error")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@browser_login_bp.route(
    "/api/accounts/<int:account_id>/browser-login/cancel", methods=["POST"]
)
@require_auth
def cancel_browser_login(account_id):
    """Cancel and close the browser window."""
    try:
        orch = _get_orchestrator()
        orch.cancel_login(account_id)
        return jsonify({"message": "已关闭浏览器窗口"}), 200
    except Exception as e:
        logger.exception("cancel_browser_login error")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500
