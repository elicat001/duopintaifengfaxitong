"""Platform login handler registry.

Maps platform names to their login handler classes.
"""

from services.platform_logins.xiaohongshu import XiaohongshuLogin
from services.platform_logins.douyin import DouyinLogin
from services.platform_logins.bilibili import BilibiliLogin
from services.platform_logins.weibo import WeiboLogin
from services.platform_logins.instagram import InstagramLogin
from services.platform_logins.tiktok import TiktokLogin
from services.platform_logins.youtube import YoutubeLogin
from services.platform_logins.twitter import TwitterLogin
from services.platform_logins.facebook import FacebookLogin


PLATFORM_HANDLERS = {
    "xiaohongshu": XiaohongshuLogin,
    "douyin": DouyinLogin,
    "bilibili": BilibiliLogin,
    "weibo": WeiboLogin,
    "instagram": InstagramLogin,
    "tiktok": TiktokLogin,
    "youtube": YoutubeLogin,
    "twitter": TwitterLogin,
    "facebook": FacebookLogin,
}


def get_handler(platform: str, browser_service):
    """Get an instantiated login handler for a platform.

    Args:
        platform: Platform name (must be in PLATFORM_HANDLERS)
        browser_service: BrowserService instance

    Returns: Instantiated platform handler
    Raises: ValueError if platform not supported
    """
    cls = PLATFORM_HANDLERS.get(platform)
    if cls is None:
        supported = ", ".join(sorted(PLATFORM_HANDLERS.keys()))
        raise ValueError(
            f"不支持的平台: {platform}。支持的平台: {supported}"
        )
    return cls(browser_service)


def get_supported_platforms() -> list:
    """Get list of all supported platform names."""
    return sorted(PLATFORM_HANDLERS.keys())


def get_platform_methods(platform: str) -> list:
    """Get supported login methods for a platform."""
    cls = PLATFORM_HANDLERS.get(platform)
    if cls is None:
        return []
    return [m.value for m in cls.SUPPORTED_METHODS]
