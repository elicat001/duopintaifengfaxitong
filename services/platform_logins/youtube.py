"""YouTube (Google) platform login handler."""

import logging
import random
import time
from typing import Callable, Optional

from services.platform_logins.base import BasePlatformLogin, LoginResult, LoginMethod

logger = logging.getLogger(__name__)


class YoutubeLogin(BasePlatformLogin):
    """YouTube/Google login handler.

    Supports: Cookie import, password login.
    Google login is a multi-step flow: email page -> password page -> optional 2FA.
    Does NOT support QR code login.
    """

    PLATFORM = "youtube"
    LOGIN_URL = "https://accounts.google.com/signin/v2/identifier?service=youtube"
    HOME_URL = "https://www.youtube.com"
    SUPPORTED_METHODS = [LoginMethod.COOKIE_IMPORT, LoginMethod.PASSWORD]

    LOGIN_SUCCESS_COOKIES = ['SID', 'HSID', 'SSID', 'APISID', 'LOGIN_INFO']
    CAPTCHA_SELECTORS = [
        'iframe[src*="recaptcha"]', '#captcha-form',
        'div[class*="captcha"]', '.g-recaptcha',
    ]
    TWO_FA_INDICATORS = [
        'input[type="tel"]',  # phone verification code
        '#totpPin',  # TOTP code
        'div[data-challengetype]',
        'text=2-Step Verification', 'text=两步验证',
    ]

    async def validate_cookies(self, page, cookies: list) -> bool:
        await page.goto(self.HOME_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        return await self.detect_login_success(page)

    async def login_with_password(self, page, username: str, password: str,
                                   progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开Google登录页...")

        await page.goto(self.LOGIN_URL, wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(2000)

        # Step 1: Enter email
        if progress_callback:
            await progress_callback("waiting_input", "正在输入邮箱...")

        email_sels = [
            'input[type="email"]', 'input#identifierId',
            'input[name="identifier"]',
        ]
        for sel in email_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await el.fill('')
                await page.wait_for_timeout(random.randint(200, 500))
                await el.type(username, delay=random.randint(50, 100))
                break

        await page.wait_for_timeout(random.randint(500, 1000))

        # Click Next
        next_sels = [
            'button:has-text("Next")', 'button:has-text("下一步")',
            '#identifierNext button', '#identifierNext',
        ]
        for sel in next_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                break

        await page.wait_for_timeout(3000)

        # Check for CAPTCHA after email step
        if await self.detect_captcha(page):
            ss = await self.browser._take_screenshot(page, "google_captcha")
            return LoginResult(
                success=False, login_state="need_captcha",
                needs_captcha=True, captcha_screenshot=ss,
                duration_ms=int((time.time() - start) * 1000),
            )

        # Step 2: Enter password
        if progress_callback:
            await progress_callback("waiting_input", "正在输入密码...")

        pwd_sels = [
            'input[type="password"]', 'input[name="Passwd"]',
            'input[name="password"]',
        ]
        for sel in pwd_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await page.wait_for_timeout(random.randint(200, 400))
                await el.type(password, delay=random.randint(50, 100))
                break

        await page.wait_for_timeout(random.randint(500, 1000))

        # Click Next (password step)
        pwd_next_sels = [
            '#passwordNext button', '#passwordNext',
            'button:has-text("Next")', 'button:has-text("下一步")',
        ]
        for sel in pwd_next_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                break

        await page.wait_for_timeout(4000)

        # Check for 2FA
        for sel in self.TWO_FA_INDICATORS:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    ss = await self.browser._take_screenshot(page, "google_2fa")
                    return LoginResult(
                        success=False, login_state="need_verify",
                        needs_verification=True, screenshot_path=ss,
                        error_message="需要Google两步验证",
                        duration_ms=int((time.time() - start) * 1000),
                    )
            except Exception:
                pass

        # Check for CAPTCHA
        if await self.detect_captcha(page):
            ss = await self.browser._take_screenshot(page, "google_captcha")
            return LoginResult(
                success=False, login_state="need_captcha",
                needs_captcha=True, captcha_screenshot=ss,
                duration_ms=int((time.time() - start) * 1000),
            )

        # Navigate to YouTube to check login
        await page.goto(self.HOME_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)

        if await self.detect_login_success(page):
            cookies = await self.browser._extract_cookies(page.context)
            return LoginResult(
                success=True, login_state="logged_in",
                cookies=cookies,
                duration_ms=int((time.time() - start) * 1000),
            )

        ss = await self.browser._take_screenshot(page, "google_failed")
        return LoginResult(
            success=False, login_state="logged_out",
            error_message="登录失败",
            screenshot_path=ss,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def login_with_qr(self, page, progress_callback: Optional[Callable] = None) -> LoginResult:
        return LoginResult(
            success=False, login_state="logged_out",
            error_message="YouTube/Google不支持扫码登录",
        )

    async def detect_captcha(self, page) -> bool:
        for sel in self.CAPTCHA_SELECTORS:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False

    async def detect_login_success(self, page) -> bool:
        """NEGATIVE check first (Sign in button = not logged in),
        then positive check (avatar button)."""
        url = page.url.lower()
        if 'accounts.google.com' in url or '/signin' in url:
            return False

        # NEGATIVE CHECK: "Sign in" button → NOT logged in
        not_logged_in_selectors = [
            'a[href*="accounts.google.com/ServiceLogin"]',  # Sign in link
            'ytd-button-renderer a[href*="accounts.google.com"]',  # YT sign in
        ]
        for sel in not_logged_in_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    logger.debug("[youtube] NOT logged in: found '%s'", sel)
                    return False
            except Exception:
                pass

        # POSITIVE CHECK: logged-in header elements
        logged_in_selectors = [
            'button#avatar-btn',                         # Avatar button
            '#avatar-btn img',                            # Avatar image
        ]
        for sel in logged_in_selectors:
            try:
                if await page.locator(sel).count() > 0:
                    logger.debug("[youtube] Logged in: found '%s'", sel)
                    return True
            except Exception:
                pass

        return False
