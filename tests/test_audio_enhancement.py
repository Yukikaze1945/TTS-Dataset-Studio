from __future__ import annotations

import wave
from pathlib import Path

from PySide6.QtWidgets import QApplication

import tts_dataset_studio.services.audio_enhancement as audio_enhancement_module
import tts_dataset_studio.ui.main_window as main_window_module
from tts_dataset_studio.domain.app_settings import AppSettings
from tts_dataset_studio.domain.models import (
    ExportRegion,
    GeneratedAudioClip,
    MediaAsset,
    Project,
)
from tts_dataset_studio.services.ai_monitor import audible_generated_tracks
from tts_dataset_studio.services.audio_enhancement import (
    build_engine_command,
    engine_steps,
    extract_generated_clip_audio,
    pipeline_label,
)
from tts_dataset_studio.services.media import ToolPaths
from tts_dataset_studio.services.project_io import load_project, save_project
from tts_dataset_studio.ui.main_window import (
    EnhancementBatchItem,
    EnhancementWorker,
)
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


def test_recommended_process_is_a_real_two_step_pipeline() -> None:
    assert engine_steps("separator+dpdfnet") == ("separator", "dpdfnet")
    assert pipeline_label(engine_steps("separator+dpdfnet")) == (
        "去除 BGM → 快速降噪"
    )


def test_enhancement_worker_feeds_each_step_into_the_next(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, bytes]] = []

    def fake_extract(_asset, _region, destination, _tools=None):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"source")
        return destination

    def fake_run(_settings, engine, source, destination, _cancel=None):
        payload = Path(source).read_bytes()
        calls.append((engine, payload))
        destination.write_bytes(payload + b"|" + engine.encode())
        return destination

    monkeypatch.setattr(main_window_module, "extract_region_audio", fake_extract)
    monkeypatch.setattr(main_window_module, "run_engine", fake_run)
    item = EnhancementBatchItem(
        region=ExportRegion(100, 600),
        text="test",
    )
    completed: list[tuple[EnhancementBatchItem, Path]] = []
    stages: list[dict] = []
    worker = EnhancementWorker(
        MediaAsset("source.wav", "source.wav", duration_ms=1000),
        [item],
        "separator+dpdfnet",
        AppSettings(),
        tmp_path / "work",
        tmp_path / "output",
    )
    worker.item_completed.connect(completed.append)
    worker.stage_changed.connect(stages.append)

    worker.run()

    assert calls == [
        ("separator", b"source"),
        ("dpdfnet", b"source|separator"),
    ]
    assert completed[0][1].read_bytes() == b"source|separator|dpdfnet"
    assert [stage["engine"] for stage in stages] == ["separator", "dpdfnet"]


def test_enhancement_worker_does_not_publish_partial_chain_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_extract(_asset, _region, destination, _tools=None):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"source")
        return destination

    def fake_run(_settings, engine, source, destination, _cancel=None):
        if engine == "dpdfnet":
            raise RuntimeError("second step failed")
        destination.write_bytes(Path(source).read_bytes() + b"|separator")
        return destination

    monkeypatch.setattr(main_window_module, "extract_region_audio", fake_extract)
    monkeypatch.setattr(main_window_module, "run_engine", fake_run)
    completed: list[object] = []
    failures: list[str] = []
    worker = EnhancementWorker(
        MediaAsset("source.wav", "source.wav", duration_ms=1000),
        [EnhancementBatchItem(ExportRegion(100, 600), "test")],
        "separator+dpdfnet",
        AppSettings(),
        tmp_path / "work",
        tmp_path / "output",
    )
    worker.item_completed.connect(completed.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert completed == []
    assert len(failures) == 1
    assert "快速降噪（步骤 2/2）失败" in failures[0]
    assert "second step failed" in failures[0]
    assert list((tmp_path / "output").glob("*.wav")) == []


def test_extract_generated_clip_audio_uses_current_non_destructive_trim(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: list[str] = []

    def fake_ffmpeg(command, **_kwargs):
        captured.extend(command)
        destination = Path(command[-1])
        with wave.open(str(destination), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(48000)
            audio.writeframes(b"\0\0" * 14400)

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr(
        audio_enhancement_module.subprocess,
        "run",
        fake_ffmpeg,
    )
    source = tmp_path / "enhanced.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"\0\0" * 48000)
    clip = GeneratedAudioClip(
        path=str(source),
        start_ms=1000,
        source_offset_ms=200,
        duration_ms=300,
        source_duration_ms=1000,
        reference_region_id="region",
        text="enhanced",
        engine="separator",
    )
    destination = tmp_path / "trimmed.wav"

    extract_generated_clip_audio(
        clip,
        destination,
        ToolPaths("ffmpeg", "ffprobe", None),
    )

    with wave.open(str(destination), "rb") as audio:
        assert audio.getframerate() == 48000
        assert audio.getnchannels() == 1
        assert abs(audio.getnframes() - 14400) <= 2
    assert captured[captured.index("-ss") + 1] == "0.200000"
    assert captured[captured.index("-t") + 1] == "0.300000"


def test_context_bar_keeps_source_actions_when_result_is_focused(qtbot) -> None:
    QApplication.instance()
    bar = ContextActionBar()
    qtbot.addWidget(bar)
    bar.show()

    bar.set_selection("region", "one region")
    assert bar.process_button.isVisibleTo(bar)
    assert bar.process_button.isEnabled()

    bar.set_focus("generated", "one generated clip")

    assert bar.process_button.isVisibleTo(bar)
    assert bar.process_button.isEnabled()
    assert bar.export_button.isVisibleTo(bar)
    assert bar.locate_button.isVisibleTo(bar)
    assert "仍作用于源片段" in bar.detail.text()


def test_context_bar_exposes_chain_and_continue_actions_for_enhancement(
    qtbot,
) -> None:
    QApplication.instance()
    bar = ContextActionBar()
    qtbot.addWidget(bar)
    bar.show()
    requested: list[tuple[str, str]] = []
    bar.process_requested.connect(
        lambda process_id, input_mode: requested.append(
            (process_id, input_mode)
        )
    )

    source_action = next(
        action
        for action in bar.process_button.menu().actions()
        if "一键去 BGM" in action.text()
    )
    continue_action = next(
        action
        for action in bar.process_button.menu().actions()
        if "继续快速降噪" in action.text()
    )
    assert not continue_action.isVisible()

    bar.set_selection("region", "one region")
    source_action.trigger()
    bar.set_focus("enhancement", "one enhancement result")
    assert continue_action.isVisible()
    continue_action.trigger()

    assert requested == [
        ("separator+dpdfnet", "source"),
        ("dpdfnet", "focused"),
    ]
    assert "继续处理当前结果" in bar.detail.text()


def test_context_bar_explains_unavailable_source_actions(qtbot) -> None:
    QApplication.instance()
    bar = ContextActionBar()
    qtbot.addWidget(bar)
    bar.show()

    bar.set_focus("generated", "one generated clip")

    assert bar.process_button.isVisibleTo(bar)
    assert not bar.process_button.isEnabled()
    assert "先点击字幕" in bar.process_button.toolTip()
    assert bar.locate_button.isVisibleTo(bar)
