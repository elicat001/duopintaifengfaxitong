"""Weibo (微博) platform login handler."""

import logging
import random
import time
from typing import Callable, Optional

from services.platform_logins.base import BasePlatformLogin, LoginResult, LoginMethod

logger = logging.getLogger(__name__)


class WeiboLogin(BasePlatformLogin):
    """Weibo login handler.

    Supports: Cookie import, password login, QR code login.
    """

    PLATFORM = "weibo"
    LOGIN_URL = "https://passport.weibo.com/sso/signin"
    HOME_URL = "https://weibo.com"
    SUPPORTED_METHODS = [LoginMethod.COOKIE_IMPORT, LoginMethod.PASSWORD, LoginMethod.QR_CODE]

    LOGIN_SUCCESS_COOKIES = ['SUB', 'SUBP', 'SSOLoginState']
    CAPTCHA_SELECTORS = [
        '.verify-box', '.verify-code-input', '#captcha',
        'img[src*="captcha"]', '.code-input',
        'iframe[src*="captcha"]',
    ]

    async def validate_cookies(self, page, cookies: list) -> bool:
        await page.goto(self.HOME_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        return await self.detect_login_success(page)

    async def login_with_password(self, page, username: str, password: str,
                                   progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开微博登录页...")

        await page.goto(self.LOGIN_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        # Switch to account/password login
        try:
            pwd_triggers = [
                'text=账号登录', 'text=密码登录',
                'span:has-text("账号登录")', 'a:has-text("账号密码登录")',
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
            'input[name="username"]', 'input[placeholder*="手机号"]',
            'input[placeholder*="邮箱"]', 'input#loginname',
            'input[type="text"]',
        ]
        for sel in username_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await el.fill('')
                await page.wait_for_timeout(random.randint(200, 400))
                await el.type(username, delay=random.randint(60, 120))
                break

        # Fill password
        pwd_sels = [
            'input[type="password"]', 'input[name="password"]',
            'input#password',
        ]
        for sel in pwd_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await page.wait_for_timeout(random.randint(200, 400))
                await el.type(password, delay=random.randint(60, 120))
                break

        await page.wait_for_timeout(random.randint(500, 1000))

        # Click login
        login_sels = [
            'button:has-text("登录")', 'a:has-text("登录")',
            'input[type="submit"]', '.login-btn',
        ]
        for sel in login_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                break

        await page.wait_for_timeout(3000)

        if await self.detect_captcha(page):
            ss = await self.browser._take_screenshot(page, "weibo_captcha")
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

        ss = await self.browser._take_screenshot(page, "weibo_failed")
        return LoginResult(
            success=False, login_state="logged_out",
            error_message="登录失败",
            screenshot_path=ss,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def login_with_qr(self, page, progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开微博登录页...")

        await page.goto(self.LOGIN_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        # Weibo usually shows QR by default, or switch to it
        try:
            qr_triggers = [
                'text=扫码登录', '.qr-login', 'span:has-text("扫码登录")',
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
            await progress_callback("waiting_qr_scan", "请使用微博APP扫描二维码")

        qr_path = await self.browser._take_screenshot(page, "weibo_qr")

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
        """NEGATIVE check first, then positive check.
        Weibo redirects to passport.weibo.com if not logged in."""
        url = page.url.lower()
        if 'passport' in url or 'login' in url or 'visitor' in url:
            return False

        # NEGATIVE CHECK: login elements → NOT logged in
        not_logged_in_selectors = [
            '.LoginCard',                              # Login card popup
            'a.LoginBtn',                              # Login button
        ]
        for sel in not_logged_in_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    logger.debug("[weibo] NOT logged in: found '%s'", sel)
                    return False
            except Exception:
                pass

        # POSITIVE CHECK: user-specific nav elements
        logged_in_selectors = [
            '.gn_name',                                 # Username in global nav
            'a[title][href*="weibo.com/u/"]',          # Personal page link in nav
        ]
        for sel in logged_in_selectors:
            try:
                if await page.locator(sel).count() > 0:
                    logger.debug("[weibo] Logged in: found '%s'", sel)
                    return True
            except Exception:
                pass

        return False
