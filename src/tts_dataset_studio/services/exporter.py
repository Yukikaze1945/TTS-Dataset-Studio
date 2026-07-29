from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from tts_dataset_studio.domain.models import (
    ExportPreset,
    ExportRegion,
    GeneratedAudioClip,
    MediaAsset,
)
from tts_dataset_studio.services.ai_monitor import audible_audio_tracks
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


def _audible_content(
    asset: MediaAsset,
    region: ExportRegion,
) -> tuple[bool, list[GeneratedAudioClip]]:
    source_audible, generated_tracks = audible_audio_tracks(asset)
    clips = sorted(
        (
            clip
            for track in generated_tracks
            for clip in track.clips
            if clip.start_ms < region.end_ms and region.start_ms < clip.end_ms
            and Path(clip.path).is_file()
        ),
        key=lambda clip: (clip.start_ms, clip.id),
    )
    if not source_audible and not clips:
        raise ValueError(
            "当前选区内没有可导出的可听音轨。"
            "请取消静音 Source，或启用/独奏包含该选区的处理音轨。"
        )
    return source_audible, clips


def _effect_filters(
    asset: MediaAsset,
    region: ExportRegion,
    preset: ExportPreset,
    normalize_gain_db: float,
    analyze_peak: bool,
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
    if analyze_peak:
        filters.append("volumedetect")
    return filters


def _build_audio_pipeline(
    tools: ToolPaths,
    asset: MediaAsset,
    region: ExportRegion,
    preset: ExportPreset,
    normalize_gain_db: float = 0.0,
    analyze_peak: bool = False,
) -> list[str]:
    duration = (region.end_ms - region.start_ms) / 1000
    source_audible, clips = _audible_content(asset, region)
    effects = _effect_filters(
        asset,
        region,
        preset,
        normalize_gain_db,
        analyze_peak,
    )
    command = [
        tools.ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
    ]
    if source_audible and not clips:
        command.extend(
            [
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
        )
        if effects:
            command.extend(["-af", ",".join(effects)])
        return command

    sample_rate = preset.sample_rate or asset.sample_rate or 48000
    requested_channels = preset.channels or asset.channels or 1
    channels = 1 if requested_channels == 1 else 2
    layout = "mono" if channels == 1 else "stereo"
    audio_format = (
        f"aresample={sample_rate},"
        f"aformat=sample_fmts=fltp:sample_rates={sample_rate}:"
        f"channel_layouts={layout}"
    )
    command.extend(
        [
            "-f",
            "lavfi",
            "-t",
            f"{duration:.6f}",
            "-i",
            f"anullsrc=r={sample_rate}:cl={layout}",
        ]
    )
    filters = [
        f"[0:a]atrim=duration={duration:.6f},"
        f"asetpts=PTS-STARTPTS,{audio_format}[base]"
    ]
    labels = ["[base]"]
    input_index = 1
    if source_audible:
        command.extend(
            [
                "-ss",
                f"{region.start_ms / 1000:.6f}",
                "-t",
                f"{duration:.6f}",
                "-i",
                asset.path,
            ]
        )
        filters.append(
            f"[{input_index}:a]atrim=duration={duration:.6f},"
            f"asetpts=PTS-STARTPTS,{audio_format}[source]"
        )
        labels.append("[source]")
        input_index += 1
    for clip_number, clip in enumerate(clips, start=1):
        overlap_start = max(region.start_ms, clip.start_ms)
        overlap_end = min(region.end_ms, clip.end_ms)
        overlap_duration = (overlap_end - overlap_start) / 1000
        source_start = (
            clip.source_offset_ms + max(0, overlap_start - clip.start_ms)
        ) / 1000
        delay_ms = overlap_start - region.start_ms
        command.extend(["-i", clip.path])
        label = f"clip{clip_number}"
        filters.append(
            f"[{input_index}:a]"
            f"atrim=start={source_start:.6f}:duration={overlap_duration:.6f},"
            f"asetpts=PTS-STARTPTS,{audio_format},"
            f"adelay={delay_ms}:all=1[{label}]"
        )
        labels.append(f"[{label}]")
        input_index += 1
    final_filters = [
        f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0",
        f"atrim=duration={duration:.6f}",
        *effects,
    ]
    filters.append(
        "".join(labels) + ",".join(final_filters) + "[export]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[export]",
            "-vn",
        ]
    )
    return command


def _detect_peak(
    tools: ToolPaths,
    asset: MediaAsset,
    region: ExportRegion,
    preset: ExportPreset,
    cancel: Event,
) -> float | None:
    if cancel.is_set():
        return None
    command = _build_audio_pipeline(
        tools,
        asset,
        region,
        preset,
        analyze_peak=True,
    )
    command.extend(["-f", "null", "-"])
    process = subprocess.run(
        command,
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
    command = _build_audio_pipeline(
        tools,
        asset,
        region,
        preset,
        normalize_gain_db,
    )
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
        peak = _detect_peak(tools, asset, region, preset, cancel)
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
