"""小红书采集器（内嵌实现，不依赖外部 MediaCrawler 源码）。

使用 Playwright 直接驱动浏览器进行关键词搜索采集。
替代原项目 media_platform/xhs/ 目录下的复杂实现。

支持多关键词采集：keywords 为列表时逐个搜索并合并结果。
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


class XhsCrawler(BaseEmbeddedCrawler):
    """小红书关键词搜索采集器。"""

    def __init__(self):
        super().__init__(platform="xhs")

    async def start(self) -> dict[str, Any]:
        """执行小红书关键词搜索采集。

        Returns:
            {
                "success": bool,
                "platform": "xhs",
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
                "platform": "xhs",
                "error": "关键词不能为空（请在 params.keywords 传入数组）",
                "items_count": 0,
                "output_files": [],
            }

        logger.info("XhsCrawler 开始采集 keywords=%s max_notes=%d", keywords, max_notes)

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
                    nid = item.get("note_id")
                    if nid and nid not in seen_ids:
                        all_items.append(item)
                        seen_ids.add(nid)
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
                "platform": "xhs",
                "items_count": len(all_items),
                "output_files": output_files,
                "error": None,
            }
        except Exception as e:
            logger.exception("XhsCrawler 采集失败")
            return {
                "success": False,
                "platform": "xhs",
                "error": str(e),
                "items_count": 0,
                "output_files": [],
            }
        finally:
            await self._close_browser()

    async def _search_and_extract(self, keyword: str, max_notes: int) -> list[dict]:
        """搜索单个关键词并提取笔记数据。"""
        page = self._page
        if page is None:
            return []

        # 1. 打开小红书搜索页
        search_url = f"https://www.xiaohongshu.com/search_result?keyword={keyword}&source=web_search_result_notes"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # 2. 检查是否需要登录（被重定向到登录页）
        if "login" in page.url.lower():
            logger.warning("XhsCrawler 未登录或 cookie 失效，无法采集")
            return []

        # 3. 滚动加载更多内容
        items: list[dict] = []
        scroll_count = 0
        max_scrolls = (max_notes // 20) + 2  # 每次滚动约加载 20 条

        while len(items) < max_notes and scroll_count < max_scrolls:
            # 提取当前页面的笔记卡片
            new_items = await self._extract_note_cards(page)
            # 去重（按 note_id）
            existing_ids = {it.get("note_id") for it in items}
            for item in new_items:
                nid = item.get("note_id")
                if nid and nid not in existing_ids:
                    items.append(item)
                    existing_ids.add(nid)
                    if len(items) >= max_notes:
                        break

            if len(items) >= max_notes:
                break

            # 滚动到底部
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(self.config.CRAWLER_MAX_SLEEP_SEC)
            scroll_count += 1

        logger.info("XhsCrawler 关键词'%s'采集到 %d 条笔记", keyword, len(items))
        return items[:max_notes]

    async def _extract_note_cards(self, page) -> list[dict]:
        """从搜索结果页提取笔记卡片数据。"""
        items: list[dict] = []
        try:
            # 小红书搜索结果笔记卡片选择器
            card_selectors = [
                "section.note-item",
                'div[class*="note-item"]',
                'a[href*="/explore/"]',
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
                    logger.debug("解析卡片失败: %s", e)
                    continue
        except Exception as e:
            logger.warning("提取笔记卡片失败: %s", e)

        return items

    async def _parse_card(self, card) -> dict | None:
        """解析单个笔记卡片。"""
        try:
            # 提取链接中的 note_id
            href = await card.get_attribute("href") or ""
            note_id_match = re.search(r"/explore/([a-f0-9]+)", href)
            note_id = note_id_match.group(1) if note_id_match else ""

            # 提取标题
            title = ""
            try:
                title_el = card.locator('.title, [class*="title"]').first
                if await title_el.count() > 0:
                    title = (await title_el.text_content() or "").strip()
            except Exception:
                pass

            # 提取作者
            author = ""
            try:
                author_el = card.locator(
                    '.author, [class*="author"] .name, .user-info .name'
                ).first
                if await author_el.count() > 0:
                    author = (await author_el.text_content() or "").strip()
            except Exception:
                pass

            # 提取点赞数
            liked_count = 0
            try:
                like_el = card.locator('[class*="like"], .count').first
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

            if not title and not note_id:
                return None

            return {
                "note_id": note_id,
                "title": title,
                "desc": title,
                "nickname": author,
                "author": author,
                "liked_count": liked_count,
                "like_count": liked_count,
                "image_list": [cover_url] if cover_url else [],
                "type": "note",
                "note_url": f"https://www.xiaohongshu.com/explore/{note_id}"
                if note_id
                else "",
            }
        except Exception as e:
            logger.debug("解析卡片异常: %s", e)
            return None


def _parse_count(text: str) -> int:
    """解析'1.2万' '500' 等数字文本。"""
    if not text:
        return 0
    text = text.strip()
    try:
        if "万" in text:
            return int(float(text.replace("万", "")) * 10000)
        if "千" in text:
            return int(float(text.replace("千", "")) * 1000)
        return int(re.sub(r"[^\d]", "", text) or 0)
    except (ValueError, TypeError):
        return 0


__all__ = ["XhsCrawler"]
