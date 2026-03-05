"""TikTok platform replier."""

import logging
import random
import time
from typing import List

from services.platform_repliers.base import BasePlatformReplier, PostInfo, ReplyResult

logger = logging.getLogger(__name__)


class TiktokReplier(BasePlatformReplier):
    PLATFORM = "tiktok"
    HOME_URL = "https://www.tiktok.com/"
    SEARCH_URL = "https://www.tiktok.com/search?q={keyword}"

    async def navigate_to_post(self, page, post_url):
        try:
            await self._safe_goto(page, post_url)
            await page.wait_for_timeout(random.randint(3000, 5000))
            return True
        except Exception:
            return False

    async def extract_post_content(self, page):
        info = PostInfo(url=page.url)
        try:
            for sel in ['[data-e2e="browse-video-desc"]', 'div.tiktok-1ejylhp-DivContainer', 'h1']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        info.content = (await el.inner_text()).strip()
                        info.title = info.content[:50]
                        break
                except Exception:
                    pass
            for sel in ['[data-e2e="browse-username"]', 'a[data-e2e="video-author-uniqueid"]']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        info.author = (await el.inner_text()).strip()
                        break
                except Exception:
                    pass
            info.media_type = "video"
        except Exception as e:
            logger.debug(f"Extract content error: {e}")
        return info

    async def scroll_to_comments(self, page):
        try:
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 400)")
                await page.wait_for_timeout(random.randint(500, 1000))
            return True
        except Exception:
            return False

    async def post_reply(self, page, reply_text):
        start = time.time()
        steps = []
        try:
            comment_selectors = [
                '[data-e2e="comment-input"] div[contenteditable="true"]',
                'div[contenteditable="true"][data-placeholder*="comment"]',
                'div[contenteditable="true"][role="textbox"]',
            ]
            clicked = await self._click_first(page, comment_selectors)
            if not clicked:
                return ReplyResult(success=False, error_code="no_comment_box",
                                   error_message="未找到评论输入框", steps=steps,
                                   duration_ms=int((time.time() - start) * 1000))
            await self._step_screenshot(page, "comment_focused", steps, "点击评论框")

            await page.wait_for_timeout(random.randint(500, 1500))
            await page.keyboard.type(reply_text, delay=random.randint(40, 70))
            await page.wait_for_timeout(random.randint(2000, 5000))
            await self._step_screenshot(page, "reply_typed", steps, "输入评论内容")

            submitted = await self._click_first(page, [
                '[data-e2e="comment-post"]',
                'button:has-text("Post")',
            ])
            if not submitted:
                await page.keyboard.press('Enter')
            await page.wait_for_timeout(random.randint(3000, 5000))
            await self._step_screenshot(page, "reply_submitted", steps, "提交评论")

            success = await self.verify_reply(page, reply_text)
            return ReplyResult(success=success, steps=steps,
                               screenshot_path=steps[-1].get("screenshot", "") if steps else "",
                               duration_ms=int((time.time() - start) * 1000),
                               error_message="" if success else "评论提交后未验证到")
        except Exception as e:
            await self._step_screenshot(page, "error", steps, str(e))
            return ReplyResult(success=False, error_code="reply_error",
                               error_message=str(e), steps=steps,
                               duration_ms=int((time.time() - start) * 1000))

    async def verify_reply(self, page, reply_text):
        await page.wait_for_timeout(2000)
        try:
            short_text = reply_text[:20]
            return await page.locator(f'text="{short_text}"').count() > 0
        except Exception:
            return False

    async def search_posts(self, page, keyword, max_results=10):
        results = []
        try:
            url = self.SEARCH_URL.format(keyword=keyword)
            await self._safe_goto(page, url)
            await page.wait_for_timeout(random.randint(3000, 5000))
            await self.human_scroll(page, random.randint(2, 4))

            links = await page.locator('a[href*="/video/"]').all()
            for link in links[:max_results]:
                try:
                    href = await link.get_attribute('href')
                    if href:
                        if not href.startswith('http'):
                            href = f"https://www.tiktok.com{href}"
                        results.append(PostInfo(url=href, media_type="video"))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Search error: {e}")
        return results
