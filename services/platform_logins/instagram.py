"""Instagram platform login handler."""

import logging
import random
import time
from typing import Callable, Optional

from services.platform_logins.base import BasePlatformLogin, LoginResult, LoginMethod

logger = logging.getLogger(__name__)


class InstagramLogin(BasePlatformLogin):
    """Instagram login handler.

    Supports: Cookie import, password login.
    Does NOT support QR code login.
    Instagram has 2FA (two-factor authentication) support.
    """

    PLATFORM = "instagram"
    LOGIN_URL = "https://www.instagram.com/accounts/login/"
    HOME_URL = "https://www.instagram.com/"
    SUPPORTED_METHODS = [LoginMethod.COOKIE_IMPORT, LoginMethod.PASSWORD]

    USERNAME_SELECTOR = 'input[name="username"]'
    PASSWORD_SELECTOR = 'input[name="password"]'
    LOGIN_BUTTON = 'button[type="submit"]'
    TWO_FA_INPUT = 'input[name="verificationCode"]'
    LOGIN_SUCCESS_COOKIES = ['sessionid', 'ds_user_id']
    CAPTCHA_SELECTORS = [
        '.captcha', '#recaptcha', 'iframe[src*="recaptcha"]',
        'iframe[src*="challenge"]',
    ]
    TWO_FA_SELECTORS = [
        'input[name="verificationCode"]',
        'form[id="datr-cookie-accept"]',
        'input[aria-label*="Security"]',
        'input[placeholder*="Code"]',
    ]

    async def validate_cookies(self, page, cookies: list) -> bool:
        await page.goto(self.HOME_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        return await self.detect_login_success(page)

    async def login_with_password(self, page, username: str, password: str,
                                   progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开Instagram登录页...")

        await page.goto(self.LOGIN_URL, wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(2000)

        # Dismiss cookie consent if present
        try:
            consent_selectors = [
                'button:has-text("Allow")', 'button:has-text("Accept")',
                'button:has-text("Allow essential and optional cookies")',
                'button:has-text("接受")',
            ]
            for sel in consent_selectors:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click()
                    await page.wait_for_timeout(1000)
                    break
        except Exception:
            pass

        if progress_callback:
            await progress_callback("waiting_input", "正在输入账号密码...")

        # Fill username with human-like typing
        username_el = page.locator(self.USERNAME_SELECTOR).first
        if await username_el.count() > 0:
            await username_el.click()
            await page.wait_for_timeout(random.randint(200, 500))
            await username_el.fill('')
            await username_el.type(username, delay=random.randint(50, 120))

        await page.wait_for_timeout(random.randint(300, 700))

        # Fill password
        password_el = page.locator(self.PASSWORD_SELECTOR).first
        if await password_el.count() > 0:
            await password_el.click()
            await page.wait_for_timeout(random.randint(200, 400))
            await password_el.type(password, delay=random.randint(50, 120))

        await page.wait_for_timeout(random.randint(500, 1000))

        # Click login button
        login_btn = page.locator(self.LOGIN_BUTTON).first
        if await login_btn.count() > 0:
            await login_btn.click()

        await page.wait_for_timeout(4000)

        # Check for CAPTCHA
        if await self.detect_captcha(page):
            ss = await self.browser._take_screenshot(page, "instagram_captcha")
            return LoginResult(
                success=False, login_state="need_captcha",
                needs_captcha=True, captcha_screenshot=ss,
                duration_ms=int((time.time() - start) * 1000),
            )

        # Check for 2FA
        for sel in self.TWO_FA_SELECTORS:
            el = page.locator(sel).first
            if await el.count() > 0:
                ss = await self.browser._take_screenshot(page, "instagram_2fa")
                return LoginResult(
                    success=False, login_state="need_verify",
                    needs_verification=True, screenshot_path=ss,
                    error_message="需要两步验证 (2FA)",
                    duration_ms=int((time.time() - start) * 1000),
                )

        # Check for success
        await page.wait_for_timeout(2000)
        if await self.detect_login_success(page):
            # Dismiss "Save Login Info" or "Turn on Notifications" popups
            try:
                dismiss_selectors = [
                    'button:has-text("Not Now")', 'button:has-text("以后再说")',
                    'button:has-text("Not now")',
                ]
                for sel in dismiss_selectors:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click()
                        await page.wait_for_timeout(500)
            except Exception:
                pass

            cookies = await self.browser._extract_cookies(page.context)
            return LoginResult(
                success=True, login_state="logged_in",
                cookies=cookies,
                duration_ms=int((time.time() - start) * 1000),
            )

        # Check for error messages on page
        error_text = ""
        try:
            error_el = page.locator('#slfErrorAlert, p[data-testid="login-error-message"]').first
            if await error_el.count() > 0:
                error_text = await error_el.text_content()
        except Exception:
            pass

        ss = await self.browser._take_screenshot(page, "instagram_failed")
        return LoginResult(
            success=False, login_state="logged_out",
            error_message=error_text or "登录失败，请检查账号密码",
            screenshot_path=ss,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def login_with_qr(self, page, progress_callback: Optional[Callable] = None) -> LoginResult:
        return LoginResult(
            success=False, login_state="logged_out",
            error_message="Instagram不支持扫码登录",
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
        """NEGATIVE check first (login form = not logged in),
        then positive check (nav bar elements)."""
        url = page.url.lower()
        # Instagram redirects to /accounts/login/ when not logged in
        if '/accounts/login' in url or '/challenge/' in url:
            return False

        # NEGATIVE CHECK: login form elements → NOT logged in
        not_logged_in_selectors = [
            'input[name="username"]',                   # Login username field
            'form[id*="login"]',                        # Login form
        ]
        for sel in not_logged_in_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    logger.debug("[instagram] NOT logged in: found '%s'", sel)
                    return False
            except Exception:
                pass

        # POSITIVE CHECK: logged-in nav elements
        logged_in_selectors = [
            'svg[aria-label="Home"]',                    # Home icon in nav
            'svg[aria-label="New post"]',                # New post icon
            'a[href="/direct/inbox/"]',                  # DM inbox link
            'img[data-testid="user-avatar"]',            # User avatar
        ]
        for sel in logged_in_selectors:
            try:
                if await page.locator(sel).count() > 0:
                    logger.debug("[instagram] Logged in: found '%s'", sel)
                    return True
            except Exception:
                pass

        return False
