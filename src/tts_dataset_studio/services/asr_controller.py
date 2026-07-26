from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from tts_dataset_studio.domain.app_settings import AppSettings

LOGGER = logging.getLogger(__name__)


def worker_script_path() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "workers" / "moss_worker.py"
    return Path(__file__).resolve().parents[1] / "workers" / "moss_worker.py"


class AsrController(QObject):
    state_changed = Signal(str)
    loaded = Signal(object)
    unloaded = Signal()
    transcription_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.state = "unloaded"
        self._process = QProcess(self)
        self._buffer = bytearray()
        self._next_id = 1
        self._pending: dict[int, str] = {}
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.finished.connect(self._process_finished)

    def _set_state(self, state: str) -> None:
        self.state = state
        self.state_changed.emit(state)

    def load_model(self, settings: AppSettings) -> None:
        if self.state not in {"unloaded", "error"}:
            return
        python = Path(settings.moss_python)
        script = worker_script_path()
        if not python.exists():
            self.failed.emit(f"MOSS Python 不存在：{python}")
            return
        if not script.exists():
            self.failed.emit(f"ASR worker 不存在：{script}")
            return
        self._set_state("loading")
        if self._process.state() == QProcess.ProcessState.NotRunning:
            self._process.setWorkingDirectory(settings.moss_root)
            self._process.start(str(python), ["-u", str(script)])
            if not self._process.waitForStarted(5000):
                self._set_state("error")
                self.failed.emit(self._process.errorString())
                return
        self._send(
            "load",
            model=settings.moss_model,
            device=settings.moss_device,
            dtype=settings.moss_dtype,
        )

    def transcribe(self, audio: Path, settings: AppSettings) -> None:
        if self.state != "loaded":
            self.failed.emit("请先加载 ASR 模型。")
            return
        self._send(
            "transcribe",
            audio=str(audio),
            prompt=settings.moss_prompt,
            max_length=settings.moss_max_length,
            max_new_tokens=settings.moss_max_new_tokens,
        )

    def unload_model(self) -> None:
        if self.state == "loaded":
            self._set_state("unloading")
            self._send("unload")

    def shutdown(self) -> None:
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return
        self._set_state("unloading")
        self._send("shutdown")
        if not self._process.waitForFinished(2500):
            self._process.kill()
            self._process.waitForFinished(1000)

    def _send(self, command: str, **payload) -> None:
        request_id = self._next_id
        self._next_id += 1
        self._pending[request_id] = command
        message = {"id": request_id, "command": command, **payload}
        self._process.write((json.dumps(message, ensure_ascii=False) + "\n").encode())

    def _read_stdout(self) -> None:
        self._buffer.extend(bytes(self._process.readAllStandardOutput()))
        while b"\n" in self._buffer:
            raw, _, rest = self._buffer.partition(b"\n")
            self._buffer = bytearray(rest)
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            self._handle_message(message)

    def _handle_message(self, message: dict) -> None:
        request_id = message.get("id")
        if isinstance(request_id, int):
            self._pending.pop(request_id, None)
        event = message.get("event")
        if event == "loaded":
            self._set_state("loaded")
            self.loaded.emit(message.get("runtime", {}))
        elif event == "unloaded":
            self._set_state("unloaded")
            self.unloaded.emit()
        elif event == "transcribed":
            self.transcription_ready.emit(message)
        elif event == "error":
            if self.state == "loading":
                self._set_state("error")
            error = str(message.get("error") or "ASR worker failed")
            worker_traceback = str(message.get("traceback") or "").strip()
            if worker_traceback:
                LOGGER.error("MOSS worker traceback:\n%s", worker_traceback)
            self.failed.emit(error)

    def _read_stderr(self) -> None:
        self._process.readAllStandardError()

    def _process_finished(self, _code: int, _status) -> None:
        was_expected = self.state in {"unloading", "unloaded"}
        self._set_state("unloaded")
        self._pending.clear()
        if not was_expected:
            self.failed.emit("ASR worker 已退出。")
