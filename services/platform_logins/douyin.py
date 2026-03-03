"""Douyin (抖音) platform login handler."""

import logging
import random
import time
from typing import Callable, Optional

from services.platform_logins.base import BasePlatformLogin, LoginResult, LoginMethod

logger = logging.getLogger(__name__)


class DouyinLogin(BasePlatformLogin):
    """Douyin login handler.

    Supports: Cookie import, password login, QR code login.
    """

    PLATFORM = "douyin"
    LOGIN_URL = "https://www.douyin.com"
    HOME_URL = "https://www.douyin.com"
    SUPPORTED_METHODS = [LoginMethod.COOKIE_IMPORT, LoginMethod.PASSWORD, LoginMethod.QR_CODE]

    LOGIN_SUCCESS_COOKIES = ['sessionid', 'passport_csrf_token', 'sid_guard']
    CAPTCHA_SELECTORS = [
        '.captcha_verify_container', '#captcha-verify-image',
        'div[class*="captcha"]', '.verify-wrap',
        'iframe[src*="verify"]',
    ]
    QR_CODE_SELECTORS = [
        '.qrcode-img img', 'canvas.qrcode', '.web-login-scan-code__content img',
        'div[class*="qrcode"] img', 'div[class*="qrcode"] canvas',
    ]

    async def validate_cookies(self, page, cookies: list) -> bool:
        await page.goto(self.HOME_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        return await self.detect_login_success(page)

    async def login_with_password(self, page, username: str, password: str,
                                   progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开抖音登录页...")

        await page.goto(self.LOGIN_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        # Try to switch to password login mode
        try:
            password_triggers = [
                'text=密码登录', 'text=账号密码登录',
                'span:has-text("密码登录")', 'div:has-text("密码登录")',
            ]
            for sel in password_triggers:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click()
                    await page.wait_for_timeout(1000)
                    break
        except Exception as e:
            logger.warning("Failed to switch to password login: %s", e)

        if progress_callback:
            await progress_callback("waiting_input", "正在输入账号密码...")

        # Find and fill username/phone field
        username_selectors = [
            'input[placeholder*="手机号"]', 'input[placeholder*="账号"]',
            'input[type="tel"]', 'input[name="mobile"]',
        ]
        for sel in username_selectors:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await el.fill('')
                await page.wait_for_timeout(random.randint(200, 500))
                await el.type(username, delay=random.randint(50, 120))
                break

        # Find and fill password field
        password_selectors = [
            'input[type="password"]', 'input[placeholder*="密码"]',
        ]
        for sel in password_selectors:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await page.wait_for_timeout(random.randint(200, 500))
                await el.type(password, delay=random.randint(50, 120))
                break

        await page.wait_for_timeout(random.randint(500, 1000))

        # Click login button
        login_selectors = [
            'button:has-text("登录")', 'button[type="submit"]',
            'div[class*="login-btn"]',
        ]
        for sel in login_selectors:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                break

        await page.wait_for_timeout(3000)

        # Check for captcha
        if await self.detect_captcha(page):
            ss = await self.browser._take_screenshot(page, "douyin_captcha")
            return LoginResult(
                success=False, login_state="need_captcha",
                needs_captcha=True, captcha_screenshot=ss,
                duration_ms=int((time.time() - start) * 1000),
            )

        # Check for success
        await page.wait_for_timeout(2000)
        if await self.detect_login_success(page):
            cookies = await self.browser._extract_cookies(page.context)
            return LoginResult(
                success=True, login_state="logged_in",
                cookies=cookies,
                duration_ms=int((time.time() - start) * 1000),
            )

        ss = await self.browser._take_screenshot(page, "douyin_login_failed")
        return LoginResult(
            success=False, login_state="logged_out",
            error_message="登录失败，请检查账号密码",
            screenshot_path=ss,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def login_with_qr(self, page, progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开抖音登录页...")

        await page.goto(self.LOGIN_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        # Try to find/switch to QR login
        try:
            qr_triggers = [
                'text=扫码登录', 'span:has-text("扫码登录")',
                'div[class*="qrcode-switch"]',
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
            await progress_callback("waiting_qr_scan", "请使用抖音APP扫描二维码")

        qr_path = await self.browser._take_screenshot(page, "douyin_qr")

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
        if 'login' in url or 'passport' in url:
            return False

        # NEGATIVE CHECK: login buttons/prompts → NOT logged in
        not_logged_in_selectors = [
            '.login-guide',                             # Login guide overlay
            'button[class*="login"]',                   # Login button
        ]
        for sel in not_logged_in_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    logger.debug("[douyin] NOT logged in: found '%s'", sel)
                    return False
            except Exception:
                pass

        # POSITIVE CHECK: user-specific elements in header
        logged_in_selectors = [
            'a[href*="/user/self"]',                    # Self profile link
            'div[data-e2e="user-info"]',               # User info panel
        ]
        for sel in logged_in_selectors:
            try:
                if await page.locator(sel).count() > 0:
                    logger.debug("[douyin] Logged in: found '%s'", sel)
                    return True
            except Exception:
                pass

        return False
