"""Simplified login orchestrator.

Flow: open browser (non-headless) → user logs in manually → extract & save cookies.
"""

import logging
import threading
from datetime import datetime
from typing import Dict, Optional

from models.database import get_connection

logger = logging.getLogger(__name__)


class LoginOrchestrator:
    """Coordinates browser login: open page, wait for user, save cookies."""

    def __init__(self, db_path, browser_service, credential_service,
                 login_status_service, account_service):
        self.db_path = db_path
        self.browser = browser_service
        self.creds = credential_service
        self.login_status = login_status_service
        self.accounts = account_service
        self._active_sessions: Dict[int, dict] = {}  # account_id -> session info
        self._lock = threading.Lock()

    def open_browser(self, account_id: int) -> dict:
        """Open a browser window to the platform's login page.

        The browser runs in NON-headless mode so the user can log in manually.
        Returns: {session_id, status, message}
        """
        # Validate account
        account = self.accounts.get(account_id)
        if not account:
            raise ValueError(f"账号 #{account_id} 不存在")

        # Check if already has an active session and reserve the slot atomically
        with self._lock:
            if account_id in self._active_sessions:
                raise RuntimeError("该账号已有一个打开的浏览器窗口")
            # Reserve slot so no other thread can start a session for this account
            self._active_sessions[account_id] = None

        platform = account["platform"]

        # Get platform login URL
        from services.platform_logins.registry import get_handler
        handler = get_handler(platform, self.browser)
        login_url = handler.LOGIN_URL

        # Create session record
        session_id = self._create_session(account_id, platform)

        try:
            # Create browser context (non-headless is set in config)
            self.browser.create_context(account_id)

            # Open new page and navigate to login URL
            page = self.browser.new_page(account_id)
            self.browser.navigate(page, login_url, wait_until="domcontentloaded")

            with self._lock:
                self._active_sessions[account_id] = {
                    "session_id": session_id,
                    "platform": platform,
                    "handler": handler,
                    "page": page,
                }

            self._update_session(session_id, "open", "浏览器已打开，请手动登录")

            return {
                "session_id": session_id,
                "status": "open",
                "message": f"已打开 {platform} 登录页面，请在浏览器窗口中手动登录",
                "login_url": login_url,
            }

        except Exception as e:
            logger.exception("Failed to open browser for account %d", account_id)
            self._update_session(session_id, "failed", f"打开浏览器失败: {e}")
            try:
                self.browser.close_context(account_id)
            except Exception:
                pass
            with self._lock:
                self._active_sessions.pop(account_id, None)
            raise

    def complete_login(self, account_id: int) -> dict:
        """Extract cookies from the open browser and save them.

        Called by the user after they finish logging in manually.
        Returns: {success, message, cookie_count}
        """
        with self._lock:
            session = self._active_sessions.get(account_id)
            if not session:
                raise ValueError("该账号没有打开的浏览器窗口")
            session_id = session["session_id"]
            handler = session["handler"]
            page = session["page"]

        try:
            # Check if login was successful via platform-specific detection
            logged_in = self.browser._run_async(
                handler.detect_login_success(page)
            )

            if not logged_in:
                return {
                    "success": False,
                    "message": "检测到尚未登录成功，请先在浏览器中完成登录",
                    "cookie_count": 0,
                }

            # Extract cookies
            context = self.browser._contexts.get(account_id)
            if not context:
                raise RuntimeError("浏览器上下文不存在")

            cookies = self.browser.extract_cookies(context)

            # Save cookies
            self.creds.save_cookies(account_id, cookies, source="browser_manual")

            # Update login status
            self.login_status.update_state(account_id, "logged_in")

            # Update account cookie timestamp
            try:
                self.accounts.update(account_id, {
                    "cookie_updated_at": datetime.now().isoformat(),
                })
            except Exception:
                pass

            # Update session
            self._update_session(session_id, "success", "登录成功，Cookie已保存")

            # Cleanup
            self._cleanup(account_id)

            return {
                "success": True,
                "message": f"登录成功！已保存 {len(cookies)} 个Cookie",
                "cookie_count": len(cookies),
            }

        except Exception as e:
            logger.exception("complete_login error for account %d", account_id)
            self._update_session(session_id, "failed", f"保存失败: {e}")
            self._cleanup(account_id)
            raise

    def cancel_login(self, account_id: int):
        """Cancel and close the browser window."""
        with self._lock:
            session = self._active_sessions.get(account_id)
            session_id = session["session_id"] if session else None
        if session_id is not None:
            self._update_session(session_id, "cancelled", "用户取消")
        self._cleanup(account_id)

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

    def is_browser_open(self, account_id: int) -> bool:
        """Check if an account has an active browser session."""
        with self._lock:
            return account_id in self._active_sessions

    # ── Internal helpers ──

    def _cleanup(self, account_id: int):
        """Close browser context and remove active session."""
        try:
            self.browser.close_context(account_id)
        except Exception:
            pass
        with self._lock:
            self._active_sessions.pop(account_id, None)

    def _create_session(self, account_id: int, platform: str) -> int:
        conn = get_connection(self.db_path)
        try:
            now = datetime.now().isoformat()
            cur = conn.execute(
                """INSERT INTO browser_login_sessions
                   (account_id, login_method, status, platform,
                    started_at, created_at, updated_at)
                   VALUES (?, 'manual', 'pending', ?, ?, ?, ?)""",
                (account_id, platform, now, now, now),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _update_session(self, session_id: int, status: str, message: str = ""):
        conn = get_connection(self.db_path)
        try:
            now = datetime.now().isoformat()
            updates = "status = ?, progress_message = ?, updated_at = ?"
            params = [status, message, now]

            if status in ("success", "failed", "cancelled"):
                updates += ", completed_at = ?"
                params.append(now)

            params.append(session_id)
            conn.execute(
                f"UPDATE browser_login_sessions SET {updates} WHERE id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()
