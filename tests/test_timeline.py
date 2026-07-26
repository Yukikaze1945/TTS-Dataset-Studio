import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tts_dataset_studio.domain.models import (
    ExportRegion,
    GeneratedAudioClip,
    MediaAsset,
    SubtitleCue,
    SubtitleTrack,
)
from tts_dataset_studio.ui.timeline import (
    TimelineCanvas,
    TimelineScrollArea,
    amplitude_to_dbfs_radius,
    apply_gain_to_peak,
    dbfs_to_amplitude,
    dbfs_y_positions,
    ruler_interval_seconds,
)


@pytest.mark.parametrize(
    ("dbfs", "amplitude"),
    [(0.0, 1.0), (-6.0, 0.501187), (-12.0, 0.251189), (-24.0, 0.063096)],
)
def test_dbfs_marks_match_linear_waveform_amplitude(
    dbfs: float,
    amplitude: float,
) -> None:
    assert dbfs_to_amplitude(dbfs) == pytest.approx(amplitude, rel=1e-5)


def test_dbfs_marks_are_mirrored_around_waveform_center() -> None:
    upper, lower = dbfs_y_positions(-12, top=42.0, height=96.0)

    assert (upper + lower) / 2 == pytest.approx(90.0)
    assert upper < 90.0 < lower


def test_expanded_waveform_uses_logarithmic_dbfs_radius() -> None:
    assert amplitude_to_dbfs_radius(1.0) == 1.0
    assert amplitude_to_dbfs_radius(0.501187) == pytest.approx(0.9, rel=1e-4)
    assert amplitude_to_dbfs_radius(0.001) == 0.0


def test_gain_changes_displayed_peak_and_marks_clipping() -> None:
    peak, clipping = apply_gain_to_peak(0.5, 6.0)
    assert peak == pytest.approx(0.997631, rel=1e-5)
    assert not clipping

    peak, clipping = apply_gain_to_peak(0.8, 6.0)
    assert peak == 1.0
    assert clipping

    peak, clipping = apply_gain_to_peak(0.8, 12.0, bypassed=True)
    assert peak == 0.8
    assert not clipping


def test_waveform_lane_can_be_dragged_tall_enough_to_show_dbfs_scale(qtbot) -> None:
    timeline = TimelineCanvas()
    qtbot.addWidget(timeline)
    timeline.set_asset(MediaAsset("audio.wav", "audio.wav", duration_ms=5000))
    timeline.show()
    original_bottom = timeline.HEADER + timeline.waveform_height
    target_height = timeline.DB_SCALE_MIN_HEIGHT + 30

    QTest.mousePress(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(300, original_bottom),
    )
    QTest.mouseMove(
        timeline,
        QPoint(300, timeline.HEADER + target_height),
        delay=10,
    )
    QTest.mouseRelease(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(300, timeline.HEADER + target_height),
    )

    assert timeline.waveform_height == target_height
    assert timeline.waveform_height >= timeline.DB_SCALE_MIN_HEIGHT


def test_plain_click_replaces_selection_and_ctrl_click_adds_or_removes(qtbot) -> None:
    first = SubtitleCue(0, 1000, "first")
    second = SubtitleCue(2000, 3000, "second")
    timeline = TimelineCanvas()
    qtbot.addWidget(timeline)
    timeline.set_asset(
        MediaAsset(
            "audio.wav",
            "audio.wav",
            duration_ms=5000,
            subtitle_tracks=[SubtitleTrack("track", cues=[first, second])],
        )
    )
    timeline.show()
    cue_y = (
        timeline.HEADER
        + timeline.waveform_height
        + timeline.TRACK_HEIGHT
        + 15
    )

    QTest.mouseClick(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(timeline._x_for_ms(500), cue_y),
    )
    QTest.mouseClick(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(timeline._x_for_ms(2500), cue_y),
    )
    assert timeline.selected_cue_ids == {second.id}

    QTest.mouseClick(
        timeline,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=QPoint(timeline._x_for_ms(500), cue_y),
    )
    assert timeline.selected_cue_ids == {first.id, second.id}

    QTest.mouseClick(
        timeline,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=QPoint(timeline._x_for_ms(2500), cue_y),
    )
    assert timeline.selected_cue_ids == {first.id}


def test_invisible_old_region_does_not_intercept_seek_click(qtbot) -> None:
    old_region = ExportRegion(1000, 2500)
    timeline = TimelineCanvas()
    qtbot.addWidget(timeline)
    timeline.set_asset(
        MediaAsset(
            "audio.wav",
            "audio.wav",
            duration_ms=5000,
            regions=[old_region],
        )
    )
    seeks: list[int] = []
    region_hits: list[tuple] = []
    timeline.seek_requested.connect(seeks.append)
    timeline.region_selected.connect(lambda *args: region_hits.append(args))
    timeline.show()

    QTest.mouseClick(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(timeline._x_for_ms(1800), timeline.HEADER + 20),
    )

    assert seeks == [1800]
    assert region_hits == []
    assert timeline.selected_region_ids == set()


def test_selected_region_body_moves_playhead_instead_of_region(qtbot) -> None:
    region = ExportRegion(1000, 2500)
    timeline = TimelineCanvas()
    qtbot.addWidget(timeline)
    timeline.set_asset(
        MediaAsset(
            "audio.wav",
            "audio.wav",
            duration_ms=5000,
            regions=[region],
        )
    )
    timeline.selected_region_id = region.id
    timeline.selected_region_ids = {region.id}
    seeks: list[int] = []
    region_hits: list[tuple] = []
    timeline.seek_requested.connect(seeks.append)
    timeline.region_selected.connect(lambda *args: region_hits.append(args))
    timeline.show()

    QTest.mouseClick(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(timeline._x_for_ms(1800), timeline.HEADER + 20),
    )

    assert seeks == [1800]
    assert region_hits == []
    assert (region.start_ms, region.end_ms) == (1000, 2500)
    assert timeline.selected_region_ids == {region.id}


def test_playhead_can_be_scrubbed_from_ruler(qtbot) -> None:
    timeline = TimelineCanvas()
    qtbot.addWidget(timeline)
    timeline.set_asset(MediaAsset("audio.wav", "audio.wav", duration_ms=5000))
    scrubs: list[int] = []
    finished: list[int] = []
    timeline.scrub_requested.connect(scrubs.append)
    timeline.scrub_finished.connect(finished.append)
    timeline.show()
    start_x = timeline._x_for_ms(1000)
    middle_x = timeline._x_for_ms(1750)
    end_x = timeline._x_for_ms(2250)

    QTest.mousePress(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(start_x, 17),
    )
    QTest.mouseMove(
        timeline,
        QPoint(middle_x, 17),
        delay=10,
    )
    QTest.mouseMove(
        timeline,
        QPoint(end_x, 17),
        delay=10,
    )
    QTest.mouseRelease(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(end_x, 17),
    )

    assert scrubs[0] == timeline._ms_for_x(start_x)
    assert scrubs[-1] == timeline._ms_for_x(end_x)
    assert len(scrubs) >= 3
    assert finished == [timeline._ms_for_x(end_x)]
    assert not timeline._scrubbing_playhead


def test_dragged_cue_edge_snaps_to_playhead(qtbot) -> None:
    cue = SubtitleCue(0, 1000, "snap")
    timeline = TimelineCanvas()
    qtbot.addWidget(timeline)
    timeline.set_asset(
        MediaAsset(
            "audio.wav",
            "audio.wav",
            duration_ms=5000,
            subtitle_tracks=[SubtitleTrack("track", cues=[cue])],
        )
    )
    timeline.set_playhead(1500)
    timeline.show()
    cue_y = (
        timeline.HEADER
        + timeline.waveform_height
        + timeline.TRACK_HEIGHT
        + 15
    )

    QTest.mousePress(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(timeline._x_for_ms(cue.end_ms), cue_y),
    )
    QTest.mouseMove(
        timeline,
        QPoint(timeline._x_for_ms(1495), cue_y),
        delay=10,
    )
    QTest.mouseRelease(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(timeline._x_for_ms(1495), cue_y),
    )

    assert cue.end_ms == 1500


def test_alt_wheel_can_zoom_one_hour_media_to_full_duration(qtbot) -> None:
    timeline = TimelineCanvas()
    scroll = TimelineScrollArea(timeline)
    qtbot.addWidget(scroll)
    scroll.resize(900, 300)
    asset = MediaAsset("long.wav", "long.wav", duration_ms=3_600_000)
    timeline.set_asset(asset)
    scroll.show()

    for _ in range(20):
        event = QWheelEvent(
            QPointF(300, 100),
            QPointF(300, 100),
            QPoint(),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.AltModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(scroll.viewport(), event)

    assert timeline.pixels_per_second == pytest.approx(
        timeline._fit_pixels_per_second(scroll.viewport().width())
    )
    assert timeline._x_for_ms(asset.duration_ms) <= scroll.viewport().width() - 80
    assert ruler_interval_seconds(timeline.pixels_per_second) >= 300


def test_alt_wheel_is_caught_over_canvas_viewport_and_scrollbar(qtbot) -> None:
    timeline = TimelineCanvas()
    scroll = TimelineScrollArea(timeline)
    qtbot.addWidget(scroll)
    scroll.resize(900, 300)
    timeline.set_asset(MediaAsset("audio.wav", "audio.wav", duration_ms=60_000))
    scroll.show()

    for target in (timeline, scroll.viewport(), scroll.horizontalScrollBar()):
        before = timeline.pixels_per_second
        event = QWheelEvent(
            QPointF(300, 100),
            QPointF(300, 100),
            QPoint(),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.AltModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(target, event)
        assert timeline.pixels_per_second < before


def test_scroll_area_follows_playhead_after_it_leaves_view(qtbot) -> None:
    timeline = TimelineCanvas()
    scroll = TimelineScrollArea(timeline)
    qtbot.addWidget(scroll)
    scroll.resize(500, 300)
    timeline.set_asset(MediaAsset("audio.wav", "audio.wav", duration_ms=30_000))
    scroll.show()
    timeline.set_playhead(20_000)

    scroll.ensure_playhead_visible()

    x = timeline._x_for_ms(timeline.playhead_ms)
    left = scroll.horizontalScrollBar().value()
    assert left > 0
    assert left <= x <= left + scroll.viewport().width()


def test_hidden_subtitle_track_is_removed_from_timeline_layout(qtbot) -> None:
    visible = SubtitleTrack("visible", cues=[SubtitleCue(0, 1000, "shown")])
    hidden = SubtitleTrack(
        "hidden",
        visible=False,
        cues=[SubtitleCue(1000, 2000, "not shown")],
    )
    timeline = TimelineCanvas()
    qtbot.addWidget(timeline)
    timeline.set_asset(
        MediaAsset(
            "audio.wav",
            "audio.wav",
            duration_ms=3000,
            subtitle_tracks=[visible, hidden],
        )
    )

    assert timeline._visible_subtitle_tracks() == [visible]
    expected_height = (
        timeline.HEADER
        + timeline.waveform_height
        + timeline.TRACK_HEIGHT
        + timeline.TRACK_HEIGHT
        + 20
    )
    assert timeline.height() == expected_height


def test_generated_audio_track_extends_timeline_and_selects_clip(qtbot) -> None:
    clip = GeneratedAudioClip(
        path="missing.wav",
        start_ms=2500,
        source_offset_ms=0,
        duration_ms=2000,
        source_duration_ms=2000,
        reference_region_id="region",
        text="generated",
    )
    asset = MediaAsset("audio.wav", "audio.wav", duration_ms=3000)
    asset.generated_track.clips.append(clip)
    timeline = TimelineCanvas()
    qtbot.addWidget(timeline)
    timeline.set_asset(asset)
    timeline.show()
    generated_y = timeline.HEADER + timeline.waveform_height + 15

    QTest.mouseClick(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(timeline._x_for_ms(3000), generated_y),
    )

    assert timeline._timeline_duration() == 4500
    assert timeline.selected_generated_clip_ids == {clip.id}


def test_generated_audio_clip_body_can_move(qtbot) -> None:
    clip = GeneratedAudioClip(
        path="missing.wav",
        start_ms=1000,
        source_offset_ms=0,
        duration_ms=1000,
        source_duration_ms=1000,
        reference_region_id="region",
        text="generated",
    )
    asset = MediaAsset("audio.wav", "audio.wav", duration_ms=5000)
    asset.generated_track.clips.append(clip)
    timeline = TimelineCanvas()
    qtbot.addWidget(timeline)
    timeline.set_asset(asset)
    timeline.show()
    generated_y = timeline.HEADER + timeline.waveform_height + 15

    QTest.mousePress(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(timeline._x_for_ms(1500), generated_y),
    )
    QTest.mouseMove(
        timeline,
        QPoint(timeline._x_for_ms(2500), generated_y),
        delay=10,
    )
    QTest.mouseRelease(
        timeline,
        Qt.MouseButton.LeftButton,
        pos=QPoint(timeline._x_for_ms(2500), generated_y),
    )

    assert clip.start_ms == 2000
