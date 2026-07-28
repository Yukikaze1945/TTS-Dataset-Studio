import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFormLayout, QScrollArea

from tts_dataset_studio.domain.models import (
    ExportRegion,
    MediaAsset,
    Project,
    SubtitleCue,
    SubtitleTrack,
)
from tts_dataset_studio.services.media import ToolPaths
from tts_dataset_studio.ui.main_window import MainWindow


def test_main_window_builds(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.windowTitle().endswith("TTS Dataset Studio")
    assert window.asset_list.acceptDrops()
    assert window.export_track_combo.count() == 0
    assert window.timeline.asset is None
    shortcuts = {action.text(): action.shortcut().toString() for action in window.actions()}
    assert shortcuts["快捷导出"] == "E"
    assert shortcuts["删除区间"] == "X"
    assert shortcuts["上一帧"] == "D"
    assert shortcuts["下一帧"] == "F"
    assert shortcuts["保存原视频静帧"] == "C"
    assert any(action.text() == "设置…" for action in window.findChildren(QAction))
    assert window.workspace_stack.currentWidget() is window.empty_workspace
    assert not window.context_bar.isVisible()


def test_export_settings_scroll_and_wrap_in_narrow_inspector(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(900, 650)
    window.show()

    export_tab = window.inspector_tabs.widget(1)

    assert isinstance(export_tab, QScrollArea)
    assert (
        export_tab.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert (
        window.export_form.rowWrapPolicy()
        == QFormLayout.RowWrapPolicy.WrapLongRows
    )
    assert (
        window.export_form.fieldGrowthPolicy()
        == QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
    )


def test_missing_media_tools_do_not_block_main_window(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_tools():
        raise FileNotFoundError("FFmpeg not found")

    monkeypatch.setattr(ToolPaths, "discover", missing_tools)
    window = MainWindow()
    qtbot.addWidget(window)

    assert not window.export_button.isEnabled()
    assert "TOOLS MISSING" in window.status_message.text()


def test_setting_in_point_immediately_marks_timeline(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    asset = MediaAsset("audio.wav", "audio.wav", duration_ms=5000)
    window.project = Project(assets=[asset], active_asset_id=asset.id)
    window.timeline.set_asset(asset)
    monkeypatch.setattr(
        type(window.player_widget),
        "position",
        property(lambda _player: 1250),
    )

    window._set_in_point()

    assert window.in_point_ms == 1250
    assert window.timeline.in_point_ms == 1250
    assert "IN" in window.status_message.text()
    window.dirty = False


def test_clicking_cue_creates_visible_selection_and_inspector_gain_sync(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    cue = SubtitleCue(1000, 2400, "测试片段")
    track = SubtitleTrack("zh", cues=[cue])
    asset = MediaAsset(
        "missing.wav",
        "missing.wav",
        duration_ms=5000,
        subtitle_tracks=[track],
        export_track_id=track.id,
    )
    window.project = Project(assets=[asset], active_asset_id=asset.id)
    window.timeline.set_asset(asset)

    window._cue_selected(track.id, cue.id)
    window.gain_spin.setValue(-6.0)

    assert len(asset.regions) == 1
    assert window.selected_region_id == asset.regions[0].id
    assert "1.400s" in window.selection_status.text()
    assert asset.gain_db == -6.0
    assert window.gain_spin.value() == -6.0
    assert not window.context_bar.isHidden()
    assert not window.context_bar.export_button.isHidden()
    window.dirty = False


def test_switching_export_track_refreshes_selected_region_text(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    chinese = SubtitleCue(1000, 2400, "请多关照")
    japanese = SubtitleCue(1000, 2400, "よろしくお願いします")
    zh_track = SubtitleTrack("中文", cues=[chinese])
    ja_track = SubtitleTrack("日文", cues=[japanese])
    asset = MediaAsset(
        "missing.wav",
        "missing.wav",
        duration_ms=5000,
        subtitle_tracks=[zh_track, ja_track],
        export_track_id=zh_track.id,
    )
    window.project = Project(assets=[asset], active_asset_id=asset.id)
    window.timeline.set_asset(asset)
    window._refresh_export_tracks()
    window._cue_selected(zh_track.id, chinese.id)
    region_id = window.selected_region_id

    window.export_track_combo.setCurrentIndex(1)

    assert asset.export_track_id == ja_track.id
    assert window.cue_text.toPlainText() == japanese.text
    assert window.selected_cue == (ja_track.id, japanese.id)
    assert window.timeline.selected_cue_ids == {japanese.id}
    assert window.selected_region_id == region_id
    window.dirty = False


def test_preview_preserves_bilingual_subtitle_lines(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    cue = SubtitleCue(1000, 2400, "请多关照\nよろしくお願いします")
    track = SubtitleTrack("双语", cues=[cue])
    asset = MediaAsset(
        "missing.mp4",
        "missing.mp4",
        duration_ms=5000,
        has_video=True,
        subtitle_tracks=[track],
    )
    window.project = Project(assets=[asset], active_asset_id=asset.id)
    window.player_widget._has_video = True
    window.player_widget.set_preview_mode("video")

    window._update_preview_subtitle(1500)

    assert window.player_widget.subtitle_overlay.text() == cue.text
    window.dirty = False


def test_asr_action_loads_engine_on_demand(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    asset = MediaAsset("audio.wav", "audio.wav", duration_ms=5000)
    window.project = Project(assets=[asset], active_asset_id=asset.id)
    region = window.project.active_asset.regions
    selected = ExportRegion(500, 1500)
    region.append(selected)
    window._apply_region_selection(selected.id, False, True)
    loaded = []
    monkeypatch.setattr(window.asr, "load_model", lambda settings: loaded.append(settings))

    window._toggle_asr_transcription()

    assert loaded == [window.app_settings]
    assert window._asr_pending_start
    assert not window.task_notice.isHidden()
    window.dirty = False


def test_plain_cue_selection_replaces_and_ctrl_selection_adds(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    first = SubtitleCue(500, 1200, "first")
    second = SubtitleCue(1500, 2300, "second")
    track = SubtitleTrack("track", cues=[first, second])
    asset = MediaAsset(
        "audio.wav",
        "audio.wav",
        duration_ms=4000,
        subtitle_tracks=[track],
    )
    window.project = Project(assets=[asset], active_asset_id=asset.id)
    window.timeline.set_asset(asset)

    window._cue_selected(track.id, first.id)
    first_region_id = window.selected_region_id
    window._cue_selected(track.id, second.id)
    second_region_id = window.selected_region_id

    assert window.selected_region_ids == {second_region_id}

    window._cue_selected(track.id, first.id, additive=True, selected=True)

    assert window.selected_region_ids == {first_region_id, second_region_id}
    assert "已选 2 个片段" in window.selection_status.text()
    window.dirty = False


def test_missing_asset_stays_offline_without_starting_player(qtbot, tmp_path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    missing = tmp_path / "does-not-exist.wav"
    asset = MediaAsset(str(missing), missing.name, duration_ms=5000)
    window.project = Project(assets=[asset], active_asset_id=asset.id)

    window._activate_asset(asset)

    assert "MISSING MEDIA" in window.media_info.text()
    assert "OFFLINE" in window.status_message.text()
    assert window.player_widget._current_path is None
    assert window.workspace_stack.currentIndex() == 1
    window.dirty = False


def test_narrow_workspace_collapses_library(qtbot, tmp_path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    missing = tmp_path / "audio.wav"
    asset = MediaAsset(str(missing), missing.name, duration_ms=5000)
    window.project = Project(assets=[asset], active_asset_id=asset.id)
    window._activate_asset(asset)
    window.show()
    window.resize(1024, 720)
    qtbot.wait(20)

    assert window.library_panel.isHidden()
    assert window.context_bar.isHidden()
    window.dirty = False


def test_visible_subtitle_tracks_are_composited_in_video_preview(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    visible = SubtitleTrack(
        "zh",
        cues=[SubtitleCue(1000, 2000, "画面字幕")],
    )
    hidden = SubtitleTrack(
        "en",
        visible=False,
        cues=[SubtitleCue(1000, 2000, "hidden subtitle")],
    )
    asset = MediaAsset(
        "video.mp4",
        "video.mp4",
        duration_ms=5000,
        has_video=True,
        subtitle_tracks=[visible, hidden],
    )
    window.project = Project(assets=[asset], active_asset_id=asset.id)
    window.player_widget._has_video = True
    window.player_widget.set_preview_mode("video")

    window._update_preview_subtitle(1500)

    assert window.player_widget._subtitle_text == "画面字幕"
    assert window.player_widget.subtitle_overlay.text() == "画面字幕"
    window.dirty = False
