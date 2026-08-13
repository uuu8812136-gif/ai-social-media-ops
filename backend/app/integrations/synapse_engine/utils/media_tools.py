"""Media inspection and publish-safe video transcoding helpers."""

from __future__ import annotations

import json
import logging
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.integrations.synapse_engine.utils.video_frames import find_ffmpeg

logger = logging.getLogger(__name__)


_H264_CODECS = {"h264", "avc1"}
_AAC_CODECS = {"aac", "mp4a"}


@dataclass(frozen=True)
class MediaStreamInfo:
    has_video: bool = False
    has_audio: bool = False
    video_codec: str | None = None
    audio_codec: str | None = None


def find_ffprobe() -> str | None:
    """Find ffprobe from PATH or next to ffmpeg."""
    exe = shutil.which("ffprobe")
    if exe:
        return exe

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe.exe" if _is_windows() else "ffprobe")
        if sibling.exists():
            return str(sibling)
    return None


def probe_media(file_path: str, *, timeout_sec: int = 10) -> MediaStreamInfo:
    """Probe media streams with ffprobe, falling back to MP4 atom parsing."""
    path = Path(file_path)
    if not path.exists():
        return MediaStreamInfo()

    info = _probe_with_ffprobe(path, timeout_sec=timeout_sec)
    if info.has_video or info.has_audio:
        return info

    if path.suffix.lower() in {".mp4", ".m4v", ".mov"}:
        return _probe_mp4_atoms(path)
    return info


def ensure_publishable_video(
    file_path: str,
    output_dir: str,
    *,
    require_audio: bool = True,
    transcode: bool = True,
) -> str:
    """Return a publish-safe video path, preserving audio whenever transcoding.

    The output format is MP4 + H.264 video + AAC audio. If the source contains an
    audio stream, the transcoded output must contain one too.
    """
    source = Path(file_path)
    info = probe_media(str(source))
    if not info.has_video:
        return str(source)

    if require_audio and not info.has_audio:
        raise ValueError(
            f"视频素材没有音频轨，发布会变成无声视频：{source.name}。"
            "请上传带声音的视频，或显式设置 allow_silent_video=true。"
        )

    if not transcode or not _needs_h264_aac_transcode(source, info):
        return str(source)

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "需要转码为 H.264/AAC，但当前运行环境没有 ffmpeg。"
            "请重建 backend/celery 镜像或在环境中安装 ffmpeg。"
        )

    target = Path(output_dir) / f"{source.stem}_h264_aac.mp4"
    transcode_to_h264_aac(str(source), str(target), ffmpeg=ffmpeg)

    output_info = probe_media(str(target))
    if info.has_audio and not output_info.has_audio:
        raise RuntimeError(f"视频转码后音轨丢失：{source.name}")
    if not output_info.has_video:
        raise RuntimeError(f"视频转码后没有视频轨：{source.name}")

    logger.info(
        "transcoded video for publishing source=%s target=%s video=%s audio=%s",
        source.name,
        target.name,
        output_info.video_codec,
        output_info.audio_codec,
    )
    return str(target)


def transcode_to_h264_aac(
    source: str, target: str, *, ffmpeg: str | None = None, timeout_sec: int = 600
) -> None:
    """Transcode video to H.264/AAC while preserving optional audio streams."""
    exe = ffmpeg or find_ffmpeg()
    if not exe:
        raise RuntimeError("ffmpeg not found")

    cmd = [
        exe,
        "-y",
        "-i",
        source,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        target,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 转码失败: {result.stderr[-1000:]}")


def _needs_h264_aac_transcode(path: Path, info: MediaStreamInfo) -> bool:
    video_codec = _normalize_codec(info.video_codec)
    audio_codec = _normalize_codec(info.audio_codec)
    if path.suffix.lower() != ".mp4":
        return True
    if video_codec and video_codec not in _H264_CODECS:
        return True
    if info.has_audio and audio_codec and audio_codec not in _AAC_CODECS:
        return True
    return False


def _probe_with_ffprobe(path: Path, *, timeout_sec: int) -> MediaStreamInfo:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return MediaStreamInfo()

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name,codec_tag_string",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_sec
        )
        if result.returncode != 0:
            return MediaStreamInfo()
        data = json.loads(result.stdout or "{}")
    except Exception:
        return MediaStreamInfo()

    return _streams_to_info(data.get("streams") or [])


def _probe_mp4_atoms(path: Path) -> MediaStreamInfo:
    try:
        data = path.read_bytes()
    except OSError:
        return MediaStreamInfo()

    offset = _find_mp4_offset(data)
    if offset:
        data = data[offset:]

    moov = _find_child(data, 0, len(data), "moov")
    if not moov:
        return MediaStreamInfo()

    streams: list[dict[str, str | None]] = []
    for _atom_start, content_start, atom_end, atom_type in _children(
        data, moov[1], moov[2]
    ):
        if atom_type != "trak":
            continue
        handler = _track_handler(data, content_start, atom_end)
        codec = _track_codec(data, content_start, atom_end)
        if handler:
            streams.append(
                {
                    "codec_type": "video"
                    if handler == "vide"
                    else "audio"
                    if handler == "soun"
                    else handler,
                    "codec_name": codec,
                }
            )
    return _streams_to_info(streams)


def _streams_to_info(streams: list[dict]) -> MediaStreamInfo:
    video_codec = None
    audio_codec = None
    for stream in streams:
        kind = stream.get("codec_type")
        codec = stream.get("codec_name") or stream.get("codec_tag_string")
        codec = _normalize_codec(codec)
        if kind == "video" and not video_codec:
            video_codec = codec
        elif kind == "audio" and not audio_codec:
            audio_codec = codec
    return MediaStreamInfo(
        has_video=bool(video_codec),
        has_audio=bool(audio_codec),
        video_codec=video_codec,
        audio_codec=audio_codec,
    )


def _find_mp4_offset(data: bytes) -> int:
    marker = data.find(b"ftyp")
    if marker >= 4:
        return marker - 4
    return 0


def _children(data: bytes, start: int, end: int):
    i = start
    while i + 8 <= end:
        size = struct.unpack(">I", data[i : i + 4])[0]
        atom_type = data[i + 4 : i + 8].decode("latin1", "replace")
        header = 8
        if size == 1 and i + 16 <= end:
            size = struct.unpack(">Q", data[i + 8 : i + 16])[0]
            header = 16
        elif size == 0:
            size = end - i
        if size < header or i + size > end:
            break
        yield i, i + header, i + size, atom_type
        i += size


def _find_child(data: bytes, start: int, end: int, name: str):
    for atom in _children(data, start, end):
        if atom[3] == name:
            return atom
    return None


def _find_path(data: bytes, start: int, end: int, names: list[str]):
    current = (None, start, end, None)
    for name in names:
        found = _find_child(data, current[1], current[2], name)
        if not found:
            return None
        current = found
        if name == "meta":
            current = (current[0], current[1] + 4, current[2], current[3])
    return current


def _track_handler(data: bytes, start: int, end: int) -> str | None:
    hdlr = _find_path(data, start, end, ["mdia", "hdlr"])
    if not hdlr or hdlr[1] + 12 > hdlr[2]:
        return None
    return data[hdlr[1] + 8 : hdlr[1] + 12].decode("latin1", "replace")


def _track_codec(data: bytes, start: int, end: int) -> str | None:
    stsd = _find_path(data, start, end, ["mdia", "minf", "stbl", "stsd"])
    if not stsd or stsd[1] + 16 > stsd[2]:
        return None
    try:
        entry_count = struct.unpack(">I", data[stsd[1] + 4 : stsd[1] + 8])[0]
    except struct.error:
        return None
    if not entry_count:
        return None
    return data[stsd[1] + 12 : stsd[1] + 16].decode("latin1", "replace")


def _normalize_codec(codec: str | None) -> str | None:
    if not codec:
        return None
    codec = codec.lower().strip()
    aliases = {
        "hevc": "hvc1",
        "h265": "hvc1",
        "hev1": "hvc1",
        "mpeg4aac": "aac",
    }
    return aliases.get(codec, codec)


def _is_windows() -> bool:
    import sys

    return sys.platform.startswith("win")


__all__ = [
    "MediaStreamInfo",
    "ensure_publishable_video",
    "find_ffprobe",
    "probe_media",
    "transcode_to_h264_aac",
]
