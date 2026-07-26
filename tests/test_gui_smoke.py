import pytest
from PySide6.QtGui import QAction

from tts_dataset_studio.domain.models import MediaAsset, Project, SubtitleCue, SubtitleTrack
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
    assert any(action.text() == "高级设置…" for action in window.findChildren(QAction))


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
