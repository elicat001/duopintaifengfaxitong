"""Login orchestrator - coordinates browser login flows across all services."""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from models.database import get_connection

logger = logging.getLogger(__name__)


class LoginOrchestrator:
    """Coordinates browser login flows between BrowserService,
    platform handlers, and all existing services."""

    def __init__(self, db_path, browser_service, credential_service,
                 proxy_service, login_status_service,
                 account_health_service, account_service, crypto_service=None):
        self.db_path = db_path
        self.browser = browser_service
        self.creds = credential_service
        self.proxy = proxy_service
        self.login_status = login_status_service
        self.health = account_health_service
        self.accounts = account_service
        self.crypto = crypto_service
        self._active_sessions: Dict[int, int] = {}  # account_id -> session_id
        self._sessions_lock = threading.Lock()  # Issue 2: protects _active_sessions
        self._db_write_lock = threading.Lock()   # Issue 1: protects _update_session DB writes
        self._proxy_rotation_lock = threading.Lock()  # Issue 3: protects proxy rotation counter
        self._proxy_rotation_index: Dict[int, int] = {}  # group_id -> last used index

    def start_login(self, account_id: int, method: str,
                    cookie_data: dict = None) -> dict:
        """Start a browser login session.

        Args:
            account_id: The account to login
            method: cookie_import | password_login | qr_login
            cookie_data: For cookie_import only, dict with 'cookies' key

        Returns: {session_id, status, message}
        Raises: ValueError, RuntimeError
        """
        # Validate account exists
        account = self.accounts.get(account_id)
        if not account:
            raise ValueError(f"账号 #{account_id} 不存在")

        # Check concurrent limit
        from config import BROWSER_MAX_CONCURRENT
        if self.browser.active_context_count >= BROWSER_MAX_CONCURRENT:
            raise RuntimeError(
                f"已达到最大并发数 ({BROWSER_MAX_CONCURRENT})，请稍后重试"
            )

        # Issue 2: Check if account already has an active session (under lock)
        with self._sessions_lock:
            if account_id in self._active_sessions:
                existing = self._get_session(self._active_sessions[account_id])
                if existing and existing["status"] not in (
                    "success", "failed", "cancelled", "timeout"
                ):
                    raise RuntimeError("该账号已有进行中的登录会话")

            # Create session record
            session_id = self._create_session(
                account_id, method, account.get("platform", "")
            )
            self._active_sessions[account_id] = session_id

        # Launch background thread
        thread = threading.Thread(
            target=self._execute_login,
            args=(session_id, account_id, method, cookie_data),
            daemon=True,
            name=f"login-{account_id}-{session_id}",
        )
        thread.start()

        return {
            "session_id": session_id,
            "status": "pending",
            "message": "登录会话已启动",
        }

    def _execute_login(self, session_id, account_id, method, cookie_data):
        """Run full login flow in background thread."""
        start = time.time()
        proxy_config = None

        try:
            # 1. Update status: launching
            self._update_session(session_id, status="launching",
                                 message="正在准备浏览器...")

            # 2. Load account data
            account = self.accounts.get(account_id)
            platform = account["platform"]
            fingerprint = {}
            fp_str = account.get("fingerprint_config", "{}")
            if fp_str:
                try:
                    fingerprint = json.loads(fp_str) if isinstance(fp_str, str) else fp_str
                except (json.JSONDecodeError, TypeError):
                    fingerprint = {}

            # 3. Load proxy config
            proxy_config = self._get_proxy_for_account(account_id)

            # 4. Create browser context
            self.browser.create_context(
                account_id,
                proxy_config=proxy_config,
                fingerprint=fingerprint,
            )

            # 5. Get platform handler
            from services.platform_logins.registry import get_handler
            handler = get_handler(platform, self.browser)

            # 6. Create new page
            page = self.browser.new_page(account_id)

            # 7. Issue 1: Progress callback is explicitly synchronous.
            #    The async handlers call `await progress_cb(...)`. For this to work
            #    correctly, progress_cb must be an async function. We make it a
            #    proper async def that calls the thread-safe _update_session.
            async def progress_cb(status, message):
                self._update_session(session_id, status=status, message=message)

            # 8. Execute login based on method
            self._update_session(session_id, status="navigating",
                                 message="正在打开登录页面...")

            if method == "cookie_import":
                result = self._do_cookie_import(
                    handler, page, account_id, cookie_data, progress_cb
                )
            elif method == "password_login":
                result = self._do_password_login(
                    handler, page, account_id, progress_cb
                )
            elif method == "qr_login":
                result = self._do_qr_login(
                    handler, page, account_id, progress_cb
                )
            else:
                raise ValueError(f"未知登录方式: {method}")

            # 9. Process result
            duration = int((time.time() - start) * 1000)
            self._process_result(
                session_id, account_id, result, method, duration, proxy_config
            )

        except Exception as e:
            logger.exception("Login failed for account %d: %s", account_id, e)
            duration = int((time.time() - start) * 1000)
            self._update_session(
                session_id, status="failed",
                message=f"登录失败: {str(e)}",
            )
            self.login_status.update_state(
                account_id, "logged_out", reason=str(e)
            )
            self.login_status.record_attempt(
                account_id,
                action=f"browser_{method}",
                status="failure",
                failure_reason=str(e),
                duration_ms=duration,
            )
        finally:
            # 10. Cleanup browser context
            try:
                self.browser.close_context(account_id)
            except Exception:
                pass
            # Issue 2: Remove from active sessions under lock
            with self._sessions_lock:
                self._active_sessions.pop(account_id, None)

    def _do_cookie_import(self, handler, page, account_id, cookie_data, progress_cb):
        """Execute cookie import login."""
        if not cookie_data:
            raise ValueError("cookie_data 不能为空")

        cookies = cookie_data.get("cookies", [])
        if not cookies:
            raise ValueError("cookies 列表为空")

        # Issue 4: Wrap handler call in try/except to ensure LoginResult is always returned
        try:
            return self.browser._run_async(
                handler.cookie_import_flow(page, cookies, progress_cb)
            )
        except Exception as e:
            logger.error("cookie_import_flow raised exception for account %d: %s",
                         account_id, e)
            from services.platform_logins.base import LoginResult
            return LoginResult(
                success=False,
                login_state="logged_out",
                error_message=f"Cookie导入异常: {str(e)}",
            )

    def _do_password_login(self, handler, page, account_id, progress_cb):
        """Execute password login using stored credentials."""
        cred = self.creds.get_primary_for_account(account_id)
        if not cred:
            raise ValueError("未找到该账号的凭证，请先添加账号密码凭证")

        cred_data = cred.get("credential_data", {})
        if isinstance(cred_data, str):
            try:
                cred_data = json.loads(cred_data)
            except json.JSONDecodeError:
                cred_data = {}

        username = cred_data.get("username", "")
        password = cred_data.get("password", "")

        if not username or not password:
            raise ValueError("凭证中缺少 username 或 password 字段")

        # Issue 4: Wrap handler call in try/except to ensure LoginResult is always returned
        try:
            return self.browser._run_async(
                handler.login_with_password(page, username, password, progress_cb)
            )
        except Exception as e:
            logger.error("login_with_password raised exception for account %d: %s",
                         account_id, e)
            from services.platform_logins.base import LoginResult
            return LoginResult(
                success=False,
                login_state="logged_out",
                error_message=f"密码登录异常: {str(e)}",
            )

    def _do_qr_login(self, handler, page, account_id, progress_cb):
        """Execute QR code login."""
        # Issue 4: Wrap handler call in try/except to ensure LoginResult is always returned
        try:
            return self.browser._run_async(
                handler.login_with_qr(page, progress_cb)
            )
        except Exception as e:
            logger.error("login_with_qr raised exception for account %d: %s",
                         account_id, e)
            from services.platform_logins.base import LoginResult
            return LoginResult(
                success=False,
                login_state="logged_out",
                error_message=f"扫码登录异常: {str(e)}",
            )

    def _process_result(self, session_id, account_id, result, method,
                        duration_ms, proxy_config):
        """Update all downstream services based on login result."""
        from services.platform_logins.base import LoginResult

        # Update session
        final_status = "success" if result.success else "failed"
        if result.needs_captcha:
            final_status = "need_captcha"
        elif result.needs_verification:
            final_status = "need_verify"

        self._update_session(
            session_id,
            status=final_status,
            message=result.error_message if not result.success else "登录成功",
            screenshot=result.screenshot_path or result.captcha_screenshot,
            qr_code=result.qr_code_path,
        )

        # Update login state
        self.login_status.update_state(
            account_id, result.login_state,
            reason=result.error_message,
        )

        # Record login attempt
        ip_used = ""
        if proxy_config:
            ip_used = f"{proxy_config.get('host', '')}:{proxy_config.get('port', '')}"

        self.login_status.record_attempt(
            account_id,
            action=f"browser_{method}",
            status="success" if result.success else "failure",
            failure_reason=result.error_message,
            ip_used=ip_used,
            duration_ms=duration_ms,
        )

        # Record proxy usage
        if proxy_config and proxy_config.get("proxy_id"):
            try:
                self.proxy.record_usage(
                    proxy_config["proxy_id"],
                    success=result.success,
                    latency_ms=duration_ms,
                )
            except Exception as e:
                logger.warning("Failed to record proxy usage: %s", e)

        # If successful, save extracted cookies
        if result.success and result.cookies:
            try:
                self.creds.create(
                    account_id=account_id,
                    credential_type="cookie",
                    credential_data={
                        "cookies": result.cookies,
                        "source": f"browser_{method}",
                        "extracted_at": datetime.now().isoformat(),
                    },
                    notes=f"浏览器{method}自动提取",
                )
            except Exception as e:
                logger.warning("Failed to save extracted cookies: %s", e)

            # Update cookie timestamp
            try:
                self.accounts.update(account_id, {
                    "cookie_updated_at": datetime.now().isoformat(),
                })
            except Exception as e:
                logger.warning("Failed to update cookie timestamp: %s", e)

        # Recompute risk score
        try:
            self.health.compute_risk_score(account_id)
        except Exception as e:
            logger.warning("Failed to recompute risk score: %s", e)

    def get_session_status(self, account_id: int) -> Optional[dict]:
        """Get the most recent login session for an account."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """SELECT * FROM browser_login_sessions
                   WHERE account_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (account_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_session_by_id(self, session_id: int) -> Optional[dict]:
        """Get a specific session by ID."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM browser_login_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def cancel_session(self, account_id: int):
        """Cancel an active login session."""
        # Issue 2: Access _active_sessions under lock
        with self._sessions_lock:
            session_id = self._active_sessions.get(account_id)
        if session_id:
            self._update_session(session_id, status="cancelled",
                                 message="用户取消")
            try:
                self.browser.close_context(account_id)
            except Exception:
                pass
            with self._sessions_lock:
                self._active_sessions.pop(account_id, None)

    def _get_proxy_for_account(self, account_id: int) -> Optional[dict]:
        """Load proxy config including decrypted password.

        Issue 3: Supports proxy group rotation. If the assignment is to a
        proxy group (not a direct proxy), rotates through active proxies in the
        group using round-robin based on fewest total_requests.

        Issue 5: Logs a warning when proxy password decryption fails.
        """
        assignment = self.proxy.get_assignment(account_id)
        if not assignment:
            return None

        proxy_id = assignment.get("proxy_id")
        proxy_group_id = assignment.get("proxy_group_id")
        assignment_type = assignment.get("assignment_type", "direct")

        # Issue 3: If assignment is to a group (not direct), rotate through
        # active proxies in the group instead of using the single assigned proxy.
        if assignment_type == "group" and proxy_group_id:
            proxy_id = self._rotate_proxy_in_group(proxy_group_id)
            if not proxy_id:
                logger.warning(
                    "No active proxies in group %d for account %d",
                    proxy_group_id, account_id,
                )
                return None
        elif not proxy_id:
            # No direct proxy and no group -- try group-based rotation as fallback
            if proxy_group_id:
                proxy_id = self._rotate_proxy_in_group(proxy_group_id)
                if not proxy_id:
                    logger.warning(
                        "No active proxies in group %d for account %d",
                        proxy_group_id, account_id,
                    )
                    return None
            else:
                return None

        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM proxies WHERE id = ? AND status = 'active'",
                (proxy_id,),
            ).fetchone()
            if not row:
                # Fallback: try without status filter in case proxy is usable
                row = conn.execute(
                    "SELECT * FROM proxies WHERE id = ?", (proxy_id,)
                ).fetchone()
                if not row:
                    return None

            proxy = dict(row)
            # Issue 5: Decrypt password if present, log warning on failure
            if proxy.get("password_encrypted") and self.crypto:
                try:
                    proxy["password"] = self.crypto.decrypt(
                        proxy["password_encrypted"]
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to decrypt proxy password for proxy %d "
                        "(account %d): %s. Proceeding without password.",
                        proxy_id, account_id, e,
                    )
                    proxy["password"] = ""
            else:
                proxy["password"] = ""

            proxy["proxy_id"] = proxy_id
            return proxy
        finally:
            conn.close()

    def _rotate_proxy_in_group(self, proxy_group_id: int) -> Optional[int]:
        """Issue 3: Select next proxy from a group using round-robin rotation.

        Queries all active proxies in the group, then picks the one with the
        fewest total_requests (least-used round-robin). This ensures fair
        distribution across proxies in the same group.

        Returns the proxy ID, or None if no active proxies exist.
        """
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """SELECT id, total_requests
                   FROM proxies
                   WHERE proxy_group_id = ? AND status = 'active'
                   ORDER BY total_requests ASC, id ASC""",
                (proxy_group_id,),
            ).fetchall()
            if not rows:
                return None

            proxies = [dict(r) for r in rows]

            # Round-robin via rotation index within the group
            with self._proxy_rotation_lock:
                last_index = self._proxy_rotation_index.get(proxy_group_id, -1)
                next_index = (last_index + 1) % len(proxies)
                self._proxy_rotation_index[proxy_group_id] = next_index

            chosen = proxies[next_index]
            logger.debug(
                "Rotated to proxy %d (index %d/%d) in group %d",
                chosen["id"], next_index, len(proxies), proxy_group_id,
            )
            return chosen["id"]
        finally:
            conn.close()

    def _create_session(self, account_id: int, method: str,
                        platform: str = "") -> int:
        """Create a new browser_login_sessions record."""
        conn = get_connection(self.db_path)
        try:
            now = datetime.now().isoformat()
            cursor = conn.execute(
                """INSERT INTO browser_login_sessions
                   (account_id, login_method, status, platform,
                    started_at, created_at, updated_at)
                   VALUES (?, ?, 'pending', ?, ?, ?, ?)""",
                (account_id, method, platform, now, now, now),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def _get_session(self, session_id: int) -> Optional[dict]:
        """Get session by ID."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM browser_login_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def _update_session(self, session_id: int, status: str = None,
                        message: str = None, screenshot: str = None,
                        qr_code: str = None):
        """Update session fields.

        Issue 1: This method is explicitly synchronous and thread-safe.
        It is called from background login threads and from the progress
        callback (which is an async def that calls this sync method).
        The _db_write_lock ensures serialized DB writes.
        """
        # Issue 1: Serialize DB writes with a threading lock
        with self._db_write_lock:
            conn = get_connection(self.db_path)
            try:
                updates = []
                params = []
                now = datetime.now().isoformat()

                if status:
                    updates.append("status = ?")
                    params.append(status)
                if message is not None:
                    updates.append("progress_message = ?")
                    params.append(message)
                if screenshot:
                    updates.append("screenshot_path = ?")
                    params.append(screenshot)
                if qr_code:
                    updates.append("qr_code_path = ?")
                    params.append(qr_code)

                # Set completed_at on terminal statuses
                if status in ("success", "failed", "cancelled", "timeout"):
                    updates.append("completed_at = ?")
                    params.append(now)

                updates.append("updated_at = ?")
                params.append(now)

                if updates:
                    params.append(session_id)
                    conn.execute(
                        f"UPDATE browser_login_sessions SET {', '.join(updates)} WHERE id = ?",
                        params,
                    )
                    conn.commit()
            finally:
                conn.close()
