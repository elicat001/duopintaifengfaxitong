"""Reply Executor - background daemon that processes auto-reply campaigns and tasks."""

import json
import logging
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from config import (
    DB_PATH, BROWSER_HEADLESS, BROWSER_TIMEOUT_SECONDS,
    BROWSER_MAX_CONCURRENT, BROWSER_SCREENSHOT_DIR, BROWSER_USER_AGENTS,
    REPLY_EXECUTOR_POLL_INTERVAL,
)
from models.database import get_connection
from services.reply_service import (
    ReplyCampaignService, ReplyTaskService, ReplyLogService,
)
from services.platform_repliers.registry import get_replier

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().isoformat()


class ReplyExecutor:
    """Background daemon that polls for reply campaigns and tasks."""

    def __init__(self, db_path: str = None, poll_interval: int = None):
        self.db_path = db_path or DB_PATH
        self.poll_interval = poll_interval or REPLY_EXECUTOR_POLL_INTERVAL
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._browser_svc = None

    def start(self):
        """Start the reply executor daemon thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("ReplyExecutor already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, name="reply-executor", daemon=True
        )
        self._thread.start()
        logger.info("ReplyExecutor started (poll_interval=%ds)", self.poll_interval)

    def stop(self):
        """Signal the executor to stop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=30)
        if self._browser_svc:
            try:
                self._browser_svc.stop()
            except Exception:
                pass
            self._browser_svc = None
        logger.info("ReplyExecutor stopped")

    def _ensure_browser(self):
        """Lazy-init browser pool (shared persistent instance pool)."""
        if self._browser_svc and self._browser_svc.is_running:
            return
        from config import BROWSER_POOL_ENABLED
        if BROWSER_POOL_ENABLED:
            from services.browser_pool import BrowserPool
            from config import (
                BROWSER_HEADLESS, BROWSER_TIMEOUT_SECONDS,
                BROWSER_MAX_CONCURRENT, BROWSER_SCREENSHOT_DIR,
                BROWSER_USER_AGENTS, BROWSER_PROFILE_DIR,
                BROWSER_POOL_MAX_INSTANCES, BROWSER_POOL_IDLE_TIMEOUT,
                BROWSER_POOL_CLEANUP_INTERVAL,
            )
            self._browser_svc = BrowserPool({
                "headless": BROWSER_HEADLESS,
                "timeout": BROWSER_TIMEOUT_SECONDS,
                "max_concurrent": BROWSER_MAX_CONCURRENT,
                "screenshot_dir": BROWSER_SCREENSHOT_DIR,
                "user_agents": BROWSER_USER_AGENTS,
                "profile_base_dir": BROWSER_PROFILE_DIR,
                "max_instances": BROWSER_POOL_MAX_INSTANCES,
                "idle_timeout": BROWSER_POOL_IDLE_TIMEOUT,
                "cleanup_interval": BROWSER_POOL_CLEANUP_INTERVAL,
            })
        else:
            from services.browser_service import BrowserService
            self._browser_svc = BrowserService({
                "headless": BROWSER_HEADLESS,
                "timeout": BROWSER_TIMEOUT_SECONDS,
                "max_concurrent": BROWSER_MAX_CONCURRENT,
                "screenshot_dir": BROWSER_SCREENSHOT_DIR,
                "user_agents": BROWSER_USER_AGENTS,
            })
        self._browser_svc.start()
        logger.info("ReplyExecutor: browser service started")

    def _poll_loop(self):
        """Main polling loop."""
        # Initial delay to let the app fully start
        self._stop_event.wait(timeout=5)

        while not self._stop_event.is_set():
            try:
                self._process_campaigns()
            except Exception:
                logger.exception("Error processing campaigns")

            try:
                self._execute_ready_replies()
            except Exception:
                logger.exception("Error executing replies")

            self._stop_event.wait(timeout=self.poll_interval)

    # ── Campaign Processing ──────────────────────────────────────

    def _process_campaigns(self):
        """Find active campaigns that need processing."""
        campaign_svc = ReplyCampaignService(self.db_path)
        campaigns = campaign_svc.list_all(status="active")

        now = _now()
        for campaign in campaigns:
            # Check if next_run_at has passed
            next_run = campaign.get("next_run_at")
            if next_run and next_run > now:
                continue

            # Check rate limits
            if not self._check_campaign_rate_limits(campaign):
                continue

            try:
                self._run_campaign_cycle(campaign)
            except Exception:
                logger.exception("Campaign #%d cycle failed", campaign["id"])
                campaign_svc.update(campaign["id"], {"error_message": "Campaign cycle failed"})

    def _run_campaign_cycle(self, campaign: dict):
        """Full cycle: discover posts -> generate AI replies -> create tasks."""
        campaign_svc = ReplyCampaignService(self.db_path)
        task_svc = ReplyTaskService(self.db_path)
        log_svc = ReplyLogService(self.db_path)

        account_id = campaign["account_id"]
        platform = campaign["platform"]

        self._ensure_browser()

        # Load account credentials
        from services.credential_service import CredentialService
        from services.crypto_service import CryptoService
        from config import CREDENTIAL_ENCRYPTION_KEY

        crypto = CryptoService(CREDENTIAL_ENCRYPTION_KEY)
        cred_svc = CredentialService(self.db_path, crypto)
        cookies = cred_svc.get_cookies(account_id)

        if not cookies:
            logger.warning("No cookies for account %d, skipping campaign %d",
                           account_id, campaign["id"])
            return

        # Load account info for proxy/fingerprint
        conn = get_connection(self.db_path)
        try:
            account = conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if not account:
                logger.warning("Account %d not found", account_id)
                return
            account = dict(account)
        finally:
            conn.close()

        # Parse proxy and fingerprint
        proxy_config = None
        if account.get("proxy_id"):
            proxy_config = self._get_proxy_config(account["proxy_id"])

        fingerprint = None
        if account.get("fingerprint_config"):
            try:
                fingerprint = json.loads(account["fingerprint_config"])
                if not isinstance(fingerprint, dict) or not fingerprint:
                    fingerprint = None
            except Exception:
                fingerprint = None

        # Create browser context
        self._browser_svc.create_context(account_id, proxy_config, fingerprint)

        try:
            context = self._browser_svc.get_context(account_id)
            home_url = get_replier(platform, self._browser_svc).HOME_URL

            # Inject cookies
            self._browser_svc.inject_cookies(context, cookies, home_url)

            page = self._browser_svc.new_page(account_id)
            replier = get_replier(platform, self._browser_svc)

            try:
                # Warmup browsing
                if campaign.get("warmup_enabled", 1):
                    browse_count = campaign.get("warmup_browse_count", 3)
                    self._browser_svc._run_async(
                        replier.simulate_browsing(page, browse_count)
                    )

                # Discover posts
                keywords = campaign.get("keywords", [])
                if isinstance(keywords, str):
                    try:
                        keywords = json.loads(keywords)
                    except Exception:
                        keywords = [keywords]

                exclude_keywords = campaign.get("exclude_keywords", [])
                if isinstance(exclude_keywords, str):
                    try:
                        exclude_keywords = json.loads(exclude_keywords)
                    except Exception:
                        exclude_keywords = []

                from services.post_discovery_service import PostDiscoveryService
                discovery = PostDiscoveryService(self.db_path)

                posts = self._browser_svc._run_async(
                    discovery.discover_posts(
                        page, replier, keywords,
                        exclude_keywords=exclude_keywords,
                        max_results=campaign.get("target_post_count", 10),
                        account_id=account_id,
                    )
                )

                if not posts:
                    logger.info("Campaign #%d: no new posts found", campaign["id"])
                    campaign_svc.update_next_run(
                        campaign["id"],
                        (datetime.now() + timedelta(minutes=campaign.get("max_interval_minutes", 60))).isoformat()
                    )
                    return

                campaign_svc.increment_counters(campaign["id"], discovered=len(posts))

                # For each post, extract content and generate AI reply
                max_replies = campaign.get("max_replies_per_run", 5)
                tasks_created = 0

                for i, post in enumerate(posts[:max_replies]):
                    if self._stop_event.is_set():
                        break

                    try:
                        # Navigate and extract content
                        navigated = self._browser_svc._run_async(
                            replier.navigate_to_post(page, post.url)
                        )
                        if not navigated:
                            continue

                        post_info = self._browser_svc._run_async(
                            replier.extract_post_content(page)
                        )

                        # Check duplicate
                        if task_svc.check_duplicate(account_id, post.url):
                            continue

                        # Generate AI reply
                        reply_text, alternatives, tokens = self._generate_reply(
                            post_info, campaign
                        )

                        if not reply_text:
                            continue

                        # Calculate scheduled time
                        scheduled_at = self._calculate_scheduled_time(campaign, i)

                        # Create reply task
                        task_id = task_svc.create({
                            "campaign_id": campaign["id"],
                            "account_id": account_id,
                            "platform": platform,
                            "post_url": post.url,
                            "post_author": post_info.author,
                            "post_title": post_info.title,
                            "post_content": post_info.content[:500],
                            "post_media_type": post_info.media_type,
                            "post_likes": post_info.likes,
                            "post_comments": post_info.comments,
                            "reply_content": reply_text,
                            "reply_content_alternatives": alternatives,
                            "selected_alternative": 0,
                            "scheduled_at": scheduled_at,
                            "state": "ready",
                            "ai_tokens_used": tokens,
                        })

                        tasks_created += 1
                        logger.info("Campaign #%d: created task #%d for %s",
                                    campaign["id"], task_id, post.url[:80])

                        # Random delay between discoveries
                        time.sleep(random.uniform(2, 5))

                    except Exception as e:
                        logger.warning("Failed to process post %s: %s", post.url[:80], e)
                        continue

                # Update campaign
                campaign_svc.update(campaign["id"], {"last_run_at": _now()})
                next_interval = random.randint(
                    campaign.get("min_interval_minutes", 15),
                    campaign.get("max_interval_minutes", 60),
                )
                campaign_svc.update_next_run(
                    campaign["id"],
                    (datetime.now() + timedelta(minutes=next_interval)).isoformat()
                )

            finally:
                try:
                    page.close()
                except Exception:
                    pass
        finally:
            self._browser_svc.close_context(account_id)

    # ── Reply Execution ──────────────────────────────────────────

    def _execute_ready_replies(self):
        """Find and execute reply tasks that are ready."""
        task_svc = ReplyTaskService(self.db_path)
        tasks = task_svc.get_next_ready(limit=3)

        for task in tasks:
            if self._stop_event.is_set():
                break

            # Atomic claim
            if not task_svc.transition(task["id"], "executing"):
                continue

            try:
                self._execute_single_reply(task)
            except Exception as e:
                logger.exception("Reply task #%d failed", task["id"])
                self._fail_task(task["id"], "unhandled_error", str(e))

    def _execute_single_reply(self, task: dict):
        """Execute a single reply task."""
        task_svc = ReplyTaskService(self.db_path)
        log_svc = ReplyLogService(self.db_path)

        account_id = task["account_id"]
        platform = task["platform"]
        start_time = time.time()

        self._ensure_browser()

        # Load credentials
        from services.credential_service import CredentialService
        from services.crypto_service import CryptoService
        from config import CREDENTIAL_ENCRYPTION_KEY

        crypto = CryptoService(CREDENTIAL_ENCRYPTION_KEY)
        cred_svc = CredentialService(self.db_path, crypto)
        cookies = cred_svc.get_cookies(account_id)

        if not cookies:
            self._fail_task(task["id"], "no_cookies", "账号无有效Cookie")
            return

        # Load account
        conn = get_connection(self.db_path)
        try:
            account = conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if not account:
                self._fail_task(task["id"], "account_not_found", "账号不存在")
                return
            account = dict(account)
        finally:
            conn.close()

        proxy_config = None
        if account.get("proxy_id"):
            proxy_config = self._get_proxy_config(account["proxy_id"])

        fingerprint = None
        if account.get("fingerprint_config"):
            try:
                fingerprint = json.loads(account["fingerprint_config"])
                if not isinstance(fingerprint, dict) or not fingerprint:
                    fingerprint = None
            except Exception:
                fingerprint = None

        # Create browser context
        self._browser_svc.create_context(account_id, proxy_config, fingerprint)

        try:
            context = self._browser_svc.get_context(account_id)
            replier = get_replier(platform, self._browser_svc)

            # Inject cookies
            self._browser_svc.inject_cookies(context, cookies, replier.HOME_URL)

            page = self._browser_svc.new_page(account_id)

            try:
                browsing_start = time.time()

                # Warmup browsing
                log_svc.add({"reply_task_id": task["id"], "step": "warmup",
                             "message": "开始暖号浏览"})
                self._browser_svc._run_async(
                    replier.simulate_browsing(page, random.randint(1, 3))
                )
                browsing_ms = int((time.time() - browsing_start) * 1000)

                # Navigate to post
                log_svc.add({"reply_task_id": task["id"], "step": "navigate",
                             "message": f"导航到帖子: {task['post_url'][:80]}"})
                navigated = self._browser_svc._run_async(
                    replier.navigate_to_post(page, task["post_url"])
                )
                if not navigated:
                    self._fail_task(task["id"], "navigate_failed", "无法打开帖子页面")
                    return

                # Simulate reading
                reading_start = time.time()
                content_len = len(task.get("post_content", ""))
                read_time = max(5, content_len / 15)
                read_time = min(read_time, 30)
                read_time = random.uniform(read_time * 0.7, read_time * 1.3)

                log_svc.add({"reply_task_id": task["id"], "step": "read",
                             "message": f"模拟阅读 {read_time:.1f}秒"})
                self._browser_svc._run_async(
                    replier.simulate_reading(page, read_time)
                )
                reading_ms = int((time.time() - reading_start) * 1000)

                # Scroll to comments
                log_svc.add({"reply_task_id": task["id"], "step": "scroll",
                             "message": "滚动到评论区"})
                self._browser_svc._run_async(
                    replier.scroll_to_comments(page)
                )

                # Random mouse movements
                self._browser_svc._run_async(
                    replier.random_mouse_movements(page, random.randint(2, 4))
                )

                # Post reply
                typing_start = time.time()
                reply_text = task.get("reply_content", "")

                log_svc.add({"reply_task_id": task["id"], "step": "type",
                             "message": f"开始输入评论: {reply_text[:30]}..."})
                result = self._browser_svc._run_async(
                    replier.post_reply(page, reply_text)
                )
                typing_ms = int((time.time() - typing_start) * 1000)

                total_ms = int((time.time() - start_time) * 1000)

                if result.success:
                    # Transition to verifying then success
                    task_svc.transition(task["id"], "verifying")

                    # Verify
                    verified = self._browser_svc._run_async(
                        replier.verify_reply(page, reply_text)
                    )

                    task_svc.update(task["id"], {
                        "reply_post_url": result.reply_url,
                        "reply_screenshot": result.screenshot_path,
                        "browsing_duration_ms": browsing_ms,
                        "reading_duration_ms": reading_ms,
                        "typing_duration_ms": typing_ms,
                        "total_duration_ms": total_ms,
                    })

                    if verified or result.success:
                        task_svc.transition(task["id"], "success")
                        log_svc.add({
                            "reply_task_id": task["id"], "step": "verify",
                            "status": "ok", "message": "评论成功",
                            "screenshot_path": result.screenshot_path,
                            "duration_ms": total_ms,
                        })

                        # Increment campaign counter
                        if task.get("campaign_id"):
                            ReplyCampaignService(self.db_path).increment_counters(
                                task["campaign_id"], replied=1
                            )
                        logger.info("Reply task #%d succeeded", task["id"])
                    else:
                        self._fail_task(task["id"], "verify_failed", "评论发布后验证失败")
                else:
                    self._fail_task(task["id"], result.error_code, result.error_message)
                    if task.get("campaign_id"):
                        ReplyCampaignService(self.db_path).increment_counters(
                            task["campaign_id"], failed=1
                        )

            finally:
                try:
                    page.close()
                except Exception:
                    pass
        finally:
            self._browser_svc.close_context(account_id)

    # ── AI Reply Generation ──────────────────────────────────────

    def _generate_reply(self, post_info, campaign: dict) -> tuple:
        """Generate AI reply. Returns (reply_text, alternatives_json, tokens_used)."""
        try:
            from services.ai_generation_service import AIGenerationService
            from services.ai_config_service import AIConfigService

            config_svc = AIConfigService(self.db_path)
            ai_config = config_svc.get_by_key(campaign.get("ai_config_key", "default"))

            if not ai_config:
                # Try any enabled config
                configs = config_svc.list_all()
                ai_config = next((c for c in configs if c.get("enabled")), None)

            if not ai_config:
                logger.warning("No AI config available for reply generation")
                return "", "[]", 0

            ai_svc = AIGenerationService(self.db_path)

            platform = campaign.get("platform", "")
            tone = campaign.get("reply_tone", "friendly")
            language = campaign.get("reply_language", "zh")
            max_length = campaign.get("reply_max_length", 200)
            custom = campaign.get("custom_instructions", "")

            tone_map = {
                "friendly": "友善亲切",
                "professional": "专业理性",
                "humorous": "幽默风趣",
                "insightful": "有深度有见解",
            }
            tone_desc = tone_map.get(tone, tone)

            system_prompt = f"""你是一个真实的{platform}用户，正在浏览并留下评论。
评论风格：{tone_desc}
语言：{"中文" if language == "zh" else language}

要求：
- 自然真实，像普通用户评论
- 禁止营销话术、广告语言
- 不@任何人
- 长度不超过{max_length}字
- 可以适当使用emoji但不过多
- 根据帖子内容做有价值的回应（提问、分享经验、表达观点）
- 每条回复风格不同，避免千篇一律
{("额外要求：" + custom) if custom else ""}

请直接输出3个不同风格的评论选项，用 --- 分隔。不要输出编号、引号或其他格式。"""

            user_prompt = f"""请为以下{platform}帖子写评论：

作者：{post_info.author or "未知"}
标题：{post_info.title or "无标题"}
内容：{post_info.content or "无内容"}
点赞数：{post_info.likes}
评论数：{post_info.comments}"""

            if post_info.tags:
                user_prompt += f"\n标签：{', '.join(post_info.tags)}"

            result = ai_svc.call_ai(
                provider=ai_config["provider"],
                model=ai_config["model"],
                api_key=ai_config.get("api_key_encrypted", ""),
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=ai_config.get("max_tokens", 1024),
                temperature=ai_config.get("temperature", 0.8),
                base_url=ai_config.get("base_url", ""),
            )

            content = result.get("content", "")
            tokens = result.get("total_tokens", 0)

            # Parse 3 alternatives
            alternatives = [alt.strip() for alt in content.split("---") if alt.strip()]
            if not alternatives:
                alternatives = [content.strip()]

            # Take first as primary
            reply_text = alternatives[0] if alternatives else ""

            return reply_text, json.dumps(alternatives, ensure_ascii=False), tokens

        except Exception as e:
            logger.error("AI reply generation failed: %s", e)
            return "", "[]", 0

    def _calculate_scheduled_time(self, campaign: dict, index: int) -> str:
        """Calculate when this reply should execute."""
        schedule_type = campaign.get("schedule_type", "immediate")
        min_interval = campaign.get("min_interval_minutes", 15)
        max_interval = campaign.get("max_interval_minutes", 60)

        if schedule_type == "immediate":
            # Space out replies with random intervals
            delay_minutes = index * random.randint(min_interval, max_interval)
            # Add jitter
            jitter_seconds = random.randint(30, 120)
            scheduled = datetime.now() + timedelta(minutes=delay_minutes, seconds=jitter_seconds)
        elif schedule_type in ("scheduled", "recurring"):
            # Find next available slot within schedule windows
            windows = campaign.get("schedule_windows", [])
            if isinstance(windows, str):
                try:
                    windows = json.loads(windows)
                except Exception:
                    windows = []

            if windows:
                scheduled = self._find_next_window_slot(windows, index, min_interval, max_interval)
            else:
                # Fallback to immediate with spacing
                delay_minutes = index * random.randint(min_interval, max_interval)
                scheduled = datetime.now() + timedelta(minutes=delay_minutes)
        else:
            scheduled = datetime.now() + timedelta(minutes=index * min_interval)

        return scheduled.isoformat()

    def _find_next_window_slot(self, windows: list, index: int,
                                min_interval: int, max_interval: int) -> datetime:
        """Find next available time slot within schedule windows."""
        now = datetime.now()
        current_day = now.weekday() + 1  # 1=Monday

        for window in windows:
            days = window.get("days", [1, 2, 3, 4, 5, 6, 7])
            start_str = window.get("start", "09:00")
            end_str = window.get("end", "22:00")

            if current_day not in days:
                continue

            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))

            window_start = now.replace(hour=start_h, minute=start_m, second=0)
            window_end = now.replace(hour=end_h, minute=end_m, second=0)

            base = max(now, window_start)
            if base < window_end:
                delay = index * random.randint(min_interval, max_interval)
                slot = base + timedelta(minutes=delay, seconds=random.randint(30, 120))
                if slot < window_end:
                    return slot

        # Fallback: next day 9:00 + delay
        tomorrow = now + timedelta(days=1)
        base = tomorrow.replace(hour=9, minute=0, second=0)
        delay = index * random.randint(min_interval, max_interval)
        return base + timedelta(minutes=delay)

    # ── Helpers ──────────────────────────────────────────────────

    def _check_campaign_rate_limits(self, campaign: dict) -> bool:
        """Check if account has exceeded hourly/daily reply limits."""
        account_id = campaign["account_id"]
        max_per_hour = campaign.get("max_replies_per_hour", 3)
        max_per_day = campaign.get("max_replies_per_day", 15)

        conn = get_connection(self.db_path)
        try:
            # Check hourly
            hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM reply_tasks
                   WHERE account_id = ? AND state = 'success' AND updated_at >= ?""",
                (account_id, hour_ago)
            ).fetchone()
            if row and row["cnt"] >= max_per_hour:
                return False

            # Check daily
            day_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM reply_tasks
                   WHERE account_id = ? AND state = 'success' AND updated_at >= ?""",
                (account_id, day_start)
            ).fetchone()
            if row and row["cnt"] >= max_per_day:
                return False

            return True
        finally:
            conn.close()

    def _fail_task(self, task_id: int, error_code: str, error_message: str):
        """Mark a task as failed."""
        task_svc = ReplyTaskService(self.db_path)
        log_svc = ReplyLogService(self.db_path)

        task_svc.update(task_id, {
            "last_error_code": error_code,
            "last_error_message": error_message,
        })
        task_svc.transition(task_id, "failed")

        log_svc.add({
            "reply_task_id": task_id,
            "step": "error",
            "status": "error",
            "error_code": error_code,
            "message": error_message,
        })
        logger.warning("Reply task #%d failed: [%s] %s", task_id, error_code, error_message)

    def _get_proxy_config(self, proxy_id: int) -> dict:
        """Load proxy configuration."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM proxies WHERE id = ? AND status = 'active'",
                (proxy_id,)
            ).fetchone()
            if not row:
                return None
            proxy = dict(row)
            return {
                "host": proxy["host"],
                "port": proxy["port"],
                "proxy_type": proxy.get("proxy_type", "http"),
                "username": proxy.get("username", ""),
                "password": proxy.get("password_encrypted", ""),
            }
        finally:
            conn.close()
