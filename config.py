import os
import logging
import secrets

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)

# Database
DB_PATH = os.path.join(BASE_DIR, "data", "scheduler.db")

# Uploads
UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads")

# JWT — MUST set JWT_SECRET env var in production
_jwt_default = "dev-secret-change-in-production"
JWT_SECRET = os.environ.get("JWT_SECRET", _jwt_default)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

# Admin credentials — MUST set in production
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

# CORS — defaults to localhost only; set CORS_ORIGINS env var for production
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000").split(",")

# Debug mode — defaults to false in production
DEBUG_MODE = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

# ── Startup security warnings ─────────────────────────────────────────
if JWT_SECRET == _jwt_default:
    logger.warning("JWT_SECRET is using insecure default! Set JWT_SECRET env var in production.")
if ADMIN_PASSWORD == "admin":
    logger.warning("ADMIN_PASSWORD is using default 'admin'! Set ADMIN_PASSWORD env var in production.")

# Scoring weights
SCORE_WEIGHTS = {
    "likes": 1.0,
    "comments": 3.0,
    "shares": 5.0,
    "views": 0.1,
}

SCORE_THRESHOLDS = {
    "high": 80.0,
    "normal": 40.0,
    "low": 15.0,
}

# Scheduling
SCHEDULE_INTERVAL_SECONDS = 3600

# AI defaults
AI_DEFAULT_PROVIDER = "anthropic"
AI_DEFAULT_MODEL = "claude-sonnet-4-20250514"
AI_MAX_DAILY_GENERATIONS = 50
AI_MAX_DAILY_TOKENS = 500000
AI_TREND_SCAN_INTERVAL_HOURS = 6

# RSS trend sources (geo=CN returns 400, use TW/HK for Chinese trends)
DEFAULT_RSS_FEEDS = [
    "https://trends.google.com/trending/rss?geo=US",
    "https://trends.google.com/trending/rss?geo=TW",
    "https://trends.google.com/trending/rss?geo=JP",
]

# Encryption — separate from JWT_SECRET; auto-generates if not set
_credential_key_default = os.environ.get("CREDENTIAL_KEY", "")
if not _credential_key_default:
    _credential_key_default = JWT_SECRET  # fallback for backward compat
    logger.warning("CREDENTIAL_KEY not set, falling back to JWT_SECRET. Set a separate CREDENTIAL_KEY env var.")
CREDENTIAL_ENCRYPTION_KEY = _credential_key_default

# Proxy defaults
PROXY_CHECK_INTERVAL_MINUTES = 15
PROXY_CHECK_TIMEOUT_SECONDS = 10
PROXY_CHECK_URL = "https://httpbin.org/ip"

# Login check defaults
LOGIN_CHECK_INTERVAL_MINUTES = 30
LOGIN_CHECK_BATCH_SIZE = 10

# Risk score thresholds
RISK_SCORE_HIGH = 70.0
RISK_SCORE_MEDIUM = 40.0

# Warming workflow
WARMING_STAGES = {
    1: {"daily_limit": 2, "hourly_limit": 1, "duration_days": 3},
    2: {"daily_limit": 4, "hourly_limit": 2, "duration_days": 3},
    3: {"daily_limit": 6, "hourly_limit": 2, "duration_days": 5},
    4: {"daily_limit": 8, "hourly_limit": 3, "duration_days": 5},
    5: {"daily_limit": 10, "hourly_limit": 3, "duration_days": 7},
}

# Browser automation
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "false").lower() == "true"
BROWSER_TIMEOUT_SECONDS = int(os.environ.get("BROWSER_TIMEOUT_SECONDS", "60"))
BROWSER_MAX_CONCURRENT = int(os.environ.get("BROWSER_MAX_CONCURRENT", "3"))
BROWSER_SCREENSHOT_DIR = os.path.join(BASE_DIR, "data", "screenshots")
BROWSER_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]
