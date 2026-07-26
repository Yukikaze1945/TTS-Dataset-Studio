from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QLabel, QStackedWidget, QWidget

from tts_dataset_studio.services.media import ToolPaths
from tts_dataset_studio.ui.mpv_backend import MpvBackend


class PlayerWidget(QStackedWidget):
    position_changed = Signal(int)
    duration_changed = Signal(int)
    error_occurred = Signal(str)
    warning_occurred = Signal(str)
    backend_changed = Signal(str)

    def __init__(self, audio_placeholder: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.qt_video = QVideoWidget()
        self.audio_placeholder = audio_placeholder
        self.addWidget(self.qt_video)
        self.addWidget(self.audio_placeholder)
        self.subtitle_overlay = QLabel(self)
        self.subtitle_overlay.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
        )
        self.subtitle_overlay.setWordWrap(True)
        self.subtitle_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.subtitle_overlay.setStyleSheet(
            "QLabel {"
            "color: white;"
            "background: rgba(0, 0, 0, 150);"
            "border-radius: 5px;"
            "padding: 7px 12px;"
            "font-size: 20px;"
            "font-weight: 600;"
            "}"
        )
        self.subtitle_overlay.hide()

        self.audio_output = QAudioOutput(self)
        self.qt_player = QMediaPlayer(self)
        self.qt_player.setAudioOutput(self.audio_output)
        self.qt_player.setVideoOutput(self.qt_video)
        self.qt_player.positionChanged.connect(
            lambda value: self.position_changed.emit(int(value))
        )
        self.qt_player.durationChanged.connect(
            lambda value: self.duration_changed.emit(int(value))
        )
        self.qt_player.errorOccurred.connect(
            lambda _error, message: self.error_occurred.emit(message)
        )

        self.mpv: MpvBackend | None = None
        self._using_mpv = False
        self._current_path: Path | None = None
        self._has_video = False
        self._preview_mode = "video"
        self._subtitle_text = ""
        self._gain_db = 0.0
        self._gain_bypassed = False
        self._range_end_ms: int | None = None
        self._initialize_mpv()

    def _initialize_mpv(self) -> None:
        if os.environ.get("TTS_DATASET_STUDIO_DISABLE_MPV") == "1":
            self.backend_changed.emit("Qt Multimedia")
            return
        try:
            executable = ToolPaths.discover().mpv
        except FileNotFoundError:
            executable = None
        if not executable:
            self.backend_changed.emit("Qt Multimedia")
            return
        self.mpv = MpvBackend(executable, self)
        self.addWidget(self.mpv.surface)
        self._using_mpv = True
        self.mpv.position_changed.connect(self._mpv_position_changed)
        self.mpv.duration_changed.connect(self.duration_changed)
        self.mpv.ready.connect(self._mpv_ready)
        self.mpv.failed.connect(self._mpv_failed)
        self.mpv.command_error.connect(self._mpv_command_error)

    @property
    def backend_name(self) -> str:
        if self._using_mpv:
            return "mpv IPC"
        return "Qt Multimedia"

    def _mpv_ready(self) -> None:
        if not self.mpv or not self._using_mpv:
            return
        self.mpv.set_gain(self._gain_db, self._gain_bypassed)
        self._render_subtitle()
        self.backend_changed.emit("mpv IPC")

    def _mpv_failed(self, message: str) -> None:
        if not self._using_mpv:
            return
        self._using_mpv = False
        if self.mpv:
            self.mpv.shutdown()
        self.backend_changed.emit("Qt Multimedia（mpv 回退）")
        if self._current_path:
            self._load_qt(self._current_path, self._has_video)
        self.error_occurred.emit(message)

    def _mpv_command_error(self, command_name: str, error: str) -> None:
        message = f"mpv 命令 {command_name} 失败：{error}"
        if command_name == "loadfile":
            self.error_occurred.emit(message)
        else:
            self.warning_occurred.emit(message)

    def _mpv_position_changed(self, milliseconds: int) -> None:
        self.position_changed.emit(milliseconds)
        if self._range_end_ms is not None and milliseconds >= self._range_end_ms:
            if self.mpv:
                self.mpv.set_paused(True)
            self._range_end_ms = None

    def load(self, path: Path, has_video: bool) -> None:
        if not path.exists():
            self.error_occurred.emit(f"素材文件不存在：{path}")
            return
        self._current_path = path
        self._has_video = has_video
        if not has_video:
            self._preview_mode = "waveform"
        self._range_end_ms = None
        if self._using_mpv and self.mpv:
            self._apply_preview_mode()
            self.mpv.load(path)
            self.mpv.set_gain(self._gain_db, self._gain_bypassed)
        else:
            self._load_qt(path, has_video)

    def _load_qt(self, path: Path, has_video: bool) -> None:
        self.qt_player.setSource(QUrl.fromLocalFile(str(path)))
        self._apply_preview_mode()

    def set_preview_mode(self, mode: str) -> None:
        if mode not in {"video", "waveform"}:
            raise ValueError(f"未知预览模式：{mode}")
        if mode == "video" and not self._has_video:
            mode = "waveform"
        self._preview_mode = mode
        self._apply_preview_mode()

    def _apply_preview_mode(self) -> None:
        if self._preview_mode == "waveform" or not self._has_video:
            self.setCurrentWidget(self.audio_placeholder)
        elif self._using_mpv and self.mpv:
            self.setCurrentWidget(self.mpv.surface)
        else:
            self.setCurrentWidget(self.qt_video)
        self._render_subtitle()

    def set_subtitle_text(self, text: str) -> None:
        text = text.strip()
        if text == self._subtitle_text:
            return
        self._subtitle_text = text
        self._render_subtitle()

    def _render_subtitle(self) -> None:
        visible_text = (
            self._subtitle_text
            if self._preview_mode == "video" and self._has_video
            else ""
        )
        if self._using_mpv and self.mpv:
            self.subtitle_overlay.hide()
            self.mpv.show_text(visible_text)
        else:
            self.subtitle_overlay.setText(visible_text)
            self.subtitle_overlay.setVisible(bool(visible_text))
            if visible_text:
                self.subtitle_overlay.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        margin = max(24, round(self.width() * 0.08))
        self.subtitle_overlay.setGeometry(
            margin,
            max(0, self.height() - 145),
            max(80, self.width() - margin * 2),
            105,
        )
        self.subtitle_overlay.raise_()

    def toggle(self) -> None:
        if self._using_mpv and self.mpv:
            self.mpv.toggle()
        elif self.qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.qt_player.pause()
        else:
            self.qt_player.play()

    def seek(self, milliseconds: int) -> None:
        if self._using_mpv and self.mpv:
            self.mpv.seek(milliseconds)
        else:
            self.qt_player.setPosition(milliseconds)

    def scrub(self, milliseconds: int) -> None:
        if self._using_mpv and self.mpv:
            self.mpv.scrub(milliseconds)
        else:
            self.qt_player.setPosition(milliseconds)

    def finish_scrub(self, milliseconds: int) -> None:
        if self._using_mpv and self.mpv:
            self.mpv.finish_scrub(milliseconds)
        else:
            self.qt_player.setPosition(milliseconds)

    def set_scrub_hz(self, frequency: int) -> None:
        if self.mpv:
            self.mpv.set_scrub_hz(frequency)

    @property
    def supports_frame_step(self) -> bool:
        return self._using_mpv and self.mpv is not None and self._has_video

    def previous_frame(self) -> bool:
        if not self.supports_frame_step or not self.mpv:
            return False
        self.mpv.set_paused(True)
        self.mpv.previous_frame()
        return True

    def next_frame(self) -> bool:
        if not self.supports_frame_step or not self.mpv:
            return False
        self.mpv.set_paused(True)
        self.mpv.next_frame()
        return True

    def play_range(self, start_ms: int, end_ms: int) -> None:
        if self._using_mpv and self.mpv:
            self._range_end_ms = end_ms
            self.mpv.seek(start_ms)
            self.mpv.set_paused(False)
            return
        self.seek(start_ms)
        self.qt_player.play()

        def stop_at(position: int) -> None:
            if position >= end_ms:
                self.qt_player.pause()
                try:
                    self.qt_player.positionChanged.disconnect(stop_at)
                except RuntimeError:
                    pass

        self.qt_player.positionChanged.connect(stop_at)

    def set_gain(self, gain_db: float, bypassed: bool = False) -> None:
        self._gain_db = gain_db
        self._gain_bypassed = bypassed
        if self._using_mpv and self.mpv:
            self.mpv.set_gain(gain_db, bypassed)
            return
        effective = 0.0 if bypassed else gain_db
        linear = min(1.0, 10 ** (effective / 20))
        self.audio_output.setVolume(linear)

    @property
    def position(self) -> int:
        if self._using_mpv and self.mpv:
            return self.mpv.position_ms
        return self.qt_player.position()

    def shutdown(self) -> None:
        if self.mpv:
            self.mpv.shutdown()
        self.qt_player.stop()

    def clear(self) -> None:
        self._range_end_ms = None
        self._current_path = None
        if self._using_mpv and self.mpv:
            self.mpv.stop()
        self.qt_player.stop()
        self.qt_player.setSource(QUrl())
        self.set_subtitle_text("")
        self.setCurrentWidget(self.audio_placeholder)
