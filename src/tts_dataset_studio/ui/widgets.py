from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPen
from PySide6.QtWidgets import QListWidget, QWidget

from tts_dataset_studio.services.media import MEDIA_EXTENSIONS
from tts_dataset_studio.services.subtitles import SUPPORTED_SUBTITLES


class DropListWidget(QListWidget):
    files_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        supported = [
            str(path)
            for path in paths
            if path.suffix.lower() in MEDIA_EXTENSIONS | SUPPORTED_SUBTITLES
        ]
        if supported:
            self.files_dropped.emit(supported)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class AudioPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.peaks: list[float] = []
        self.position_ratio = 0.0
        self.setMinimumHeight(240)

    def set_peaks(self, peaks: list[float]) -> None:
        self.peaks = peaks
        self.update()

    def set_position(self, position_ms: int, duration_ms: int) -> None:
        self.position_ratio = position_ms / duration_ms if duration_ms else 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0a0f14"))
        center = self.height() / 2
        painter.setPen(QPen(QColor("#243846"), 1))
        painter.drawLine(24, round(center), self.width() - 24, round(center))
        if not self.peaks:
            painter.setPen(QColor("#627184"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "AUDIO · 波形准备中")
            return
        available = max(1, self.width() - 48)
        painter.setPen(QPen(QColor("#5bd4bc"), 1.2))
        for x in range(available):
            index = min(len(self.peaks) - 1, round(x / available * (len(self.peaks) - 1)))
            amplitude = self.peaks[index] * self.height() * 0.36
            painter.drawLine(x + 24, round(center - amplitude), x + 24, round(center + amplitude))
        playhead = 24 + round(self.position_ratio * available)
        painter.setPen(QPen(QColor("#ffcc66"), 2))
        painter.drawLine(playhead, 18, playhead, self.height() - 18)

