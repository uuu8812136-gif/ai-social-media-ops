"""MediaCrawler 源码加载器（内嵌版，不依赖外部 sys.path 注入）。

原加载策略通过 sys.path.insert(0, MEDIACRAWLER_SRC_DIR) 加载外部源码，
现已改为加载本项目内部 app.integrations.mediacrawler_engine.embedded 包。

提供：
- ensure_loaded(): 始终返回 True（内嵌源码随项目分发）
- apply_config_overrides(): 把配置覆盖写到 EmbeddedConfig 类属性
- get_crawler_factory(): 返回 EmbeddedCrawlerFactory 类
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_loaded = True  # 内嵌源码始终可用


def ensure_loaded() -> bool:
    """检查 MediaCrawler 内嵌源码是否可用。

    Returns:
        始终返回 True（内嵌源码随项目分发，不依赖外部路径）
    """
    return _loaded


def apply_config_overrides(overrides: dict[str, Any] | None = None) -> None:
    """把配置覆盖写到 EmbeddedConfig 类属性。

    Args:
        overrides: 自定义配置覆盖（key -> value）；为空时从 settings 读取默认值
    """
    from app.integrations.mediacrawler_engine.embedded.config import EmbeddedConfig

    # 先从 settings 同步默认配置
    EmbeddedConfig.from_settings()

    # 再应用调用方传入的覆盖
    if overrides:
        EmbeddedConfig.apply_overrides(overrides)

    logger.info(
        "MediaCrawler 配置已同步: headless=%s max_notes=%d save_format=%s",
        EmbeddedConfig.HEADLESS,
        EmbeddedConfig.CRAWLER_MAX_NOTES_COUNT,
        EmbeddedConfig.SAVE_DATA_OPTION,
    )


def get_crawler_factory():
    """返回 EmbeddedCrawlerFactory 类。"""
    from app.integrations.mediacrawler_engine.embedded.factory import (
        EmbeddedCrawlerFactory,
    )

    return EmbeddedCrawlerFactory


__all__ = ["ensure_loaded", "apply_config_overrides", "get_crawler_factory"]
