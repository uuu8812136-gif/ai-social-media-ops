"""MediaCrawler 内嵌采集器工厂（替代原 main.CrawlerFactory）。

根据平台代码返回对应的内嵌采集器实例。
不支持的平台返回 None（由 service 层降级处理）。

已实现：
- xhs（小红书）：关键词搜索采集
- dy（抖音）：关键词搜索采集
- bili（B站）：关键词搜索采集（beta，未平台级实测）

未实现（返回 None）：
- ks / wb / tieba / zhihu
"""

from __future__ import annotations

import logging
from typing import Any

from app.integrations.mediacrawler_engine.embedded.crawlers.base import (
    BaseEmbeddedCrawler,
)
from app.integrations.mediacrawler_engine.embedded.crawlers.bili import BilibiliCrawler
from app.integrations.mediacrawler_engine.embedded.crawlers.dy import DouyinCrawler
from app.integrations.mediacrawler_engine.embedded.crawlers.xhs import XhsCrawler

logger = logging.getLogger(__name__)


class EmbeddedCrawlerFactory:
    """内嵌采集器工厂。

    支持的平台：
    - xhs（小红书）：关键词搜索采集
    - dy（抖音）：关键词搜索采集
    - bili（B站）：关键词搜索采集（beta）
    - ks / wb / tieba / zhihu：暂未实现，返回 None
    """

    # 平台 -> 采集器类映射
    _CRAWLER_MAP: dict[str, type[BaseEmbeddedCrawler]] = {
        "xhs": XhsCrawler,
        "dy": DouyinCrawler,
        "bili": BilibiliCrawler,
    }

    # 支持但未实现采集器的平台（返回 None + 清晰错误信息）
    _UNSUPPORTED_PLATFORMS = {"ks", "wb", "tieba", "zhihu"}

    @staticmethod
    def create_crawler(
        platform: str, mode: str = "search"
    ) -> BaseEmbeddedCrawler | None:
        """创建采集器实例。

        Args:
            platform: 平台代码（xhs|dy|bili|ks|wb|tieba|zhihu）
            mode: 采集模式（search|creator|detail|comment）

        Returns:
            采集器实例；不支持的平台返回 None
        """
        platform = (platform or "").strip().lower()
        crawler_cls = EmbeddedCrawlerFactory._CRAWLER_MAP.get(platform)
        if crawler_cls is not None:
            logger.info(
                "EmbeddedCrawlerFactory 创建采集器 platform=%s mode=%s", platform, mode
            )
            return crawler_cls()
        if platform in EmbeddedCrawlerFactory._UNSUPPORTED_PLATFORMS:
            logger.warning(
                "EmbeddedCrawlerFactory: 平台 %s 的采集器尚未实现，"
                "请后续迁移 MediaCrawler media_platform/%s/ 源码",
                platform,
                platform,
            )
        else:
            logger.warning("EmbeddedCrawlerFactory: 不支持的平台 %s", platform)
        return None

    @staticmethod
    def list_supported_platforms() -> list[dict[str, Any]]:
        """返回支持的平台列表。

        crawler_available=True 表示已实现真实采集器；
        crawler_available=False 表示平台已知但采集器未实现（前端应禁用）。
        """
        return [
            {
                "platform": "xhs",
                "name": "小红书",
                "alias": "xiaohongshu",
                "crawler_available": True,
            },
            {
                "platform": "dy",
                "name": "抖音",
                "alias": "douyin",
                "crawler_available": True,
            },
            {
                "platform": "bili",
                "name": "B站",
                "alias": "bilibili",
                "crawler_available": True,
            },
            {
                "platform": "ks",
                "name": "快手",
                "alias": "kuaishou",
                "crawler_available": False,
            },
            {
                "platform": "wb",
                "name": "微博",
                "alias": "weibo",
                "crawler_available": False,
            },
        ]


__all__ = ["EmbeddedCrawlerFactory"]
