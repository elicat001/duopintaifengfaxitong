from datetime import datetime
from enum import Enum
from pydantic import BaseModel
from typing import Optional, List, Any, Union


# ── Enums ────────────────────────────────────────────────────────────────

class Platform(str, Enum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    TWITTER = "twitter"
    FACEBOOK = "facebook"
    XIAOHONGSHU = "xiaohongshu"
    WEIBO = "weibo"
    BILIBILI = "bilibili"


class AccountStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    BANNED = "banned"
    WARMING = "warming"
    LOGIN_EXPIRED = "login_expired"
    NEED_VERIFY = "need_verify"
    RATE_LIMITED = "rate_limited"
    COOLDOWN = "cooldown"
    DISABLED = "disabled"


class ContentType(str, Enum):
    IMAGE_SINGLE = "image_single"
    IMAGE_CAROUSEL = "image_carousel"
    VIDEO = "video"


class ContentStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETIRED = "retired"
    ARCHIVED = "archived"


class AssetType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class VariantStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"


class PolicyScope(str, Enum):
    GROUP = "group"
    ACCOUNT = "account"


class JobState(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    PREPARING = "preparing"
    PUBLISHING = "publishing"
    VERIFYING = "verifying"
    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    NEEDS_REVIEW = "needs_review"
    FAILED_FINAL = "failed_final"
    CANCELLED = "cancelled"
    ACCOUNT_PAUSED = "account_paused"


class JobLogStep(str, Enum):
    PREPARE = "prepare"
    PUBLISH = "publish"
    VERIFY = "verify"
    METRICS = "metrics"


class JobLogStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


class LoginState(str, Enum):
    LOGGED_IN = "logged_in"
    LOGGED_OUT = "logged_out"
    EXPIRED = "expired"
    NEED_CAPTCHA = "need_captcha"
    NEED_VERIFY = "need_verify"
    BANNED = "banned"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class CredentialType(str, Enum):
    COOKIE = "cookie"


class ProxyType(str, Enum):
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


class ProxyStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    TESTING = "testing"


class RotationStrategy(str, Enum):
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"
    STICKY = "sticky"
    GEO_MATCH = "geo_match"


class AssignmentType(str, Enum):
    DIRECT = "direct"
    POOL = "pool"


class Frequency(str, Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    PAUSED = "paused"


# ── Models ───────────────────────────────────────────────────────────────

class AccountGroup(BaseModel):
    id: Optional[int] = None
    name: str
    description: str = ""


class Account(BaseModel):
    id: Optional[int] = None
    platform: Platform
    handle: str
    display_name: str = ""
    group_id: Optional[int] = None
    status: AccountStatus = AccountStatus.ACTIVE
    daily_limit: int = 10
    hourly_limit: int = 3
    last_success_at: Optional[str] = None
    executor_account_ref: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Content(BaseModel):
    id: Optional[int] = None
    title: str
    topic: str = ""
    language: str = "zh"
    content_type: ContentType = ContentType.IMAGE_SINGLE
    status: ContentStatus = ContentStatus.DRAFT
    tags: Optional[List[str]] = None
    copyright_flags: Optional[dict] = None
    dedupe_hash: str = ""
    created_by: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Asset(BaseModel):
    id: Optional[int] = None
    asset_type: AssetType = AssetType.IMAGE
    storage_url: str = ""
    sha256: str = ""
    width: int = 0
    height: int = 0
    duration_sec: Optional[float] = None
    filesize_bytes: int = 0
    meta: Optional[dict] = None
    created_at: Optional[str] = None


class Variant(BaseModel):
    id: Optional[int] = None
    content_id: int
    platform: Optional[str] = None
    caption: str = ""
    headline: str = ""
    hashtags: Optional[List[str]] = None
    cover_asset_id: Optional[int] = None
    media_asset_ids: Optional[List[int]] = None
    variant_fingerprint: str = ""
    status: VariantStatus = VariantStatus.READY
    created_at: Optional[str] = None


class Policy(BaseModel):
    id: Optional[int] = None
    name: str
    scope_type: PolicyScope = PolicyScope.GROUP
    scope_id: str = ""
    platform: Platform = Platform.INSTAGRAM
    posting_windows: Optional[List[dict]] = None
    max_per_day: int = 10
    max_per_hour: int = 3
    min_interval_minutes: int = 30
    min_stagger_minutes: int = 5
    cooldown_days: int = 7
    topic_mix: Optional[dict] = None
    enabled: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Job(BaseModel):
    id: Optional[int] = None
    account_id: int
    content_id: int
    variant_id: Optional[int] = None
    scheduled_at: Optional[str] = None
    state: JobState = JobState.DRAFT
    attempt_count: int = 0
    max_attempts: int = 5
    next_run_at: Optional[str] = None
    platform_post_id: str = ""
    platform_post_url: str = ""
    idempotency_key: str = ""
    last_error_code: str = ""
    last_error_message: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class JobLog(BaseModel):
    id: Optional[int] = None
    job_id: int
    step: JobLogStep = JobLogStep.PUBLISH
    status: JobLogStatus = JobLogStatus.OK
    error_code: str = ""
    message: str = ""
    raw: Optional[dict] = None
    created_at: Optional[str] = None


class Metric(BaseModel):
    id: Optional[int] = None
    job_id: int
    platform_post_id: str = ""
    captured_at: Optional[str] = None
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    extra: Optional[dict] = None


class AccountCredential(BaseModel):
    id: Optional[int] = None
    account_id: int
    credential_type: CredentialType = CredentialType.COOKIE
    credential_data_encrypted: str = ""
    is_active: bool = True
    expires_at: Optional[str] = None
    last_refreshed_at: Optional[str] = None
    last_validated_at: Optional[str] = None
    validation_status: str = "unknown"
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AccountLoginStatus(BaseModel):
    id: Optional[int] = None
    account_id: int
    login_state: LoginState = LoginState.UNKNOWN
    health_score: float = 0.0
    consecutive_failures: int = 0
    total_login_attempts: int = 0
    total_login_successes: int = 0
    last_login_at: Optional[str] = None
    last_login_check_at: Optional[str] = None
    last_failure_reason: str = ""
    last_state_change_at: Optional[str] = None
    check_interval_minutes: int = 30
    alert_sent: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class LoginLog(BaseModel):
    id: Optional[int] = None
    account_id: int
    action: str = "login_check"
    status: str = "success"
    previous_state: str = ""
    new_state: str = ""
    failure_reason: str = ""
    ip_used: str = ""
    response_code: Optional[int] = None
    response_snippet: str = ""
    duration_ms: int = 0
    created_at: Optional[str] = None


class ProxyGroup(BaseModel):
    id: Optional[int] = None
    name: str
    description: str = ""
    rotation_strategy: RotationStrategy = RotationStrategy.ROUND_ROBIN
    created_at: Optional[str] = None


class Proxy(BaseModel):
    id: Optional[int] = None
    name: str = ""
    proxy_type: ProxyType = ProxyType.HTTP
    host: str
    port: int
    username: str = ""
    password_encrypted: str = ""
    proxy_group_id: Optional[int] = None
    region: str = ""
    provider: str = ""
    status: ProxyStatus = ProxyStatus.ACTIVE
    is_sticky: bool = False
    avg_latency_ms: float = 0.0
    success_rate: float = 100.0
    total_requests: int = 0
    total_failures: int = 0
    last_check_at: Optional[str] = None
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_failure_reason: str = ""
    bandwidth_used_mb: float = 0.0
    max_bandwidth_mb: float = 0.0
    notes: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AccountProxyAssignment(BaseModel):
    id: Optional[int] = None
    account_id: int
    proxy_id: Optional[int] = None
    proxy_group_id: Optional[int] = None
    assignment_type: AssignmentType = AssignmentType.DIRECT
    is_active: bool = True
    last_rotation_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── Agent Models ─────────────────────────────────────────────────────────


class ContentItem(BaseModel):
    """Used by content_manager agent for CRUD operations."""
    id: Optional[int] = None
    title: str
    body: str = ""
    content_type: str = "image_single"
    status: ContentStatus = ContentStatus.DRAFT
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PerformanceRecord(BaseModel):
    """Used by performance_tracker and scoring_engine agents."""
    id: Optional[int] = None
    content_id: int
    likes: int = 0
    comments: int = 0
    shares: int = 0
    views: int = 0
    recorded_at: Optional[Union[str, datetime]] = None


class ScoreResult(BaseModel):
    """Output of scoring_engine.evaluate_content()."""
    content_id: int
    score: float = 0.0
    recommended_frequency: Frequency = Frequency.NORMAL


class SchedulePlan(BaseModel):
    """Used by scheduler agent for publish scheduling."""
    id: Optional[int] = None
    content_id: int
    score: float = 0.0
    frequency: Frequency = Frequency.NORMAL
    next_publish_at: Optional[str] = None
    last_published_at: Optional[str] = None
    publish_count: int = 0
    updated_at: Optional[str] = None
