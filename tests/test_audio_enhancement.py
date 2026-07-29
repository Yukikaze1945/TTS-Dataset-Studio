from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from tts_dataset_studio.domain.app_settings import AppSettings
from tts_dataset_studio.domain.models import (
    GeneratedAudioClip,
    MediaAsset,
    Project,
)
from tts_dataset_studio.services.ai_monitor import audible_generated_tracks
from tts_dataset_studio.services.audio_enhancement import build_engine_command
from tts_dataset_studio.services.project_io import load_project, save_project
from tts_dataset_studio.ui.timeline import TimelineCanvas
from tts_dataset_studio.ui.workspace import ContextActionBar


def _clip(path: str, clip_id: str, start_ms: int = 0) -> GeneratedAudioClip:
    return GeneratedAudioClip(
        path=path,
        start_ms=start_ms,
        source_offset_ms=0,
        duration_ms=500,
        source_duration_ms=500,
        reference_region_id=f"region-{clip_id}",
        text=clip_id,
        engine="dpdfnet",
        id=clip_id,
    )


def test_media_asset_has_separate_generated_and_enhancement_tracks() -> None:
    asset = MediaAsset("audio.wav", "audio.wav")

    assert asset.generated_track.kind == "generated"
    assert asset.enhancement_track.kind == "enhancement"
    assert asset.enhancement_track is not asset.generated_track
    assert [track.name for track in asset.generated_audio_tracks] == [
        "AI 生成",
        "增强音轨",
    ]


def test_project_round_trip_preserves_enhancement_track(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    enhanced = tmp_path / "enhanced.wav"
    enhanced.write_bytes(b"enhanced")
    asset = MediaAsset(str(source), source.name)
    asset.enhancement_track.clips.append(_clip(str(enhanced), "enhanced"))
    project = Project(assets=[asset], active_asset_id=asset.id)
    destination = tmp_path / "project.ttds"

    save_project(project, destination)
    restored = load_project(destination)

    track = restored.active_asset.enhancement_track
    assert track.kind == "enhancement"
    assert track.clips[0].engine == "dpdfnet"
    assert Path(track.clips[0].path).is_file()


def test_audible_generated_tracks_respect_mute_and_solo() -> None:
    asset = MediaAsset("audio.wav", "audio.wav")
    generated = asset.generated_track
    enhancement = asset.enhancement_track
    generated.muted = False
    enhancement.muted = False

    assert audible_generated_tracks(asset) == [generated, enhancement]
    enhancement.solo = True
    assert audible_generated_tracks(asset) == [enhancement]
    asset.source_solo = True
    assert audible_generated_tracks(asset) == [enhancement]
    enhancement.solo = False
    assert audible_generated_tracks(asset) == []


def test_timeline_duration_includes_all_generated_tracks(qtbot) -> None:
    timeline = TimelineCanvas()
    qtbot.addWidget(timeline)
    asset = MediaAsset("audio.wav", "audio.wav", duration_ms=1000)
    asset.enhancement_track.clips.append(_clip("enhanced.wav", "enhanced", 1800))

    timeline.set_asset(asset)

    assert timeline._timeline_duration() == 2300


def test_build_dpdfnet_command_uses_configured_environment(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    settings = AppSettings(
        dpdfnet_python=str(python),
        dpdfnet_model="dpdfnet2_48khz_hr",
        dpdfnet_attn_limit_db=9,
    )

    command, cwd = build_engine_command(
        settings,
        "dpdfnet",
        tmp_path / "input.wav",
        tmp_path / "output.wav",
    )

    assert command[0] == str(python)
    assert "dpdfnet2_48khz_hr" in command
    assert "9" in command
    assert cwd is None


def test_build_separator_command_uses_model_cache_and_autocast(
    tmp_path: Path,
) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    model_dir = tmp_path / "models"
    settings = AppSettings(
        separator_python=str(python),
        separator_model="bs-roformer.ckpt",
        separator_model_dir=str(model_dir),
        separator_use_autocast=True,
    )

    command, cwd = build_engine_command(
        settings,
        "separator",
        tmp_path / "input.wav",
        tmp_path / "output.wav",
    )

    assert command[0] == str(python)
    assert command[command.index("--model") + 1] == "bs-roformer.ckpt"
    assert command[command.index("--model-dir") + 1] == str(model_dir)
    assert "--use-autocast" in command
    assert cwd is None


def test_build_stupase_command_requires_official_checkout(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    root = tmp_path / "pase"
    inference = root / "stupase" / "inference" / "inference.py"
    inference.parent.mkdir(parents=True)
    inference.write_bytes(b"")
    model_dir = tmp_path / "models"
    settings = AppSettings(
        stupase_python=str(python),
        stupase_root=str(root),
        stupase_model_dir=str(model_dir),
        stupase_device="cuda:0",
    )

    command, cwd = build_engine_command(
        settings,
        "stupase",
        tmp_path / "input.wav",
        tmp_path / "output.wav",
    )

    assert command[command.index("--root") + 1] == str(root)
    assert command[command.index("--model-dir") + 1] == str(model_dir)
    assert command[command.index("--device") + 1] == "cuda:0"
    assert cwd == root


def test_context_bar_exposes_audio_processing_only_for_source_selection(qtbot) -> None:
    QApplication.instance()
    bar = ContextActionBar()
    qtbot.addWidget(bar)

    bar.set_selection("region", "one region")
    assert bar.process_button.isVisibleTo(bar)
    bar.set_selection("generated", "one generated clip")
    assert not bar.process_button.isVisible()
