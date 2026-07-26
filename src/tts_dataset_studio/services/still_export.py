from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tts_dataset_studio.domain.models import MediaAsset
from tts_dataset_studio.services.media import ToolPaths
from tts_dataset_studio.services.naming import format_timecode, sanitize_filename


def still_base_name(asset: MediaAsset, milliseconds: int, template: str) -> str:
    variables = {
        "source": Path(asset.display_name).stem,
        "timecode": format_timecode(milliseconds),
        "milliseconds": max(0, milliseconds),
    }
    try:
        return sanitize_filename(template.format(**variables))
    except (KeyError, ValueError) as exc:
        raise ValueError(f"静帧命名模板无效：{exc}") from exc


def unique_still_path(folder: Path, base_name: str, extension: str) -> Path:
    candidate = folder / f"{base_name}.{extension}"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{base_name}_{counter:03d}.{extension}"
        counter += 1
    return candidate


def export_still(
    asset: MediaAsset,
    milliseconds: int,
    output_folder: Path,
    template: str = "{source}_{timecode}",
    image_format: str = "png",
    jpeg_quality: int = 95,
    tools: ToolPaths | None = None,
) -> Path:
    if not asset.has_video:
        raise ValueError("当前素材没有视频画面。")
    tools = tools or ToolPaths.discover()
    image_format = image_format.casefold()
    if image_format not in {"png", "jpg", "jpeg"}:
        raise ValueError(f"不支持的静帧格式：{image_format}")
    extension = "jpg" if image_format in {"jpg", "jpeg"} else "png"
    output_folder.mkdir(parents=True, exist_ok=True)
    destination = unique_still_path(
        output_folder,
        still_base_name(asset, milliseconds, template),
        extension,
    )
    temporary = destination.with_name(f"{destination.stem}.partial.{extension}")
    command = [
        tools.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        asset.path,
        "-ss",
        f"{max(0, milliseconds) / 1000:.6f}",
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
    ]
    if extension == "jpg":
        qscale = max(2, min(31, round(31 - jpeg_quality * 29 / 100)))
        command += ["-q:v", str(qscale)]
    command.append(str(temporary))
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if process.returncode or not temporary.exists():
        temporary.unlink(missing_ok=True)
        raise RuntimeError(process.stderr.strip() or "静帧导出失败")
    os.replace(temporary, destination)
    return destination
