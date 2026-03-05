"""Facebook platform replier."""

import logging
import random
import time
from typing import List

from services.platform_repliers.base import BasePlatformReplier, PostInfo, ReplyResult

logger = logging.getLogger(__name__)


class FacebookReplier(BasePlatformReplier):
    PLATFORM = "facebook"
    HOME_URL = "https://www.facebook.com/"
    SEARCH_URL = "https://www.facebook.com/search/posts/?q={keyword}"

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
            for sel in ['div[data-ad-preview="message"]', 'div[data-testid="post_message"]', 'div.userContent']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        info.content = (await el.inner_text()).strip()
                        info.title = info.content[:50]
                        break
                except Exception:
                    pass
            for sel in ['strong a', 'h2 a span', 'a[role="link"] strong span']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        info.author = (await el.inner_text()).strip()
                        break
                except Exception:
                    pass
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
                'div[aria-label*="comment"][contenteditable="true"]',
                'div[aria-label*="Comment"][contenteditable="true"]',
                'div[aria-label*="Write a comment"][contenteditable="true"]',
                'form[role="presentation"] div[contenteditable="true"]',
            ]
            clicked = await self._click_first(page, comment_selectors)
            if not clicked:
                # Try clicking "Write a comment" placeholder first
                await self._click_first(page, [
                    'div[aria-label*="Write a comment"]',
                    'div[aria-label*="评论"]',
                    'span:has-text("Write a comment")',
                ])
                await page.wait_for_timeout(1000)
                clicked = await self._click_first(page, comment_selectors)

            if not clicked:
                return ReplyResult(success=False, error_code="no_comment_box",
                                   error_message="未找到评论输入框", steps=steps,
                                   duration_ms=int((time.time() - start) * 1000))
            await self._step_screenshot(page, "comment_focused", steps, "点击评论框")

            await page.wait_for_timeout(random.randint(500, 1500))
            await page.keyboard.type(reply_text, delay=random.randint(40, 80))
            await page.wait_for_timeout(random.randint(2000, 5000))
            await self._step_screenshot(page, "reply_typed", steps, "输入评论内容")

            # Facebook submits with Enter
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

            links = await page.locator('a[href*="/posts/"], a[href*="permalink"]').all()
            seen = set()
            for link in links:
                if len(results) >= max_results:
                    break
                try:
                    href = await link.get_attribute('href')
                    if href and href not in seen:
                        seen.add(href)
                        if not href.startswith('http'):
                            href = f"https://www.facebook.com{href}"
                        results.append(PostInfo(url=href))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Search error: {e}")
        return results
