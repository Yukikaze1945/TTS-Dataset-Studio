from __future__ import annotations

import copy
import shutil
import subprocess
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget

from tts_dataset_studio.domain.app_settings import (
    DEFAULT_MOSS_PROMPT,
    LEGACY_MOSS_PROMPT,
    MOSS_HOME_ENV,
    AppSettings,
    detect_moss_root,
)
from tts_dataset_studio.domain.models import (
    ExportPreset,
    ExportRegion,
    MediaAsset,
    Project,
    SubtitleCue,
    SubtitleTrack,
)
from tts_dataset_studio.services.asr_controller import AsrController
from tts_dataset_studio.services.exporter import export_region
from tts_dataset_studio.services.media import probe_media
from tts_dataset_studio.services.project_io import load_project, save_project
from tts_dataset_studio.services.still_export import export_still
from tts_dataset_studio.ui.advanced_settings import AdvancedSettingsDialog
from tts_dataset_studio.ui.main_window import MainWindow
from tts_dataset_studio.ui.player import PlayerWidget


def test_app_settings_round_trip(tmp_path: Path) -> None:
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    value = AppSettings(
        audio_output_mode="custom",
        audio_output_dir=str(tmp_path / "audio"),
        still_format="jpeg",
        moss_device="cpu",
    )
    value.save(store)

    restored = AppSettings.load(store)

    assert restored.audio_output_mode == "custom"
    assert restored.audio_output_dir == str(tmp_path / "audio")
    assert restored.still_format == "jpeg"
    assert restored.moss_device == "cpu"


def test_legacy_asr_prompt_is_migrated_to_timestamp_prompt(tmp_path: Path) -> None:
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    store.setValue("advanced/moss_prompt", LEGACY_MOSS_PROMPT)

    restored = AppSettings.load(store)

    assert restored.moss_prompt == DEFAULT_MOSS_PROMPT
    assert "[S01]" in restored.moss_prompt


def test_damaged_asr_prompt_is_migrated_to_timestamp_prompt(tmp_path: Path) -> None:
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    store.setValue("advanced/moss_prompt", "broken \ufffd prompt")

    restored = AppSettings.load(store)

    assert restored.moss_prompt == DEFAULT_MOSS_PROMPT
    assert "\ufffd" not in restored.moss_prompt


def test_moss_root_is_detected_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "MOSS-Transcribe-Diarize"
    root.mkdir()
    monkeypatch.setenv(MOSS_HOME_ENV, str(root))

    assert detect_moss_root() == root
    settings = AppSettings()
    assert settings.moss_root == str(root)
    assert settings.moss_python == str(root / ".venv" / "Scripts" / "python.exe")


def test_worker_normalizes_invalid_prompt() -> None:
    from tts_dataset_studio.workers.moss_worker import normalize_prompt

    assert normalize_prompt(None, "official") == "official"
    assert normalize_prompt("bad \ufffd value", "official") == "official"
    assert normalize_prompt(" custom ", "official") == "custom"


def test_asr_controller_logs_worker_traceback(caplog) -> None:
    controller = AsrController()
    errors: list[str] = []
    controller.failed.connect(errors.append)

    with caplog.at_level("ERROR"):
        controller._handle_message(
            {
                "id": 2,
                "event": "error",
                "error": "TypeError: failed",
                "traceback": "worker stack marker",
            }
        )

    assert errors == ["TypeError: failed"]
    assert "worker stack marker" in caplog.text


def test_advanced_settings_dialog_exposes_save_tools_and_asr_tabs(
    qtbot,
    tmp_path: Path,
) -> None:
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    dialog = AdvancedSettingsDialog(store)
    qtbot.addWidget(dialog)

    tabs = dialog.findChild(type(dialog.layout().itemAt(0).widget()))

    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "保存与命名",
        "播放与工具",
        "ASR",
    ]
    assert dialog.moss_python.text().endswith(r".venv\Scripts\python.exe")


def test_subtitle_speaker_and_origin_survive_project_round_trip(tmp_path: Path) -> None:
    cue = SubtitleCue(10, 500, "hello", speaker="S01", origin="moss-asr")
    asset = MediaAsset("audio.wav", "audio.wav", subtitle_tracks=[SubtitleTrack("ASR", cues=[cue])])
    project = Project(assets=[asset], active_asset_id=asset.id)
    path = tmp_path / "project.ttds"

    save_project(project, path)
    restored = load_project(path)

    restored_cue = restored.assets[0].subtitle_tracks[0].cues[0]
    assert restored_cue.speaker == "S01"
    assert restored_cue.origin == "moss-asr"


def test_player_frame_step_uses_mpv_commands(qtbot) -> None:
    player = PlayerWidget(QWidget())
    qtbot.addWidget(player)
    calls: list[object] = []
    player._using_mpv = True
    player._has_video = True
    player.mpv = SimpleNamespace(
        set_paused=lambda value: calls.append(("pause", value)),
        previous_frame=lambda: calls.append("previous"),
        next_frame=lambda: calls.append("next"),
    )

    assert player.previous_frame()
    assert player.next_frame()
    assert calls == [("pause", True), "previous", ("pause", True), "next"]
    player.mpv = None
    player._using_mpv = False


def test_asr_controller_state_messages(qtbot) -> None:
    controller = AsrController()
    qtbot.addWidget(QWidget())
    loaded: list[dict] = []
    transcribed: list[dict] = []
    controller.loaded.connect(loaded.append)
    controller.transcription_ready.connect(transcribed.append)

    controller._handle_message({"id": 1, "event": "loaded", "runtime": {"gpu": "RTX"}})
    controller._handle_message({"id": 2, "event": "transcribed", "segments": []})

    assert controller.state == "loaded"
    assert loaded == [{"gpu": "RTX"}]
    assert transcribed == [{"id": 2, "event": "transcribed", "segments": []}]


def test_asr_results_replace_overlapping_machine_cues_and_are_undoable(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    old = SubtitleCue(1000, 1800, "old", origin="moss-asr")
    track = SubtitleTrack("MOSS ASR", cues=[old])
    region = ExportRegion(900, 2000)
    asset = MediaAsset(
        "audio.wav",
        "audio.wav",
        duration_ms=3000,
        subtitle_tracks=[track],
        regions=[region],
    )
    window.project = Project(assets=[asset], active_asset_id=asset.id)
    window.timeline.set_asset(asset)
    window._asr_asset_id = asset.id
    window._asr_busy = True
    window._asr_results = [
        (
            copy.deepcopy(region),
            [{"start": 0.1, "end": 0.7, "speaker": "S02", "text": "new"}],
        )
    ]

    window._apply_asr_results()

    cues = asset.subtitle_tracks[0].cues
    assert [(cue.text, cue.speaker, cue.origin) for cue in cues] == [
        ("new", "S02", "moss-asr")
    ]
    window.undo_stack.undo()
    assert asset.subtitle_tracks[0].cues[0].text == "old"
    window.dirty = False


def test_cancel_asr_discards_result_without_unloading_model(qtbot, tmp_path: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    region = ExportRegion(0, 1000)
    window.asr.state = "loaded"
    window._asr_state_changed("loaded")
    window._asr_busy = True
    window._asr_current = (region, tmp_path / "region.wav")
    window._asr_results = [(region, [{"text": "partial"}])]

    window._cancel_asr_batch()

    assert window.asr.state == "loaded"
    assert window._asr_cancel_requested
    assert window.asr_load_button.text() == "卸载 ASR 模型"

    window._asr_transcription_ready(
        {"segments": [{"start": 0, "end": 1, "text": "discard me"}]}
    )

    assert window.asr.state == "loaded"
    assert not window._asr_busy
    assert not window._asr_cancel_requested
    assert window.asr_load_button.text() == "卸载 ASR 模型"
    window.dirty = False


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")
def test_default_audio_export_and_still_use_source_folder(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    audio = tmp_path / "tone.wav"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            str(audio),
        ],
        check=True,
    )
    audio_asset = probe_media(audio)
    result = export_region(
        audio_asset,
        ExportRegion(0, 500),
        ExportPreset(write_txt=False),
        1,
        Event(),
    )
    assert result.audio_path.parent == tmp_path

    video = tmp_path / "video.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    video_asset = probe_media(video)
    still = export_still(video_asset, 300, tmp_path)
    assert still.parent == tmp_path
    assert still.suffix == ".png"
    assert still.stat().st_size > 0
