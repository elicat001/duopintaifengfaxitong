"""Xiaohongshu platform replier."""

import logging
import random
import time
from typing import List

from services.platform_repliers.base import BasePlatformReplier, PostInfo, ReplyResult

logger = logging.getLogger(__name__)


class XiaohongshuReplier(BasePlatformReplier):
    PLATFORM = "xiaohongshu"
    HOME_URL = "https://www.xiaohongshu.com/"
    SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={keyword}&source=web_search_result_notes"

    async def navigate_to_post(self, page, post_url):
        try:
            await self._safe_goto(page, post_url)
            await page.wait_for_timeout(random.randint(2000, 4000))
            return True
        except Exception:
            return False

    async def extract_post_content(self, page):
        info = PostInfo(url=page.url)
        try:
            # Title
            for sel in ['#detail-title', '.title', 'div.note-text h1']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        info.title = (await el.inner_text()).strip()
                        break
                except Exception:
                    pass
            # Content
            for sel in ['#detail-desc', '.desc', '.note-text span']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        info.content = (await el.inner_text()).strip()
                        break
                except Exception:
                    pass
            # Author
            for sel in ['.author-wrapper .username', '.user-nickname', 'a.name']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        info.author = (await el.inner_text()).strip()
                        break
                except Exception:
                    pass
            # Likes
            for sel in ['.like-wrapper span', '.engagement span.count']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        text = (await el.inner_text()).strip()
                        info.likes = int(''.join(filter(str.isdigit, text)) or '0')
                        break
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Extract content error: {e}")
        return info

    async def scroll_to_comments(self, page):
        try:
            # Scroll down to comment section
            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 400)")
                await page.wait_for_timeout(random.randint(500, 1000))
            # Look for comment section
            for sel in ['.comment-container', '#comment-area', '.comments-el']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.scroll_into_view_if_needed()
                        return True
                except Exception:
                    pass
            return True  # Still scrolled down
        except Exception:
            return False

    async def post_reply(self, page, reply_text):
        start = time.time()
        steps = []
        try:
            # Click comment input
            comment_selectors = [
                '#content-textarea',
                '.comment-input',
                'div[contenteditable="true"].reply-input',
                'div[contenteditable="true"]',
                'textarea[placeholder*="评论"]',
                'textarea[placeholder*="说点什么"]',
            ]
            clicked = await self._click_first(page, comment_selectors)
            if not clicked:
                return ReplyResult(success=False, error_code="no_comment_box",
                                   error_message="未找到评论输入框", steps=steps,
                                   duration_ms=int((time.time() - start) * 1000))
            await self._step_screenshot(page, "comment_focused", steps, "点击评论框")

            # Type reply with human-like delays
            await page.wait_for_timeout(random.randint(500, 1500))
            await page.keyboard.type(reply_text, delay=random.randint(40, 70))
            await page.wait_for_timeout(random.randint(2000, 5000))
            await self._step_screenshot(page, "reply_typed", steps, "输入评论内容")

            # Submit
            submitted = await self._click_first(page, [
                'button:has-text("发送")',
                'button:has-text("评论")',
                'button.submit-btn',
                'div.submit-btn',
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
            found = await page.locator(f'text="{short_text}"').count()
            return found > 0
        except Exception:
            return False

    async def search_posts(self, page, keyword, max_results=10):
        results = []
        try:
            url = self.SEARCH_URL.format(keyword=keyword)
            await self._safe_goto(page, url)
            await page.wait_for_timeout(random.randint(3000, 5000))
            await self.human_scroll(page, random.randint(2, 4))

            links = await page.locator('a[href*="/explore/"], a[href*="/discovery/item/"], section.note-item a').all()
            for link in links[:max_results]:
                try:
                    href = await link.get_attribute('href')
                    if href:
                        if not href.startswith('http'):
                            href = f"https://www.xiaohongshu.com{href}"
                        title_text = ""
                        try:
                            title_text = (await link.inner_text()).strip()
                        except Exception:
                            pass
                        results.append(PostInfo(url=href, title=title_text[:100]))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Search error: {e}")
        return results
