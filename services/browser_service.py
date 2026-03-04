"""Browser automation service using Playwright.

Manages browser lifecycle, context pooling, proxy configuration,
fingerprint application, cookie management, and screenshots.
Uses a dedicated background thread with asyncio event loop
for async Playwright operations, exposing sync methods for Flask.
"""

import asyncio
import atexit
import json
import logging
import os
import random
import threading
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Module-level registry so atexit can clean up all instances
_instances: list = []
_instances_lock = threading.Lock()


def _atexit_cleanup():
    """Clean up all BrowserService instances on process exit."""
    with _instances_lock:
        instances = list(_instances)
    for instance in instances:
        try:
            instance.stop()
        except Exception as e:
            logger.error("atexit cleanup error for BrowserService: %s", e)


atexit.register(_atexit_cleanup)


class BrowserService:
    """Manages Playwright browser lifecycle with sync/async bridge."""

    def __init__(self, config: dict):
        self._config = config
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._playwright = None
        self._browser = None
        self._contexts: Dict[int, Any] = {}  # account_id -> BrowserContext
        self._pages: Dict[int, Any] = {}  # account_id -> Page
        self._lock = threading.Lock()
        self._browser_lock = threading.Lock()  # Issue 4: lock for browser launch
        self._started = False

        screenshot_dir = config.get("screenshot_dir", "data/screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)

        # Register this instance for atexit cleanup (Issue 2)
        with _instances_lock:
            _instances.append(self)

    def start(self):
        """Start the background event loop thread and launch browser."""
        if self._started:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="playwright-loop"
        )
        self._thread.start()
        # Launch browser on the background loop
        self._run_async(self._launch_browser())
        self._started = True
        logger.info("BrowserService started (headless=%s)", self._config.get("headless", True))

    def stop(self):
        """Close all contexts, browser, and stop event loop."""
        if not self._started:
            return
        try:
            self._run_async(self._shutdown())
        except Exception as e:
            logger.error("Error during BrowserService shutdown: %s", e)
        self._started = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        # Join the daemon thread so it exits cleanly (Issue 2)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning("Playwright event loop thread did not exit within timeout")
        logger.info("BrowserService stopped")

        # Remove from module-level registry
        with _instances_lock:
            try:
                _instances.remove(self)
            except ValueError:
                pass

    def _run_loop(self):
        """Run the asyncio event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_async(self, coro) -> Any:
        """Schedule coroutine on background loop and block for result.

        On timeout, cancels the underlying task to prevent coroutine/resource
        leaks (Issue 3).
        """
        if not self._loop or not self._loop.is_running():
            raise RuntimeError("BrowserService event loop not running")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        timeout = self._config.get("timeout", 60)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            future.cancel()
            logger.error(
                "Async operation timed out after %ds — cancelled the pending task", timeout
            )
            raise TimeoutError(
                f"BrowserService operation timed out after {timeout}s"
            )

    async def _launch_browser(self):
        """Launch Playwright and Chromium browser."""
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._config.get("headless", True),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        logger.info("Chromium browser launched")

    async def _shutdown(self):
        """Close all contexts and browser."""
        for account_id in list(self._pages.keys()):
            try:
                await self._pages[account_id].close()
                logger.debug("Page closed for account %d", account_id)
            except Exception as e:
                logger.warning("Error closing page for account %d: %s", account_id, e)
        self._pages.clear()

        for account_id in list(self._contexts.keys()):
            try:
                await self._contexts[account_id].close()
                logger.debug("Context closed for account %d", account_id)
            except Exception as e:
                logger.warning("Error closing context for account %d: %s", account_id, e)
        self._contexts.clear()

        if self._browser:
            try:
                await self._browser.close()
                logger.info("Browser closed")
            except Exception as e:
                logger.warning("Error closing browser: %s", e)
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
                logger.info("Playwright stopped")
            except Exception as e:
                logger.warning("Error stopping Playwright: %s", e)
            self._playwright = None

    async def _ensure_browser(self):
        """Re-launch browser if it was closed or crashed.

        Uses double-checked locking (Issue 4) so that concurrent callers
        don't each try to launch a separate browser instance.
        """
        if self._browser is not None and self._browser.is_connected():
            return
        # Acquire lock for browser re-launch
        with self._browser_lock:
            # Double-check after acquiring the lock
            if self._browser is not None and self._browser.is_connected():
                return
            logger.warning("Browser disconnected, re-launching...")
            await self._launch_browser()

    async def _create_context(
        self,
        account_id: int,
        proxy_config: Optional[dict] = None,
        fingerprint: Optional[dict] = None,
    ):
        """Create a new BrowserContext with proxy and fingerprint."""
        await self._ensure_browser()

        with self._lock:
            if account_id in self._contexts:
                logger.debug("Reusing existing context for account %d", account_id)
                return self._contexts[account_id]

        fp = fingerprint or {}
        user_agents = self._config.get("user_agents", [])

        # Build proxy
        proxy = None
        if proxy_config and proxy_config.get("host"):
            proxy_type = proxy_config.get("proxy_type", "http")
            server = f"{proxy_type}://{proxy_config['host']}:{proxy_config['port']}"
            proxy = {"server": server}
            if proxy_config.get("username"):
                proxy["username"] = proxy_config["username"]
            if proxy_config.get("password"):
                proxy["password"] = proxy_config["password"]
            logger.debug("Proxy configured for account %d: %s", account_id, server)

        # Build context options
        ctx_opts = {
            "user_agent": fp.get("user_agent", random.choice(user_agents) if user_agents else None),
            "viewport": fp.get("viewport", {"width": 1920, "height": 1080}),
            "locale": fp.get("locale", "zh-CN"),
            "timezone_id": fp.get("timezone", "Asia/Shanghai"),
            "color_scheme": fp.get("color_scheme", "light"),
            "ignore_https_errors": True,
        }
        if proxy:
            ctx_opts["proxy"] = proxy

        # Remove None values
        ctx_opts = {k: v for k, v in ctx_opts.items() if v is not None}

        context = await self._browser.new_context(**ctx_opts)

        # Anti-detection: override navigator.webdriver
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        with self._lock:
            self._contexts[account_id] = context
        logger.info("Browser context created for account %d", account_id)
        return context

    async def _close_context(self, account_id: int):
        """Close and remove a browser context.

        Uses try/finally to guarantee the context and page are removed from
        tracking dicts even if close() raises (Issue 1).
        """
        with self._lock:
            page = self._pages.pop(account_id, None)
        if page:
            try:
                await page.close()
                logger.debug("Page closed for account %d", account_id)
            except Exception as e:
                logger.error("Error closing page for account %d: %s", account_id, e)
            finally:
                # Ensure page reference is released even on error
                page = None

        with self._lock:
            ctx = self._contexts.pop(account_id, None)
        if ctx:
            try:
                await ctx.close()
                logger.info("Context closed for account %d", account_id)
            except Exception as e:
                logger.error("Error closing context for account %d: %s", account_id, e)
            finally:
                # Ensure context reference is released even on error
                ctx = None

    async def _new_page(self, account_id: int):
        """Create a new page in the account's context."""
        with self._lock:
            ctx = self._contexts.get(account_id)
        if not ctx:
            raise RuntimeError(f"No browser context for account {account_id}")
        page = await ctx.new_page()
        with self._lock:
            self._pages[account_id] = page
        logger.debug("New page created for account %d", account_id)
        return page

    async def _take_screenshot(self, page, name: str) -> str:
        """Take a screenshot and save to screenshot directory."""
        screenshot_dir = self._config.get("screenshot_dir", "data/screenshots")
        filename = f"{name}_{int(time.time())}.png"
        filepath = os.path.join(screenshot_dir, filename)
        await page.screenshot(path=filepath, full_page=False)
        logger.info("Screenshot saved: %s", filepath)
        return filepath

    async def _inject_cookies(self, context, cookies: list, url: str):
        """Add cookies to browser context."""
        if not cookies:
            logger.debug("No cookies to inject")
            return
        # Ensure cookies have required fields
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.hostname or ""

        pw_cookies = []
        for c in cookies:
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
                if c.get("sameSite"):
                    cookie["sameSite"] = c["sameSite"]
                pw_cookies.append(cookie)

        if pw_cookies:
            await context.add_cookies(pw_cookies)
            logger.info("Injected %d cookies for %s", len(pw_cookies), domain)

    async def _extract_cookies(self, context) -> list:
        """Extract all cookies from context."""
        cookies = await context.cookies()
        logger.debug("Extracted %d cookies from context", len(cookies))
        return [
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
                "expires": c.get("expires", -1),
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", False),
                "sameSite": c.get("sameSite", "None"),
            }
            for c in cookies
        ]

    async def _navigate(self, page, url: str, wait_until: str = "networkidle"):
        """Navigate to URL with timeout."""
        timeout = self._config.get("timeout", 60) * 1000
        logger.debug("Navigating to %s (wait_until=%s, timeout=%dms)", url, wait_until, timeout)
        await page.goto(url, wait_until=wait_until, timeout=timeout)
        logger.debug("Navigation complete: %s", url)

    # ──── Synchronous public API (called from Flask threads) ────

    def create_context(self, account_id: int, proxy_config=None, fingerprint=None):
        return self._run_async(
            self._create_context(account_id, proxy_config, fingerprint)
        )

    def close_context(self, account_id: int):
        return self._run_async(self._close_context(account_id))

    def new_page(self, account_id: int):
        return self._run_async(self._new_page(account_id))

    def take_screenshot(self, page, name: str) -> str:
        return self._run_async(self._take_screenshot(page, name))

    def inject_cookies(self, context, cookies: list, url: str):
        return self._run_async(self._inject_cookies(context, cookies, url))

    def extract_cookies(self, context) -> list:
        return self._run_async(self._extract_cookies(context))

    def navigate(self, page, url: str, wait_until: str = "networkidle"):
        return self._run_async(self._navigate(page, url, wait_until))

    @property
    def active_context_count(self) -> int:
        return len(self._contexts)

    @property
    def is_running(self) -> bool:
        return self._started
