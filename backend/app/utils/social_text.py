"""社媒最终发布文案清理。

模型可以用 hook/body/cta 等结构化字段帮助生成，但这些字段名属于内部元数据，
不应出现在用户实际发布到平台的正文中。
"""

from __future__ import annotations

import json
import re
from typing import Any


_PUBLISH_LABELS = (
    r"开场钩子|开头钩子|内容钩子|钩子|hook|"
    r"正文内容|内容正文|主体内容|正文|"
    r"行动引导|行动号召|结尾引导|CTA|"
    r"视频脚本|口播脚本"
)
_PREFIX_RE = re.compile(
    rf"^\s*(?:(?:[-*•#]+|\d+[.)、])\s*)*"
    rf"(?:\*\*|__)?(?:【)?(?:{_PUBLISH_LABELS})(?:】)?"
    rf"\s*(?:[:：]|[-—])\s*(?:\*\*|__)?\s*",
    re.IGNORECASE,
)
_HEADER_ONLY_RE = re.compile(
    rf"^\s*(?:(?:[-*•#]+|\d+[.)、])\s*)*"
    rf"(?:\*\*|__)?(?:【)?(?:{_PUBLISH_LABELS})(?:】)?"
    rf"(?:\*\*|__)?\s*$",
    re.IGNORECASE,
)
_LOCALIZATION_RE = re.compile(
    r"^\s*(?:(?:[-*•#]+|\d+[.)、])\s*)*"
    r"(?:\*\*|__)?(?:【)?本地化(?:建议|版本|改写)?(?:】)?"
    r"\s*(?:[:：]|[-—])?",
    re.IGNORECASE,
)


def sanitize_publish_text(value: Any) -> str:
    """移除模型结构标签，返回可以直接投递到社媒平台的纯正文。"""
    if value is None:
        return ""
    if isinstance(value, dict):
        parsed = value
        text = ""
    else:
        text = str(value).strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            parsed = None

    structured_payload = False
    if isinstance(parsed, dict):
        structured_payload = True
        body_text = parsed.get("body_text")
        if body_text:
            return sanitize_publish_text(body_text)
        text = "\n".join(
            str(parsed.get(field) or "").strip()
            for field in ("hook", "body", "cta")
            if str(parsed.get(field) or "").strip()
        )

    cleaned: list[str] = []
    for raw_line in text.splitlines():
        if _LOCALIZATION_RE.match(raw_line):
            # localizations 是供运营选择的改写建议，不是主帖正文。
            continue
        if not structured_payload and _HEADER_ONLY_RE.match(raw_line):
            continue
        line = raw_line
        # 兼容模型偶尔输出“正文：钩子：内容”这类重复标签。
        for _ in range(3):
            stripped = _PREFIX_RE.sub("", line, count=1)
            if stripped == line:
                break
            line = stripped
        line = line.strip()
        if line:
            cleaned.append(line)
    return "\n".join(cleaned).strip()
