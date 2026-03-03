"""Twitter (X) platform login handler."""

import logging
import random
import time
from typing import Callable, Optional

from services.platform_logins.base import BasePlatformLogin, LoginResult, LoginMethod

logger = logging.getLogger(__name__)


class TwitterLogin(BasePlatformLogin):
    """Twitter/X login handler.

    Supports: Cookie import, password login.
    Twitter has an unusual multi-step login: username -> password -> optional email verification.
    Does NOT support QR code login.
    """

    PLATFORM = "twitter"
    LOGIN_URL = "https://x.com/i/flow/login"
    HOME_URL = "https://x.com/home"
    SUPPORTED_METHODS = [LoginMethod.COOKIE_IMPORT, LoginMethod.PASSWORD]

    LOGIN_SUCCESS_COOKIES = ['auth_token', 'ct0', 'twid']
    CAPTCHA_SELECTORS = [
        'iframe[src*="arkose"]', 'iframe[src*="funcaptcha"]',
        'div[class*="captcha"]',
    ]

    async def validate_cookies(self, page, cookies: list) -> bool:
        await page.goto(self.HOME_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        return await self.detect_login_success(page)

    async def login_with_password(self, page, username: str, password: str,
                                   progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开Twitter登录页...")

        await page.goto(self.LOGIN_URL, wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(3000)

        # Step 1: Enter username/email
        if progress_callback:
            await progress_callback("waiting_input", "正在输入用户名...")

        username_sels = [
            'input[autocomplete="username"]', 'input[name="text"]',
            'input[type="text"]',
        ]
        for sel in username_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await el.fill('')
                await page.wait_for_timeout(random.randint(200, 500))
                await el.type(username, delay=random.randint(50, 120))
                break

        await page.wait_for_timeout(random.randint(500, 1000))

        # Click Next
        next_sels = [
            'button:has-text("Next")', 'button:has-text("下一步")',
            'div[role="button"]:has-text("Next")',
            'div[role="button"]:has-text("下一步")',
        ]
        for sel in next_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                break

        await page.wait_for_timeout(3000)

        # Twitter sometimes asks for email verification (unusual challenge)
        email_challenge_sels = [
            'input[data-testid="ocfEnterTextTextInput"]',
            'input[name="text"][autocomplete="on"]',
        ]
        for sel in email_challenge_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                # Twitter is asking for email to verify identity
                # Check if this is the email challenge (not password)
                page_text = await page.content()
                if 'password' not in page_text.lower()[:500]:
                    ss = await self.browser._take_screenshot(page, "twitter_email_verify")
                    return LoginResult(
                        success=False, login_state="need_verify",
                        needs_verification=True, screenshot_path=ss,
                        error_message="Twitter需要验证邮箱地址",
                        duration_ms=int((time.time() - start) * 1000),
                    )

        # Step 2: Enter password
        if progress_callback:
            await progress_callback("waiting_input", "正在输入密码...")

        pwd_sels = [
            'input[type="password"]', 'input[name="password"]',
            'input[autocomplete="current-password"]',
        ]
        for sel in pwd_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                await page.wait_for_timeout(random.randint(200, 400))
                await el.type(password, delay=random.randint(50, 120))
                break

        await page.wait_for_timeout(random.randint(500, 1000))

        # Click Log in
        login_sels = [
            'button[data-testid="LoginForm_Login_Button"]',
            'button:has-text("Log in")', 'button:has-text("登录")',
            'div[role="button"]:has-text("Log in")',
        ]
        for sel in login_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                await el.click()
                break

        await page.wait_for_timeout(4000)

        # Check for CAPTCHA
        if await self.detect_captcha(page):
            ss = await self.browser._take_screenshot(page, "twitter_captcha")
            return LoginResult(
                success=False, login_state="need_captcha",
                needs_captcha=True, captcha_screenshot=ss,
                duration_ms=int((time.time() - start) * 1000),
            )

        # Check for 2FA
        twofa_sels = [
            'input[data-testid="ocfEnterTextTextInput"]',
            'input[name="text"][inputmode="numeric"]',
        ]
        for sel in twofa_sels:
            el = page.locator(sel).first
            if await el.count() > 0:
                ss = await self.browser._take_screenshot(page, "twitter_2fa")
                return LoginResult(
                    success=False, login_state="need_verify",
                    needs_verification=True, screenshot_path=ss,
                    error_message="需要Twitter两步验证",
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

        ss = await self.browser._take_screenshot(page, "twitter_failed")
        return LoginResult(
            success=False, login_state="logged_out",
            error_message="登录失败",
            screenshot_path=ss,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def login_with_qr(self, page, progress_callback: Optional[Callable] = None) -> LoginResult:
        return LoginResult(
            success=False, login_state="logged_out",
            error_message="Twitter不支持扫码登录",
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
        """NEGATIVE check first (login flow = not logged in),
        then positive check (timeline elements)."""
        url = page.url.lower()
        # Twitter redirects to login flow when not authenticated
        if '/i/flow/login' in url or '/login' in url:
            return False

        # NEGATIVE CHECK: login/signup elements → NOT logged in
        not_logged_in_selectors = [
            'input[autocomplete="username"]',           # Login username field
            'a[href="/i/flow/login"]',                  # Login flow link
            'a[href="/i/flow/signup"]',                 # Signup link
        ]
        for sel in not_logged_in_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    logger.debug("[twitter] NOT logged in: found '%s'", sel)
                    return False
            except Exception:
                pass

        # POSITIVE CHECK: logged-in elements
        logged_in_selectors = [
            'a[data-testid="AppTabBar_Home_Link"]',     # Home tab
            'a[data-testid="AppTabBar_Profile_Link"]',  # Profile tab
            'div[data-testid="SideNav_AccountSwitcher_Button"]', # Account switcher
        ]
        for sel in logged_in_selectors:
            try:
                if await page.locator(sel).count() > 0:
                    logger.debug("[twitter] Logged in: found '%s'", sel)
                    return True
            except Exception:
                pass

        return False
