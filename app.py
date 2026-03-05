"""Enterprise Content Distribution System — Flask Entry Point."""

import sys
import os
import io

# Force UTF-8 on Windows — PYTHONUTF8 only works before interpreter starts,
# so we also reconfigure stdout/stderr to avoid encoding crashes at runtime.
if sys.platform == "win32":
    os.environ["PYTHONUTF8"] = "1"
    for stream in ("stdout", "stderr"):
        cur = getattr(sys, stream)
        if hasattr(cur, "reconfigure"):
            cur.reconfigure(encoding="utf-8", errors="replace")
        elif cur.encoding != "utf-8":
            setattr(sys, stream, io.TextIOWrapper(
                cur.buffer, encoding="utf-8", errors="replace"))

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, send_from_directory, make_response, jsonify
from flask_cors import CORS

from config import DB_PATH, CORS_ORIGINS, DEBUG_MODE
from models.database import init_database

# Initialize database
init_database(DB_PATH)

# Start background job executor
from config import JOB_EXECUTOR_ENABLED, JOB_EXECUTOR_POLL_INTERVAL
if JOB_EXECUTOR_ENABLED:
    from services.job_executor import JobExecutor
    _job_executor = JobExecutor(
        db_path=DB_PATH,
        poll_interval=JOB_EXECUTOR_POLL_INTERVAL,
    )
    _job_executor.start()

# Create app
app = Flask(__name__, static_folder="static", static_url_path="")
app.json.ensure_ascii = False  # Return Chinese characters directly, not \uXXXX escapes
CORS(app, origins=CORS_ORIGINS)

# Register blueprints
from api.contents import contents_bp
from api.accounts import accounts_bp
from api.policies import policies_bp
from api.jobs import jobs_bp
from api.dashboard import dashboard_bp

app.register_blueprint(contents_bp)
app.register_blueprint(accounts_bp)
app.register_blueprint(policies_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(dashboard_bp)

from api.ai import ai_bp
app.register_blueprint(ai_bp)

from api.credentials import credentials_bp
from api.login_status import login_status_bp
from api.proxies import proxies_bp
from api.account_health import account_health_bp

app.register_blueprint(credentials_bp)
app.register_blueprint(login_status_bp)
app.register_blueprint(proxies_bp)
app.register_blueprint(account_health_bp)

from api.browser_login import browser_login_bp
app.register_blueprint(browser_login_bp)

from api.replies import replies_bp
app.register_blueprint(replies_bp)

from api.browser_pool import browser_pool_bp
app.register_blueprint(browser_pool_bp)

# Start background reply executor
from config import REPLY_EXECUTOR_ENABLED, REPLY_EXECUTOR_POLL_INTERVAL
if REPLY_EXECUTOR_ENABLED:
    from services.reply_executor import ReplyExecutor
    _reply_executor = ReplyExecutor(
        db_path=DB_PATH,
        poll_interval=REPLY_EXECUTOR_POLL_INTERVAL,
    )
    _reply_executor.start()

import logging
logger = logging.getLogger(__name__)

@app.errorhandler(500)
def handle_500(e):
    logger.exception("Internal server error")
    return jsonify({"error": "内部服务器错误"}), 500


@app.route("/")
def index():
    resp = make_response(send_from_directory(app.static_folder, "index.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


def _check_auth_token():
    """Check auth from header or query param (for img src tags)."""
    from flask import request as _req, g
    from api.auth import decode_token
    token = None
    auth_header = _req.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = _req.args.get("token")
    if not token:
        return False
    try:
        payload = decode_token(token)
        g.user_id = payload["user_id"]
        return True
    except Exception:
        return False


@app.route("/api/screenshots/<path:filename>")
def serve_screenshot(filename):
    """Serve screenshot images from the screenshots directory."""
    if not _check_auth_token():
        return jsonify({"error": "需要认证"}), 401
    from config import BROWSER_SCREENSHOT_DIR
    return send_from_directory(BROWSER_SCREENSHOT_DIR, filename)


if __name__ == "__main__":
    app.run(debug=DEBUG_MODE, port=5000)
