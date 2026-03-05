"""Weibo platform replier."""

import logging
import random
import time
from typing import List

from services.platform_repliers.base import BasePlatformReplier, PostInfo, ReplyResult

logger = logging.getLogger(__name__)


class WeiboReplier(BasePlatformReplier):
    PLATFORM = "weibo"
    HOME_URL = "https://weibo.com/"
    SEARCH_URL = "https://s.weibo.com/weibo?q={keyword}"

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
            for sel in ['.weibo-text', 'div[node-type="feed_list_content"]', '.WB_text']:
                try:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        info.content = (await el.inner_text()).strip()
                        info.title = info.content[:50]
                        break
                except Exception:
                    pass
            for sel in ['.username', 'a[nick-name]', '.head-info_nick']:
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
            for _ in range(5):
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
                'textarea[placeholder*="评论"]',
                'textarea[placeholder*="转发理由"]',
                'textarea.W_input',
                'div[contenteditable="true"]',
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
                'button:has-text("评论")',
                'button:has-text("发送")',
                'a.W_btn_a:has-text("评论")',
            ])
            if not submitted:
                await page.keyboard.press('Enter', modifiers=['Control'])
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

            cards = await page.locator('div.card-wrap .content a[href*="weibo.com"]').all()
            for card in cards[:max_results]:
                try:
                    href = await card.get_attribute('href')
                    if href:
                        if not href.startswith('http'):
                            href = f"https:{href}"
                        title_text = ""
                        try:
                            title_text = (await card.inner_text()).strip()
                        except Exception:
                            pass
                        results.append(PostInfo(url=href, title=title_text[:100]))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Search error: {e}")
        return results
