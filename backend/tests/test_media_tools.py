import struct

import pytest

from app.integrations.synapse_engine.utils import media_tools


def _atom(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + kind + payload


def _trak(handler: bytes, codec: bytes) -> bytes:
    hdlr = _atom(
        b"hdlr", b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00" + handler + (b"\x00" * 12)
    )
    sample_entry = struct.pack(">I", 16) + codec + (b"\x00" * 8)
    stsd = _atom(b"stsd", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + sample_entry)
    return _atom(b"trak", _atom(b"mdia", hdlr + _atom(b"minf", _atom(b"stbl", stsd))))


def _mp4_with_tracks(*tracks: tuple[bytes, bytes]) -> bytes:
    ftyp = _atom(b"ftyp", b"isom\x00\x00\x02\x00isomiso2avc1mp41")
    moov = _atom(b"moov", b"".join(_trak(handler, codec) for handler, codec in tracks))
    return ftyp + moov


def test_mp4_atom_fallback_detects_video_and_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(media_tools, "find_ffprobe", lambda: None)
    path = tmp_path / "with_audio.mp4"
    path.write_bytes(_mp4_with_tracks((b"vide", b"hvc1"), (b"soun", b"mp4a")))

    info = media_tools.probe_media(str(path))

    assert info.has_video is True
    assert info.has_audio is True
    assert info.video_codec == "hvc1"
    assert info.audio_codec == "mp4a"


def test_ensure_publishable_video_blocks_accidental_silent_upload(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(media_tools, "find_ffprobe", lambda: None)
    path = tmp_path / "silent.mp4"
    path.write_bytes(_mp4_with_tracks((b"vide", b"avc1")))

    with pytest.raises(ValueError, match="没有音频轨"):
        media_tools.ensure_publishable_video(str(path), str(tmp_path))


def test_transcode_command_preserves_optional_audio_map(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Result()

    monkeypatch.setattr(media_tools.subprocess, "run", fake_run)

    media_tools.transcode_to_h264_aac("input.mp4", "output.mp4", ffmpeg="ffmpeg")

    cmd = captured["cmd"]
    assert "-map" in cmd
    assert "0:v:0" in cmd
    assert "0:a?" in cmd
    assert "libx264" in cmd
    assert "aac" in cmd
