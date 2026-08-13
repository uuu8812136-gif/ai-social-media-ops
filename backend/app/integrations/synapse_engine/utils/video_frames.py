"""视频首帧/封面提取工具。

复刻 Synapse utils/video_frames.py 的 extract_first_frame 能力。
优先用 ffmpeg 提取 0.1s 处的首帧，避免黑帧。
"""

import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]


def find_ffmpeg() -> str | None:
    """定位 ffmpeg 可执行文件。

    优先级：
    1. PATH 中的 ffmpeg
    2. 项目根 .playwright-browsers/ffmpeg-*/ffmpeg(.exe)（Playwright 自带）
    """
    exe = shutil.which("ffmpeg")
    if exe:
        return exe

    # 在 Playwright 浏览器目录中查找 ffmpeg
    candidates_dirs = [
        _REPO_ROOT / ".playwright-browsers",
        _REPO_ROOT / "browsers",
    ]
    for base in candidates_dirs:
        if not base.exists():
            continue
        for ffmpeg_dir in base.glob("ffmpeg-*"):
            name = "ffmpeg.exe" if _is_windows() else "ffmpeg"
            candidate = ffmpeg_dir / name
            if candidate.exists():
                return str(candidate)
            # 也可能在子目录
            for f in ffmpeg_dir.rglob(name):
                if f.exists():
                    return str(f)
    return None


def _is_windows() -> bool:
    import sys

    return sys.platform.startswith("win")


def extract_first_frame(
    video_path: str, out_path: str, *, overwrite: bool = True
) -> None:
    """提取视频首帧（在 0.1s 处取一帧），输出为 PNG 图片。

    Args:
        video_path: 输入视频路径
        out_path: 输出图片路径（PNG）
        overwrite: 是否覆盖已存在的输出文件
    Raises:
        FileNotFoundError: ffmpeg 未找到
        RuntimeError: ffmpeg 执行失败
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FileNotFoundError(
            "ffmpeg 未找到，请安装 ffmpeg 或将其加入 PATH。"
            " Windows 可执行: playwright install ffmpeg"
        )
    if not Path(video_path).exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    cmd = [
        ffmpeg,
        "-y" if overwrite else "-n",
        "-ss",
        "0.1",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 提取首帧失败: {result.stderr[-500:]}")


def extract_frame_at(
    video_path: str, out_path: str, timestamp: float = 1.0, *, overwrite: bool = True
) -> None:
    """提取指定时间戳的帧。"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg 未找到")
    cmd = [
        ffmpeg,
        "-y" if overwrite else "-n",
        "-ss",
        str(timestamp),
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 提取帧失败: {result.stderr[-500:]}")
