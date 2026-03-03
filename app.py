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


if __name__ == "__main__":
    app.run(debug=DEBUG_MODE, port=5000)
