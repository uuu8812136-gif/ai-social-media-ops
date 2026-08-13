"""MediaCrawler 内嵌 ContextVars 模块（替代原 var.py）。

使用 ContextVar 实现任务间隔离，避免并发任务互相覆盖。
原项目的 var.py 模块全局变量模式已废弃。

协议约定：
- keywords_var: list[str]  多关键词列表（前端传入数组，不再 str(list)）
- max_notes_var: int       最大采集条数
- creator_id_var: str      创作者 ID
- note_id_var: str         笔记/视频 ID
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# 采集任务上下文变量（每个任务独立隔离）
platform_var: ContextVar[str] = ContextVar("platform", default="")
crawler_type_var: ContextVar[str] = ContextVar("crawler_type", default="search")
# keywords 为列表，支持多关键词采集
keywords_var: ContextVar[list[str]] = ContextVar("keywords", default=[])
creator_id_var: ContextVar[str] = ContextVar("creator_id", default="")
note_id_var: ContextVar[str] = ContextVar("note_id", default="")
max_notes_var: ContextVar[int] = ContextVar("max_notes", default=20)
max_comments_var: ContextVar[int] = ContextVar("max_comments", default=10)
save_dir_var: ContextVar[str] = ContextVar("save_dir", default="")


def populate_context(
    platform: str,
    crawler_type: str,
    params: dict[str, Any],
) -> None:
    """把采集参数写入 ContextVars。

    Args:
        platform: 平台代码（xhs|dy|bili|ks|wb|tieba|zhihu）
        crawler_type: 采集类型（search|creator|detail|comment）
        params: 采集参数，支持的 key：
            - keywords: list[str] | str  多关键词（数组或单个字符串）
            - creator_id: str            创作者 ID
            - note_id: str               笔记/视频 ID
            - max_notes: int             最大采集条数
            - max_comments: int          最大评论条数
    """
    platform_var.set(platform)
    crawler_type_var.set(crawler_type)

    # keywords: 统一转为 list[str]
    raw_keywords = params.get("keywords")
    if isinstance(raw_keywords, list):
        keywords_var.set([str(k).strip() for k in raw_keywords if str(k).strip()])
    elif isinstance(raw_keywords, str) and raw_keywords.strip():
        # 兼容单个字符串
        keywords_var.set([raw_keywords.strip()])
    else:
        keywords_var.set([])

    creator_id_var.set(str(params.get("creator_id") or ""))
    note_id_var.set(str(params.get("note_id") or ""))

    if params.get("max_notes") is not None:
        try:
            max_notes_var.set(int(params["max_notes"]))
        except (TypeError, ValueError):
            pass
    if params.get("max_comments") is not None:
        try:
            max_comments_var.set(int(params["max_comments"]))
        except (TypeError, ValueError):
            pass


def clear_context() -> None:
    """清空 ContextVars（任务结束时调用）。"""
    for var in (
        platform_var,
        crawler_type_var,
        keywords_var,
        creator_id_var,
        note_id_var,
        max_notes_var,
        max_comments_var,
        save_dir_var,
    ):
        var.set(var.default)  # type: ignore[attr-defined]


__all__ = [
    "platform_var",
    "crawler_type_var",
    "keywords_var",
    "creator_id_var",
    "note_id_var",
    "max_notes_var",
    "max_comments_var",
    "save_dir_var",
    "populate_context",
    "clear_context",
]
