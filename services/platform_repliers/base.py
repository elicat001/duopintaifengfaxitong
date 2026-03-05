"""Abstract base class for platform reply handlers."""

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PostInfo:
    """Extracted information about a target post."""
    url: str = ""
    author: str = ""
    title: str = ""
    content: str = ""
    media_type: str = ""
    likes: int = 0
    comments: int = 0
    tags: list = field(default_factory=list)


@dataclass
class ReplyResult:
    """Result of a reply attempt."""
    success: bool
    reply_url: str = ""
    error_code: str = ""
    error_message: str = ""
    screenshot_path: str = ""
    duration_ms: int = 0
    steps: list = field(default_factory=list)


class BasePlatformReplier(ABC):
    """Abstract base for all platform reply handlers."""

    PLATFORM: str = ""
    HOME_URL: str = ""
    SEARCH_URL: str = ""  # URL template with {keyword} placeholder

    def __init__(self, browser_service):
        self.browser = browser_service

    @abstractmethod
    async def navigate_to_post(self, page, post_url: str) -> bool:
        """Navigate to a specific post URL. Returns True if successful."""

    @abstractmethod
    async def extract_post_content(self, page) -> PostInfo:
        """Extract post title, content, author, metrics from current page."""

    @abstractmethod
    async def scroll_to_comments(self, page) -> bool:
        """Scroll down to the comment section."""

    @abstractmethod
    async def post_reply(self, page, reply_text: str) -> ReplyResult:
        """Type and submit a reply to the post."""

    @abstractmethod
    async def verify_reply(self, page, reply_text: str) -> bool:
        """Verify the reply was successfully posted."""

    @abstractmethod
    async def search_posts(self, page, keyword: str, max_results: int = 10) -> List[PostInfo]:
        """Search for posts matching keyword. Returns list of PostInfo."""

    # ── Shared human-simulation methods ──

    async def simulate_browsing(self, page, browse_count: int = 3):
        """Warm-up: browse homepage feed, click random posts, come back."""
        try:
            await self._safe_goto(page, self.HOME_URL)
            await page.wait_for_timeout(random.randint(2000, 5000))

            # Scroll feed
            scroll_count = random.randint(3, 8)
            await self.human_scroll(page, scroll_count)

            # Click random posts
            for i in range(min(browse_count, 3)):
                try:
                    # Try to find clickable post links
                    links = page.locator('a[href*="/"]').all()
                    visible_links = []
                    for link in await links if hasattr(links, '__aiter__') else []:
                        if await link.is_visible():
                            visible_links.append(link)

                    if not visible_links:
                        # Fallback: just scroll more
                        await self.human_scroll(page, 2)
                        continue

                    target = random.choice(visible_links)
                    await target.click()
                    await page.wait_for_timeout(random.randint(2000, 8000))

                    # Random scroll on the post
                    await self.human_scroll(page, random.randint(1, 3))

                    await page.go_back()
                    await page.wait_for_timeout(random.randint(1000, 3000))
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Warm-up browsing error (non-fatal): {e}")

    async def simulate_reading(self, page, duration_seconds: float):
        """Simulate human reading: slow scroll with variable pauses."""
        elapsed = 0.0
        while elapsed < duration_seconds:
            # Scroll down a bit
            scroll_px = random.randint(100, 300)
            await page.evaluate(f"window.scrollBy(0, {scroll_px})")
            pause = random.uniform(0.5, 1.5)
            await page.wait_for_timeout(int(pause * 1000))
            elapsed += pause

            # Occasionally scroll back up slightly (re-reading)
            if random.random() < 0.2:
                back_px = random.randint(30, 100)
                await page.evaluate(f"window.scrollBy(0, -{back_px})")
                re_pause = random.uniform(0.3, 0.8)
                await page.wait_for_timeout(int(re_pause * 1000))
                elapsed += re_pause

        # 40% chance to hover over author area
        if random.random() < 0.4:
            try:
                await self.random_mouse_movements(page, 1)
            except Exception:
                pass

    async def human_scroll(self, page, scroll_count: int = 3,
                           min_pause: float = 0.5, max_pause: float = 2.0):
        """Scroll with human-like variable speed and pauses."""
        for _ in range(scroll_count):
            scroll_px = random.randint(200, 600)
            await page.evaluate(f"window.scrollBy(0, {scroll_px})")
            pause_ms = int(random.uniform(min_pause, max_pause) * 1000)
            await page.wait_for_timeout(pause_ms)

    async def human_type(self, page, selector: str, text: str,
                         min_delay: int = 30, max_delay: int = 80):
        """Type text character by character with human-like delays.

        Includes thinking pauses, occasional typos with backspace correction.
        """
        el = page.locator(selector).first
        await el.click()
        await page.wait_for_timeout(random.randint(500, 1500))

        chars_typed = 0
        for char in text:
            # Occasional typo (3% chance per character)
            if random.random() < 0.03 and chars_typed > 0:
                wrong_char = random.choice('abcdefghijklmnopqrstuvwxyz')
                await page.keyboard.type(wrong_char, delay=random.randint(min_delay, max_delay))
                await page.wait_for_timeout(random.randint(200, 400))
                await page.keyboard.press('Backspace')
                await page.wait_for_timeout(random.randint(100, 300))

            await page.keyboard.type(char, delay=random.randint(min_delay, max_delay))
            chars_typed += 1

            # Punctuation pause
            if char in '。，、！？.,:;!?':
                await page.wait_for_timeout(random.randint(200, 500))

            # Thinking pause every 10-20 chars
            if chars_typed % random.randint(10, 20) == 0:
                await page.wait_for_timeout(random.randint(500, 2000))

    async def human_type_contenteditable(self, page, selector: str, text: str,
                                          min_delay: int = 30, max_delay: int = 80):
        """Type into a contenteditable div with human-like delays."""
        el = page.locator(selector).first
        await el.click()
        await page.wait_for_timeout(random.randint(500, 1500))

        chars_typed = 0
        for char in text:
            if random.random() < 0.03 and chars_typed > 0:
                wrong_char = random.choice('abcdefghijklmnopqrstuvwxyz')
                await page.keyboard.type(wrong_char, delay=random.randint(min_delay, max_delay))
                await page.wait_for_timeout(random.randint(200, 400))
                await page.keyboard.press('Backspace')
                await page.wait_for_timeout(random.randint(100, 300))

            await page.keyboard.type(char, delay=random.randint(min_delay, max_delay))
            chars_typed += 1

            if char in '。，、！？.,:;!?':
                await page.wait_for_timeout(random.randint(200, 500))

            if chars_typed % random.randint(10, 20) == 0:
                await page.wait_for_timeout(random.randint(500, 2000))

    async def random_mouse_movements(self, page, count: int = 3):
        """Move mouse randomly to simulate human cursor behavior."""
        viewport = page.viewport_size or {"width": 1920, "height": 1080}
        for _ in range(count):
            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)
            await page.mouse.move(x, y)
            await page.wait_for_timeout(random.randint(200, 600))

    # ── Reused helpers from BasePlatformPublisher ──

    async def _click_first(self, page, selectors: list, timeout: int = 3000) -> bool:
        """Try clicking the first visible selector from the list."""
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    await page.wait_for_timeout(random.randint(500, 1000))
                    return True
            except Exception:
                pass
        return False

    async def _safe_goto(self, page, url: str, timeout: int = 60000):
        """Navigate with fallback."""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        except Exception:
            try:
                await page.goto(url, wait_until="load", timeout=timeout)
            except Exception:
                pass
        await page.wait_for_timeout(3000)

    async def _safe_screenshot(self, page, name: str) -> str:
        """Take screenshot, return path or empty string on failure."""
        try:
            return await self.browser._take_screenshot(page, name)
        except Exception:
            return ""

    async def _step_screenshot(self, page, step_name: str, steps: list, message: str = ""):
        """Take a screenshot for a step and append to steps list."""
        ss = await self._safe_screenshot(page, f"{self.PLATFORM}_reply_{step_name}")
        steps.append({
            "step": step_name,
            "screenshot": ss,
            "message": message or step_name,
        })
        return ss
