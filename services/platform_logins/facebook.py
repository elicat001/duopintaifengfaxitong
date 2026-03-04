"""Facebook platform login handler."""

import logging
import random
import time
from typing import Callable, Optional

from services.platform_logins.base import BasePlatformLogin, LoginResult, LoginMethod

logger = logging.getLogger(__name__)


class FacebookLogin(BasePlatformLogin):

    PLATFORM = "facebook"
    LOGIN_URL = "https://www.facebook.com/login/"
    HOME_URL = "https://www.facebook.com/"
    SUPPORTED_METHODS = [LoginMethod.COOKIE_IMPORT, LoginMethod.PASSWORD]

    USERNAME_SELECTOR = 'input[name="email"]'
    PASSWORD_SELECTOR = 'input[name="pass"]'
    LOGIN_BUTTON = 'button[name="login"]'
    LOGIN_SUCCESS_COOKIES = ['c_user', 'xs']
    CAPTCHA_SELECTORS = [
        '#captcha', 'img[src*="captcha"]',
        'iframe[src*="recaptcha"]', 'div[id*="captcha"]',
    ]

    async def validate_cookies(self, page, cookies: list) -> bool:
        await page.goto(self.HOME_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        return await self.detect_login_success(page)

    async def login_with_password(self, page, username: str, password: str,
                                   progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开Facebook登录页...")

        await page.goto(self.LOGIN_URL, wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(2000)

        # Dismiss cookie consent if present
        try:
            for sel in ['button[data-cookiebanner="accept_button"]',
                        'button:has-text("Allow")', 'button:has-text("Accept All")']:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click()
                    await page.wait_for_timeout(1000)
                    break
        except Exception:
            pass

        if progress_callback:
            await progress_callback("waiting_input", "正在输入账号密码...")

        username_el = page.locator(self.USERNAME_SELECTOR).first
        if await username_el.count() > 0:
            await username_el.click()
            await page.wait_for_timeout(random.randint(200, 500))
            await username_el.fill('')
            await username_el.type(username, delay=random.randint(50, 120))

        await page.wait_for_timeout(random.randint(300, 700))

        password_el = page.locator(self.PASSWORD_SELECTOR).first
        if await password_el.count() > 0:
            await password_el.click()
            await page.wait_for_timeout(random.randint(200, 400))
            await password_el.type(password, delay=random.randint(50, 120))

        await page.wait_for_timeout(random.randint(500, 1000))

        login_btn = page.locator(self.LOGIN_BUTTON).first
        if await login_btn.count() > 0:
            await login_btn.click()

        await page.wait_for_timeout(5000)

        if await self.detect_captcha(page):
            ss = await self.browser._take_screenshot(page, "facebook_captcha")
            return LoginResult(
                success=False, login_state="need_captcha",
                needs_captcha=True, captcha_screenshot=ss,
                duration_ms=int((time.time() - start) * 1000),
            )

        # Check for 2FA / checkpoint
        for sel in ['input[name="approvals_code"]', 'form[action*="checkpoint"]']:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    ss = await self.browser._take_screenshot(page, "facebook_2fa")
                    return LoginResult(
                        success=False, login_state="need_verify",
                        needs_verification=True, screenshot_path=ss,
                        error_message="需要两步验证 (2FA)",
                        duration_ms=int((time.time() - start) * 1000),
                    )
            except Exception:
                pass

        await page.wait_for_timeout(2000)
        if await self.detect_login_success(page):
            cookies = await self.browser._extract_cookies(page.context)
            return LoginResult(
                success=True, login_state="logged_in",
                cookies=cookies,
                duration_ms=int((time.time() - start) * 1000),
            )

        error_text = ""
        try:
            error_el = page.locator('div[role="alert"], div._9ay7').first
            if await error_el.count() > 0:
                error_text = await error_el.text_content()
        except Exception:
            pass

        ss = await self.browser._take_screenshot(page, "facebook_failed")
        return LoginResult(
            success=False, login_state="logged_out",
            error_message=error_text or "登录失败，请检查账号密码",
            screenshot_path=ss,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def login_with_qr(self, page, progress_callback: Optional[Callable] = None) -> LoginResult:
        return LoginResult(
            success=False, login_state="logged_out",
            error_message="Facebook不支持扫码登录",
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
        url = page.url.lower()
        if '/login' in url and 'facebook.com/login' in url:
            return False
        if '/checkpoint/' in url:
            return False

        # NEGATIVE: login form visible → not logged in
        visible_count = 0
        for sel in ['input[name="email"]', 'input[name="pass"]', 'button[name="login"]']:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    visible_count += 1
            except Exception:
                pass
        if visible_count >= 2:
            return False

        # POSITIVE: logged-in nav elements
        for sel in ['div[role="navigation"]', 'a[href*="/friends"]',
                    'a[aria-label="Messenger"]', 'a[href="/"][aria-label]']:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass

        return False
