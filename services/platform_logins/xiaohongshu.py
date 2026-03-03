"""Xiaohongshu (小红书) platform login handler."""

import logging
import time
from typing import Callable, Optional

from services.platform_logins.base import BasePlatformLogin, LoginResult, LoginMethod

logger = logging.getLogger(__name__)


class XiaohongshuLogin(BasePlatformLogin):
    """Xiaohongshu login handler.

    Supports: Cookie import, QR code login.
    Does NOT support password login (xiaohongshu uses phone+SMS only).
    """

    PLATFORM = "xiaohongshu"
    LOGIN_URL = "https://www.xiaohongshu.com"
    HOME_URL = "https://www.xiaohongshu.com"
    SUPPORTED_METHODS = [LoginMethod.COOKIE_IMPORT, LoginMethod.QR_CODE]

    LOGIN_URL_KEYWORDS = ["login", "passport"]

    # DOM selectors (may need updating as site changes)
    QR_LOGIN_TRIGGER = 'div.login-container >> text=扫码登录'
    QR_CODE_IMAGE = '.qrcode-img img, canvas.qrcode, .login-qrcode img'
    LOGIN_SUCCESS_COOKIES = ['web_session', 'a1']
    CAPTCHA_SELECTORS = [
        '.captcha-container', '.verify-bar', '.verify-wrap',
        'iframe[src*="captcha"]', '.slider-verify',
    ]

    async def validate_cookies(self, page, cookies: list) -> bool:
        await page.goto(self.HOME_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)
        return await self.detect_login_success(page)

    async def login_with_password(self, page, username: str, password: str,
                                   progress_callback: Optional[Callable] = None) -> LoginResult:
        return LoginResult(
            success=False,
            login_state="logged_out",
            error_message="小红书不支持账号密码登录，请使用扫码登录或Cookie导入",
        )

    async def login_with_qr(self, page, progress_callback: Optional[Callable] = None) -> LoginResult:
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在打开小红书登录页...")

        await page.goto(self.LOGIN_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        # Try clicking QR code login tab
        try:
            qr_triggers = [
                'text=扫码登录', '.qrcode-tab', '.login-type-switch',
                'span:has-text("扫码登录")', 'div:has-text("扫码登录")',
            ]
            for sel in qr_triggers:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.click()
                    await page.wait_for_timeout(1500)
                    break
        except Exception as e:
            logger.warning("Failed to click QR login tab: %s", e)

        # Take screenshot of QR code
        if progress_callback:
            await progress_callback("waiting_qr_scan", "请使用小红书APP扫描二维码")

        qr_path = await self.browser._take_screenshot(page, "xiaohongshu_qr")

        # Poll for login success
        return await self._wait_for_qr_scan(
            page, qr_path, progress_callback, timeout_seconds=240
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
        """NEGATIVE check first (login prompts = not logged in),
        then positive check (user-specific header elements)."""
        url = page.url.lower()
        if 'login' in url or 'passport' in url:
            return False

        # NEGATIVE CHECK: login prompts/buttons → NOT logged in
        not_logged_in_selectors = [
            '.login-container',              # Login popup container
            '.login-btn',                    # Login button
            'button.login-button',           # Login button variant
        ]
        for sel in not_logged_in_selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    logger.debug("[xiaohongshu] NOT logged in: found '%s'", sel)
                    return False
            except Exception:
                pass

        # POSITIVE CHECK: user-specific elements (only in logged-in header)
        logged_in_selectors = [
            '.reds-button-new-note',          # Publish button (only for logged-in)
            'a[href*="/user/profile"]',       # Profile link in sidebar
        ]
        for sel in logged_in_selectors:
            try:
                if await page.locator(sel).count() > 0:
                    logger.debug("[xiaohongshu] Logged in: found '%s'", sel)
                    return True
            except Exception:
                pass

        return False
