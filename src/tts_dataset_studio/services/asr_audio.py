from __future__ import annotations

import subprocess
from pathlib import Path

from tts_dataset_studio.domain.models import ExportRegion, MediaAsset
from tts_dataset_studio.services.media import ToolPaths


def extract_asr_audio(
    asset: MediaAsset,
    region: ExportRegion,
    destination: Path,
    tools: ToolPaths | None = None,
) -> Path:
    tools = tools or ToolPaths.discover()
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        tools.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{region.start_ms / 1000:.6f}",
        "-to",
        f"{region.end_ms / 1000:.6f}",
        "-i",
        asset.path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-y",
        str(destination),
    ]
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if process.returncode:
        destination.unlink(missing_ok=True)
        raise RuntimeError(process.stderr.strip() or "ASR 临时音频提取失败")
    return destination
