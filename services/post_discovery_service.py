"""Post Discovery Service - discovers posts on platforms for auto-reply campaigns."""

import logging
from typing import List, Optional

from models.database import get_connection
from services.platform_repliers.base import PostInfo

logger = logging.getLogger(__name__)


class PostDiscoveryService:
    """Discovers posts on platforms matching keywords for auto-reply."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def discover_posts(
        self,
        page,
        replier,
        keywords: List[str],
        exclude_keywords: List[str] = None,
        max_results: int = 10,
        account_id: int = None,
    ) -> List[PostInfo]:
        """Search for posts matching keywords on a platform.

        Filters out:
        - Posts already replied to by this account
        - Posts matching exclude_keywords
        - Posts with empty content

        Returns list of PostInfo sorted by engagement.
        """
        all_posts = []
        exclude_keywords = exclude_keywords or []

        for keyword in keywords:
            try:
                posts = await replier.search_posts(page, keyword, max_results=max_results)
                all_posts.extend(posts)
            except Exception as e:
                logger.warning(f"Search failed for keyword '{keyword}': {e}")
                continue

        # Deduplicate by URL
        seen_urls = set()
        unique_posts = []
        for post in all_posts:
            if post.url and post.url not in seen_urls:
                seen_urls.add(post.url)
                unique_posts.append(post)

        # Filter exclude keywords
        if exclude_keywords:
            unique_posts = self._filter_by_exclude_keywords(unique_posts, exclude_keywords)

        # Filter already replied
        if account_id:
            unique_posts = self._filter_duplicates(account_id, unique_posts)

        # Sort by engagement (likes + comments)
        unique_posts = self._sort_by_engagement(unique_posts)

        return unique_posts[:max_results]

    def _filter_duplicates(self, account_id: int, posts: List[PostInfo]) -> List[PostInfo]:
        """Remove posts that this account has already targeted."""
        if not posts:
            return posts

        conn = get_connection(self.db_path)
        try:
            # Get all post URLs already targeted by this account
            rows = conn.execute(
                """SELECT post_url FROM reply_tasks
                   WHERE account_id = ? AND state NOT IN ('cancelled', 'skipped')""",
                (account_id,)
            ).fetchall()
            existing_urls = {row["post_url"] for row in rows}
            return [p for p in posts if p.url not in existing_urls]
        finally:
            conn.close()

    def _filter_by_exclude_keywords(self, posts: List[PostInfo], exclude: List[str]) -> List[PostInfo]:
        """Remove posts whose content or title matches exclude patterns."""
        exclude_lower = [kw.lower() for kw in exclude]
        filtered = []
        for post in posts:
            text = f"{post.title} {post.content}".lower()
            if not any(kw in text for kw in exclude_lower):
                filtered.append(post)
        return filtered

    def _sort_by_engagement(self, posts: List[PostInfo]) -> List[PostInfo]:
        """Sort posts by engagement score (likes + comments * 3)."""
        return sorted(posts, key=lambda p: p.likes + p.comments * 3, reverse=True)
