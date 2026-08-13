"""Integrations package - 内嵌 SynapseAutomation 发布引擎和 MediaCrawler 采集引擎。

所有外部项目源码以 Python 模块形式迁入并通过 sys.path 注入加载，
不走 HTTP / 不开 iframe / 不启原项目独立服务。

延迟导入：EmbeddedSynapseService / EmbeddedMediaCrawlerService 通过
property 访问，避免在 __init__ 阶段就触发原项目源码加载。
"""

__all__ = ["EmbeddedSynapseService", "EmbeddedMediaCrawlerService"]


def __getattr__(name: str):
    if name == "EmbeddedSynapseService":
        from app.integrations.synapse_engine.service import EmbeddedSynapseService

        return EmbeddedSynapseService
    if name == "EmbeddedMediaCrawlerService":
        from app.integrations.mediacrawler_engine.service import (
            EmbeddedMediaCrawlerService,
        )

        return EmbeddedMediaCrawlerService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
