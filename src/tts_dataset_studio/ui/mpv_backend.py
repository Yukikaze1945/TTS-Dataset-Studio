from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, Qt, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QWidget


def encode_command(parts: list[object], request_id: int | None = None) -> bytes:
    payload: dict[str, object] = {"command": parts}
    if request_id is not None:
        payload["request_id"] = request_id
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def gain_db_to_percent(gain_db: float, bypassed: bool = False) -> float:
    effective = 0.0 if bypassed else gain_db
    return max(0.0, min(400.0, 100 * (10 ** (effective / 20))))


class MpvBackend(QObject):
    position_changed = Signal(int)
    duration_changed = Signal(int)
    pause_changed = Signal(bool)
    volume_changed = Signal(float)
    ready = Signal()
    failed = Signal(str)
    command_error = Signal(str, str)

    def __init__(self, executable: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.surface = QWidget()
        self.surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.surface.setStyleSheet("background: #080c11;")
        self.executable = executable
        self.position_ms = 0
        self.duration_ms = 0
        self.paused = True
        self.volume_percent = 100.0
        self.connected = False
        self._closed = False
        self._read_buffer = bytearray()
        self._queued_commands: list[list[object]] = []
        self._next_request_id = 1
        self._pending_commands: dict[int, str] = {}
        self._pipe_name = f"tts-dataset-studio-{os.getpid()}-{uuid4().hex}"
        self._process = QProcess(self)
        self._socket = QLocalSocket(self)
        self._connect_timer = QTimer(self)
        self._connect_timer.setInterval(50)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(4000)
        self._scrub_timer = QTimer(self)
        self._scrub_timer.setSingleShot(True)
        self._scrub_timer.setInterval(33)
        self._pending_scrub_ms: int | None = None
        self._process.errorOccurred.connect(self._process_error)
        self._process.finished.connect(self._process_finished)
        self._socket.connected.connect(self._socket_connected)
        self._socket.readyRead.connect(self._read_messages)
        self._socket.errorOccurred.connect(self._socket_error)
        self._connect_timer.timeout.connect(self._try_connect)
        self._timeout_timer.timeout.connect(
            lambda: self._fail("mpv IPC 连接超时，已切换到 Qt 播放器。")
        )
        self._scrub_timer.timeout.connect(self._flush_scrub)
        self._start()

    def _start(self) -> None:
        window_id = int(self.surface.winId())
        pipe_path = rf"\\.\pipe\{self._pipe_name}"
        arguments = [
            "--no-config",
            "--idle=yes",
            "--keep-open=yes",
            "--force-window=yes",
            "--pause=yes",
            "--osc=no",
            "--input-default-bindings=no",
            "--input-vo-keyboard=no",
            "--sub-auto=no",
            "--sid=no",
            "--terminal=no",
            "--msg-level=all=no",
            "--volume-max=400",
            "--osd-align-x=center",
            "--osd-align-y=bottom",
            "--osd-margin-y=56",
            "--osd-font-size=42",
            "--osd-border-size=3",
            "--gpu-api=d3d11",
            f"--wid={window_id}",
            f"--input-ipc-server={pipe_path}",
        ]
        self._process.start(self.executable, arguments)
        self._connect_timer.start()
        self._timeout_timer.start()

    def _try_connect(self) -> None:
        if self.connected or self._closed:
            self._connect_timer.stop()
            return
        if self._socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            self._socket.connectToServer(self._pipe_name)

    def _socket_connected(self) -> None:
        if self._closed:
            return
        self.connected = True
        self._connect_timer.stop()
        self._timeout_timer.stop()
        self.command(["observe_property", 1, "time-pos"])
        self.command(["observe_property", 2, "duration"])
        self.command(["observe_property", 3, "pause"])
        self.command(["observe_property", 4, "volume"])
        queued = self._queued_commands
        self._queued_commands = []
        for command in queued:
            self.command(command)
        self.ready.emit()

    def _socket_error(self, _error) -> None:
        # ConnectionRefused is expected while mpv creates its named pipe.
        if not self.connected and not self._closed:
            self._socket.abort()

    def _process_error(self, _error) -> None:
        self._fail(self._process.errorString() or "无法启动 mpv。")

    def _process_finished(self, exit_code: int, _status) -> None:
        if not self._closed and exit_code:
            self._fail(f"mpv 异常退出，代码 {exit_code}。")

    def _fail(self, message: str) -> None:
        if self._closed:
            return
        self._closed = True
        self.connected = False
        self._connect_timer.stop()
        self._timeout_timer.stop()
        self.failed.emit(message)

    def command(self, parts: list[object]) -> None:
        if self._closed:
            return
        if not self.connected:
            self._queued_commands.append(parts)
            return
        request_id = self._next_request_id
        self._next_request_id += 1
        command_name = str(parts[0]) if parts else "unknown"
        self._pending_commands[request_id] = command_name
        self._socket.write(encode_command(parts, request_id))
        self._socket.flush()

    def _read_messages(self) -> None:
        self._read_buffer.extend(bytes(self._socket.readAll()))
        while b"\n" in self._read_buffer:
            raw, _, remainder = self._read_buffer.partition(b"\n")
            self._read_buffer = bytearray(remainder)
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if message.get("event") == "property-change":
                self._property_changed(message.get("name"), message.get("data"))
            request_id = message.get("request_id")
            command_name = (
                self._pending_commands.pop(request_id, "unknown")
                if isinstance(request_id, int)
                else "unknown"
            )
            error = message.get("error")
            if error and error != "success":
                self.command_error.emit(command_name, str(error))

    def _property_changed(self, name: str, value: object) -> None:
        if name == "time-pos" and isinstance(value, (int, float)):
            self.position_ms = round(float(value) * 1000)
            self.position_changed.emit(self.position_ms)
        elif name == "duration" and isinstance(value, (int, float)):
            self.duration_ms = round(float(value) * 1000)
            self.duration_changed.emit(self.duration_ms)
        elif name == "pause" and isinstance(value, bool):
            self.paused = value
            self.pause_changed.emit(value)
        elif name == "volume" and isinstance(value, (int, float)):
            self.volume_percent = float(value)
            self.volume_changed.emit(self.volume_percent)

    def load(self, path: Path) -> None:
        self.command(["loadfile", str(path.resolve()), "replace"])

    def toggle(self) -> None:
        self.command(["cycle", "pause"])

    def seek(self, milliseconds: int) -> None:
        self.command(["seek", max(0, milliseconds) / 1000, "absolute+exact"])

    def scrub(self, milliseconds: int) -> None:
        self._pending_scrub_ms = max(0, milliseconds)
        if not self._scrub_timer.isActive():
            self._scrub_timer.start()

    def set_scrub_hz(self, frequency: int) -> None:
        self._scrub_timer.setInterval(max(8, round(1000 / max(1, frequency))))

    def _flush_scrub(self) -> None:
        if self._pending_scrub_ms is None:
            return
        milliseconds = self._pending_scrub_ms
        self._pending_scrub_ms = None
        self.command(["seek", milliseconds / 1000, "absolute+keyframes"])

    def finish_scrub(self, milliseconds: int) -> None:
        self._scrub_timer.stop()
        self._pending_scrub_ms = None
        self.seek(milliseconds)

    def previous_frame(self) -> None:
        self.command(["frame-back-step"])

    def next_frame(self) -> None:
        self.command(["frame-step"])

    def set_paused(self, paused: bool) -> None:
        self.command(["set_property", "pause", paused])

    def stop(self) -> None:
        self.command(["stop"])

    def set_gain(self, gain_db: float, bypassed: bool) -> None:
        self.command(["set_property", "volume", gain_db_to_percent(gain_db, bypassed)])

    def set_muted(self, muted: bool) -> None:
        self.command(["set_property", "mute", muted])

    def show_text(self, text: str) -> None:
        self.command(["show-text", text, 86_400_000 if text else 1])

    def shutdown(self) -> None:
        if not self._closed and self.connected:
            self.command(["quit"])
        self._closed = True
        self._connect_timer.stop()
        self._timeout_timer.stop()
        self._scrub_timer.stop()
        self._pending_scrub_ms = None
        self._socket.abort()
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.terminate()
            if not self._process.waitForFinished(1200):
                self._process.kill()
                self._process.waitForFinished(500)
