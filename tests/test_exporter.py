from pathlib import Path

import pytest

from tts_dataset_studio.domain.models import (
    ExportPreset,
    ExportRegion,
    GeneratedAudioClip,
    MediaAsset,
)
from tts_dataset_studio.services.exporter import build_ffmpeg_command
from tts_dataset_studio.services.media import ToolPaths


def test_build_ffmpeg_command_uses_requested_audio_settings(tmp_path: Path) -> None:
    asset = MediaAsset("input.wav", "input.wav", gain_db=-3.0)
    region = ExportRegion(1000, 3500)
    preset = ExportPreset(
        sample_rate=24000,
        channels=1,
        gain_db=1.0,
        fade_in_ms=50,
        fade_out_ms=100,
    )
    tools = ToolPaths("ffmpeg", "ffprobe", None)

    command = build_ffmpeg_command(tools, asset, region, preset, tmp_path / "out.wav")

    assert command[0] == "ffmpeg"
    assert command[command.index("-ar") + 1] == "24000"
    assert command[command.index("-ac") + 1] == "1"
    assert "volume=-2.000dB" in command[command.index("-af") + 1]
    assert command[-1].endswith("out.wav")


def test_build_ffmpeg_command_exports_solo_enhancement_track(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    enhanced = tmp_path / "enhanced.wav"
    source.write_bytes(b"source")
    enhanced.write_bytes(b"enhanced")
    asset = MediaAsset(str(source), source.name, duration_ms=3000)
    track = asset.enhancement_track
    track.muted = False
    track.solo = True
    track.clips.append(
        GeneratedAudioClip(
            path=str(enhanced),
            start_ms=1000,
            source_offset_ms=0,
            duration_ms=1000,
            source_duration_ms=1000,
            reference_region_id="region",
            text="enhanced",
            engine="separator",
        )
    )

    command = build_ffmpeg_command(
        ToolPaths("ffmpeg", "ffprobe", None),
        asset,
        ExportRegion(1000, 2000),
        ExportPreset(),
        tmp_path / "out.wav",
    )

    assert str(enhanced) in command
    assert str(source) not in command
    assert "-filter_complex" in command
    assert command[command.index("-map") + 1] == "[export]"


def test_build_ffmpeg_command_mixes_all_audible_tracks(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    enhanced = tmp_path / "enhanced.wav"
    source.write_bytes(b"source")
    enhanced.write_bytes(b"enhanced")
    asset = MediaAsset(str(source), source.name, duration_ms=1000)
    track = asset.enhancement_track
    track.muted = False
    track.clips.append(
        GeneratedAudioClip(
            path=str(enhanced),
            start_ms=0,
            source_offset_ms=0,
            duration_ms=1000,
            source_duration_ms=1000,
            reference_region_id="region",
            text="enhanced",
        )
    )

    command = build_ffmpeg_command(
        ToolPaths("ffmpeg", "ffprobe", None),
        asset,
        ExportRegion(0, 1000),
        ExportPreset(),
        tmp_path / "out.wav",
    )

    assert str(source) in command
    assert str(enhanced) in command
    graph = command[command.index("-filter_complex") + 1]
    assert "amix=inputs=3" in graph


def test_build_ffmpeg_command_rejects_fully_muted_region(
    tmp_path: Path,
) -> None:
    asset = MediaAsset("source.wav", "source.wav", source_muted=True)

    with pytest.raises(ValueError, match="没有可导出的可听音轨"):
        build_ffmpeg_command(
            ToolPaths("ffmpeg", "ffprobe", None),
            asset,
            ExportRegion(0, 1000),
            ExportPreset(),
            tmp_path / "out.wav",
        )
