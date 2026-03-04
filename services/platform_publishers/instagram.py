"""Instagram platform publisher."""

import logging
import time
from typing import List, Optional

from services.platform_publishers.base import BasePlatformPublisher, PublishResult

logger = logging.getLogger(__name__)


class InstagramPublisher(BasePlatformPublisher):
    PLATFORM = "instagram"
    PUBLISH_URL = "https://www.instagram.com/"
    HOME_URL = "https://www.instagram.com/"

    async def publish(self, page, content, variant, media_paths):
        start = time.time()
        steps = []
        try:
            if not media_paths:
                return PublishResult(
                    success=False, error_code="no_media",
                    error_message="Instagram发布需要至少一张图片或视频",
                    steps=steps, duration_ms=int((time.time() - start) * 1000),
                )

            # Step 1: Navigate
            await self._safe_goto(page, self.HOME_URL)
            await self._step_screenshot(page, "01_navigate", steps, "打开Instagram首页")

            # Step 2: Click "New post"
            clicked = await self._click_first(page, [
                'svg[aria-label="New post"]', '[aria-label="New post"]',
                'svg[aria-label="新帖子"]', '[aria-label="新帖子"]',
                'a[href="/create/style/"]', 'a[href="/create/select/"]',
            ])
            await page.wait_for_timeout(2000)
            await self._step_screenshot(page, "02_new_post", steps,
                                        "点击新帖子" if clicked else "未找到新帖子按钮")

            # Step 3: Upload file
            file_input = page.locator('input[type="file"]').first
            if len(media_paths) > 1:
                await file_input.set_input_files(media_paths)
            else:
                await file_input.set_input_files(media_paths[0])
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

            await self._step_screenshot(page, "03_file_uploaded", steps, f"上传了 {len(media_paths)} 个文件")

            # Step 4: Click Next (crop + filter)
            for i in range(2):
                await self._click_first(page, [
                    'button:has-text("Next")', 'button:has-text("下一步")',
                    'div[role="button"]:has-text("Next")',
                ])
                await page.wait_for_timeout(1500)
            await self._step_screenshot(page, "04_next_steps", steps, "跳过裁剪和滤镜")

            # Step 5: Fill caption
            caption = self._get_caption(content, variant)
            for sel in [
                'div[aria-label="Write a caption..."]', 'div[aria-label="写下你的想法..."]',
                'textarea[aria-label="Write a caption..."]', 'div[role="textbox"]',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click()
                        await page.keyboard.type(caption, delay=20)
                        break
                except Exception:
                    pass
            await page.wait_for_timeout(1000)
            await self._step_screenshot(page, "05_caption_filled", steps, f"填写描述: {caption[:50]}...")

            # Step 6: Click Share
            shared = await self._click_first(page, [
                'button:has-text("Share")', 'button:has-text("分享")',
                'div[role="button"]:has-text("Share")',
            ])
            await page.wait_for_timeout(6000)
            await self._step_screenshot(page, "06_after_share", steps,
                                        "点击分享" if shared else "未找到分享按钮")

            # Step 7: Verify
            success = await self.verify_published(page)
            await self._step_screenshot(page, "07_verify", steps,
                                        "发布成功" if success else "发布状态未确认")

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
        # PRIMARY: URL-based verification - Instagram redirects to /p/ or /reel/ after publish
        url = page.url.lower()
        if "/p/" in url or "/reel/" in url:
            return True

        # SECONDARY: Text-based verification
        for sel in [
            'text=Your post has been shared', 'text=已分享你的帖子',
        ]:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False
