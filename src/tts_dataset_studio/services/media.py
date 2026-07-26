from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from tts_dataset_studio.domain.models import MediaAsset
from tts_dataset_studio.services.subtitles import find_matching_subtitles, parse_subtitle

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
    if asset.subtitle_tracks:
        asset.export_track_id = asset.subtitle_tracks[0].id
    return asset
