"""Browser Instance Pool - manages persistent browser instances per account.

Each account gets a dedicated browser with persistent profile directory,
shared across JobExecutor and ReplyExecutor. Supports both local Playwright
and remote CDP (Chrome DevTools Protocol) connections.
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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from services.browser_profile_manager import BrowserProfileManager

logger = logging.getLogger(__name__)

# Module-level registry for atexit cleanup
_pool_instances: list = []
_pool_instances_lock = threading.Lock()


def _atexit_cleanup():
    """Clean up all BrowserPool instances on process exit."""
    with _pool_instances_lock:
        instances = list(_pool_instances)
    for inst in instances:
        try:
            inst.stop()
        except Exception as e:
            logger.error("atexit cleanup error for BrowserPool: %s", e)


atexit.register(_atexit_cleanup)


# ── Anti-detection JavaScript ─────────────────────────────────────────────

_ANTI_DETECTION_SCRIPT_TEMPLATE = """
(() => {
    // ── 1. navigator.webdriver ──────────────────────────────────────
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true,
    });
    // Remove webdriver from prototype chain
    delete Object.getPrototypeOf(navigator).webdriver;

    // ── 2. navigator.languages ──────────────────────────────────────
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en-US', 'en'],
        configurable: true,
    });

    // ── 3. navigator.plugins (realistic entries) ────────────────────
    const makePlugin = (name, description, filename, mimeType) => {
        const plugin = Object.create(Plugin.prototype);
        Object.defineProperties(plugin, {
            name:        { get: () => name },
            description: { get: () => description },
            filename:    { get: () => filename },
            length:      { get: () => 1 },
            0:           { get: () => ({ type: mimeType, suffixes: '', description: '', enabledPlugin: plugin }) },
        });
        return plugin;
    };
    const pluginArray = [
        makePlugin('Chrome PDF Plugin', 'Portable Document Format', 'internal-pdf-viewer', 'application/x-google-chrome-pdf'),
        makePlugin('Chrome PDF Viewer', '', 'mhjfbmdgcfjbbpaeojofohoefgiehjai', 'application/pdf'),
        makePlugin('Native Client', '', 'internal-nacl-plugin', 'application/x-nacl'),
    ];
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const arr = pluginArray;
            arr.item = (i) => arr[i] || null;
            arr.namedItem = (n) => arr.find(p => p.name === n) || null;
            arr.refresh = () => {};
            return arr;
        },
        configurable: true,
    });

    // ── 4. navigator.mimeTypes ──────────────────────────────────────
    Object.defineProperty(navigator, 'mimeTypes', {
        get: () => {
            const arr = [
                { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' },
                { type: 'application/x-nacl', suffixes: '', description: 'Native Client Executable' },
            ];
            arr.item = (i) => arr[i] || null;
            arr.namedItem = (n) => arr.find(m => m.type === n) || null;
            return arr;
        },
        configurable: true,
    });

    // ── 5. chrome object ────────────────────────────────────────────
    if (!window.chrome) window.chrome = {};
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            connect: () => {},
            sendMessage: () => {},
            id: undefined,
        };
    }
    window.chrome.app = {
        isInstalled: false,
        InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
        RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
        getDetails: () => null,
        getIsInstalled: () => false,
    };
    window.chrome.csi = () => ({
        onloadT: performance.timing.domContentLoadedEventEnd,
        startE: performance.timing.navigationStart,
        pageT: Date.now() - performance.timing.navigationStart,
    });
    window.chrome.loadTimes = () => ({
        commitLoadTime: performance.timing.responseStart / 1000,
        connectionInfo: 'h2',
        finishDocumentLoadTime: performance.timing.domContentLoadedEventEnd / 1000,
        finishLoadTime: performance.timing.loadEventEnd / 1000,
        firstPaintAfterLoadTime: 0,
        firstPaintTime: performance.timing.domContentLoadedEventEnd / 1000,
        navigationType: 'Other',
        npnNegotiatedProtocol: 'h2',
        requestTime: performance.timing.navigationStart / 1000,
        startLoadTime: performance.timing.navigationStart / 1000,
        wasAlternateProtocolAvailable: false,
        wasFetchedViaSpdy: true,
        wasNpnNegotiated: true,
    });

    // ── 6. permissions override ─────────────────────────────────────
    const originalQuery = window.navigator.permissions?.query;
    if (originalQuery) {
        window.navigator.permissions.query = (parameters) => {
            if (parameters.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission });
            }
            return originalQuery(parameters);
        };
    }

    // ── 7. Canvas fingerprint noise (seeded) ────────────────────────
    const CANVAS_SEED = '__CANVAS_SEED__';
    const seedHash = (str) => {
        let h = 0;
        for (let i = 0; i < str.length; i++) {
            h = ((h << 5) - h + str.charCodeAt(i)) | 0;
        }
        return h;
    };
    const canvasNoise = seedHash(CANVAS_SEED) / 2147483647;

    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type, quality) {
        const ctx = this.getContext('2d');
        if (ctx) {
            const imageData = ctx.getImageData(0, 0, this.width, this.height);
            const data = imageData.data;
            // Apply subtle deterministic noise based on seed
            for (let i = 0; i < data.length; i += 4) {
                const noise = ((canvasNoise * (i + 1) * 1000) % 3) - 1;  // -1, 0, or 1
                data[i] = Math.max(0, Math.min(255, data[i] + noise));
            }
            ctx.putImageData(imageData, 0, 0);
        }
        return origToDataURL.call(this, type, quality);
    };

    const origToBlob = HTMLCanvasElement.prototype.toBlob;
    HTMLCanvasElement.prototype.toBlob = function(callback, type, quality) {
        // Trigger noise injection via toDataURL first
        this.toDataURL(type, quality);
        return origToBlob.call(this, callback, type, quality);
    };

    // ── 8. WebGL vendor/renderer override ───────────────────────────
    const WEBGL_VENDOR = '__WEBGL_VENDOR__';
    const WEBGL_RENDERER = '__WEBGL_RENDERER__';

    const getParameterProxyHandler = {
        apply: function(target, thisArg, args) {
            const param = args[0];
            const debugExt = thisArg.getExtension('WEBGL_debug_renderer_info');
            if (debugExt) {
                if (param === debugExt.UNMASKED_VENDOR_WEBGL) return WEBGL_VENDOR;
                if (param === debugExt.UNMASKED_RENDERER_WEBGL) return WEBGL_RENDERER;
            }
            return target.apply(thisArg, args);
        }
    };

    const origGetParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = new Proxy(origGetParameter, getParameterProxyHandler);

    try {
        const origGetParameter2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = new Proxy(origGetParameter2, getParameterProxyHandler);
    } catch(e) { /* WebGL2 may not exist */ }

    // ── 9. AudioContext fingerprint override ─────────────────────────
    const AUDIO_SEED = __AUDIO_SEED__;
    const origCreateOscillator = (window.OfflineAudioContext || window.webkitOfflineAudioContext || function(){}).prototype.createOscillator;
    if (origCreateOscillator) {
        const origGetFloatFrequencyData = AnalyserNode.prototype.getFloatFrequencyData;
        AnalyserNode.prototype.getFloatFrequencyData = function(array) {
            origGetFloatFrequencyData.call(this, array);
            for (let i = 0; i < array.length; i++) {
                array[i] += AUDIO_SEED * 0.0001;
            }
        };
    }

    // ── 10. Platform & hardware overrides ───────────────────────────
    const PLATFORM_STR = '__PLATFORM_STRING__';
    const HW_CONCURRENCY = __HW_CONCURRENCY__;
    const DEV_MEMORY = __DEV_MEMORY__;

    Object.defineProperty(navigator, 'platform', {
        get: () => PLATFORM_STR,
        configurable: true,
    });
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => HW_CONCURRENCY,
        configurable: true,
    });
    if (navigator.deviceMemory !== undefined) {
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => DEV_MEMORY,
            configurable: true,
        });
    }

    // ── 11. Prevent iframe detection ────────────────────────────────
    try {
        Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
            get: function() {
                return window;
            }
        });
    } catch (e) { /* may fail in some contexts, that's ok */ }

    // ── 12. Screen dimensions override ──────────────────────────────
    const SCREEN_W = __SCREEN_W__;
    const SCREEN_H = __SCREEN_H__;
    const COLOR_DEPTH = __COLOR_DEPTH__;

    Object.defineProperty(screen, 'width', { get: () => SCREEN_W });
    Object.defineProperty(screen, 'height', { get: () => SCREEN_H });
    Object.defineProperty(screen, 'availWidth', { get: () => SCREEN_W });
    Object.defineProperty(screen, 'availHeight', { get: () => SCREEN_H - 40 });
    Object.defineProperty(screen, 'colorDepth', { get: () => COLOR_DEPTH });
    Object.defineProperty(screen, 'pixelDepth', { get: () => COLOR_DEPTH });
})();
"""


def _build_anti_detection_script(fingerprint: dict) -> str:
    """Build the anti-detection JS with account-specific fingerprint values."""
    script = _ANTI_DETECTION_SCRIPT_TEMPLATE
    script = script.replace("'__CANVAS_SEED__'", repr(fingerprint.get("canvas_seed", "default")))
    script = script.replace("'__WEBGL_VENDOR__'", repr(fingerprint.get("webgl_vendor", "Google Inc. (NVIDIA)")))
    script = script.replace("'__WEBGL_RENDERER__'", repr(fingerprint.get("webgl_renderer", "ANGLE (NVIDIA GeForce GTX 1660)")))
    script = script.replace("'__PLATFORM_STRING__'", repr(fingerprint.get("platform_string", "Win32")))
    script = script.replace("__AUDIO_SEED__", str(fingerprint.get("audio_seed", 0.001)))
    script = script.replace("__HW_CONCURRENCY__", str(fingerprint.get("hardware_concurrency", 8)))
    script = script.replace("__DEV_MEMORY__", str(fingerprint.get("device_memory", 8)))

    screen_res = fingerprint.get("screen_resolution", [1920, 1080])
    script = script.replace("__SCREEN_W__", str(screen_res[0]))
    script = script.replace("__SCREEN_H__", str(screen_res[1]))
    script = script.replace("__COLOR_DEPTH__", str(fingerprint.get("color_depth", 24)))

    return script


# ── BrowserInstance dataclass ──────────────────────────────────────────────

@dataclass
class BrowserInstance:
    """Tracks a single browser instance."""
    account_id: int
    browser: Any = None           # Playwright Browser or BrowserContext
    page: Any = None              # Current active page
    profile_dir: str = ""
    cdp_url: str = ""             # ws://... for remote browsers
    mode: str = "local"           # "local" | "remote_cdp" | "docker"
    status: str = "idle"          # "idle" | "in_use" | "launching" | "error"
    created_at: float = 0.0
    last_used_at: float = 0.0
    use_count: int = 0
    error_message: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)
    _playwright: Any = field(default=None, repr=False)
    _context: Any = field(default=None, repr=False)  # BrowserContext for CDP mode


# ── BrowserPool ────────────────────────────────────────────────────────────

class BrowserPool:
    """Manages a pool of persistent browser instances per account."""

    def __init__(self, config: dict = None):
        """
        Config keys:
        - profile_base_dir: base directory for browser profiles
        - headless: bool
        - timeout: seconds
        - user_agents: list
        - screenshot_dir: str
        - max_instances: max concurrent browsers (default 10)
        - idle_timeout: seconds before idle browser is closed (default 600 = 10min)
        - cleanup_interval: how often to check for idle instances (default 60s)
        """
        self._config = config or {}
        self._instances: Dict[int, BrowserInstance] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._cleanup_thread: Optional[threading.Thread] = None
        self._started = False
        self._stop_event = threading.Event()

        # Config defaults
        self._max_instances = self._config.get("max_instances", 10)
        self._idle_timeout = self._config.get("idle_timeout", 600)
        self._cleanup_interval = self._config.get("cleanup_interval", 60)
        self._timeout = self._config.get("timeout", 60)

        # Screenshot dir
        screenshot_dir = self._config.get("screenshot_dir", "data/screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)

        # Profile manager
        profile_base = self._config.get("profile_base_dir", None)
        self._profile_manager = BrowserProfileManager(base_dir=profile_base)

        # Register for atexit cleanup
        with _pool_instances_lock:
            _pool_instances.append(self)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self):
        """Start the pool: init event loop thread + idle cleanup thread."""
        if self._started:
            return

        self._stop_event.clear()

        # Start asyncio event loop in a background thread
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_loop, daemon=True, name="browser-pool-loop"
        )
        self._loop_thread.start()

        # Start idle cleanup thread
        self._cleanup_thread = threading.Thread(
            target=self._idle_cleanup_loop, daemon=True, name="browser-pool-cleanup"
        )
        self._cleanup_thread.start()

        self._started = True
        logger.info(
            "BrowserPool started (max_instances=%d, idle_timeout=%ds, headless=%s)",
            self._max_instances,
            self._idle_timeout,
            self._config.get("headless", True),
        )

    def stop(self):
        """Stop all instances and cleanup threads."""
        if not self._started:
            return

        logger.info("BrowserPool stopping...")
        self._stop_event.set()

        # Close all browser instances
        with self._lock:
            account_ids = list(self._instances.keys())

        for account_id in account_ids:
            try:
                self.close_instance(account_id)
            except Exception as e:
                logger.error("Error closing instance for account %d: %s", account_id, e)

        self._started = False

        # Stop the event loop
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        # Wait for threads to finish
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5)
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)

        logger.info("BrowserPool stopped")

        # Remove from atexit registry
        with _pool_instances_lock:
            try:
                _pool_instances.remove(self)
            except ValueError:
                pass

    def _run_loop(self):
        """Run the asyncio event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    # ── Core async bridge ──────────────────────────────────────────────────

    def _run_async(self, coro) -> Any:
        """Schedule coroutine on background loop and block for result."""
        if not self._loop or not self._loop.is_running():
            raise RuntimeError("BrowserPool event loop not running. Call start() first.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        timeout = self._timeout
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            future.cancel()
            logger.error("Async operation timed out after %ds - cancelled", timeout)
            raise TimeoutError(f"BrowserPool operation timed out after {timeout}s")

    # ── Acquire / Release ──────────────────────────────────────────────────

    def acquire(self, account_id: int, proxy_config: dict = None,
                fingerprint: dict = None, cookies: list = None,
                home_url: str = "") -> BrowserInstance:
        """Acquire a browser instance for account.

        - If instance exists and is idle, reuse it
        - If instance exists and is in_use, wait or raise
        - If no instance, create new one with persistent profile
        - Inject cookies if provided
        - Returns BrowserInstance with page ready
        """
        with self._lock:
            instance = self._instances.get(account_id)

        if instance is not None:
            # Try to acquire the instance lock
            acquired = instance.lock.acquire(timeout=self._timeout)
            if not acquired:
                raise TimeoutError(
                    f"Browser instance for account {account_id} is busy (timed out waiting)"
                )
            try:
                if instance.status == "error":
                    # Instance is in error state, close and recreate
                    logger.warning(
                        "Account %d instance in error state (%s), recreating",
                        account_id, instance.error_message,
                    )
                    self._run_async(self._close_instance(instance))
                    with self._lock:
                        self._instances.pop(account_id, None)
                    # Fall through to create new instance below
                    instance = None
                elif instance.status in ("idle", "in_use"):
                    # Check if browser is still alive
                    if instance.mode == "local" and instance.browser:
                        try:
                            # For persistent context, browser IS the context
                            # Check if it's still connected
                            pages = instance.browser.pages
                        except Exception:
                            logger.warning(
                                "Account %d browser disconnected, recreating", account_id
                            )
                            self._run_async(self._close_instance(instance))
                            with self._lock:
                                self._instances.pop(account_id, None)
                            instance = None
                    if instance is not None:
                        # Reuse existing instance
                        instance.status = "in_use"
                        instance.last_used_at = time.time()
                        instance.use_count += 1

                        # Create a new page if needed
                        if instance.page is None or instance.page.is_closed():
                            instance.page = self._run_async(
                                self._create_page(instance)
                            )

                        # Inject cookies if provided
                        if cookies:
                            url = home_url or "https://example.com"
                            self._run_async(
                                self._inject_cookies(instance, cookies, url)
                            )

                        logger.info(
                            "Reused browser instance for account %d (use_count=%d)",
                            account_id, instance.use_count,
                        )
                        return instance
            finally:
                if instance is not None:
                    instance.lock.release()

        # Need to create a new instance
        if len(self._instances) >= self._max_instances:
            # Try to evict the oldest idle instance
            self._evict_oldest_idle()
            if len(self._instances) >= self._max_instances:
                raise RuntimeError(
                    f"BrowserPool at capacity ({self._max_instances}). "
                    "Cannot create new instance."
                )

        # Get or create profile
        profile_info = self._profile_manager.get_or_create_profile(account_id)
        profile_dir = profile_info["profile_dir"]
        fp = fingerprint or profile_info["fingerprint"]

        # Launch new browser instance
        instance = self._run_async(
            self._launch_local_browser(account_id, profile_dir, proxy_config, fp)
        )
        instance.status = "in_use"
        instance.last_used_at = time.time()
        instance.use_count = 1

        with self._lock:
            self._instances[account_id] = instance

        # Create initial page
        instance.page = self._run_async(self._create_page(instance))

        # Inject cookies if provided
        if cookies:
            url = home_url or "https://example.com"
            self._run_async(self._inject_cookies(instance, cookies, url))

        logger.info("Created new browser instance for account %d", account_id)
        return instance

    def release(self, account_id: int, save_cookies: bool = True):
        """Release browser instance back to pool (mark idle, don't close).

        - Save cookies back if save_cookies=True (returned for caller to persist)
        - Close the page but keep browser alive
        - Mark as idle for reuse
        """
        with self._lock:
            instance = self._instances.get(account_id)
        if not instance:
            logger.warning("release() called for unknown account %d", account_id)
            return

        try:
            # Extract cookies before closing page (caller may want to save them)
            extracted_cookies = []
            if save_cookies:
                try:
                    extracted_cookies = self._run_async(
                        self._extract_cookies(instance)
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to extract cookies for account %d: %s",
                        account_id, e,
                    )

            # Close the page but keep the browser/context alive
            if instance.page and not instance.page.is_closed():
                try:
                    self._run_async(instance.page.close())
                except Exception as e:
                    logger.debug("Error closing page for account %d: %s", account_id, e)
            instance.page = None

            instance.status = "idle"
            instance.last_used_at = time.time()

            # Update profile last-used timestamp
            self._profile_manager.update_last_used(account_id)

            logger.info(
                "Released browser instance for account %d (cookies=%d)",
                account_id, len(extracted_cookies),
            )
            return extracted_cookies

        except Exception as e:
            instance.status = "error"
            instance.error_message = str(e)
            logger.error("Error releasing instance for account %d: %s", account_id, e)
            return []

    def get_page(self, account_id: int) -> Any:
        """Get the active page for an account's browser instance."""
        with self._lock:
            instance = self._instances.get(account_id)
        if not instance:
            raise RuntimeError(f"No browser instance for account {account_id}")
        if instance.page is None or instance.page.is_closed():
            instance.page = self._run_async(self._create_page(instance))
        return instance.page

    def close_instance(self, account_id: int):
        """Force close a specific browser instance."""
        with self._lock:
            instance = self._instances.pop(account_id, None)
        if not instance:
            return
        try:
            self._run_async(self._close_instance(instance))
        except Exception as e:
            logger.error("Error force-closing instance for account %d: %s", account_id, e)
        logger.info("Closed browser instance for account %d", account_id)

    def get_pool_status(self) -> dict:
        """Return pool status: active count, idle count, instance details."""
        with self._lock:
            instances = dict(self._instances)

        active = 0
        idle = 0
        error = 0
        details = []

        for account_id, inst in instances.items():
            if inst.status == "in_use":
                active += 1
            elif inst.status == "idle":
                idle += 1
            elif inst.status == "error":
                error += 1

            details.append({
                "account_id": account_id,
                "mode": inst.mode,
                "status": inst.status,
                "profile_dir": inst.profile_dir,
                "cdp_url": inst.cdp_url,
                "created_at": inst.created_at,
                "last_used_at": inst.last_used_at,
                "use_count": inst.use_count,
                "error_message": inst.error_message,
                "idle_seconds": time.time() - inst.last_used_at if inst.status == "idle" else 0,
            })

        return {
            "started": self._started,
            "total": len(instances),
            "active": active,
            "idle": idle,
            "error": error,
            "max_instances": self._max_instances,
            "idle_timeout": self._idle_timeout,
            "instances": details,
        }

    # ── Connection modes ───────────────────────────────────────────────────

    def connect_remote_cdp(self, account_id: int, cdp_url: str) -> BrowserInstance:
        """Connect to a remote browser via Chrome DevTools Protocol.

        Used for Docker containers or external browsers like OpenClaw.
        ws://localhost:9222 format.
        """
        with self._lock:
            existing = self._instances.get(account_id)
        if existing and existing.status != "error":
            logger.warning(
                "Account %d already has an instance, closing before CDP connect",
                account_id,
            )
            self.close_instance(account_id)

        instance = self._run_async(self._connect_cdp_browser(account_id, cdp_url))
        instance.status = "in_use"
        instance.last_used_at = time.time()
        instance.use_count = 1

        with self._lock:
            self._instances[account_id] = instance

        # Create page
        instance.page = self._run_async(self._create_page(instance))

        logger.info("Connected to remote CDP for account %d: %s", account_id, cdp_url)
        return instance

    # ── Internal async methods ─────────────────────────────────────────────

    async def _launch_local_browser(
        self,
        account_id: int,
        profile_dir: str,
        proxy_config: dict = None,
        fingerprint: dict = None,
    ) -> BrowserInstance:
        """Launch a local browser with persistent context."""
        from playwright.async_api import async_playwright

        fp = fingerprint or {}
        user_agents = self._config.get("user_agents", [])

        # Build proxy config
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

        # Choose user agent: from fingerprint, or random from list, or default
        ua = fp.get("user_agent")
        if not ua and user_agents:
            ua = random.choice(user_agents)

        # Build viewport from fingerprint screen resolution
        screen_res = fp.get("screen_resolution", [1920, 1080])
        viewport = {"width": screen_res[0], "height": screen_res[1]}

        # Launch persistent context (user data dir = profile_dir)
        pw = await async_playwright().start()

        launch_opts = {
            "user_data_dir": profile_dir,
            "headless": self._config.get("headless", True),
            "viewport": viewport,
            "locale": fp.get("locale", "zh-CN"),
            "timezone_id": fp.get("timezone", "Asia/Shanghai"),
            "color_scheme": fp.get("color_scheme", "light"),
            "ignore_https_errors": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        }
        if ua:
            launch_opts["user_agent"] = ua
        if proxy:
            launch_opts["proxy"] = proxy

        context = await pw.chromium.launch_persistent_context(**launch_opts)

        # Apply anti-detection scripts
        anti_detection_js = _build_anti_detection_script(fp)
        await context.add_init_script(anti_detection_js)

        instance = BrowserInstance(
            account_id=account_id,
            browser=context,  # persistent context IS the browser+context
            profile_dir=profile_dir,
            mode="local",
            status="launching",
            created_at=time.time(),
            _playwright=pw,
        )

        logger.info(
            "Launched persistent browser for account %d (profile=%s)",
            account_id, profile_dir,
        )
        return instance

    async def _connect_cdp_browser(
        self, account_id: int, cdp_url: str
    ) -> BrowserInstance:
        """Connect to remote browser via CDP websocket."""
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(cdp_url)

        # Get or create a context
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
        else:
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                ignore_https_errors=True,
            )

        # Apply anti-detection on the context
        # Use a default fingerprint for CDP connections
        profile_info = self._profile_manager.get_or_create_profile(account_id)
        fp = profile_info["fingerprint"]
        anti_detection_js = _build_anti_detection_script(fp)
        await context.add_init_script(anti_detection_js)

        instance = BrowserInstance(
            account_id=account_id,
            browser=browser,
            cdp_url=cdp_url,
            mode="remote_cdp",
            status="launching",
            created_at=time.time(),
            _playwright=pw,
            _context=context,
        )

        logger.info("Connected to CDP browser for account %d at %s", account_id, cdp_url)
        return instance

    async def _create_page(self, instance: BrowserInstance) -> Any:
        """Create a new page in the browser instance."""
        if instance.mode == "local":
            # For persistent context, new_page() creates a page in the context
            page = await instance.browser.new_page()
        elif instance.mode in ("remote_cdp", "docker"):
            context = instance._context
            if context is None:
                contexts = instance.browser.contexts
                if contexts:
                    context = contexts[0]
                else:
                    context = await instance.browser.new_context()
                instance._context = context
            page = await context.new_page()
        else:
            raise RuntimeError(f"Unknown browser mode: {instance.mode}")

        logger.debug("New page created for account %d", instance.account_id)
        return page

    async def _close_instance(self, instance: BrowserInstance):
        """Close browser instance and cleanup."""
        # Close page
        if instance.page and not instance.page.is_closed():
            try:
                await instance.page.close()
            except Exception as e:
                logger.debug("Error closing page: %s", e)
        instance.page = None

        # Close browser/context
        if instance.browser:
            try:
                await instance.browser.close()
            except Exception as e:
                logger.debug("Error closing browser: %s", e)
            instance.browser = None

        # Close CDP context if separate
        if instance._context:
            try:
                await instance._context.close()
            except Exception:
                pass
            instance._context = None

        # Stop playwright
        if instance._playwright:
            try:
                await instance._playwright.stop()
            except Exception as e:
                logger.debug("Error stopping playwright: %s", e)
            instance._playwright = None

        instance.status = "closed"
        logger.debug("Instance closed for account %d", instance.account_id)

    async def _inject_cookies(self, instance: BrowserInstance, cookies: list, url: str):
        """Inject cookies into browser context."""
        if not cookies:
            return

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
            # For persistent context, add_cookies is on the context itself
            if instance.mode == "local":
                await instance.browser.add_cookies(pw_cookies)
            else:
                context = instance._context or (
                    instance.browser.contexts[0] if instance.browser.contexts else None
                )
                if context:
                    await context.add_cookies(pw_cookies)
            logger.info(
                "Injected %d cookies for account %d (%s)",
                len(pw_cookies), instance.account_id, domain,
            )

    async def _extract_cookies(self, instance: BrowserInstance) -> list:
        """Extract cookies from browser context."""
        if instance.mode == "local":
            cookies = await instance.browser.cookies()
        else:
            context = instance._context or (
                instance.browser.contexts[0] if instance.browser.contexts else None
            )
            if context:
                cookies = await context.cookies()
            else:
                cookies = []

        logger.debug(
            "Extracted %d cookies for account %d",
            len(cookies), instance.account_id,
        )
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

    async def _apply_anti_detection(self, context_or_page):
        """Apply comprehensive anti-detection measures to a context or page.

        This is used as a fallback when init_script wasn't set at launch time
        (e.g., for dynamically created pages on CDP connections).
        """
        # Get default fingerprint values
        fp = {
            "canvas_seed": "fallback_seed",
            "webgl_vendor": "Google Inc. (NVIDIA)",
            "webgl_renderer": "ANGLE (NVIDIA GeForce GTX 1660 SUPER)",
            "audio_seed": 0.001,
            "platform_string": "Win32",
            "hardware_concurrency": 8,
            "device_memory": 8,
            "screen_resolution": [1920, 1080],
            "color_depth": 24,
        }
        script = _build_anti_detection_script(fp)

        # Determine if it's a context or page
        if hasattr(context_or_page, 'add_init_script'):
            await context_or_page.add_init_script(script)
        elif hasattr(context_or_page, 'evaluate'):
            await context_or_page.evaluate(script)

    async def _take_screenshot(self, page, name: str) -> str:
        """Take screenshot and save."""
        screenshot_dir = self._config.get("screenshot_dir", "data/screenshots")
        filename = f"{name}_{int(time.time())}.png"
        filepath = os.path.join(screenshot_dir, filename)
        await page.screenshot(path=filepath, full_page=False)
        logger.info("Screenshot saved: %s", filepath)
        return filepath

    # ── Background threads ─────────────────────────────────────────────────

    def _idle_cleanup_loop(self):
        """Background thread: close idle instances past timeout."""
        logger.debug("Idle cleanup thread started (interval=%ds)", self._cleanup_interval)
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._cleanup_interval)
            if self._stop_event.is_set():
                break

            now = time.time()
            to_close = []

            with self._lock:
                for account_id, instance in list(self._instances.items()):
                    if instance.status == "idle":
                        idle_time = now - instance.last_used_at
                        if idle_time > self._idle_timeout:
                            to_close.append(account_id)
                    elif instance.status == "error":
                        # Also clean up errored instances
                        to_close.append(account_id)

            for account_id in to_close:
                logger.info(
                    "Closing idle/errored browser instance for account %d",
                    account_id,
                )
                try:
                    self.close_instance(account_id)
                except Exception as e:
                    logger.error(
                        "Error during idle cleanup for account %d: %s",
                        account_id, e,
                    )

            if to_close:
                logger.info("Idle cleanup: closed %d instances", len(to_close))

        logger.debug("Idle cleanup thread stopped")

    def _evict_oldest_idle(self):
        """Evict the oldest idle instance to make room for a new one."""
        oldest_id = None
        oldest_time = float('inf')

        with self._lock:
            for account_id, instance in self._instances.items():
                if instance.status == "idle" and instance.last_used_at < oldest_time:
                    oldest_time = instance.last_used_at
                    oldest_id = account_id

        if oldest_id is not None:
            logger.info("Evicting oldest idle instance (account %d) to make room", oldest_id)
            self.close_instance(oldest_id)

    # ── Sync API for Flask threads (backward compatible with BrowserService) ──

    def create_context(self, account_id: int, proxy_config=None, fingerprint=None):
        """Backward-compatible: acquire an instance.

        Returns the browser context (persistent context for local, or BrowserContext for CDP).
        """
        instance = self.acquire(account_id, proxy_config, fingerprint)
        # Return the context object for backward compat
        if instance.mode == "local":
            return instance.browser  # persistent context IS the context
        return instance._context

    def close_context(self, account_id: int):
        """Backward-compatible: release an instance (don't destroy, just idle it)."""
        self.release(account_id)

    def new_page(self, account_id: int):
        """Backward-compatible: get/create page."""
        return self.get_page(account_id)

    def take_screenshot(self, page, name: str) -> str:
        """Take a screenshot synchronously."""
        return self._run_async(self._take_screenshot(page, name))

    def inject_cookies(self, context, cookies: list, url: str):
        """Backward-compatible: inject cookies by finding the instance from context."""
        # Find instance by context reference
        instance = self._find_instance_by_context(context)
        if instance:
            self._run_async(self._inject_cookies(instance, cookies, url))
        else:
            logger.warning("inject_cookies: could not find instance for given context")

    def extract_cookies(self, context) -> list:
        """Backward-compatible: extract cookies by finding the instance from context."""
        instance = self._find_instance_by_context(context)
        if instance:
            return self._run_async(self._extract_cookies(instance))
        logger.warning("extract_cookies: could not find instance for given context")
        return []

    def navigate(self, page, url: str, wait_until: str = "networkidle"):
        """Navigate to URL synchronously."""
        timeout = self._timeout * 1000
        self._run_async(page.goto(url, wait_until=wait_until, timeout=timeout))

    def get_context(self, account_id: int):
        """Return the browser context for backward compat."""
        with self._lock:
            inst = self._instances.get(account_id)
        if not inst:
            return None
        if inst.mode == "local":
            return inst.browser  # persistent context
        return inst._context

    def _find_instance_by_context(self, context) -> Optional[BrowserInstance]:
        """Find a BrowserInstance by its context reference."""
        with self._lock:
            for instance in self._instances.values():
                if instance.mode == "local" and instance.browser is context:
                    return instance
                if instance._context is context:
                    return instance
        return None

    @property
    def active_context_count(self) -> int:
        """Number of tracked browser instances."""
        return len(self._instances)

    @property
    def is_running(self) -> bool:
        """Whether the pool has been started."""
        return self._started
