"""MediaCrawler 内嵌采集器基类。

替代原项目的 base/base_crawler.py AbstractCrawler。
提供 Playwright 浏览器启动、登录态加载、数据保存的通用流程。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.integrations.mediacrawler_engine.embedded.config import EmbeddedConfig
from app.integrations.mediacrawler_engine.embedded.var import (
    save_dir_var,
)

logger = logging.getLogger(__name__)


class BaseEmbeddedCrawler:
    """内嵌采集器基类。

    子类需要实现：
    - _get_login_url() -> str：平台登录页 URL
    - _get_search_url(keyword) -> str：搜索页 URL
    - _extract_items(page) -> list[dict]：从页面提取采集条目
    """

    def __init__(self, platform: str):
        self.platform = platform
        self.config = EmbeddedConfig
        self._browser = None
        self._context = None
        self._page = None
        self._pw = None

    async def start(self) -> dict[str, Any]:
        """启动采集流程（模板方法）。

        Returns:
            {
                "success": bool,
                "platform": str,
                "items_count": int,
                "output_files": list[dict],
                "error": str | None,
            }
        """
        raise NotImplementedError("子类必须实现 start()")

    # ===== 浏览器管理 =====

    async def _launch_browser(
        self,
        storage_state: dict | None = None,
        headless: bool | None = None,
    ) -> None:
        """启动 Playwright 浏览器。"""
        from app.integrations.synapse_engine.utils.playwright_provider import (
            async_playwright,
            configure_windows_event_loop,
        )

        configure_windows_event_loop()
        self._pw = await async_playwright().start()

        headless = self.config.HEADLESS if headless is None else headless
        launch_kwargs: dict[str, Any] = {"headless": headless}

        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        context_kwargs: dict[str, Any] = {
            "user_agent": self.config.BROWSER_USER_AGENT,
            "viewport": {"width": 1280, "height": 800},
        }
        if storage_state:
            context_kwargs["storage_state"] = storage_state
        self._context = await self._browser.new_context(**context_kwargs)
        self._page = await self._context.new_page()

    async def _close_browser(self) -> None:
        """关闭浏览器。"""
        for resource in (self._page, self._context, self._browser):
            if resource is not None:
                try:
                    await resource.close()
                except Exception:
                    pass
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None

    # ===== 数据保存 =====

    def _get_save_dir(self) -> Path:
        """获取保存目录。

        save_dir_var 已由 service 层设置为 data/mediacrawler/{platform}（最终目录），
        直接使用，不再追加 platform，避免出现 {platform}/{platform} 重复路径。
        仅在 save_dir_var 未设置时回退到 SAVE_DATA_DIR/{platform}。
        """
        save_dir = save_dir_var.get()
        if save_dir:
            p = Path(save_dir)
        else:
            p = Path(self.config.SAVE_DATA_DIR) / self.platform
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _save_items(self, items: list[dict]) -> str:
        """把采集条目保存为 JSONL 文件。

        Returns:
            保存的文件路径
        """
        if not items:
            return ""
        save_dir = self._get_save_dir()
        timestamp = int(time.time())
        file_path = save_dir / f"{self.platform}_{timestamp}.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        logger.info("%s 采集保存 %d 条到 %s", self.platform, len(items), file_path)
        return str(file_path)

    # ===== Cookie 加载 =====

    def _load_storage_state(self) -> dict | None:
        """加载平台 cookie（从 Synapse cookie 管理器）。"""
        try:
            from app.integrations.synapse_engine.cookie import CookieManager

            # MediaCrawler 平台代码 -> Synapse 平台名映射
            platform_map = {
                "xhs": "xiaohongshu",
                "dy": "douyin",
                "bili": "bilibili",
                "ks": "kuaishou",
            }
            synapse_platform = platform_map.get(self.platform, self.platform)
            cookie_mgr = CookieManager()
            # 找第一个可用的账号 cookie
            accounts = cookie_mgr.list_accounts(synapse_platform)
            if not accounts:
                return None
            first = accounts[0]
            return cookie_mgr.load(synapse_platform, first.get("account_id", ""))
        except Exception as e:
            logger.warning("%s 加载 cookie 失败: %s", self.platform, e)
            return None


__all__ = ["BaseEmbeddedCrawler"]
