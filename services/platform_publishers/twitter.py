"""Twitter/X platform publisher."""

import logging
import time
from typing import List, Optional

from services.platform_publishers.base import BasePlatformPublisher, PublishResult

logger = logging.getLogger(__name__)


class TwitterPublisher(BasePlatformPublisher):
    PLATFORM = "twitter"
    PUBLISH_URL = "https://x.com/compose/post"
    HOME_URL = "https://x.com/home"

    async def publish(self, page, content, variant, media_paths):
        start = time.time()
        steps = []
        try:
            # Step 1: Navigate
            await self._safe_goto(page, self.PUBLISH_URL)
            await self._step_screenshot(page, "01_navigate", steps, "打开Twitter发帖页")

            # Step 2: Fill tweet text
            caption = self._get_caption(content, variant)
            textbox = page.locator('div[role="textbox"][data-testid="tweetTextarea_0"], div[role="textbox"]').first
            await textbox.click()
            await page.wait_for_timeout(500)
            await page.keyboard.type(caption, delay=30)
            await page.wait_for_timeout(1000)
            await self._step_screenshot(page, "02_text_filled", steps, f"填写内容: {caption[:50]}...")

            # Step 3: Upload media
            if media_paths:
                file_input = page.locator('input[type="file"][accept*="image"], input[type="file"][accept*="video"], input[data-testid="fileInput"]').first
                await file_input.set_input_files(media_paths)
                await page.wait_for_timeout(3000)

                # After file upload, wait for upload indicator to disappear or preview to appear
                for _ in range(15):  # max 30 seconds
                    await page.wait_for_timeout(2000)
                    # Check if file input has been processed (upload progress gone or preview visible)
                    try:
                        progress = page.locator('[class*="progress"], [class*="uploading"], [class*="loading"]')
                        if await progress.count() == 0:
                            break
                    except Exception:
                        break

                await self._step_screenshot(page, "03_media_uploaded", steps, f"上传了 {len(media_paths)} 个文件")

            # Step 4: Click Post
            posted = await self._click_first(page, [
                'button[data-testid="tweetButton"]',
                'button[data-testid="tweetButtonInline"]',
                'button:has-text("Post")',
                'button:has-text("发推")',
            ])
            await page.wait_for_timeout(5000)
            await self._step_screenshot(page, "04_after_submit", steps, "点击发布按钮" if posted else "未找到发布按钮")

            # Step 5: Verify
            success = await self.verify_published(page)
            await self._step_screenshot(page, "05_verify", steps, "发布成功" if success else "发布状态未确认")

            return PublishResult(
                success=success,
                platform_post_url=page.url if success and "/status/" in page.url else "",
                error_message="" if success else "发布后未检测到成功状态",
                steps=steps, duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            await self._step_screenshot(page, "error", steps, f"异常: {str(e)}")
            return PublishResult(
                success=False, error_code="publish_error",
                error_message=str(e), steps=steps,
                duration_ms=int((time.time() - start) * 1000),
            )

    async def verify_published(self, page) -> bool:
        url = page.url.lower()
        if "/compose" not in url and "/status/" in url:
            return True
        for sel in ['div[data-testid="toast"]', 'a[href*="/status/"]']:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False
