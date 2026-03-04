"""Bilibili platform publisher."""

import logging
import time
from typing import List, Optional

from services.platform_publishers.base import BasePlatformPublisher, PublishResult

logger = logging.getLogger(__name__)


class BilibiliPublisher(BasePlatformPublisher):
    PLATFORM = "bilibili"
    PUBLISH_URL = "https://member.bilibili.com/platform/upload/text/edit"
    HOME_URL = "https://www.bilibili.com/"

    async def publish(self, page, content, variant, media_paths):
        start = time.time()
        steps = []
        try:
            await self._safe_goto(page, self.PUBLISH_URL)
            await self._step_screenshot(page, "01_navigate", steps, "打开B站投稿页")

            if media_paths:
                file_input = page.locator('input[type="file"]').first
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

                await self._step_screenshot(page, "02_file_uploaded", steps, f"上传 {len(media_paths)} 个文件")

            title = self._get_headline(content, variant)
            for sel in ['input[placeholder*="标题"]', 'input.input-val', '#videoTitle']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.fill(title)
                        break
                except Exception:
                    pass

            caption = self._get_caption(content, variant)
            for sel in ['div.ql-editor', 'div[contenteditable="true"]', 'textarea']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click()
                        await page.keyboard.type(caption, delay=15)
                        break
                except Exception:
                    pass
            await page.wait_for_timeout(1000)
            await self._step_screenshot(page, "03_content_filled", steps, "填写标题和简介")

            posted = await self._click_first(page, ['button:has-text("立即投稿")', 'button:has-text("投稿")', 'button.submit-add'])
            await page.wait_for_timeout(5000)
            await self._step_screenshot(page, "04_after_submit", steps, "点击投稿")

            success = await self.verify_published(page)
            await self._step_screenshot(page, "05_verify", steps, "投稿成功" if success else "投稿状态未确认")

            return PublishResult(
                success=success, steps=steps,
                error_message="" if success else "投稿后未检测到成功状态",
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
        # PRIMARY: URL-based verification - Bilibili redirects away from upload page after success
        url = page.url.lower()
        if "member.bilibili.com" in url and "/upload" not in url and "/edit" not in url:
            return True

        # SECONDARY: Text-based verification (Chinese and English)
        for sel in ['text=投稿成功', 'text=稿件投递成功', 'text=发布成功', 'text=Upload successful']:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False
