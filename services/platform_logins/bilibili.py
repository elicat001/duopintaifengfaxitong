"""Bilibili (哔哩哔哩) platform login handler."""

import logging
import random
import time
from typing import Callable, Optional

from services.platform_logins.base import BasePlatformLogin, LoginResult, LoginMethod

logger = logging.getLogger(__name__)


class BilibiliLogin(BasePlatformLogin):
    """Bilibili login handler.

    Supports: Cookie import, password login, QR code login.
    Known for geetest slider CAPTCHA.
    """

    PLATFORM = "bilibili"
    LOGIN_URL = "https://passport.bilibili.com/login"
    HOME_URL = "https://www.bilibili.com"
    SUPPORTED_METHODS = [LoginMethod.COOKIE_IMPORT, LoginMethod.PASSWORD, LoginMethod.QR_CODE]

    LOGIN_SUCCESS_COOKIES = ['SESSDATA', 'bili_jct', 'DedeUserID']
    CAPTCHA_SELECTORS = [
        '.geetest_panel', '.geetest_widget', '.geetest_radar_tip',
        '#gc-box', '.geetest_holder', 'div[class*="geetest"]',
        'iframe[src*="geetest"]',
    ]

    async def validate_cookies(self, page, cookies: list) -> bool:
        await page.goto(self.HOME_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)
        return await self.detect_login_success(page)

    async def login_with_password(self, page, username: str, password: str,
                                   progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开B站登录页...")

        await page.goto(self.LOGIN_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        # Switch to password login if needed
        try:
            pwd_triggers = [
                'text=密码登录', 'span:has-text("密码登录")',
                '.tab--account', 'li:has-text("密码登录")',
            ]
            for sel in pwd_triggers:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click()
                    await page.wait_for_timeout(1000)
                    break
        except Exception:
            pass

        if progress_callback:
            await progress_callback("waiting_input", "正在输入账号密码...")

        # Fill username
        username_sels = [
            'input[placeholder*="账号"]', 'input[placeholder*="手机号"]',
            'input#login-username', 'input[autocomplete="username"]',
        ]
        for sel in username_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await el.fill('')
                await page.wait_for_timeout(random.randint(200, 400))
                await el.type(username, delay=random.randint(50, 100))
                break

        # Fill password
        pwd_sels = [
            'input[type="password"]', 'input#login-passwd',
            'input[placeholder*="密码"]',
        ]
        for sel in pwd_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await page.wait_for_timeout(random.randint(200, 400))
                await el.type(password, delay=random.randint(50, 100))
                break

        await page.wait_for_timeout(random.randint(300, 600))

        # Click login
        login_sels = [
            'button:has-text("登录")', '.btn-login', 'button[type="submit"]',
            'div[class*="login-btn"]',
        ]
        for sel in login_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                break

        await page.wait_for_timeout(3000)

        # Check for geetest captcha
        if await self.detect_captcha(page):
            ss = await self.browser._take_screenshot(page, "bilibili_geetest")
            return LoginResult(
                success=False, login_state="need_captcha",
                needs_captcha=True, captcha_screenshot=ss,
                error_message="需要完成滑块验证",
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

        ss = await self.browser._take_screenshot(page, "bilibili_failed")
        return LoginResult(
            success=False, login_state="logged_out",
            error_message="登录失败",
            screenshot_path=ss,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def login_with_qr(self, page, progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开B站登录页...")

        await page.goto(self.LOGIN_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        # B站默认显示扫码登录，也可能需要点击
        try:
            qr_triggers = [
                'text=扫码登录', '.tab--qrcode', 'span:has-text("扫码登录")',
                'li:has-text("扫码登录")',
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
            await progress_callback("waiting_qr_scan", "请使用哔哩哔哩APP扫描二维码")

        qr_path = await self.browser._take_screenshot(page, "bilibili_qr")

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
        """Check login: NEGATIVE check first (login buttons = not logged in),
        then positive check (user-specific elements in header)."""
        url = page.url.lower()
        if 'passport' in url or 'login' in url:
            return False

        # NEGATIVE CHECK FIRST: if login button/prompt exists → NOT logged in
        # This is more reliable than positive checks because login prompts
        # are only shown to unauthenticated users.
        not_logged_in_selectors = [
            '.header-login-entry',                     # "登录" button in header
            '.login-panel-popover',                    # Login popup/popover
        ]
        for sel in not_logged_in_selectors:
            try:
                count = await page.locator(sel).count()
                if count > 0:
                    # Also check if it's visible (not hidden)
                    el = page.locator(sel).first
                    if await el.is_visible():
                        logger.debug("[bilibili] NOT logged in: found login button '%s'", sel)
                        return False
            except Exception:
                pass

        # POSITIVE CHECK: user-specific header elements (NOT generic .bili-avatar
        # which appears in video feeds for all users!)
        # These only exist in the header when the user is actually logged in.
        logged_in_selectors = [
            '.header-avatar-wrap--container img',      # Logged-in user's avatar in header
            '.right-entry .header-upload-entry',       # Upload button (only for logged-in)
            'a.right-entry-item[href*="space.bilibili.com"]',  # Personal space in header
        ]
        for sel in logged_in_selectors:
            try:
                if await page.locator(sel).count() > 0:
                    logger.debug("[bilibili] Logged in: found header element '%s'", sel)
                    return True
            except Exception:
                pass

        return False
