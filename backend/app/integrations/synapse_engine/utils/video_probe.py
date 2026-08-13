"""视频元数据探测工具。

复刻 Synapse utils/video_probe.py，通过 ffprobe 命令读取视频时长、宽高、
旋转角度、朝向、封面建议比例。
"""

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def _find_ffprobe() -> Optional[str]:
    """定位 ffprobe 可执行文件。"""
    candidates = [
        shutil.which("ffprobe"),
        shutil.which("avprobe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def cover_aspect_ratio_for_orientation(orientation: Optional[str]) -> str:
    """根据朝向返回封面建议比例。"""
    if orientation == "portrait":
        return "3:4"
    if orientation == "landscape":
        return "4:3"
    return "1:1"


def probe_video_metadata(file_path: str, *, timeout_sec: int = 10) -> dict:
    """探测视频元数据。

    返回 dict：
        duration: float        视频时长（秒）
        width: int             视频宽度（像素）
        height: int            视频高度（像素）
        rotation: int          旋转角度（0/90/180/270）
        aspect_ratio: str      宽高比 "16:9" / "9:16" / "1:1"
        orientation: str       portrait / landscape / square
        cover_aspect_ratio: str  封面建议比例
    """
    default = {
        "duration": None,
        "width": None,
        "height": None,
        "rotation": 0,
        "aspect_ratio": "1:1",
        "orientation": "square",
        "cover_aspect_ratio": "1:1",
    }
    ffprobe = _find_ffprobe()
    if not ffprobe or not Path(file_path).exists():
        return default

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:stream_tags=rotate:format=duration",
        "-of",
        "json",
        file_path,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_sec
        )
        if result.returncode != 0:
            return default
        data = json.loads(result.stdout or "{}")
    except Exception:
        return default

    streams = data.get("streams", [])
    if not streams:
        return default
    stream = streams[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    duration_str = data.get("format", {}).get("duration") or stream.get("duration")
    try:
        duration = float(duration_str) if duration_str else 0.0
    except (TypeError, ValueError):
        duration = 0.0

    # 旋转角度规范化
    rotate_tag = stream.get("tags", {}).get("rotate", "0")
    try:
        rotation = int(rotate_tag) % 360
    except (TypeError, ValueError):
        rotation = 0
    if rotation in (90, 270):
        width, height = height, width

    # 朝向判断
    if width and height:
        if width > height:
            orientation = "landscape"
            ar = _simplify_ratio(width, height)
        elif height > width:
            orientation = "portrait"
            ar = _simplify_ratio(width, height)
        else:
            orientation = "square"
            ar = "1:1"
    else:
        orientation = "square"
        ar = "1:1"

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "rotation": rotation,
        "aspect_ratio": ar,
        "orientation": orientation,
        "cover_aspect_ratio": cover_aspect_ratio_for_orientation(orientation),
    }


def _simplify_ratio(a: int, b: int) -> str:
    g = math.gcd(a, b)
    if g == 0:
        return "1:1"
    return f"{a // g}:{b // g}"
