"""B站（哔哩哔哩）采集器（MVP 内嵌实现）。

当前能力（beta / 未平台级实测）：
- 仅支持关键词搜索列表采集（打开 search.bilibili.com/video 做 DOM 卡片抓取）
- B站搜索结果页公开可访问，通常无需登录；有 cookie 时复用可降低风控概率
- 不支持 UP 主主页采集、视频详情、评论、弹幕采集

采集流程：
1. （可选）加载 bilibili 登录态（从 Synapse cookie 管理器读取）
2. 打开搜索页 https://search.bilibili.com/video?keyword={keyword}
3. 翻页 / 滚动加载，解析视频卡片（标题/UP主/播放量/封面/bvid）
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


class BilibiliCrawler(BaseEmbeddedCrawler):
    """B站关键词搜索采集器（MVP，仅 search 模式）。"""

    def __init__(self):
        super().__init__(platform="bili")

    async def start(self) -> dict[str, Any]:
        keywords: list[str] = keywords_var.get()
        max_notes = max_notes_var.get()

        if not keywords:
            return {
                "success": False,
                "platform": "bili",
                "error": "关键词不能为空（请在 params.keywords 传入数组）",
                "items_count": 0,
                "output_files": [],
            }

        logger.info(
            "BilibiliCrawler 开始采集 keywords=%s max_notes=%d", keywords, max_notes
        )

        storage_state = self._load_storage_state()
        try:
            await self._launch_browser(storage_state=storage_state)
            all_items: list[dict] = []
            seen_ids: set[str] = set()
            remaining = max_notes
            for kw in keywords:
                if remaining <= 0:
                    break
                items = await self._search_and_extract(kw, remaining)
                for item in items:
                    bvid = item.get("note_id")
                    if bvid and bvid not in seen_ids:
                        all_items.append(item)
                        seen_ids.add(bvid)
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
                "platform": "bili",
                "items_count": len(all_items),
                "output_files": output_files,
                "error": None,
            }
        except Exception as e:
            logger.exception("BilibiliCrawler 采集失败")
            return {
                "success": False,
                "platform": "bili",
                "error": str(e),
                "items_count": 0,
                "output_files": [],
            }
        finally:
            await self._close_browser()

    async def _search_and_extract(self, keyword: str, max_notes: int) -> list[dict]:
        page = self._page
        if page is None:
            return []

        items: list[dict] = []
        seen: set[str] = set()
        max_pages = (max_notes // 20) + 2  # B站搜索每页约 20-30 条
        for page_no in range(1, max_pages + 1):
            if len(items) >= max_notes:
                break
            search_url = (
                f"https://search.bilibili.com/video?keyword={keyword}&page={page_no}"
            )
            try:
                await page.goto(
                    search_url, wait_until="domcontentloaded", timeout=30000
                )
            except Exception as e:
                logger.warning("BilibiliCrawler 打开搜索页失败 page=%d: %s", page_no, e)
                break
            await asyncio.sleep(3)

            new_items = await self._extract_video_cards(page)
            if not new_items:
                # 无更多结果，停止翻页
                break
            for item in new_items:
                bvid = item.get("note_id")
                if bvid and bvid not in seen:
                    items.append(item)
                    seen.add(bvid)
                    if len(items) >= max_notes:
                        break

        logger.info("BilibiliCrawler 关键词'%s'采集到 %d 条", keyword, len(items))
        return items[:max_notes]

    async def _extract_video_cards(self, page) -> list[dict]:
        items: list[dict] = []
        card_selectors = [
            ".bili-video-card",
            ".video-list-item",
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
                logger.debug("解析 B站卡片失败: %s", e)
                continue
        return items

    async def _parse_card(self, card) -> dict | None:
        bvid = ""
        video_url = ""
        try:
            link = card.locator('a[href*="/video/"]').first
            if await link.count() > 0:
                href = await link.get_attribute("href") or ""
                if href.startswith("//"):
                    href = "https:" + href
                video_url = href
                match = re.search(r"/video/(BV[0-9A-Za-z]+)", href)
                if match:
                    bvid = match.group(1)
        except Exception:
            pass

        title = ""
        try:
            tit = card.locator(
                '.bili-video-card__info--tit, [class*="info--tit"], h3'
            ).first
            if await tit.count() > 0:
                title = (
                    (await tit.get_attribute("title"))
                    or (await tit.text_content())
                    or ""
                )
                title = title.strip()
        except Exception:
            pass

        author = ""
        try:
            au = card.locator(
                '.bili-video-card__info--author, [class*="info--author"], [class*="author"]'
            ).first
            if await au.count() > 0:
                author = (await au.text_content() or "").strip()
        except Exception:
            pass

        play_count = 0
        try:
            stat = card.locator(
                '.bili-video-card__stats--item, [class*="stats--item"]'
            ).first
            if await stat.count() > 0:
                play_count = _parse_count((await stat.text_content() or "").strip())
        except Exception:
            pass

        cover_url = ""
        try:
            img = card.locator("img").first
            if await img.count() > 0:
                cover_url = await img.get_attribute("src") or ""
                if cover_url.startswith("//"):
                    cover_url = "https:" + cover_url
        except Exception:
            pass

        if not title and not bvid:
            return None

        return {
            "note_id": bvid,
            "video_id": bvid,
            "title": title,
            "desc": title,
            "nickname": author,
            "author": author,
            "liked_count": play_count,
            "play_count": play_count,
            "image_list": [cover_url] if cover_url else [],
            "video_url": video_url,
            "note_url": video_url,
            "type": "video",
        }


def _parse_count(text: str) -> int:
    """解析'1.2万' '500' '1.3w' 等播放量文本。"""
    if not text:
        return 0
    text = text.strip()
    try:
        if "万" in text or "w" in text.lower():
            num = re.sub(r"[^\d.]", "", text)
            return int(float(num) * 10000) if num else 0
        if "亿" in text:
            num = re.sub(r"[^\d.]", "", text)
            return int(float(num) * 100000000) if num else 0
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else 0
    except (ValueError, TypeError):
        return 0


__all__ = ["BilibiliCrawler"]
