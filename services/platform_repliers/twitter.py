"""Twitter platform replier."""

import logging
import random
import time
from typing import List

from services.platform_repliers.base import BasePlatformReplier, PostInfo, ReplyResult

logger = logging.getLogger(__name__)


class TwitterReplier(BasePlatformReplier):
    PLATFORM = "twitter"
    HOME_URL = "https://x.com/home"
    SEARCH_URL = "https://x.com/search?q={keyword}&src=typed_query&f=live"

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
            for sel in ['div[data-testid="tweetText"]', 'article div[lang]']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        info.content = (await el.inner_text()).strip()
                        info.title = info.content[:50]
                        break
                except Exception:
                    pass
            for sel in ['div[data-testid="User-Name"] a span', 'a[role="link"] span.css-1jxf684']:
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
            # Twitter reply box is on the same page as the tweet
            comment_selectors = [
                'div[data-testid="tweetTextarea_0"] div[role="textbox"]',
                'div[role="textbox"][data-testid="tweetTextarea_0"]',
                'div[data-testid="reply"] div[role="textbox"]',
                'div[role="textbox"]',
            ]
            clicked = await self._click_first(page, comment_selectors)
            if not clicked:
                return ReplyResult(success=False, error_code="no_comment_box",
                                   error_message="未找到回复输入框", steps=steps,
                                   duration_ms=int((time.time() - start) * 1000))
            await self._step_screenshot(page, "comment_focused", steps, "点击回复框")

            await page.wait_for_timeout(random.randint(500, 1500))
            await page.keyboard.type(reply_text, delay=random.randint(40, 70))
            await page.wait_for_timeout(random.randint(2000, 5000))
            await self._step_screenshot(page, "reply_typed", steps, "输入回复内容")

            submitted = await self._click_first(page, [
                'button[data-testid="tweetButtonInline"]',
                'button[data-testid="tweetButton"]',
                'button:has-text("Reply")',
                'button:has-text("回复")',
            ])
            await page.wait_for_timeout(random.randint(3000, 5000))
            await self._step_screenshot(page, "reply_submitted", steps, "提交回复")

            success = await self.verify_reply(page, reply_text)
            return ReplyResult(success=success, steps=steps,
                               screenshot_path=steps[-1].get("screenshot", "") if steps else "",
                               duration_ms=int((time.time() - start) * 1000),
                               error_message="" if success else "回复提交后未验证到")
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

            links = await page.locator('a[href*="/status/"]').all()
            seen = set()
            for link in links:
                if len(results) >= max_results:
                    break
                try:
                    href = await link.get_attribute('href')
                    if href and '/status/' in href and href not in seen:
                        seen.add(href)
                        if not href.startswith('http'):
                            href = f"https://x.com{href}"
                        results.append(PostInfo(url=href))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Search error: {e}")
        return results
