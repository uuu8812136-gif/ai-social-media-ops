"""Parse structured data from LLM responses without leaking Markdown wrappers."""

from __future__ import annotations

import json
import re
from typing import Any


_FENCED_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def clean_model_text(raw: Any) -> str:
    text = str(raw or "").strip()
    match = _FENCED_BLOCK.search(text)
    if match:
        return match.group(1).strip()
    return text.replace("```json", "").replace("```JSON", "").replace("```", "").strip()


def extract_json_value(raw: Any) -> Any:
    """Extract the first valid JSON object/array from a model response."""
    text = clean_model_text(raw)
    candidates = [text]
    candidates.extend(
        match.group(1).strip() for match in _FENCED_BLOCK.finditer(str(raw or ""))
    )

    decoder = json.JSONDecoder()
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            pass
        for index, char in enumerate(candidate):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[index:])
                return value
            except json.JSONDecodeError:
                continue
    return None


def extract_json_object(raw: Any) -> dict[str, Any] | None:
    value = extract_json_value(raw)
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return None


__all__ = ["clean_model_text", "extract_json_value", "extract_json_object"]
