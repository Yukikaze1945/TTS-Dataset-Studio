from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from tts_dataset_studio.domain.models import ExportPreset, ExportRegion, MediaAsset
from tts_dataset_studio.services.media import ToolPaths
from tts_dataset_studio.services.naming import base_name_for_region, unique_output_path


@dataclass(slots=True)
class ExportResult:
    audio_path: Path
    text_path: Path | None


def _codec_args(preset: ExportPreset) -> list[str]:
    if preset.container == "wav":
        return ["-c:a", preset.codec]
    if preset.container == "flac":
        return ["-c:a", "flac", "-compression_level", str(preset.flac_compression)]
    if preset.container == "mp3":
        return ["-c:a", "libmp3lame", "-b:a", preset.mp3_bitrate]
    raise ValueError(f"不支持的导出格式：{preset.container}")


def _detect_peak(
    tools: ToolPaths,
    asset: MediaAsset,
    region: ExportRegion,
    cancel: Event,
) -> float | None:
    if cancel.is_set():
        return None
    process = subprocess.run(
        [
            tools.ffmpeg,
            "-v",
            "info",
            "-i",
            asset.path,
            "-ss",
            f"{region.start_ms / 1000:.6f}",
            "-t",
            f"{(region.end_ms - region.start_ms) / 1000:.6f}",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    match = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", process.stderr)
    return float(match.group(1)) if match else None


def build_ffmpeg_command(
    tools: ToolPaths,
    asset: MediaAsset,
    region: ExportRegion,
    preset: ExportPreset,
    destination: Path,
    normalize_gain_db: float = 0.0,
) -> list[str]:
    duration = (region.end_ms - region.start_ms) / 1000
    gain = 0.0 if asset.gain_bypassed else asset.gain_db
    gain += preset.gain_db + normalize_gain_db
    filters: list[str] = []
    if gain:
        filters.append(f"volume={gain:.3f}dB")
    if preset.fade_in_ms:
        filters.append(f"afade=t=in:st=0:d={preset.fade_in_ms / 1000:.6f}")
    if preset.fade_out_ms:
        fade_start = max(0.0, duration - preset.fade_out_ms / 1000)
        filters.append(
            f"afade=t=out:st={fade_start:.6f}:d={preset.fade_out_ms / 1000:.6f}"
        )
    command = [
        tools.ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        asset.path,
        "-ss",
        f"{region.start_ms / 1000:.6f}",
        "-t",
        f"{duration:.6f}",
        "-map",
        "0:a:0",
        "-vn",
    ]
    if filters:
        command += ["-af", ",".join(filters)]
    if preset.sample_rate:
        command += ["-ar", str(preset.sample_rate)]
    if preset.channels:
        command += ["-ac", str(preset.channels)]
    command += _codec_args(preset)
    command += ["-progress", "pipe:1", "-loglevel", "error", str(destination)]
    return command


def export_region(
    asset: MediaAsset,
    region: ExportRegion,
    preset: ExportPreset,
    index: int,
    cancel: Event,
    progress: Callable[[int], None] | None = None,
    tools: ToolPaths | None = None,
    default_output_dir: str = "",
) -> ExportResult:
    tools = tools or ToolPaths.discover()
    output_folder = (
        Path(preset.output_dir)
        if preset.output_dir
        else Path(default_output_dir)
        if default_output_dir
        else Path(asset.path).parent
    )
    output_folder.mkdir(parents=True, exist_ok=True)
    base_name, text = base_name_for_region(asset, region, preset, index)
    destination = unique_output_path(output_folder, base_name, preset.container)
    temporary = destination.with_name(f"{destination.stem}.partial{destination.suffix}")
    normalize_gain = 0.0
    if preset.peak_normalize:
        peak = _detect_peak(tools, asset, region, cancel)
        if peak is not None:
            normalize_gain = preset.peak_target_db - peak
    command = build_ffmpeg_command(
        tools,
        asset,
        region,
        preset,
        temporary,
        normalize_gain,
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    duration_us = max(1, (region.end_ms - region.start_ms) * 1000)
    assert process.stdout is not None
    for line in process.stdout:
        if cancel.is_set():
            process.terminate()
            process.wait(timeout=5)
            temporary.unlink(missing_ok=True)
            raise InterruptedError("导出已取消")
        if line.startswith("out_time_us=") and progress:
            current = int(line.split("=", 1)[1] or 0)
            progress(min(99, round(current / duration_us * 100)))
    return_code = process.wait()
    if return_code:
        temporary.unlink(missing_ok=True)
        error = process.stderr.read().strip() if process.stderr else ""
        raise RuntimeError(error or "FFmpeg 导出失败")
    os.replace(temporary, destination)
    text_path: Path | None = None
    if preset.write_txt and text is not None:
        text_path = destination.with_suffix(".txt")
        text_path.write_text(text, encoding="utf-8")
    if progress:
        progress(100)
    return ExportResult(destination, text_path)
