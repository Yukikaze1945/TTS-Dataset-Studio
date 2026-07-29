from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QSizePolicy, QWidget

from tts_dataset_studio.domain.models import (
    ExportRegion,
    GeneratedAudioClip,
    MediaAsset,
    SubtitleCue,
)

DBFS_MARKS = (0, -6, -12, -24, -48)
DBFS_FLOOR = -60.0


def dbfs_to_amplitude(dbfs: float) -> float:
    """Convert a dBFS value to the linear amplitude used by the waveform."""
    return 10 ** (dbfs / 20)


def amplitude_to_dbfs_radius(amplitude: float) -> float:
    """Map linear peak amplitude onto a logarithmic -60..0 dBFS ruler."""
    if amplitude <= 0:
        return 0.0
    dbfs = 20 * math.log10(min(1.0, amplitude))
    return max(0.0, min(1.0, (dbfs - DBFS_FLOOR) / -DBFS_FLOOR))


def apply_gain_to_peak(
    peak: float,
    gain_db: float,
    bypassed: bool = False,
) -> tuple[float, bool]:
    effective_gain = 0.0 if bypassed else gain_db
    adjusted = max(0.0, peak) * (10 ** (effective_gain / 20))
    return min(1.0, adjusted), adjusted > 1.0


def ruler_interval_seconds(pixels_per_second: float) -> int:
    for interval in (1, 2, 5, 10, 30, 60, 120, 300, 600, 1800, 3600):
        if pixels_per_second * interval >= 70:
            return interval
    return 7200


def ruler_timecode(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def dbfs_y_positions(
    dbfs: float,
    top: float,
    height: float,
) -> tuple[float, float]:
    center = top + height / 2
    radius = height * 0.43
    relative_radius = max(0.0, min(1.0, (dbfs - DBFS_FLOOR) / -DBFS_FLOOR))
    offset = relative_radius * radius
    return center - offset, center + offset


class WaveformDbScale(QWidget):
    """Fixed dBFS ruler aligned with the waveform lane of the timeline."""

    source_mute_clicked = Signal()
    source_solo_clicked = Signal()
    generated_mute_clicked = Signal(str)
    generated_solo_clicked = Signal(str)

    WIDTH = 92

    def __init__(
        self,
        timeline: TimelineCanvas,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.timeline = timeline
        timeline.waveform_height_changed.connect(lambda _height: self.update())
        self.setFixedWidth(self.WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setToolTip(
            "轨道监听：M = 静音，S = 独奏。存在独奏轨时只播放独奏轨。"
        )
        self.setAccessibleName("音轨静音与独奏控制")

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#111821"))
        top = float(TimelineCanvas.HEADER)
        height = float(self.timeline.waveform_height)
        painter.fillRect(
            QRectF(0, top, self.width(), height),
            QColor("#0d161e"),
        )
        painter.setFont(QFont("Consolas", 7))
        painter.setPen(QColor("#7f91a5"))
        painter.drawText(
            QRectF(0, 4, self.width() - 5, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "dBFS",
        )
        if height < TimelineCanvas.DB_SCALE_MIN_HEIGHT:
            painter.setPen(QColor("#667789"))
            painter.drawText(
                QRectF(4, top, self.width() - 10, height),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "↕\n拉高\n看标尺",
            )
            self._paint_track_controls(painter)
            return
        for dbfs in DBFS_MARKS:
            upper, lower = dbfs_y_positions(dbfs, top, height)
            label = f"{dbfs}"
            for y in (upper, lower):
                painter.setPen(QPen(QColor("#344555"), 1))
                painter.drawLine(self.width() - 7, round(y), self.width(), round(y))
                painter.setPen(QColor("#8798aa"))
                painter.drawText(
                    QRectF(2, y - 8, self.width() - 12, 16),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )
        center = top + height / 2
        painter.setPen(QColor("#667789"))
        painter.drawText(
            QRectF(2, center - 8, self.width() - 12, 16),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "-∞",
        )
        painter.setPen(QPen(QColor("#253443"), 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        self._paint_track_controls(painter)

    def _paint_track_controls(self, painter: QPainter) -> None:
        asset = self.timeline.asset
        if not asset:
            return
        source_y = TimelineCanvas.HEADER + 5
        painter.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        painter.setPen(QColor("#9fb0c0"))
        painter.drawText(
            QRectF(4, source_y, 42, 20),
            Qt.AlignmentFlag.AlignVCenter,
            "原声",
        )
        states = [
            ("M", asset.source_muted, QRectF(49, source_y, 18, 20)),
            ("S", asset.source_solo, QRectF(70, source_y, 18, 20)),
        ]
        for index, track in enumerate(asset.generated_audio_tracks):
            track_y = (
                TimelineCanvas.HEADER
                + self.timeline.waveform_height
                + index * TimelineCanvas.TRACK_HEIGHT
                + 5
            )
            label = "增强" if track.kind == "enhancement" else "AI"
            painter.drawText(
                QRectF(4, track_y, 42, 20),
                Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            states.extend(
                [
                    ("M", track.muted, QRectF(49, track_y, 18, 20)),
                    ("S", track.solo, QRectF(70, track_y, 18, 20)),
                ]
            )
        for text, active, rect in states:
            painter.setBrush(QColor("#d99135" if active else "#1d2a36"))
            painter.setPen(QPen(QColor("#ffc36b" if active else "#415466"), 1))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor("#17120b" if active else "#a8b8c6"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            if active:
                painter.setBrush(QColor("#fff1cf"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(
                    QRectF(rect.right() - 4, rect.top() + 2, 2.5, 2.5)
                )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self.timeline.asset:
            return
        y = event.position().y()
        x = event.position().x()
        source_y = TimelineCanvas.HEADER + 5
        if 49 <= x <= 67 and source_y <= y <= source_y + 20:
            self.source_mute_clicked.emit()
        elif 70 <= x <= 88 and source_y <= y <= source_y + 20:
            self.source_solo_clicked.emit()
        else:
            for index, track in enumerate(self.timeline.asset.generated_audio_tracks):
                track_y = (
                    TimelineCanvas.HEADER
                    + self.timeline.waveform_height
                    + index * TimelineCanvas.TRACK_HEIGHT
                    + 5
                )
                if 49 <= x <= 67 and track_y <= y <= track_y + 20:
                    self.generated_mute_clicked.emit(track.id)
                    break
                if 70 <= x <= 88 and track_y <= y <= track_y + 20:
                    self.generated_solo_clicked.emit(track.id)
                    break
        self.update()


class TimelineScrollArea(QScrollArea):
    """Scroll area that owns timeline zoom gestures before scrollbars consume them."""

    def __init__(
        self,
        timeline: TimelineCanvas,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.timeline = timeline
        self.setWidget(timeline)
        for target in (
            self.viewport(),
            timeline,
            self.horizontalScrollBar(),
            self.verticalScrollBar(),
        ):
            target.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel and self._is_alt_zoom(event):
            self._apply_zoom_event(event)
            return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._is_alt_zoom(event):
            self._apply_zoom_event(event)
            return
        super().wheelEvent(event)

    @staticmethod
    def _is_alt_zoom(event: QWheelEvent) -> bool:
        modifiers = event.modifiers() | QApplication.keyboardModifiers()
        return bool(modifiers & Qt.KeyboardModifier.AltModifier)

    def _apply_zoom_event(self, event: QWheelEvent) -> None:
        angle = event.angleDelta()
        delta = angle.y() or angle.x()
        self.timeline.zoom_by_wheel_delta(delta, self.viewport().width())
        QTimer.singleShot(0, self.center_on_playhead)
        event.accept()

    def center_on_playhead(self) -> None:
        viewport_width = self.viewport().width()
        x = self.timeline._x_for_ms(self.timeline.playhead_ms)
        self.horizontalScrollBar().setValue(max(0, x - viewport_width // 2))

    def ensure_playhead_visible(self) -> None:
        bar = self.horizontalScrollBar()
        viewport_width = self.viewport().width()
        x = self.timeline._x_for_ms(self.timeline.playhead_ms)
        if x < bar.value() or x > bar.value() + viewport_width:
            bar.setValue(max(0, x - viewport_width // 2))

    def fit_timeline(self) -> None:
        self.timeline.fit_to_width(self.viewport().width())
        QTimer.singleShot(0, self.center_on_playhead)


@dataclass(slots=True)
class _DragState:
    kind: str
    item_id: str
    edge: str
    origin_x: int
    start_ms: int
    end_ms: int
    source_offset_ms: int = 0


class TimelineCanvas(QWidget):
    cue_selected = Signal(str, str, bool, bool)
    region_selected = Signal(str, bool, bool)
    generated_clip_selected = Signal(str, bool, bool)
    generated_focus_cleared = Signal()
    generated_clip_changed = Signal(object)
    generated_clip_collision = Signal(str)
    item_changed = Signal(object)
    seek_requested = Signal(int)
    scrub_requested = Signal(int)
    scrub_finished = Signal(int)
    waveform_height_changed = Signal(int)

    HEADER = 42
    DEFAULT_WAVEFORM_HEIGHT = 96
    MIN_WAVEFORM_HEIGHT = 48
    MAX_WAVEFORM_HEIGHT = 280
    DB_SCALE_MIN_HEIGHT = 120
    TRACK_HEIGHT = 42

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.asset: MediaAsset | None = None
        self.peaks: list[float] = []
        self.generated_peaks: dict[str, list[float]] = {}
        self.pixels_per_second = 90.0
        self.playhead_ms = 0
        self.in_point_ms: int | None = None
        self.selected_cue_id: str | None = None
        self.selected_cue_ids: set[str] = set()
        self.selected_region_id: str | None = None
        self.selected_region_ids: set[str] = set()
        self.selected_generated_clip_id: str | None = None
        self.selected_generated_clip_ids: set[str] = set()
        self._drag: _DragState | None = None
        self._resizing_waveform = False
        self._scrubbing_playhead = False
        self.waveform_height = self.DEFAULT_WAVEFORM_HEIGHT
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_asset(self, asset: MediaAsset | None, peaks: list[float] | None = None) -> None:
        self.asset = asset
        self.peaks = peaks or []
        self.selected_cue_id = None
        self.selected_cue_ids.clear()
        self.selected_region_id = None
        self.selected_region_ids.clear()
        self.selected_generated_clip_id = None
        self.selected_generated_clip_ids.clear()
        self.in_point_ms = None
        self._resize_for_content()
        self.update()

    def set_waveform(self, peaks: list[float]) -> None:
        self.peaks = peaks
        self.update()

    def set_generated_waveform(self, clip_id: str, peaks: list[float]) -> None:
        self.generated_peaks[clip_id] = peaks
        self.update()

    def set_playhead(self, milliseconds: int) -> None:
        old_x = self._x_for_ms(self.playhead_ms)
        self.playhead_ms = max(0, milliseconds)
        new_x = self._x_for_ms(self.playhead_ms)
        self.update(min(old_x, new_x) - 3, 0, abs(new_x - old_x) + 7, self.height())

    def set_in_point(self, milliseconds: int | None) -> None:
        self.in_point_ms = milliseconds
        self.update()

    def _resize_for_content(self) -> None:
        track_count = len(self._visible_subtitle_tracks()) + len(
            self._generated_tracks()
        )
        height = (
            self.HEADER
            + self.waveform_height
            + max(1, track_count) * self.TRACK_HEIGHT
            + 20
        )
        duration = self._timeline_duration()
        width = max(900, round(duration / 1000 * self.pixels_per_second) + 80)
        self.setFixedSize(width, height)

    def _visible_subtitle_tracks(self):
        if not self.asset:
            return []
        return [track for track in self.asset.subtitle_tracks if track.visible]

    def _generated_tracks(self):
        return self.asset.generated_audio_tracks if self.asset else []

    def _generated_track_for_clip(self, clip_id: str):
        if not self.asset:
            return None
        return self.asset.track_for_clip(clip_id)

    def _generated_clip(self, clip_id: str) -> GeneratedAudioClip | None:
        track = self._generated_track_for_clip(clip_id)
        if not track:
            return None
        return next((clip for clip in track.clips if clip.id == clip_id), None)

    def _timeline_duration(self) -> int:
        if not self.asset:
            return 10_000
        generated_end = max(
            (clip.end_ms for clip in self.asset.generated_clips()),
            default=0,
        )
        return max(1, self.asset.duration_ms, generated_end)

    def _x_for_ms(self, milliseconds: int) -> int:
        return round(milliseconds / 1000 * self.pixels_per_second)

    def _ms_for_x(self, x: int) -> int:
        value = round(x / self.pixels_per_second * 1000)
        maximum = self._timeline_duration() if self.asset else value
        return max(0, min(maximum, value))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(event.rect(), QColor("#0c1117"))
        if not self.asset:
            painter.setPen(QColor("#647184"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "拖入音视频以建立时间轴")
            return
        self._paint_ruler(painter)
        self._paint_waveform(painter)
        self._paint_regions(painter)
        self._paint_generated_tracks(painter)
        self._paint_subtitles(painter)
        self._paint_waveform_resize_handle(painter)
        x = self._x_for_ms(self.playhead_ms)
        painter.setPen(QPen(QColor("#ffcc66"), 1.5))
        painter.drawLine(x, 18, x, self.height())
        painter.setBrush(QColor("#ffcc66"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon([QPoint(x - 5, 17), QPoint(x + 5, 17), QPoint(x, 25)])
        self._paint_in_point(painter)

    def _paint_in_point(self, painter: QPainter) -> None:
        if self.in_point_ms is None:
            return
        x = self._x_for_ms(self.in_point_ms)
        color = QColor("#58d6c1")
        painter.setPen(QPen(QColor(88, 214, 193, 210), 2))
        painter.drawLine(x, 17, x, self.height())
        label_rect = QRectF(max(1, x - 2), 2, 30, 17)
        painter.setPen(QPen(QColor("#397f74"), 1))
        painter.setBrush(QColor("#122f2c"))
        painter.drawRoundedRect(label_rect, 3, 3)
        painter.setPen(color)
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, "IN")

    def _paint_ruler(self, painter: QPainter) -> None:
        painter.fillRect(0, 0, self.width(), self.HEADER, QColor("#151c25"))
        interval = ruler_interval_seconds(self.pixels_per_second)
        total_seconds = max(1, self.asset.duration_ms // 1000 + 1)
        painter.setFont(QFont("Consolas", 8))
        for second in range(0, total_seconds + 1, interval):
            x = round(second * self.pixels_per_second)
            painter.setPen(QColor("#405064"))
            painter.drawLine(x, 28, x, self.HEADER)
            painter.setPen(QColor("#77869a"))
            painter.drawText(x + 4, 18, ruler_timecode(second))

    def _paint_waveform(self, painter: QPainter) -> None:
        top = self.HEADER
        rect = QRectF(0, top, self.width(), self.waveform_height)
        painter.fillRect(rect, QColor("#101a22"))
        center = top + self.waveform_height / 2
        if self.waveform_height >= self.DB_SCALE_MIN_HEIGHT:
            for dbfs in DBFS_MARKS:
                upper, lower = dbfs_y_positions(
                    dbfs,
                    float(top),
                    float(self.waveform_height),
                )
                color = QColor("#314552" if dbfs in (0, -6, -12) else "#263641")
                pen = QPen(color, 1)
                if dbfs not in (0, -6):
                    pen.setStyle(Qt.PenStyle.DotLine)
                painter.setPen(pen)
                painter.drawLine(0, round(upper), self.width(), round(upper))
                painter.drawLine(0, round(lower), self.width(), round(lower))
        painter.setPen(QPen(QColor("#405866"), 1))
        painter.drawLine(0, round(center), self.width(), round(center))
        if not self.peaks:
            painter.setPen(QColor("#526171"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "正在生成波形…")
            return
        duration = max(1, self.asset.duration_ms)
        waveform_color = QColor("#54c7b3")
        clipping_color = QColor("#ff5f66")
        painter.setPen(QPen(waveform_color, 1))
        pen_is_clipping = False
        last_x = -1
        merged_peak = 0.0
        for index, peak in enumerate(self.peaks):
            x = round(index / max(1, len(self.peaks) - 1) * self._x_for_ms(duration))
            merged_peak = max(merged_peak, peak)
            if x == last_x:
                continue
            adjusted_peak, clipping = apply_gain_to_peak(
                merged_peak,
                self.asset.gain_db,
                self.asset.gain_bypassed,
            )
            if clipping != pen_is_clipping:
                painter.setPen(
                    QPen(clipping_color if clipping else waveform_color, 1)
                )
                pen_is_clipping = clipping
            visible_peak = (
                amplitude_to_dbfs_radius(adjusted_peak)
                if self.waveform_height >= self.DB_SCALE_MIN_HEIGHT
                else adjusted_peak
            )
            amplitude = visible_peak * (self.waveform_height * 0.43)
            painter.drawLine(x, round(center - amplitude), x, round(center + amplitude))
            last_x = x
            merged_peak = 0.0

    def _paint_waveform_resize_handle(self, painter: QPainter) -> None:
        y = self.HEADER + self.waveform_height
        painter.setPen(QPen(QColor("#405468"), 1))
        painter.drawLine(0, y, self.width(), y)
        painter.setPen(QPen(QColor("#71869a"), 2))
        painter.drawLine(10, y - 2, 38, y - 2)
        painter.drawLine(10, y + 2, 38, y + 2)

    def _paint_regions(self, painter: QPainter) -> None:
        for region in self.asset.regions:
            left = self._x_for_ms(region.start_ms)
            right = self._x_for_ms(region.end_ms)
            selected = region.id in self.selected_region_ids
            if not selected:
                continue
            painter.fillRect(
                QRectF(left, self.HEADER, right - left, self.height()),
                QColor(98, 213, 190, 78),
            )
            painter.setPen(QPen(QColor("#82ead5"), 2))
            painter.drawLine(left, self.HEADER, left, self.height())
            painter.drawLine(right, self.HEADER, right, self.height())

    def _paint_subtitles(self, painter: QPainter) -> None:
        top = (
            self.HEADER
            + self.waveform_height
            + len(self._generated_tracks()) * self.TRACK_HEIGHT
        )
        for track_index, track in enumerate(self._visible_subtitle_tracks()):
            row_top = top + track_index * self.TRACK_HEIGHT
            painter.fillRect(
                QRectF(0, row_top, self.width(), self.TRACK_HEIGHT - 1),
                QColor("#141b24"),
            )
            for cue in track.cues:
                left = self._x_for_ms(cue.start_ms)
                right = max(left + 4, self._x_for_ms(cue.end_ms))
                selected = cue.id in self.selected_cue_ids
                painter.setBrush(QColor("#3b9384" if selected else "#263f4d"))
                painter.setPen(QPen(QColor("#8be7d4" if selected else "#405d6c"), 1))
                cue_rect = QRectF(left + 1, row_top + 5, right - left - 2, self.TRACK_HEIGHT - 11)
                painter.drawRoundedRect(cue_rect, 4, 4)
                painter.setPen(QColor("#effaf8" if selected else "#bac8d1"))
                painter.setClipRect(cue_rect.adjusted(6, 0, -4, 0))
                painter.drawText(
                    cue_rect.adjusted(6, 0, 0, 0),
                    Qt.AlignmentFlag.AlignVCenter,
                    cue.text,
                )
                painter.setClipping(False)

    def _paint_generated_tracks(self, painter: QPainter) -> None:
        if not self.asset:
            return
        for track_index, track in enumerate(self._generated_tracks()):
            row_top = (
                self.HEADER
                + self.waveform_height
                + track_index * self.TRACK_HEIGHT
            )
            self._paint_generated_track(painter, track, row_top)

    def _paint_generated_track(self, painter: QPainter, track, row_top: int) -> None:
        is_enhancement = track.kind == "enhancement"
        painter.fillRect(
            QRectF(0, row_top, self.width(), self.TRACK_HEIGHT - 1),
            QColor("#13211f" if is_enhancement else "#151c26"),
        )
        for clip in track.clips:
            left = self._x_for_ms(clip.start_ms)
            right = max(left + 5, self._x_for_ms(clip.end_ms))
            selected = clip.id in self.selected_generated_clip_ids
            rect = QRectF(
                left + 1,
                row_top + 4,
                max(3, right - left - 2),
                self.TRACK_HEIGHT - 9,
            )
            online = Path(clip.path).is_file()
            if is_enhancement:
                fill = "#247b70" if selected else "#244740"
                outline = "#7ee3cf" if selected else "#477c72"
                waveform = "#9df1df"
                text_color = "#edfffb"
            else:
                fill = "#9a6128" if selected else "#533d2c"
                outline = "#ffc36b" if selected else "#98724e"
                waveform = "#ffd08a"
                text_color = "#fff2df"
            painter.setBrush(QColor(fill))
            painter.setPen(QPen(QColor(outline), 1))
            painter.drawRoundedRect(rect, 4, 4)
            peaks = self.generated_peaks.get(clip.id, [])
            if peaks:
                center = rect.center().y()
                height = rect.height() * 0.37
                painter.setPen(QPen(QColor(waveform), 1))
                for index, peak in enumerate(peaks):
                    x = rect.left() + index / max(1, len(peaks) - 1) * rect.width()
                    amplitude = min(1.0, peak) * height
                    painter.drawLine(
                        round(x),
                        round(center - amplitude),
                        round(x),
                        round(center + amplitude),
                    )
            painter.setPen(QColor(text_color if online else "#ff7676"))
            painter.setClipRect(rect.adjusted(5, 0, -3, 0))
            painter.drawText(
                rect.adjusted(5, 0, -3, 0),
                Qt.AlignmentFlag.AlignVCenter,
                clip.text if online else f"OFFLINE · {clip.text}",
            )
            painter.setClipping(False)

    def _hit_test(self, pos: QPoint) -> tuple[str, str, str] | None:
        if not self.asset:
            return None
        x_ms = self._ms_for_x(pos.x())
        tolerance_ms = round(7 / self.pixels_per_second * 1000)
        generated_top = self.HEADER + self.waveform_height
        generated_tracks = self._generated_tracks()
        generated_bottom = generated_top + len(generated_tracks) * self.TRACK_HEIGHT
        if generated_top <= pos.y() < generated_bottom:
            track_index = (pos.y() - generated_top) // self.TRACK_HEIGHT
            track = generated_tracks[track_index]
            for clip in reversed(track.clips):
                if clip.start_ms - tolerance_ms <= x_ms <= clip.end_ms + tolerance_ms:
                    edge = (
                        "left"
                        if abs(x_ms - clip.start_ms) <= tolerance_ms
                        else "right"
                    )
                    if (
                        clip.start_ms + tolerance_ms
                        < x_ms
                        < clip.end_ms - tolerance_ms
                    ):
                        edge = "body"
                    return "generated", clip.id, edge
        subtitle_top = generated_bottom
        if pos.y() >= subtitle_top:
            track_index = (pos.y() - subtitle_top) // self.TRACK_HEIGHT
            visible_tracks = self._visible_subtitle_tracks()
            if 0 <= track_index < len(visible_tracks):
                track = visible_tracks[track_index]
                for cue in track.cues:
                    if cue.start_ms - tolerance_ms <= x_ms <= cue.end_ms + tolerance_ms:
                        edge = "left" if abs(x_ms - cue.start_ms) <= tolerance_ms else "right"
                        if cue.start_ms + tolerance_ms < x_ms < cue.end_ms - tolerance_ms:
                            edge = "body"
                        return "cue", f"{track.id}:{cue.id}", edge
        for region in reversed(self.asset.regions):
            if region.id not in self.selected_region_ids:
                continue
            if abs(x_ms - region.start_ms) <= tolerance_ms:
                return "region", region.id, "left"
            if abs(x_ms - region.end_ms) <= tolerance_ms:
                return "region", region.id, "right"
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self.asset:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if event.position().y() < self.HEADER:
            self._scrubbing_playhead = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.scrub_requested.emit(self._ms_for_x(round(event.position().x())))
            event.accept()
            return
        waveform_bottom = self.HEADER + self.waveform_height
        if abs(event.position().y() - waveform_bottom) <= 6:
            self._resizing_waveform = True
            self.setCursor(Qt.CursorShape.SplitVCursor)
            event.accept()
            return
        hit = self._hit_test(event.position().toPoint())
        if hit is None:
            if self.selected_generated_clip_ids:
                self.selected_generated_clip_ids.clear()
                self.selected_generated_clip_id = None
                self.generated_focus_cleared.emit()
                self.update()
            self.seek_requested.emit(self._ms_for_x(round(event.position().x())))
            return
        kind, item_id, edge = hit
        additive = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if kind == "cue":
            track_id, cue_id = item_id.split(":", 1)
            track = next(track for track in self.asset.subtitle_tracks if track.id == track_id)
            cue = next(cue for cue in track.cues if cue.id == cue_id)
            selected = True
            if additive:
                if cue_id in self.selected_cue_ids:
                    self.selected_cue_ids.remove(cue_id)
                    selected = False
                else:
                    self.selected_cue_ids.add(cue_id)
            else:
                self.selected_cue_ids = {cue_id}
                self.selected_region_ids.clear()
            if self.selected_generated_clip_ids:
                self.selected_generated_clip_ids.clear()
                self.selected_generated_clip_id = None
                self.generated_focus_cleared.emit()
            self.selected_cue_id = cue_id if selected else None
            self.cue_selected.emit(track_id, cue_id, additive, selected)
            self._drag = _DragState(
                kind,
                item_id,
                edge,
                round(event.position().x()),
                cue.start_ms,
                cue.end_ms,
            )
        elif kind == "generated":
            clip = self._generated_clip(item_id)
            if clip is None:
                return
            selected = True
            if additive:
                if item_id in self.selected_generated_clip_ids:
                    self.selected_generated_clip_ids.remove(item_id)
                    selected = False
                else:
                    self.selected_generated_clip_ids.add(item_id)
            else:
                self.selected_generated_clip_ids = {item_id}
            self.selected_generated_clip_id = (
                item_id if selected else next(iter(self.selected_generated_clip_ids), None)
            )
            self.generated_clip_selected.emit(item_id, additive, selected)
            self._drag = _DragState(
                kind,
                item_id,
                edge,
                round(event.position().x()),
                clip.start_ms,
                clip.end_ms,
                clip.source_offset_ms,
            )
        else:
            region = next(region for region in self.asset.regions if region.id == item_id)
            selected = True
            if additive:
                if item_id in self.selected_region_ids:
                    self.selected_region_ids.remove(item_id)
                    selected = False
                else:
                    self.selected_region_ids.add(item_id)
            else:
                self.selected_region_ids = {item_id}
                self.selected_cue_ids.clear()
                self.selected_cue_id = None
            if self.selected_generated_clip_ids:
                self.selected_generated_clip_ids.clear()
                self.selected_generated_clip_id = None
                self.generated_focus_cleared.emit()
            self.selected_region_id = item_id if selected else None
            self.region_selected.emit(item_id, additive, selected)
            self._drag = _DragState(
                kind,
                item_id,
                edge,
                round(event.position().x()),
                region.start_ms,
                region.end_ms,
            )
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._scrubbing_playhead:
            self.scrub_requested.emit(self._ms_for_x(round(event.position().x())))
            event.accept()
            return
        if self._resizing_waveform:
            new_height = max(
                self.MIN_WAVEFORM_HEIGHT,
                min(
                    self.MAX_WAVEFORM_HEIGHT,
                    round(event.position().y()) - self.HEADER,
                ),
            )
            if new_height != self.waveform_height:
                self.waveform_height = new_height
                self._resize_for_content()
                self.waveform_height_changed.emit(new_height)
                self.update()
            return
        if not self._drag or not self.asset:
            hit = self._hit_test(event.position().toPoint())
            cursor = Qt.CursorShape.ArrowCursor
            waveform_bottom = self.HEADER + self.waveform_height
            if event.position().y() < self.HEADER:
                cursor = Qt.CursorShape.SizeHorCursor
            elif abs(event.position().y() - waveform_bottom) <= 6:
                cursor = Qt.CursorShape.SplitVCursor
            elif hit and hit[2] in {"left", "right"}:
                cursor = Qt.CursorShape.SizeHorCursor
            elif hit:
                cursor = Qt.CursorShape.PointingHandCursor
            self.setCursor(cursor)
            return
        delta_ms = round(
            (event.position().x() - self._drag.origin_x) / self.pixels_per_second * 1000
        )
        if self._drag.kind == "cue":
            track_id, cue_id = self._drag.item_id.split(":", 1)
            track = next(track for track in self.asset.subtitle_tracks if track.id == track_id)
            item: SubtitleCue | ExportRegion = next(cue for cue in track.cues if cue.id == cue_id)
        elif self._drag.kind == "region":
            item = next(region for region in self.asset.regions if region.id == self._drag.item_id)
        else:
            clip = self._generated_clip(self._drag.item_id)
            if clip is None:
                return
            if self._drag.edge == "body":
                clip.start_ms = max(
                    0,
                    self._snap_to_playhead(self._drag.start_ms + delta_ms),
                )
            elif self._drag.edge == "left":
                delta = max(
                    -self._drag.source_offset_ms,
                    min(self._drag.end_ms - self._drag.start_ms - 10, delta_ms),
                )
                clip.start_ms = max(0, self._drag.start_ms + delta)
                actual_delta = clip.start_ms - self._drag.start_ms
                clip.source_offset_ms = self._drag.source_offset_ms + actual_delta
                clip.duration_ms = (
                    self._drag.end_ms - self._drag.start_ms - actual_delta
                )
            else:
                proposed_end = self._snap_to_playhead(self._drag.end_ms + delta_ms)
                clip.duration_ms = max(
                    10,
                    min(
                        clip.source_duration_ms - clip.source_offset_ms,
                        proposed_end - clip.start_ms,
                    ),
                )
            self._resize_for_content()
            self.update()
            return
        if self._drag.edge == "left":
            proposed = self._snap_to_playhead(self._drag.start_ms + delta_ms)
            item.start_ms = max(0, min(self._drag.end_ms - 10, proposed))
        elif self._drag.edge == "right":
            proposed = self._snap_to_playhead(self._drag.end_ms + delta_ms)
            item.end_ms = min(
                self.asset.duration_ms,
                max(self._drag.start_ms + 10, proposed),
            )
        else:
            duration = self._drag.end_ms - self._drag.start_ms
            start = max(0, min(self.asset.duration_ms - duration, self._drag.start_ms + delta_ms))
            item.start_ms = start
            item.end_ms = start + duration
        self.update()

    def _snap_to_playhead(self, milliseconds: int) -> int:
        tolerance_ms = max(20, round(10 / self.pixels_per_second * 1000))
        if abs(milliseconds - self.playhead_ms) <= tolerance_ms:
            return self.playhead_ms
        return milliseconds

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._scrubbing_playhead:
            self._scrubbing_playhead = False
            self.unsetCursor()
            self.scrub_finished.emit(self._ms_for_x(round(event.position().x())))
            event.accept()
            return
        if self._resizing_waveform:
            self._resizing_waveform = False
            self.unsetCursor()
            event.accept()
            return
        if self._drag:
            drag = self._drag
            if drag.kind == "cue" and self.asset:
                track_id, cue_id = drag.item_id.split(":", 1)
                track = next(track for track in self.asset.subtitle_tracks if track.id == track_id)
                item = next(cue for cue in track.cues if cue.id == cue_id)
            elif drag.kind == "region" and self.asset:
                item = next(region for region in self.asset.regions if region.id == drag.item_id)
            elif self.asset:
                item = self._generated_clip(drag.item_id)
            else:
                item = None
            self._drag = None
            if isinstance(item, GeneratedAudioClip):
                before = (
                    drag.start_ms,
                    drag.source_offset_ms,
                    drag.end_ms - drag.start_ms,
                )
                after = (item.start_ms, item.source_offset_ms, item.duration_ms)
                track = self._generated_track_for_clip(item.id)
                collision = bool(track) and any(
                    other.id != item.id
                    and item.start_ms < other.end_ms
                    and other.start_ms < item.end_ms
                    for other in track.clips
                )
                if collision:
                    item.start_ms, item.source_offset_ms, item.duration_ms = before
                    self.generated_clip_collision.emit(
                        "AI 音频片段不能与同轨其他片段重叠。"
                    )
                    self._resize_for_content()
                    self.update()
                elif before != after:
                    self.generated_clip_changed.emit((item, before, after))
            elif item and (item.start_ms, item.end_ms) != (drag.start_ms, drag.end_ms):
                self.item_changed.emit(
                    (item, (drag.start_ms, drag.end_ms), (item.start_ms, item.end_ms))
                )

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.zoom_by_wheel_delta(event.angleDelta().y())
            event.accept()
            return
        super().wheelEvent(event)

    def zoom_by_wheel_delta(
        self,
        delta: int,
        viewport_width: int | None = None,
    ) -> None:
        if not delta:
            return
        factor = 1.8 if delta > 0 else 1 / 1.8
        minimum = self._fit_pixels_per_second(viewport_width)
        self.pixels_per_second = max(
            minimum,
            min(2000.0, self.pixels_per_second * factor),
        )
        self._resize_for_content()
        self.update()

    def fit_to_width(self, viewport_width: int) -> None:
        self.pixels_per_second = self._fit_pixels_per_second(viewport_width)
        self._resize_for_content()
        self.update()

    def _fit_pixels_per_second(self, viewport_width: int | None = None) -> float:
        if not self.asset or self.asset.duration_ms <= 0:
            return 0.01
        if viewport_width is None:
            viewport = self.parentWidget()
            viewport_width = viewport.width() if viewport else 900
        available_width = max(120, viewport_width - 80)
        duration_seconds = self.asset.duration_ms / 1000
        return max(0.001, available_width / duration_seconds)
