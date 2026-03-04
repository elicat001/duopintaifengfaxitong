"""Background job executor.

Polls for queued jobs and processes them through the state machine:
  queued -> preparing -> publishing -> verifying -> success
Runs as a daemon thread started from app.py.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class JobExecutor:
    """Background job executor that processes queued publishing jobs."""

    def __init__(self, db_path: str, poll_interval: int = 10):
        self.db_path = db_path
        self.poll_interval = poll_interval
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._browser_svc = None

    def start(self):
        """Start the executor daemon thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("JobExecutor already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="job-executor",
        )
        self._thread.start()
        logger.info("JobExecutor started (poll_interval=%ds)", self.poll_interval)

    def stop(self):
        """Signal the executor to stop."""
        self._stop_event.set()
        if self._browser_svc:
            self._browser_svc.stop()
            self._browser_svc = None
        logger.info("JobExecutor stopped")

    def _ensure_browser(self):
        """Lazy-init the browser service (non-headless for visibility)."""
        if self._browser_svc and self._browser_svc.is_running:
            return
        from config import (
            BROWSER_HEADLESS, BROWSER_TIMEOUT_SECONDS, BROWSER_MAX_CONCURRENT,
            BROWSER_SCREENSHOT_DIR, BROWSER_USER_AGENTS,
        )
        from services.browser_service import BrowserService
        self._browser_svc = BrowserService({
            "headless": BROWSER_HEADLESS,
            "timeout": BROWSER_TIMEOUT_SECONDS,
            "max_concurrent": BROWSER_MAX_CONCURRENT,
            "screenshot_dir": BROWSER_SCREENSHOT_DIR,
            "user_agents": BROWSER_USER_AGENTS,
        })
        self._browser_svc.start()

    def _poll_loop(self):
        """Main polling loop."""
        while not self._stop_event.is_set():
            try:
                self._process_next_job()
            except Exception:
                logger.exception("Unexpected error in executor poll loop")
            self._stop_event.wait(timeout=self.poll_interval)

    def _process_next_job(self):
        """Pick up one queued job and process it.

        Uses atomic transition queued->preparing as a lease to prevent
        multiple executors from processing the same job.
        """
        from services.job_service import JobService
        job_svc = JobService(self.db_path)
        jobs = job_svc.list_all(state="queued", limit=5)
        if not jobs:
            return

        # Try to acquire lease on first available job
        job = None
        for candidate in jobs:
            if job_svc.transition(candidate["id"], "preparing"):
                job = candidate
                break
        if not job:
            return  # All candidates already claimed

        logger.info("Processing job #%d (lease acquired)", job["id"])
        try:
            self._execute_job(job)
        except Exception as e:
            logger.exception("Job #%d failed with unhandled exception", job["id"])
            self._fail_job(job["id"], "unhandled_error", str(e))

    def _execute_job(self, job: dict):
        """Full execution flow for a single job."""
        from config import CREDENTIAL_ENCRYPTION_KEY, UPLOAD_DIR
        from services.job_service import JobService, JobLogService
        from services.account_service import AccountService
        from services.content_service import ContentService, VariantService, AssetService
        from services.credential_service import CredentialService
        from services.crypto_service import CryptoService
        from services.proxy_service import ProxyService
        from services.platform_publishers.registry import get_publisher

        job_id = job["id"]
        account_id = job["account_id"]
        content_id = job["content_id"]
        variant_id = job.get("variant_id")

        job_svc = JobService(self.db_path)
        log_svc = JobLogService(self.db_path)
        account_svc = AccountService(self.db_path)
        content_svc = ContentService(self.db_path)
        variant_svc = VariantService(self.db_path)
        asset_svc = AssetService(self.db_path)
        crypto = CryptoService(CREDENTIAL_ENCRYPTION_KEY)
        cred_svc = CredentialService(self.db_path, crypto)
        proxy_svc = ProxyService(self.db_path)

        # === PHASE 1: already in preparing (lease acquired in _process_next_job) ===
        log_svc.add({"job_id": job_id, "step": "prepare", "status": "ok",
                      "message": "开始准备发布"})

        # Load account
        account = account_svc.get(account_id)
        if not account:
            self._fail_job(job_id, "account_not_found", f"账号 #{account_id} 不存在")
            return
        if account.get("status") != "active":
            job_svc.transition(job_id, "failed_retryable")
            log_svc.add({"job_id": job_id, "step": "prepare", "status": "error",
                          "error_code": "account_inactive",
                          "message": f"账号状态: {account.get('status')}"})
            return

        platform = account["platform"]

        # Rate limit check
        if not self._check_rate_limits(account_id, account):
            job_svc.transition(job_id, "failed_retryable")
            log_svc.add({"job_id": job_id, "step": "prepare", "status": "error",
                          "error_code": "rate_limited",
                          "message": "超出账号发布频率限制"})
            return

        # Load cookies
        cookies = cred_svc.get_cookies(account_id)
        if not cookies:
            self._fail_job(job_id, "no_cookies",
                           "账号没有有效的Cookie，请先登录")
            return

        # Load content
        content = content_svc.get(content_id)
        if not content:
            self._fail_job(job_id, "content_not_found",
                           f"内容 #{content_id} 不存在")
            return

        # Load variant
        variant = None
        if variant_id:
            variant = variant_svc.get(variant_id)

        # Resolve media paths
        media_paths = []
        asset_ids = []
        if variant and variant.get("media_asset_ids"):
            asset_ids = variant["media_asset_ids"]
            if isinstance(asset_ids, str):
                try:
                    asset_ids = json.loads(asset_ids)
                except Exception:
                    asset_ids = []
        for aid in asset_ids:
            asset = asset_svc.get(aid)
            if asset and asset.get("storage_url"):
                url = asset["storage_url"]
                if not os.path.isabs(url):
                    url = os.path.join(UPLOAD_DIR, url)
                if os.path.exists(url):
                    media_paths.append(url)

        # Proxy config
        proxy_config = None
        try:
            assignment = proxy_svc.get_assignment(account_id)
            if assignment and assignment.get("host"):
                proxy_config = {
                    "host": assignment["host"],
                    "port": assignment["port"],
                    "proxy_type": assignment.get("proxy_type", "http"),
                    "username": assignment.get("username", ""),
                    "password": assignment.get("password", ""),
                }
        except Exception:
            pass

        # Fingerprint
        fingerprint = None
        fp_raw = account.get("fingerprint_config")
        if fp_raw:
            if isinstance(fp_raw, str):
                try:
                    fingerprint = json.loads(fp_raw)
                except Exception:
                    pass
            elif isinstance(fp_raw, dict):
                fingerprint = fp_raw

        # Get publisher
        try:
            publisher = get_publisher(platform, self._browser_svc)
        except ValueError as e:
            self._fail_job(job_id, "unsupported_platform", str(e))
            return

        log_svc.add({"job_id": job_id, "step": "prepare", "status": "ok",
                      "message": f"准备完成: platform={platform}, media={len(media_paths)}个文件"})

        # === PHASE 2: preparing -> publishing ===
        if not job_svc.transition(job_id, "publishing"):
            logger.error("Job #%d: cannot transition to publishing", job_id)
            return

        self._ensure_browser()

        try:
            self._browser_svc.create_context(
                account_id, proxy_config=proxy_config, fingerprint=fingerprint
            )
            context = self._browser_svc.get_context(account_id)
            publish_url = publisher.PUBLISH_URL or publisher.HOME_URL
            self._browser_svc.inject_cookies(context, cookies, publish_url)
            page = self._browser_svc.new_page(account_id)

            result = self._browser_svc._run_async(
                publisher.publish(page, content, variant, media_paths)
            )

            log_svc.add({
                "job_id": job_id, "step": "publish",
                "status": "ok" if result.success else "error",
                "error_code": result.error_code,
                "message": result.error_message or "发布完成",
                "raw": {
                    "platform_post_id": result.platform_post_id,
                    "platform_post_url": result.platform_post_url,
                    "screenshot": result.screenshot_path,
                    "duration_ms": result.duration_ms,
                    "steps": result.steps or [],
                },
            })
        except Exception as e:
            logger.exception("Job #%d: browser error during publishing", job_id)
            self._fail_job(job_id, "browser_error", str(e))
            self._cleanup_context(account_id)
            return

        # === PHASE 3: publishing -> verifying -> success ===
        if result.success:
            if not job_svc.transition(job_id, "verifying"):
                self._cleanup_context(account_id)
                return

            # Update post info
            self._update_post_info(job_id, result.platform_post_id,
                                    result.platform_post_url)

            try:
                verified = self._browser_svc._run_async(
                    publisher.verify_published(page)
                )
            except Exception:
                verified = False

            if verified:
                job_svc.transition(job_id, "success")
                log_svc.add({"job_id": job_id, "step": "verify",
                              "status": "ok", "message": "发布验证成功"})
            else:
                # Could not verify — mark as needs_review rather than failing
                job_svc.transition(job_id, "needs_review")
                log_svc.add({"job_id": job_id, "step": "verify",
                              "status": "ok",
                              "message": "发布已提交，验证结果不确定"})
        else:
            job_svc.transition(job_id, "failed_retryable")

        self._cleanup_context(account_id)

    def _check_rate_limits(self, account_id: int, account: dict) -> bool:
        """Check if account is within daily and hourly limits."""
        from models.database import get_connection

        daily_limit = account.get("daily_limit", 10)
        hourly_limit = account.get("hourly_limit", 3)
        conn = get_connection(self.db_path)
        try:
            now = datetime.now()
            day_start = now.replace(hour=0, minute=0, second=0).isoformat()
            hour_start = (now - timedelta(hours=1)).isoformat()

            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE account_id = ? AND state = 'success' AND updated_at >= ?",
                (account_id, day_start),
            ).fetchone()
            if row and row["cnt"] >= daily_limit:
                return False

            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE account_id = ? AND state = 'success' AND updated_at >= ?",
                (account_id, hour_start),
            ).fetchone()
            if row and row["cnt"] >= hourly_limit:
                return False

            return True
        finally:
            conn.close()

    def _update_post_info(self, job_id: int, post_id: str, post_url: str):
        from models.database import get_connection
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                "UPDATE jobs SET platform_post_id = ?, platform_post_url = ?, updated_at = ? WHERE id = ?",
                (post_id or "", post_url or "", datetime.now().isoformat(), job_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _fail_job(self, job_id: int, error_code: str, error_message: str):
        from services.job_service import JobService, JobLogService
        from models.database import get_connection

        job_svc = JobService(self.db_path)
        log_svc = JobLogService(self.db_path)

        job_svc.transition(job_id, "failed_retryable")
        log_svc.add({
            "job_id": job_id, "step": "publish", "status": "error",
            "error_code": error_code, "message": error_message,
        })
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                "UPDATE jobs SET last_error_code = ?, last_error_message = ?, updated_at = ? WHERE id = ?",
                (error_code, error_message, datetime.now().isoformat(), job_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _cleanup_context(self, account_id: int):
        try:
            if self._browser_svc:
                self._browser_svc.close_context(account_id)
        except Exception:
            pass
