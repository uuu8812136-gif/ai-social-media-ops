"""抖音采集器（MVP 内嵌实现，不依赖外部 MediaCrawler 源码）。

当前能力（MVP）：
- 仅支持关键词搜索列表采集（打开 douyin.com/search 做 DOM 卡片抓取）
- 不支持视频下载、作者主页采集、视频详情、评论采集
- 后续如需接入完整 Douyin_TikTok_Download_API，应按内嵌模块方式迁入本目录，
  不要独立起另一个项目服务

采集流程：
1. 加载抖音登录态（从 Synapse cookie 管理器读取 douyin cookie）
2. 打开抖音搜索页 https://www.douyin.com/search/{keyword}?type=video
3. 滚动加载，解析视频卡片（标题/作者/点赞/封面/video_id）
4. 保存为 JSONL 文件
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.integrations.mediacrawler_engine.embedded.crawlers.base import (
    BaseEmbeddedCrawler,
)
from app.integrations.mediacrawler_engine.embedded.var import (
    keywords_var,
    max_notes_var,
)

logger = logging.getLogger(__name__)


class DouyinCrawler(BaseEmbeddedCrawler):
    """抖音关键词搜索采集器（MVP）。

    仅实现关键词搜索列表采集，不支持 creator/detail/comment 模式。
    """

    def __init__(self):
        super().__init__(platform="dy")

    async def start(self) -> dict[str, Any]:
        """执行抖音关键词搜索采集。

        Returns:
            {
                "success": bool,
                "platform": "dy",
                "items_count": int,
                "output_files": list[dict],
                "error": str | None,
            }
        """
        keywords: list[str] = keywords_var.get()
        max_notes = max_notes_var.get()

        if not keywords:
            return {
                "success": False,
                "platform": "dy",
                "error": "关键词不能为空（请在 params.keywords 传入数组）",
                "items_count": 0,
                "output_files": [],
            }

        logger.info(
            "DouyinCrawler 开始采集 keywords=%s max_notes=%d", keywords, max_notes
        )

        storage_state = self._load_storage_state()
        try:
            await self._launch_browser(storage_state=storage_state)
            # 多关键词逐个搜索，合并结果
            all_items: list[dict] = []
            seen_ids: set[str] = set()
            remaining = max_notes
            for kw in keywords:
                if remaining <= 0:
                    break
                items = await self._search_and_extract(kw, remaining)
                for item in items:
                    vid = item.get("video_id") or item.get("note_id")
                    if vid and vid not in seen_ids:
                        all_items.append(item)
                        seen_ids.add(vid)
                        remaining -= 1
                        if remaining <= 0:
                            break

            output_files: list[dict] = []
            if all_items:
                file_path = self._save_items(all_items)
                if file_path:
                    output_files.append(
                        {
                            "path": file_path,
                            "name": file_path.split("/")[-1].split("\\")[-1],
                            "items_count": len(all_items),
                        }
                    )

            return {
                "success": True,
                "platform": "dy",
                "items_count": len(all_items),
                "output_files": output_files,
                "error": None,
            }
        except Exception as e:
            logger.exception("DouyinCrawler 采集失败")
            return {
                "success": False,
                "platform": "dy",
                "error": str(e),
                "items_count": 0,
                "output_files": [],
            }
        finally:
            await self._close_browser()

    async def _search_and_extract(self, keyword: str, max_notes: int) -> list[dict]:
        """搜索单个关键词并提取视频数据。"""
        page = self._page
        if page is None:
            return []

        # 1. 打开抖音搜索页
        search_url = f"https://www.douyin.com/search/{keyword}?type=video"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)

        # 2. 检查是否需要登录（被重定向到登录页）
        current_url = page.url.lower()
        if "login" in current_url or "passport" in current_url:
            logger.warning("DouyinCrawler 未登录或 cookie 失效，无法采集")
            return []

        # 3. 滚动加载更多内容
        items: list[dict] = []
        scroll_count = 0
        max_scrolls = (max_notes // 10) + 3  # 抖音每次滚动约加载 10 条

        while len(items) < max_notes and scroll_count < max_scrolls:
            # 提取当前页面的视频卡片
            new_items = await self._extract_video_cards(page)
            # 去重（按 video_id）
            existing_ids = {it.get("video_id") for it in items}
            for item in new_items:
                vid = item.get("video_id")
                if vid and vid not in existing_ids:
                    items.append(item)
                    existing_ids.add(vid)
                    if len(items) >= max_notes:
                        break

            if len(items) >= max_notes:
                break

            # 滚动到底部
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(self.config.CRAWLER_MAX_SLEEP_SEC + 1)
            scroll_count += 1

        logger.info("DouyinCrawler 关键词'%s'采集到 %d 条视频", keyword, len(items))
        return items[:max_notes]

    async def _extract_video_cards(self, page) -> list[dict]:
        """从搜索结果页提取视频卡片数据。"""
        items: list[dict] = []
        try:
            # 抖音搜索结果视频卡片选择器
            card_selectors = [
                'li[data-e2e="scroll-list-item"]',
                'div[data-e2e="search-result-list"] li',
                'ul[data-e2e="search-result-list"] li',
                'div[class*="videoCard"]',
                'div[class*="video-card"]',
            ]
            cards = []
            for sel in card_selectors:
                try:
                    found = page.locator(sel)
                    count = await found.count()
                    if count > 0:
                        for i in range(count):
                            cards.append(found.nth(i))
                        break
                except Exception:
                    continue

            for card in cards:
                try:
                    item = await self._parse_card(card)
                    if item:
                        items.append(item)
                except Exception as e:
                    logger.debug("解析视频卡片失败: %s", e)
                    continue
        except Exception as e:
            logger.warning("提取视频卡片失败: %s", e)

        return items

    async def _parse_card(self, card) -> dict | None:
        """解析单个视频卡片。"""
        try:
            # 提取视频链接中的 video_id
            video_id = ""
            video_url = ""
            try:
                # 找卡片内的链接
                link = card.locator('a[href*="/video/"]').first
                if await link.count() > 0:
                    href = await link.get_attribute("href") or ""
                    video_url = (
                        href
                        if href.startswith("http")
                        else f"https://www.douyin.com{href}"
                    )
                    match = re.search(r"/video/(\d+)", href)
                    if match:
                        video_id = match.group(1)
            except Exception:
                pass

            # 提取标题/描述
            title = ""
            try:
                desc_el = card.locator(
                    '[class*="title"], [class*="desc"], [class*="text"]'
                ).first
                if await desc_el.count() > 0:
                    title = (await desc_el.text_content() or "").strip()
            except Exception:
                pass

            # 提取作者
            author = ""
            try:
                author_el = card.locator(
                    '[class*="author"], [class*="nickname"], [class*="user-name"]'
                ).first
                if await author_el.count() > 0:
                    author = (await author_el.text_content() or "").strip()
            except Exception:
                pass

            # 提取点赞数
            liked_count = 0
            try:
                # 抖音点赞数通常在 [class*="like"] 或具体数字元素中
                like_el = card.locator(
                    '[class*="like"], [data-e2e="video-like-count"]'
                ).first
                if await like_el.count() > 0:
                    like_text = (await like_el.text_content() or "").strip()
                    liked_count = _parse_count(like_text)
            except Exception:
                pass

            # 提取封面图
            cover_url = ""
            try:
                img_el = card.locator("img").first
                if await img_el.count() > 0:
                    cover_url = await img_el.get_attribute("src") or ""
            except Exception:
                pass

            if not title and not video_id:
                return None

            return {
                "video_id": video_id,
                "note_id": video_id,  # 统一字段，方便 writeback 解析
                "title": title,
                "desc": title,
                "nickname": author,
                "author": author,
                "liked_count": liked_count,
                "like_count": liked_count,
                "image_list": [cover_url] if cover_url else [],
                "video_url": video_url,
                "type": "video",
                "note_url": video_url,
            }
        except Exception as e:
            logger.debug("解析视频卡片异常: %s", e)
            return None


def _parse_count(text: str) -> int:
    """解析'1.2万' '500' '1.3w' 等数字文本。"""
    if not text:
        return 0
    text = text.strip()
    try:
        if "万" in text or "w" in text.lower():
            num = re.sub(r"[^\d.]", "", text)
            return int(float(num) * 10000) if num else 0
        if "千" in text or "k" in text.lower():
            num = re.sub(r"[^\d.]", "", text)
            return int(float(num) * 1000) if num else 0
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else 0
    except (ValueError, TypeError):
        return 0


__all__ = ["DouyinCrawler"]
