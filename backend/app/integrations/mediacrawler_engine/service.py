"""EmbeddedMediaCrawlerService - MediaCrawler 内嵌采集引擎服务。

提供：
1. list_platforms(): 支持的平台列表
2. run_crawl(): 执行一次采集任务（在 Celery worker 中调用）
3. list_data_files(): 列出已采集文件
4. parse_data_files(): 解析采集文件为标准 dict 列表

不调 HTTP、不开子进程、不启原项目 WebUI、不依赖外部源码路径。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.integrations.mediacrawler_engine.embedded.var import (
    clear_context,
    populate_context,
    save_dir_var,
)
from app.integrations.mediacrawler_engine.loader import (
    apply_config_overrides,
    ensure_loaded,
    get_crawler_factory,
)
from app.integrations.mediacrawler_engine.stores import (
    list_data_files as _list_data_files,
    parse_data_file,
    resolve_data_file,
)

logger = logging.getLogger(__name__)


class EmbeddedMediaCrawlerService:
    """MediaCrawler 内嵌采集引擎服务。"""

    _instance: "EmbeddedMediaCrawlerService | None" = None

    def __new__(cls) -> "EmbeddedMediaCrawlerService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.settings = get_settings()
        # 全局串行锁：避免并发任务资源竞争
        self._crawl_lock = asyncio.Lock()

    # ===== 元数据 =====

    @staticmethod
    def list_platforms() -> list[dict]:
        """返回支持的平台列表。"""
        from app.integrations.mediacrawler_engine.embedded.factory import (
            EmbeddedCrawlerFactory,
        )

        return EmbeddedCrawlerFactory.list_supported_platforms()

    def is_available(self) -> bool:
        """检查 MediaCrawler 内嵌源码是否可用（始终 True）。"""
        return ensure_loaded()

    # ===== 采集 =====

    async def run_crawl(
        self,
        platform: str,
        crawler_type: str,
        params: dict[str, Any],
        config_overrides: dict[str, Any] | None = None,
        save_dir: str | None = None,
    ) -> dict[str, Any]:
        """执行一次采集任务。

        必须在 Celery worker 中调用（避免阻塞 FastAPI 主进程）。

        Args:
            platform: 平台代码（xhs|dy|bili|ks|wb|tieba|zhihu）
            crawler_type: 采集类型（search|creator|detail|comment）
            params: 采集参数（关键字、creator_id、note_id 等）
            config_overrides: 覆盖 EmbeddedConfig 的 key-value
            save_dir: 保存目录（不传使用默认）

        Returns:
            {
                "success": True/False,
                "platform": "...",
                "items_count": N,
                "output_files": [...],
                "error": "...",
            }
        """
        async with self._crawl_lock:
            if not ensure_loaded():
                return {
                    "success": False,
                    "platform": platform,
                    "error": "MediaCrawler 内嵌源码不可用",
                    "items_count": 0,
                    "output_files": [],
                }

            try:
                # 1. 覆盖配置
                apply_config_overrides(config_overrides)

                # 2. 设置保存目录到 ContextVar
                if save_dir:
                    Path(save_dir).mkdir(parents=True, exist_ok=True)
                    save_dir_var.set(save_dir)

                # 3. 合并 config_overrides 中的 max_notes/max_comments 到 params
                # 前端可能把 max_notes 放在 config 字段，这里兼容合并
                merged_params = dict(params)
                if config_overrides:
                    for key in ("max_notes", "max_comments"):
                        if key in config_overrides and key not in merged_params:
                            merged_params[key] = config_overrides[key]
                populate_context(platform, crawler_type, merged_params)

                # 4. 创建并启动 crawler
                factory_cls = get_crawler_factory()
                if factory_cls is None:
                    return {
                        "success": False,
                        "platform": platform,
                        "error": "CrawlerFactory 加载失败",
                        "items_count": 0,
                        "output_files": [],
                    }

                factory = factory_cls()
                crawler = factory.create_crawler(platform=platform, mode=crawler_type)
                if crawler is None:
                    return {
                        "success": False,
                        "platform": platform,
                        "error": (
                            f"平台 {platform} 的采集器尚未实现，"
                            f"当前已支持 xhs（小红书）、dy（抖音）关键词搜索采集"
                        ),
                        "items_count": 0,
                        "output_files": [],
                    }

                # 启动采集
                result = await crawler.start()

                # 5. 解析输出文件统计（确保 output_files 格式统一）
                if result.get("success") and result.get("output_files"):
                    data_dir = save_dir or self._default_data_dir(platform)
                    files = _list_data_files(data_dir, platform)
                    total_items = 0
                    parsed_files = []
                    for f in files:
                        items = parse_data_file(resolve_data_file(f["path"]))
                        f["items_count"] = len(items)
                        total_items += len(items)
                        parsed_files.append(f)
                    # 以 crawler 返回的 items_count 为准
                    if result.get("items_count", 0) == 0 and total_items > 0:
                        result["items_count"] = total_items
                    result["output_files"] = parsed_files or result.get(
                        "output_files", []
                    )

                return result
            except Exception as e:
                logger.exception("MediaCrawler 采集失败 platform=%s", platform)
                return {
                    "success": False,
                    "platform": platform,
                    "error": str(e),
                    "items_count": 0,
                    "output_files": [],
                }
            finally:
                clear_context()

    def _default_data_dir(self, platform: str) -> str:
        return str(Path(self.settings.MEDIACRAWLER_DATA_DIR) / platform)

    # ===== 数据文件 =====

    def list_data_files(self, platform: str | None = None) -> list[dict[str, Any]]:
        """列出已采集的数据文件。"""
        data_dir = Path(self.settings.MEDIACRAWLER_DATA_DIR)
        if platform:
            data_dir = data_dir / platform
        return _list_data_files(data_dir, platform)

    def parse_file(self, file_path: str) -> list[dict[str, Any]]:
        """解析单个采集文件为标准 dict 列表。"""
        return parse_data_file(resolve_data_file(file_path))


__all__ = ["EmbeddedMediaCrawlerService"]
