"""Registry for platform reply handlers."""

import logging

logger = logging.getLogger(__name__)


def get_replier(platform: str, browser_service):
    """Return an instance of the appropriate platform replier.

    Lazy imports to avoid circular dependencies.
    """
    platform = platform.lower().strip()

    if platform == "xiaohongshu":
        from services.platform_repliers.xiaohongshu import XiaohongshuReplier
        return XiaohongshuReplier(browser_service)
    elif platform == "douyin":
        from services.platform_repliers.douyin import DouyinReplier
        return DouyinReplier(browser_service)
    elif platform == "weibo":
        from services.platform_repliers.weibo import WeiboReplier
        return WeiboReplier(browser_service)
    elif platform == "bilibili":
        from services.platform_repliers.bilibili import BilibiliReplier
        return BilibiliReplier(browser_service)
    elif platform == "instagram":
        from services.platform_repliers.instagram import InstagramReplier
        return InstagramReplier(browser_service)
    elif platform == "tiktok":
        from services.platform_repliers.tiktok import TiktokReplier
        return TiktokReplier(browser_service)
    elif platform == "youtube":
        from services.platform_repliers.youtube import YoutubeReplier
        return YoutubeReplier(browser_service)
    elif platform == "twitter":
        from services.platform_repliers.twitter import TwitterReplier
        return TwitterReplier(browser_service)
    elif platform == "facebook":
        from services.platform_repliers.facebook import FacebookReplier
        return FacebookReplier(browser_service)
    else:
        raise ValueError(f"Unsupported platform for reply: {platform}")


def get_supported_platforms() -> list:
    """Return list of platforms that support replying."""
    return [
        "xiaohongshu", "douyin", "weibo", "bilibili",
        "instagram", "tiktok", "youtube", "twitter", "facebook",
    ]
