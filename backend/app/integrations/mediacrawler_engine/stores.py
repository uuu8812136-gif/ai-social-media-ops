"""采集数据文件解析器。

MediaCrawler 输出文件支持 csv|json|jsonl|sqlite|excel|db 多种格式，
本模块提供统一读取接口，把采集到的笔记/视频数据解析为标准 dict 列表，
供写入 crawler_items 表使用。
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def resolve_data_file(file_path: str | Path) -> Path:
    """Resolve a crawler output file and confine it to MEDIACRAWLER_DATA_DIR."""
    from app.core.config import get_settings

    settings = get_settings()
    base_dir = Path(settings.MEDIACRAWLER_DATA_DIR).resolve()
    try:
        target = Path(file_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("非法采集文件路径") from exc
    if base_dir not in target.parents or not target.is_file():
        raise PermissionError("只允许访问采集数据目录内的文件")
    if target.stat().st_size > settings.CRAWLER_PARSE_MAX_SIZE:
        raise ValueError("采集数据文件超过解析大小限制")
    return target


def parse_data_file(file_path: str | Path) -> list[dict[str, Any]]:
    """根据文件扩展名自动选择解析器。"""
    p = Path(file_path)
    if not p.exists():
        logger.warning("采集文件不存在: %s", p)
        return []

    suffix = p.suffix.lower()
    try:
        if suffix == ".json":
            result = _parse_json(p)
            return _limit_items(result)
        if suffix == ".jsonl":
            return _parse_jsonl(p)
        if suffix == ".csv":
            return _parse_csv(p)
        if suffix == ".db" or suffix == ".sqlite":
            return _parse_sqlite(p)
        if suffix in (".xlsx", ".xls"):
            return _limit_items(_parse_excel(p))
        logger.warning("不支持的采集文件格式: %s", suffix)
        return []
    except Exception as e:
        logger.exception("解析采集文件失败 %s: %s", p, e)
        return []


def _parse_json(p: Path) -> list[dict[str, Any]]:
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _parse_jsonl(p: Path) -> list[dict[str, Any]]:
    from app.core.config import get_settings

    max_items = get_settings().CRAWLER_PARSE_MAX_ITEMS
    result: list[dict[str, Any]] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    result.append(item)
                if len(result) >= max_items:
                    break
            except json.JSONDecodeError:
                continue
    return result


def _parse_csv(p: Path) -> list[dict[str, Any]]:
    from app.core.config import get_settings

    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [
            row for _, row in zip(range(get_settings().CRAWLER_PARSE_MAX_ITEMS), reader)
        ]


def _parse_sqlite(p: Path) -> list[dict[str, Any]]:
    from app.core.config import get_settings

    max_items = get_settings().CRAWLER_PARSE_MAX_ITEMS
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        # 列出所有表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        result: list[dict[str, Any]] = []
        for table in tables:
            if len(result) >= max_items:
                break
            try:
                quoted_table = str(table).replace('"', '""')
                # SQLite identifiers cannot be bound as parameters. The name comes
                # from sqlite_master and embedded quotes are escaped above.
                cursor.execute(
                    f'SELECT * FROM "{quoted_table}" LIMIT ?',  # nosec B608
                    (max_items - len(result),),
                )
                rows = cursor.fetchmany(max_items - len(result))
                for row in rows:
                    result.append(dict(row))
            except sqlite3.Error:
                continue
        return result
    finally:
        conn.close()


def _parse_excel(p: Path) -> list[dict[str, Any]]:
    try:
        import pandas as pd
    except ImportError:
        logger.warning("pandas 未安装，无法解析 Excel 文件")
        return []
    df = pd.read_excel(p)
    return df.to_dict(orient="records")


def _limit_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.core.config import get_settings

    limit = get_settings().CRAWLER_PARSE_MAX_ITEMS
    return [item for item in items if isinstance(item, dict)][:limit]


def list_data_files(
    data_dir: str | Path, platform: str | None = None
) -> list[dict[str, Any]]:
    """列出采集目录下的所有数据文件。"""
    d = Path(data_dir).resolve()
    if not d.exists():
        return []
    files = []
    for ext in ("*.json", "*.jsonl", "*.csv", "*.db", "*.sqlite", "*.xlsx"):
        for p in d.rglob(ext):
            try:
                resolved = p.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if d not in resolved.parents or not resolved.is_file():
                continue
            files.append(
                {
                    "path": str(resolved),
                    "name": resolved.name,
                    "size": resolved.stat().st_size,
                    "modified": resolved.stat().st_mtime,
                    "platform": platform or "",
                }
            )
    return files


__all__ = ["parse_data_file", "list_data_files", "resolve_data_file"]
