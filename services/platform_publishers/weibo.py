"""Weibo platform publisher."""

import logging
import time
from typing import List, Optional

from services.platform_publishers.base import BasePlatformPublisher, PublishResult

logger = logging.getLogger(__name__)


class WeiboPublisher(BasePlatformPublisher):
    PLATFORM = "weibo"
    PUBLISH_URL = "https://weibo.com/"
    HOME_URL = "https://weibo.com/"

    async def publish(self, page, content, variant, media_paths):
        start = time.time()
        steps = []
        try:
            await self._safe_goto(page, self.HOME_URL)
            await self._step_screenshot(page, "01_navigate", steps, "打开微博首页")

            caption = self._get_caption(content, variant)
            for sel in ['textarea[placeholder*="有什么新鲜事"]', 'textarea.W_input', 'div[contenteditable="true"]']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click()
                        await page.wait_for_timeout(500)
                        await page.keyboard.type(caption, delay=20)
                        break
                except Exception:
                    pass
            await page.wait_for_timeout(1000)
            await self._step_screenshot(page, "02_text_filled", steps, f"填写内容: {caption[:50]}...")

            if media_paths:
                await self._click_first(page, ['div[title="图片"]', 'a[title="图片"]', 'div.W_icon_addpic'])
                await page.wait_for_timeout(500)
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

                await self._step_screenshot(page, "03_media_uploaded", steps, f"上传 {len(media_paths)} 张图片")

            posted = await self._click_first(page, ['button:has-text("发布")', 'button:has-text("发送")', 'a.W_btn_a:has-text("发布")'])
            await page.wait_for_timeout(5000)
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
        # PRIMARY: Check if text input has been cleared (post was submitted successfully)
        for sel in ['textarea[placeholder*="有什么新鲜事"]', 'textarea.W_input', 'div[contenteditable="true"]']:
            try:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text_val = await el.input_value() if await el.evaluate("el => el.tagName") == "TEXTAREA" else await el.inner_text()
                    if not text_val or len(text_val.strip()) == 0:
                        return True
            except Exception:
                pass

        # SECONDARY: Text-based verification (Chinese and English)
        for sel in ['text=发布成功', 'text=Post successful', 'div.W_layer_tips']:
            try:
                if await page.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False
