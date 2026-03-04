"""YouTube platform publisher."""

import logging
import time
from typing import List, Optional

from services.platform_publishers.base import BasePlatformPublisher, PublishResult

logger = logging.getLogger(__name__)


class YoutubePublisher(BasePlatformPublisher):
    PLATFORM = "youtube"
    PUBLISH_URL = "https://studio.youtube.com/"
    HOME_URL = "https://www.youtube.com/"

    async def publish(self, page, content, variant, media_paths):
        start = time.time()
        steps = []
        try:
            if not media_paths:
                return PublishResult(
                    success=False, error_code="no_media",
                    error_message="YouTube发布需要上传视频文件",
                    steps=steps, duration_ms=int((time.time() - start) * 1000),
                )

            # Step 1: Navigate to studio
            await self._safe_goto(page, "https://studio.youtube.com/")
            await self._step_screenshot(page, "01_navigate", steps, "打开YouTube Studio")

            # Step 2: Click CREATE
            await self._click_first(page, [
                'button#create-icon', 'button:has-text("CREATE")',
                'button:has-text("创建")', 'ytcp-button#create-icon',
            ])
            await page.wait_for_timeout(1000)
            await self._click_first(page, [
                'tp-yt-paper-item:has-text("Upload videos")',
                'tp-yt-paper-item:has-text("上传视频")', '#text-item-0',
            ])
            await page.wait_for_timeout(2000)
            await self._step_screenshot(page, "02_upload_dialog", steps, "打开上传对话框")

            # Step 3: Upload video
            file_input = page.locator('input[type="file"]').first
            await file_input.set_input_files(media_paths[0])
            await page.wait_for_timeout(5000)

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

            await self._step_screenshot(page, "03_file_uploaded", steps, "上传视频文件")

            # Step 4: Fill title
            title = self._get_headline(content, variant)
            try:
                title_input = page.locator('#textbox[aria-label*="title"], #title-textarea #textbox').first
                await title_input.click()
                await page.keyboard.press("Control+a")
                await page.keyboard.type(title, delay=20)
            except Exception:
                pass
            await page.wait_for_timeout(500)

            # Step 5: Fill description
            caption = self._get_caption(content, variant)
            try:
                desc_input = page.locator('#textbox[aria-label*="description"], #description-textarea #textbox').first
                await desc_input.click()
                await page.keyboard.type(caption, delay=15)
            except Exception:
                pass
            await page.wait_for_timeout(1000)
            await self._step_screenshot(page, "04_details_filled", steps, f"填写标题和描述")

            # Step 6: Select "Not made for kids"
            await self._click_first(page, [
                'tp-yt-paper-radio-button[name="NOT_MADE_FOR_KIDS"]',
                '#audience tp-yt-paper-radio-button:nth-child(2)',
            ])

            # Step 7: Click Next 3 times
            for _ in range(3):
                await self._click_first(page, ['button#next-button', 'ytcp-button#next-button'])
                await page.wait_for_timeout(2000)
            await self._step_screenshot(page, "05_visibility", steps, "进入可见性设置")

            # Step 8: Select Public + Publish
            await self._click_first(page, [
                'tp-yt-paper-radio-button[name="PUBLIC"]',
                '#privacy-radios tp-yt-paper-radio-button:first-child',
            ])
            await page.wait_for_timeout(1000)
            await self._click_first(page, ['button#done-button', 'ytcp-button#done-button'])
            await page.wait_for_timeout(8000)
            await self._step_screenshot(page, "06_after_publish", steps, "点击发布")

            success = await self.verify_published(page)
            await self._step_screenshot(page, "07_verify", steps, "发布成功" if success else "发布状态未确认")

            return PublishResult(
                success=success,
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
        # PRIMARY: URL-based verification - after publish, YouTube Studio leaves the upload page
        url = page.url.lower()
        if "studio.youtube.com" in url and "/upload" not in url:
            return True

        # SECONDARY: Text-based verification
        for sel in ['text=Video published', 'text=视频已发布', 'a[href*="youtu.be"]', 'a[href*="youtube.com/watch"]']:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False
