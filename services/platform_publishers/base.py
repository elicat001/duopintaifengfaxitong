"""Abstract base class for platform publisher handlers."""

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """Result of a publish attempt."""
    success: bool
    platform_post_id: str = ""
    platform_post_url: str = ""
    error_code: str = ""
    error_message: str = ""
    screenshot_path: str = ""
    duration_ms: int = 0
    steps: list = field(default_factory=list)  # [{"step": "name", "screenshot": "path", "message": "..."}]


class BasePlatformPublisher(ABC):
    """Abstract base for all platform publish handlers."""

    PLATFORM: str = ""
    PUBLISH_URL: str = ""
    HOME_URL: str = ""

    def __init__(self, browser_service):
        self.browser = browser_service

    @abstractmethod
    async def publish(
        self, page, content: dict, variant: Optional[dict], media_paths: List[str],
    ) -> PublishResult:
        """Navigate to publish page, fill content, upload media, submit."""

    @abstractmethod
    async def verify_published(self, page) -> bool:
        """Check if the post was successfully published after submission."""

    def _get_caption(self, content: dict, variant: Optional[dict]) -> str:
        """Build caption text from variant or content."""
        if variant and variant.get("caption"):
            text = variant["caption"]
        else:
            text = content.get("title", "")
            body = content.get("body", "")
            if body:
                text = f"{text}\n\n{body}" if text else body

        hashtags = []
        if variant and isinstance(variant.get("hashtags"), list):
            hashtags = variant["hashtags"]
        if hashtags:
            text += "\n" + " ".join(f"#{tag}" for tag in hashtags)
        return text

    def _get_headline(self, content: dict, variant: Optional[dict]) -> str:
        """Get headline/title for platforms with separate title field."""
        if variant and variant.get("headline"):
            return variant["headline"]
        return content.get("title", "")

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

    async def _fill_contenteditable(self, page, selector: str, text: str):
        """Fill a contenteditable div with text."""
        el = page.locator(selector).first
        await el.click()
        await page.wait_for_timeout(300)
        await page.keyboard.type(text, delay=random.randint(15, 40))

    async def _safe_goto(self, page, url: str, timeout: int = 60000):
        """Navigate with fallback: try domcontentloaded first, then load."""
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
        ss = await self._safe_screenshot(page, f"{self.PLATFORM}_{step_name}")
        steps.append({
            "step": step_name,
            "screenshot": ss,
            "message": message or step_name,
        })
        return ss
