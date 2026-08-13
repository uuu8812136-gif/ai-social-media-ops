"""平台元数据适配器。

复刻 Synapse myUtils/platform_metadata_adapter.py。
按平台规范格式化标题/描述/话题，避免超长或重复话题。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class PlatformLayout(str, Enum):
    """平台字段布局类型。"""

    SEPARATE = "separate"  # 标题/描述/标签各自独立
    TITLE_DESCRIPTION = "title_description"  # 标题+描述，话题嵌入描述
    COMBINED = "combined"  # 标题/描述/标签合并为一个字段
    TITLE_COMBINED = "title_combined"  # 标题+合并字段


@dataclass
class PlatformFieldConfig:
    """单平台字段配置。"""

    name: str
    code: int
    layout: PlatformLayout
    title_enabled: bool = True
    title_max_length: int = 100
    description_enabled: bool = True
    description_supports_hashtags: bool = True
    tags_enabled: bool = False
    tags_max_count: int = 0
    combined_enabled: bool = False
    combined_max_length: int = 5000


PLATFORM_CONFIGS: dict[int, PlatformFieldConfig] = {
    1: PlatformFieldConfig(  # 小红书
        name="xiaohongshu",
        code=1,
        layout=PlatformLayout.TITLE_DESCRIPTION,
        title_enabled=True,
        title_max_length=20,
        description_enabled=True,
        description_supports_hashtags=True,
        tags_enabled=False,
        tags_max_count=0,
    ),
    2: PlatformFieldConfig(  # 视频号
        name="channels",
        code=2,
        layout=PlatformLayout.TITLE_COMBINED,
        title_enabled=False,
        title_max_length=0,
        description_enabled=True,
        description_supports_hashtags=True,
        tags_enabled=False,
        combined_enabled=True,
        combined_max_length=500,
    ),
    3: PlatformFieldConfig(  # 抖音
        name="douyin",
        code=3,
        layout=PlatformLayout.TITLE_DESCRIPTION,
        title_enabled=True,
        title_max_length=30,
        description_enabled=True,
        description_supports_hashtags=False,
        tags_enabled=True,
        tags_max_count=10,
    ),
    4: PlatformFieldConfig(  # 快手
        name="kuaishou",
        code=4,
        layout=PlatformLayout.COMBINED,
        title_enabled=False,
        description_enabled=True,
        combined_enabled=True,
        combined_max_length=2000,
    ),
    5: PlatformFieldConfig(  # B 站
        name="bilibili",
        code=5,
        layout=PlatformLayout.SEPARATE,
        title_enabled=True,
        title_max_length=80,
        description_enabled=True,
        description_supports_hashtags=True,
        tags_enabled=True,
        tags_max_count=12,
    ),
}


class PlatformMetadataAdapter:
    """平台元数据适配器。"""

    @staticmethod
    def format(
        platform_code: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        config = PLATFORM_CONFIGS.get(platform_code)
        if not config:
            return {
                "title": title or "",
                "description": description or "",
                "tags": tags or [],
            }

        title = title or ""
        description = description or ""
        tags = list(tags or [])

        if config.layout == PlatformLayout.SEPARATE:
            return {
                "title": PlatformMetadataAdapter._truncate(
                    title, config.title_max_length
                ),
                "description": PlatformMetadataAdapter._truncate(
                    description,
                    config.combined_max_length if config.combined_max_length else 5000,
                ),
                "tags": tags[: config.tags_max_count] if config.tags_enabled else [],
            }

        if config.layout == PlatformLayout.TITLE_DESCRIPTION:
            # 话题嵌入描述
            full_description = PlatformMetadataAdapter._merge_description_and_tags(
                description, tags
            )
            return {
                "title": PlatformMetadataAdapter._truncate(
                    title, config.title_max_length
                ),
                "description": PlatformMetadataAdapter._truncate(
                    full_description, 5000
                ),
                "tags": [],
            }

        if config.layout == PlatformLayout.TITLE_COMBINED:
            # 视频号：标题和合并字段
            combined = PlatformMetadataAdapter._merge_description_and_tags(
                description, tags
            )
            if title:
                combined = f"{title}\n{combined}" if combined else title
            return {
                "title": "",
                "description": PlatformMetadataAdapter._truncate(
                    combined, config.combined_max_length
                ),
                "tags": [],
            }

        if config.layout == PlatformLayout.COMBINED:
            # 快手：所有字段合并
            combined = PlatformMetadataAdapter._combine_all(title, description, tags)
            return {
                "title": "",
                "description": PlatformMetadataAdapter._truncate(
                    combined, config.combined_max_length
                ),
                "tags": [],
            }

        return {"title": title, "description": description, "tags": tags}

    @staticmethod
    def _merge_description_and_tags(description: str, tags: list[str]) -> str:
        if not tags:
            return description
        tag_str = " ".join(f"#{t.lstrip('#').strip()}" for t in tags if t)
        if not tag_str:
            return description
        if description:
            return f"{description}\n{tag_str}"
        return tag_str

    @staticmethod
    def _combine_all(title: str, description: str, tags: list[str]) -> str:
        parts = []
        if title:
            parts.append(title)
        if description:
            parts.append(description)
        if tags:
            tag_str = " ".join(f"#{t.lstrip('#').strip()}" for t in tags if t)
            if tag_str:
                parts.append(tag_str)
        return "\n".join(parts)

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        if not text or max_length <= 0:
            return text or ""
        if len(text) <= max_length:
            return text
        return text[:max_length]


def format_metadata_for_platform(platform_code: int, metadata: dict) -> dict:
    """便捷封装：metadata 应包含 title/description/topics。"""
    return PlatformMetadataAdapter.format(
        platform_code,
        title=metadata.get("title"),
        description=metadata.get("description"),
        tags=metadata.get("topics") or metadata.get("tags") or [],
    )
