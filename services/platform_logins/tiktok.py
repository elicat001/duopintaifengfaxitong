"""TikTok platform login handler."""

import logging
import random
import time
from typing import Callable, Optional

from services.platform_logins.base import BasePlatformLogin, LoginResult, LoginMethod

logger = logging.getLogger(__name__)


class TiktokLogin(BasePlatformLogin):
    """TikTok login handler.

    Supports: Cookie import, password login, QR code login.
    """

    PLATFORM = "tiktok"
    LOGIN_URL = "https://www.tiktok.com/login/phone-or-email/email"
    HOME_URL = "https://www.tiktok.com"
    SUPPORTED_METHODS = [LoginMethod.COOKIE_IMPORT, LoginMethod.PASSWORD, LoginMethod.QR_CODE]

    LOGIN_SUCCESS_COOKIES = ['sessionid', 'tt_csrf_token', 'sid_tt']
    CAPTCHA_SELECTORS = [
        '.captcha_verify_container', '#captcha-verify-image',
        'div[class*="captcha"]', 'iframe[src*="verify"]',
        '.verify-wrap', '#tiktok-verify-ele',
    ]

    async def validate_cookies(self, page, cookies: list) -> bool:
        await page.goto(self.HOME_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        return await self.detect_login_success(page)

    async def login_with_password(self, page, username: str, password: str,
                                   progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开TikTok登录页...")

        await page.goto(self.LOGIN_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        if progress_callback:
            await progress_callback("waiting_input", "正在输入账号密码...")

        # Fill email/username
        email_sels = [
            'input[name="username"]', 'input[placeholder*="Email"]',
            'input[placeholder*="email"]', 'input[type="text"]',
        ]
        for sel in email_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await el.fill('')
                await page.wait_for_timeout(random.randint(200, 500))
                await el.type(username, delay=random.randint(50, 120))
                break

        await page.wait_for_timeout(random.randint(300, 600))

        # Fill password
        pwd_sels = [
            'input[type="password"]', 'input[placeholder*="Password"]',
            'input[placeholder*="password"]',
        ]
        for sel in pwd_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await page.wait_for_timeout(random.randint(200, 400))
                await el.type(password, delay=random.randint(50, 120))
                break

        await page.wait_for_timeout(random.randint(500, 1000))

        # Click login
        login_sels = [
            'button[type="submit"]', 'button:has-text("Log in")',
            'button:has-text("登录")', 'button[data-e2e="login-button"]',
        ]
        for sel in login_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                break

        await page.wait_for_timeout(4000)

        if await self.detect_captcha(page):
            ss = await self.browser._take_screenshot(page, "tiktok_captcha")
            return LoginResult(
                success=False, login_state="need_captcha",
                needs_captcha=True, captcha_screenshot=ss,
                duration_ms=int((time.time() - start) * 1000),
            )

        await page.wait_for_timeout(2000)
        if await self.detect_login_success(page):
            cookies = await self.browser._extract_cookies(page.context)
            return LoginResult(
                success=True, login_state="logged_in",
                cookies=cookies,
                duration_ms=int((time.time() - start) * 1000),
            )

        ss = await self.browser._take_screenshot(page, "tiktok_failed")
        return LoginResult(
            success=False, login_state="logged_out",
            error_message="登录失败",
            screenshot_path=ss,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def login_with_qr(self, page, progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开TikTok登录页...")

        await page.goto("https://www.tiktok.com/login", wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        # TikTok may show QR by default or need clicking
        try:
            qr_triggers = [
                'text=Scan QR code', 'div:has-text("Use QR code")',
                'a[href*="qrcode"]',
            ]
            for sel in qr_triggers:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click()
                    await page.wait_for_timeout(1500)
                    break
        except Exception:
            pass

        if progress_callback:
            await progress_callback("waiting_qr_scan", "请使用TikTok APP扫描二维码")

        qr_path = await self.browser._take_screenshot(page, "tiktok_qr")

        return await self._wait_for_qr_scan(page, qr_path, progress_callback, timeout_seconds=240)

    async def detect_captcha(self, page) -> bool:
        for sel in self.CAPTCHA_SELECTORS:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    async def detect_login_success(self, page) -> bool:
        """NEGATIVE check first, then positive check."""
        url = page.url.lower()
        if '/login' in url:
            return False

        # NEGATIVE CHECK: login buttons → NOT logged in
        not_logged_in_selectors = [
            'a[href*="/login"]',                        # Login link
            'button[data-e2e="top-login-button"]',     # Top login button
        ]
        for sel in not_logged_in_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    logger.debug("[tiktok] NOT logged in: found '%s'", sel)
                    return False
            except Exception:
                pass

        # POSITIVE CHECK: logged-in-only elements
        logged_in_selectors = [
            'div[data-e2e="profile-icon"]',             # Profile icon
            'a[data-e2e="upload-icon"]',                # Upload icon (logged-in only)
        ]
        for sel in logged_in_selectors:
            try:
                if await page.locator(sel).count() > 0:
                    logger.debug("[tiktok] Logged in: found '%s'", sel)
                    return True
            except Exception:
                pass

        return False
