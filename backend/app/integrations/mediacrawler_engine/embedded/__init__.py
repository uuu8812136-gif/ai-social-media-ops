"""MediaCrawler 内嵌源码包。

本包提供 MediaCrawler 核心模块的内部实现，替代原项目的 sys.path 注入加载方式：
- config: 全局配置变量（替代 config.base_config）
- var: ContextVars 跨任务传参（替代 var.py）
- factory: CrawlerFactory 采集器工厂（替代 main.CrawlerFactory）
- crawlers: 各平台采集器实现

不依赖 D:\\social-auto-stack\\MediaCrawler 外部源码。
"""

from app.integrations.mediacrawler_engine.embedded.config import EmbeddedConfig
from app.integrations.mediacrawler_engine.embedded.factory import EmbeddedCrawlerFactory
from app.integrations.mediacrawler_engine.embedded.var import (
    clear_context,
    populate_context,
)

__all__ = [
    "EmbeddedConfig",
    "EmbeddedCrawlerFactory",
    "populate_context",
    "clear_context",
]
