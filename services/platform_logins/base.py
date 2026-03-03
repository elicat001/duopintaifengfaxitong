"""Abstract base class for platform login handlers."""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class LoginMethod(Enum):
    COOKIE_IMPORT = "cookie_import"
    PASSWORD = "password_login"
    QR_CODE = "qr_login"


@dataclass
class LoginResult:
    """Result of a login attempt."""
    success: bool
    login_state: str  # maps to LoginStatusService states
    cookies: Optional[list] = None
    error_message: str = ""
    screenshot_path: str = ""
    qr_code_path: str = ""
    duration_ms: int = 0
    needs_captcha: bool = False
    needs_verification: bool = False
    captcha_screenshot: str = ""


class BasePlatformLogin(ABC):
    """Abstract base for all platform login handlers.

    Each platform implements this interface with platform-specific
    selectors, login flows, and detection logic.
    """

    PLATFORM: str = ""
    LOGIN_URL: str = ""
    HOME_URL: str = ""
    SUPPORTED_METHODS: List[LoginMethod] = [
        LoginMethod.COOKIE_IMPORT,
        LoginMethod.PASSWORD,
        LoginMethod.QR_CODE,
    ]

    def __init__(self, browser_service):
        self.browser = browser_service

    @abstractmethod
    async def validate_cookies(self, page, cookies: list) -> bool:
        """Check if provided cookies result in a logged-in state."""

    @abstractmethod
    async def login_with_password(
        self, page, username: str, password: str,
        progress_callback: Optional[Callable] = None,
    ) -> LoginResult:
        """Fill and submit the login form."""

    @abstractmethod
    async def login_with_qr(
        self, page,
        progress_callback: Optional[Callable] = None,
    ) -> LoginResult:
        """Navigate to QR login page and wait for scan."""

    @abstractmethod
    async def detect_captcha(self, page) -> bool:
        """Check if current page shows a CAPTCHA challenge."""

    @abstractmethod
    async def detect_login_success(self, page) -> bool:
        """Check if current page indicates successful login."""

    # Login-page URL keywords — if final URL contains any of these,
    # the server rejected our cookies and redirected to login.
    LOGIN_URL_KEYWORDS: List[str] = [
        "login", "signin", "sign_in", "passport", "accounts/login",
        "sso", "authorize", "auth",
    ]

    async def cookie_import_flow(
        self, page, cookies: list,
        progress_callback: Optional[Callable] = None,
    ) -> LoginResult:
        """Cookie import flow: inject -> navigate -> validate.

        Validation uses TWO reliable checks:
        1. URL redirect check — did server redirect us to a login page?
        2. DOM check via detect_login_success — negative-first approach
           (checks for login buttons FIRST, then logged-in indicators)
        """
        start = time.time()

        if progress_callback:
            await progress_callback("navigating", "正在注入Cookie...")

        pw_cookies = self._normalize_cookies(cookies)
        await self.browser._inject_cookies(page.context, pw_cookies, self.HOME_URL)

        if progress_callback:
            await progress_callback("verifying", "正在验证登录状态...")

        try:
            await page.goto(self.HOME_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            logger.warning("Navigation timeout for %s: %s", self.PLATFORM, e)
            try:
                await page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass

        await page.wait_for_timeout(3000)

        duration = int((time.time() - start) * 1000)

        # CHECK 1: URL redirect detection — if server sent us to login page, cookies are invalid
        final_url = page.url.lower()
        redirected_to_login = any(kw in final_url for kw in self.LOGIN_URL_KEYWORDS)
        if redirected_to_login:
            logger.info("[%s] Cookie import FAILED: redirected to login page: %s",
                        self.PLATFORM, page.url)
            screenshot = await self.browser._take_screenshot(
                page, f"{self.PLATFORM}_cookie_redirect"
            )
            return LoginResult(
                success=False,
                login_state="expired",
                error_message=f"Cookie无效，被重定向到登录页: {page.url}",
                screenshot_path=screenshot,
                duration_ms=duration,
            )

        # CHECK 2: DOM-based detection — uses negative-first approach
        # (each platform first checks for login buttons/forms, then positive indicators)
        dom_logged_in = await self.detect_login_success(page)

        if dom_logged_in:
            new_cookies = await self.browser._extract_cookies(page.context)
            logger.info("[%s] Cookie import SUCCESS (DOM confirmed)", self.PLATFORM)
            return LoginResult(
                success=True,
                login_state="logged_in",
                cookies=new_cookies,
                duration_ms=duration,
            )

        # All checks failed — take screenshot for debugging
        screenshot = await self.browser._take_screenshot(
            page, f"{self.PLATFORM}_cookie_failed"
        )
        logger.info("[%s] Cookie import FAILED: dom_logged_in=%s, url=%s",
                    self.PLATFORM, dom_logged_in, page.url)
        return LoginResult(
            success=False,
            login_state="expired",
            error_message="Cookie验证失败: 页面未显示登录状态，Cookie可能已过期",
            screenshot_path=screenshot,
            duration_ms=duration,
        )

    def _normalize_cookies(self, cookies_input) -> list:
        """Convert various cookie formats to Playwright's format.

        Handles:
        - list of dicts (standard format)
        - JSON string of list
        - semicolon-separated string "name1=val1; name2=val2"
        - Netscape cookie file format
        """
        if isinstance(cookies_input, str):
            cookies_input = cookies_input.strip()
            # Try JSON
            if cookies_input.startswith("["):
                try:
                    cookies_input = json.loads(cookies_input)
                except json.JSONDecodeError:
                    pass

            # Semicolon-separated string
            if isinstance(cookies_input, str):
                result = []
                domain = urlparse(self.HOME_URL).hostname or ""
                for pair in cookies_input.split(";"):
                    pair = pair.strip()
                    if "=" in pair:
                        name, value = pair.split("=", 1)
                        result.append({
                            "name": name.strip(),
                            "value": value.strip(),
                            "domain": domain,
                            "path": "/",
                        })
                return result

        if isinstance(cookies_input, list):
            domain = urlparse(self.HOME_URL).hostname or ""
            result = []
            for c in cookies_input:
                if isinstance(c, dict):
                    cookie = {
                        "name": c.get("name", ""),
                        "value": c.get("value", ""),
                        "domain": c.get("domain", domain),
                        "path": c.get("path", "/"),
                    }
                    if c.get("expires"):
                        cookie["expires"] = c["expires"]
                    if c.get("httpOnly") is not None:
                        cookie["httpOnly"] = c["httpOnly"]
                    if c.get("secure") is not None:
                        cookie["secure"] = c["secure"]
                    result.append(cookie)
            return result

        return []

    async def _type_human(self, page, selector: str, text: str):
        """Type text with human-like delays between keystrokes."""
        import random
        element = page.locator(selector)
        await element.click()
        await page.wait_for_timeout(random.randint(100, 300))
        for char in text:
            await element.type(char, delay=random.randint(50, 150))
        await page.wait_for_timeout(random.randint(200, 500))

    async def _wait_for_qr_scan(
        self, page, qr_path: str,
        progress_callback: Optional[Callable] = None,
        timeout_seconds: int = 240,
        poll_interval_ms: int = 2000,
    ) -> LoginResult:
        """Poll for QR code login completion.

        Shared helper for platforms that support QR login.
        """
        start = time.time()
        iterations = timeout_seconds * 1000 // poll_interval_ms

        for i in range(iterations):
            await page.wait_for_timeout(poll_interval_ms)

            # Check for CAPTCHA
            if await self.detect_captcha(page):
                captcha_ss = await self.browser._take_screenshot(
                    page, f"{self.PLATFORM}_captcha"
                )
                return LoginResult(
                    success=False,
                    login_state="need_captcha",
                    needs_captcha=True,
                    captcha_screenshot=captcha_ss,
                    qr_code_path=qr_path,
                    duration_ms=int((time.time() - start) * 1000),
                )

            # Check for login success
            if await self.detect_login_success(page):
                cookies = await self.browser._extract_cookies(page.context)
                return LoginResult(
                    success=True,
                    login_state="logged_in",
                    cookies=cookies,
                    qr_code_path=qr_path,
                    duration_ms=int((time.time() - start) * 1000),
                )

        return LoginResult(
            success=False,
            login_state="logged_out",
            error_message=f"扫码超时 ({timeout_seconds}秒)",
            qr_code_path=qr_path,
            duration_ms=int((time.time() - start) * 1000),
        )
