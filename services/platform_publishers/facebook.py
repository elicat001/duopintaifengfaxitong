"""Facebook platform publisher."""

import logging
import time
from typing import List, Optional

from services.platform_publishers.base import BasePlatformPublisher, PublishResult

logger = logging.getLogger(__name__)


class FacebookPublisher(BasePlatformPublisher):
    PLATFORM = "facebook"
    PUBLISH_URL = "https://www.facebook.com/"
    HOME_URL = "https://www.facebook.com/"

    async def publish(self, page, content, variant, media_paths):
        start = time.time()
        steps = []
        try:
            # Step 1: Navigate to homepage
            await self._safe_goto(page, self.HOME_URL)
            await self._step_screenshot(page, "01_navigate", steps, "打开Facebook首页")

            # Step 2: Click compose box
            clicked = await self._click_first(page, [
                'div[role="button"]:has-text("What\'s on your mind")',
                'div[role="button"]:has-text("你在想什么")',
                'span:has-text("What\'s on your mind")',
                'span:has-text("你在想什么")',
            ])
            await page.wait_for_timeout(2000)
            await self._step_screenshot(page, "02_compose_open", steps,
                                        "打开发帖框" if clicked else "未找到发帖框")
            if not clicked:
                return PublishResult(
                    success=False, error_code="compose_not_found",
                    error_message="未找到Facebook发帖框，可能Cookie已过期或页面结构变化",
                    steps=steps, duration_ms=int((time.time() - start) * 1000),
                )

            # Step 3: Fill post text
            caption = self._get_caption(content, variant)
            filled = False
            for sel in [
                'div[role="textbox"][contenteditable="true"]',
                'div[aria-label*="your mind"]',
                'div[aria-label*="你在想什么"]',
            ]:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click()
                        await page.keyboard.type(caption, delay=25)
                        filled = True
                        break
                except Exception:
                    pass
            await page.wait_for_timeout(1000)
            await self._step_screenshot(page, "03_text_filled", steps,
                                        f"填写内容: {caption[:50]}..." if filled else "未找到文本框")

            # Step 4: Upload media if any
            if media_paths:
                await self._click_first(page, [
                    'div[aria-label="Photo/video"]',
                    'div[aria-label="照片/视频"]',
                ])
                await page.wait_for_timeout(1000)
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

                await self._step_screenshot(page, "04_media_uploaded", steps,
                                            f"上传了 {len(media_paths)} 个文件")

            # Step 5: Click Post button
            posted = await self._click_first(page, [
                'div[aria-label="Post"][role="button"]',
                'div[aria-label="发布"][role="button"]',
                'span:has-text("Post")',
                'span:has-text("发布")',
            ])
            await page.wait_for_timeout(5000)
            await self._step_screenshot(page, "05_after_submit", steps,
                                        "点击发布按钮" if posted else "未找到发布按钮")

            # Step 6: Verify
            success = await self.verify_published(page)
            await self._step_screenshot(page, "06_verify", steps,
                                        "发布成功" if success else "发布状态未确认")

            return PublishResult(
                success=success,
                error_message="" if success else "发布后未检测到成功状态",
                steps=steps,
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
        # PRIMARY: URL-based verification - after posting, Facebook redirects away from compose
        url = page.url.lower()
        if "facebook.com" in url and "/compose" not in url and "dialog" not in url:
            # Check that the compose dialog is no longer visible
            compose_sels = [
                'div[aria-label="Create a post"]',
                'div[aria-label="创建帖子"]',
            ]
            compose_visible = False
            for sel in compose_sels:
                try:
                    if await page.locator(sel).count() > 0:
                        compose_visible = True
                        break
                except Exception:
                    pass
            if not compose_visible:
                return True

        # SECONDARY: Check that compose dialog is gone (fallback)
        compose_sels = [
            'div[aria-label="Create a post"]',
            'div[aria-label="创建帖子"]',
        ]
        for sel in compose_sels:
            try:
                if await page.locator(sel).count() > 0:
                    return False
            except Exception:
                pass
        return True
