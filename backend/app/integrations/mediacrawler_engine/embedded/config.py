"""MediaCrawler 内嵌配置模块（替代原 config.base_config）。

使用类属性而非模块全局变量，避免并发任务互相覆盖。
原项目的 base_config 模块全局变量模式已废弃。
"""

from __future__ import annotations

from app.core.config import get_settings


class EmbeddedConfig:
    """MediaCrawler 内嵌配置（从项目 settings 读取，不依赖外部源码）。

    原项目使用模块级全局变量（PLATFORM、KEYWORDS、CRAWLER_TYPE 等），
    本实现改为类属性 + 实例属性，避免并发任务互相覆盖。
    """

    # 浏览器配置
    HEADLESS: bool = True
    ENABLE_CDP_MODE: bool = False
    CDP_DEBUG_PORT: int = 9222
    BROWSER_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )

    # 采集数量限制
    CRAWLER_MAX_NOTES_COUNT: int = 20
    CRAWLER_MAX_COMMENTS_COUNT: int = 10

    # 采集开关
    ENABLE_GET_COMMENTS: bool = True
    ENABLE_GET_SUB_COMMENTS: bool = False
    ENABLE_GET_MEDIA: bool = False

    # 并发与节流
    MAX_CONCURRENCY: int = 1
    CRAWLER_MAX_SLEEP_SEC: int = 2

    # 数据保存
    SAVE_DATA_OPTION: str = "jsonl"  # csv|json|jsonl|sqlite|excel|db
    SAVE_DATA_DIR: str = "data/mediacrawler"

    # 平台 API 凭证（从 settings 读取，留空表示不使用 API 模式）
    XHS_ABM: str = ""
    XHS_WEBID: str = ""

    @classmethod
    def from_settings(cls) -> "EmbeddedConfig":
        """从项目 settings 同步默认配置。"""
        settings = get_settings()
        cls.HEADLESS = settings.MEDIACRAWLER_HEADLESS
        cls.ENABLE_CDP_MODE = settings.MEDIACRAWLER_ENABLE_CDP_MODE
        cls.CDP_DEBUG_PORT = settings.MEDIACRAWLER_CDP_DEBUG_PORT
        cls.CRAWLER_MAX_NOTES_COUNT = settings.MEDIACRAWLER_MAX_NOTES_COUNT
        cls.CRAWLER_MAX_COMMENTS_COUNT = settings.MEDIACRAWLER_MAX_COMMENTS_COUNT
        cls.ENABLE_GET_COMMENTS = settings.MEDIACRAWLER_ENABLE_GET_COMMENTS
        cls.ENABLE_GET_SUB_COMMENTS = settings.MEDIACRAWLER_ENABLE_GET_SUB_COMMENTS
        cls.ENABLE_GET_MEDIA = settings.MEDIACRAWLER_ENABLE_GET_MEDIA
        cls.MAX_CONCURRENCY = settings.MEDIACRAWLER_MAX_CONCURRENCY
        cls.CRAWLER_MAX_SLEEP_SEC = settings.MEDIACRAWLER_CRAWLER_MAX_SLEEP_SEC
        cls.SAVE_DATA_OPTION = settings.MEDIACRAWLER_DEFAULT_SAVE_FORMAT
        cls.SAVE_DATA_DIR = settings.MEDIACRAWLER_DATA_DIR
        return cls

    @classmethod
    def apply_overrides(cls, overrides: dict | None = None) -> None:
        """应用配置覆盖。"""
        if not overrides:
            return
        for key, value in overrides.items():
            if hasattr(cls, key):
                setattr(cls, key, value)

    @classmethod
    def as_dict(cls) -> dict:
        """返回当前配置的 dict 形式（用于日志/调试）。"""
        return {
            k: getattr(cls, k)
            for k in dir(cls)
            if not k.startswith("_") and not callable(getattr(cls, k))
        }


__all__ = ["EmbeddedConfig"]
