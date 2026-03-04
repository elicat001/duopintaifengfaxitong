"""Platform publisher handler registry."""

from services.platform_publishers.instagram import InstagramPublisher
from services.platform_publishers.twitter import TwitterPublisher
from services.platform_publishers.youtube import YoutubePublisher
from services.platform_publishers.facebook import FacebookPublisher
from services.platform_publishers.tiktok import TiktokPublisher
from services.platform_publishers.xiaohongshu import XiaohongshuPublisher
from services.platform_publishers.bilibili import BilibiliPublisher
from services.platform_publishers.weibo import WeiboPublisher
from services.platform_publishers.douyin import DouyinPublisher


PUBLISHER_HANDLERS = {
    "instagram": InstagramPublisher,
    "twitter": TwitterPublisher,
    "youtube": YoutubePublisher,
    "facebook": FacebookPublisher,
    "tiktok": TiktokPublisher,
    "xiaohongshu": XiaohongshuPublisher,
    "bilibili": BilibiliPublisher,
    "weibo": WeiboPublisher,
    "douyin": DouyinPublisher,
}


def get_publisher(platform: str, browser_service):
    """Get an instantiated publisher handler for a platform."""
    cls = PUBLISHER_HANDLERS.get(platform)
    if cls is None:
        supported = ", ".join(sorted(PUBLISHER_HANDLERS.keys()))
        raise ValueError(f"不支持的发布平台: {platform}。支持的平台: {supported}")
    return cls(browser_service)
