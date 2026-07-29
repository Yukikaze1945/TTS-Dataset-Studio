from __future__ import annotations

import subprocess
from pathlib import Path

from tts_dataset_studio.domain.models import GeneratedAudioTrack, MediaAsset
from tts_dataset_studio.services.media import ToolPaths


def audible_audio_tracks(
    asset: MediaAsset,
) -> tuple[bool, list[GeneratedAudioTrack]]:
    any_solo = asset.source_solo or any(
        track.solo for track in asset.generated_audio_tracks
    )
    source_audible = (
        asset.has_audio
        and not asset.source_muted
        and (not any_solo or asset.source_solo)
    )
    generated = [
        track
        for track in asset.generated_audio_tracks
        if not track.muted and (not any_solo or track.solo)
    ]
    return source_audible, generated


def audible_generated_tracks(asset: MediaAsset) -> list[GeneratedAudioTrack]:
    return audible_audio_tracks(asset)[1]


def build_ai_monitor_cache(
    asset: MediaAsset,
    destination: Path,
    tools: ToolPaths | None = None,
) -> Path:
    tools = tools or ToolPaths.discover()
    clips = [
        clip
        for track in audible_generated_tracks(asset)
        for clip in track.clips
        if Path(clip.path).is_file()
    ]
    duration_ms = max(
        asset.duration_ms,
        max((clip.end_ms for clip in clips), default=0),
        1,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp.flac")
    command = [
        tools.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
    ]
    for clip in clips:
        command.extend(["-i", clip.path])
    filters = [
        f"[0:a]atrim=duration={duration_ms / 1000:.6f},"
        "asetpts=PTS-STARTPTS[base]"
    ]
    labels = ["[base]"]
    for index, clip in enumerate(clips, start=1):
        label = f"clip{index}"
        filters.append(
            f"[{index}:a]"
            f"atrim=start={clip.source_offset_ms / 1000:.6f}:"
            f"duration={clip.duration_ms / 1000:.6f},"
            "asetpts=PTS-STARTPTS,"
            "aresample=48000,"
            "aformat=sample_fmts=fltp:sample_rates=48000:"
            "channel_layouts=stereo,"
            f"adelay={clip.start_ms}:all=1[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0,"
        f"atrim=duration={duration_ms / 1000:.6f}[mix]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[mix]",
            "-c:a",
            "flac",
            "-y",
            str(temporary),
        ]
    )
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
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            process.stderr.strip() or "AI 音轨监听缓存生成失败"
        )
    temporary.replace(destination)
    return destination
