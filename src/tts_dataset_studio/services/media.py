from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tts_dataset_studio.domain.models import MediaAsset, SubtitleTrack
from tts_dataset_studio.services.subtitles import find_matching_subtitles, parse_subtitle

LOGGER = logging.getLogger(__name__)

MEDIA_EXTENSIONS = {
    ".wav",
    ".flac",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".avi",
    ".m4v",
}

BITMAP_SUBTITLE_CODECS = {
    "dvb_subtitle",
    "dvd_subtitle",
    "hdmv_pgs_subtitle",
    "xsub",
}


@dataclass(slots=True)
class ToolPaths:
    ffmpeg: str
    ffprobe: str
    mpv: str | None

    @classmethod
    def discover(cls) -> ToolPaths:
        roots = [Path(sys.executable).parent]
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            roots.insert(0, Path(bundle_root))

        def locate(name: str) -> str | None:
            executable = f"{name}.exe"
            for root in roots:
                candidate = root / executable
                if candidate.exists():
                    return str(candidate)
            discovered = shutil.which(name)
            if discovered and Path(discovered).suffix.casefold() == ".com":
                real_executable = Path(discovered).with_suffix(".exe")
                if real_executable.exists():
                    return str(real_executable)
            return discovered

        ffmpeg = locate("ffmpeg")
        ffprobe = locate("ffprobe")
        if not ffmpeg or not ffprobe:
            raise FileNotFoundError("未找到 ffmpeg/ffprobe，请安装后加入 PATH。")
        return cls(ffmpeg=ffmpeg, ffprobe=ffprobe, mpv=locate("mpv"))


def _embedded_subtitle_name(stream: dict, order: int) -> str:
    tags = stream.get("tags") or {}
    language = str(tags.get("language") or "").strip()
    title = str(tags.get("title") or "").strip()
    details = [value for value in (language, title) if value and value != "und"]
    suffix = f" · {' · '.join(details)}" if details else ""
    return f"内嵌字幕 {order}{suffix}"


def _extract_embedded_subtitles(
    media_path: Path,
    streams: list[dict],
    tools: ToolPaths,
) -> list[SubtitleTrack]:
    subtitle_streams = [
        stream
        for stream in streams
        if stream.get("codec_type") == "subtitle"
        and stream.get("codec_name") not in BITMAP_SUBTITLE_CODECS
    ]
    if not subtitle_streams:
        return []
    tracks = []
    with tempfile.TemporaryDirectory(prefix="tts-studio-subtitles-") as folder:
        for order, stream in enumerate(subtitle_streams, start=1):
            stream_index = stream.get("index")
            if stream_index is None:
                continue
            output = Path(folder) / f"embedded-{order}.srt"
            process = subprocess.run(
                [
                    tools.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(media_path),
                    "-map",
                    f"0:{stream_index}",
                    "-c:s",
                    "srt",
                    "-y",
                    str(output),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if process.returncode or not output.is_file():
                LOGGER.warning(
                    "Embedded subtitle stream %s could not be extracted: %s",
                    stream_index,
                    process.stderr.strip(),
                )
                continue
            try:
                track = parse_subtitle(output)
            except ValueError:
                continue
            track.name = _embedded_subtitle_name(stream, order)
            track.source_path = ""
            tracks.append(track)
    return tracks


def probe_media(path: Path, tools: ToolPaths | None = None) -> MediaAsset:
    if not path.exists():
        raise FileNotFoundError(path)
    tools = tools or ToolPaths.discover()
    process = subprocess.run(
        [
            tools.ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if process.returncode:
        raise ValueError(process.stderr.strip() or f"无法读取媒体：{path.name}")
    payload = json.loads(process.stdout)
    streams = payload.get("streams", [])
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    duration = payload.get("format", {}).get("duration")
    if duration is None:
        duration = next((item.get("duration") for item in streams if item.get("duration")), 0)
    asset = MediaAsset.from_path(path)
    asset.duration_ms = round(float(duration or 0) * 1000)
    asset.has_audio = audio is not None
    asset.has_video = video is not None
    asset.sample_rate = int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None
    asset.channels = int(audio["channels"]) if audio and audio.get("channels") else None
    if not asset.has_audio:
        raise ValueError("素材不包含音频轨，无法用于 TTS 数据集。")
    for subtitle_path in find_matching_subtitles(path):
        try:
            asset.subtitle_tracks.append(parse_subtitle(subtitle_path))
        except ValueError:
            continue
    asset.subtitle_tracks.extend(_extract_embedded_subtitles(path, streams, tools))
    if asset.subtitle_tracks:
        asset.export_track_id = asset.subtitle_tracks[0].id
    return asset
