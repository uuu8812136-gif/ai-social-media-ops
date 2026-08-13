"""MediaCrawler 内嵌采集器包。

导出各平台采集器类和基类。
"""

from app.integrations.mediacrawler_engine.embedded.crawlers.base import (
    BaseEmbeddedCrawler,
)
from app.integrations.mediacrawler_engine.embedded.crawlers.dy import DouyinCrawler
from app.integrations.mediacrawler_engine.embedded.crawlers.xhs import XhsCrawler

__all__ = ["BaseEmbeddedCrawler", "XhsCrawler", "DouyinCrawler"]
