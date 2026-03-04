"""TikTok platform publisher."""

import logging
import time
from typing import List, Optional

from services.platform_publishers.base import BasePlatformPublisher, PublishResult

logger = logging.getLogger(__name__)


class TiktokPublisher(BasePlatformPublisher):
    PLATFORM = "tiktok"
    PUBLISH_URL = "https://www.tiktok.com/upload"
    HOME_URL = "https://www.tiktok.com/"

    async def publish(self, page, content, variant, media_paths):
        start = time.time()
        steps = []
        try:
            if not media_paths:
                return PublishResult(
                    success=False, error_code="no_media",
                    error_message="TikTok发布需要上传视频文件",
                    steps=steps, duration_ms=int((time.time() - start) * 1000),
                )

            await self._safe_goto(page, self.PUBLISH_URL)
            await self._step_screenshot(page, "01_navigate", steps, "打开TikTok上传页")

            file_input = page.locator('input[type="file"]').first
            await file_input.set_input_files(media_paths)
            await page.wait_for_timeout(5000 + len(media_paths) * 2000)

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

            await self._step_screenshot(page, "02_file_uploaded", steps, f"上传 {len(media_paths)} 个视频文件")

            caption = self._get_caption(content, variant)
            for sel in [
                'div[contenteditable="true"][data-text="true"]',
                'div.public-DraftEditor-content', 'div[role="textbox"]',
                'div[contenteditable="true"]',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click()
                        await page.keyboard.press("Control+a")
                        await page.keyboard.type(caption, delay=20)
                        break
                except Exception:
                    pass
            await page.wait_for_timeout(2000)
            await self._step_screenshot(page, "03_caption_filled", steps, f"填写描述: {caption[:50]}...")

            posted = await self._click_first(page, [
                'button:has-text("Post")', 'button:has-text("发布")',
                'button[data-e2e="upload-btn"]',
            ])
            await page.wait_for_timeout(8000)
            await self._step_screenshot(page, "04_after_submit", steps, "点击发布")

            success = await self.verify_published(page)
            await self._step_screenshot(page, "05_verify", steps, "发布成功" if success else "发布状态未确认")

            return PublishResult(
                success=success, steps=steps,
                error_message="" if success else "发布后未检测到成功状态",
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            await self._step_screenshot(page, "error", steps, f"异常: {str(e)}")
            return PublishResult(
                success=False, error_code="publish_error",
                error_message=str(e), steps=steps,
                duration_ms=int((time.time() - start) * 1000),
            )

    async def verify_published(self, page) -> bool:
        # PRIMARY: URL-based verification - TikTok redirects away from /upload after publish
        if "/upload" not in page.url:
            return True

        # SECONDARY: Text-based verification
        for sel in ['text=Your video is being uploaded', 'text=uploaded', 'text=已上传',
                    'div:has-text("Your video has been published")']:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False
