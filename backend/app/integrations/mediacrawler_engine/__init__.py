"""MediaCrawler 内嵌采集引擎。

把 MediaCrawler 的核心采集能力作为本项目内部 Python 模块加载：
1. 通过 sys.path 注入 MEDIACRAWLER_SRC_DIR，直接 import 原项目 CrawlerFactory
2. 用 CrawlerFactory.create_crawler() + AbstractCrawler.start() 进程内执行采集
3. 不开子进程、不走 HTTP、不启原项目 WebUI

对外只暴露 EmbeddedMediaCrawlerService。
"""

from app.integrations.mediacrawler_engine.service import EmbeddedMediaCrawlerService

__all__ = ["EmbeddedMediaCrawlerService"]
