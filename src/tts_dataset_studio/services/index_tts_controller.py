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
        return Path(bundle_root) / "workers" / "index_tts_worker.py"
    return Path(__file__).resolve().parents[1] / "workers" / "index_tts_worker.py"


class IndexTtsController(QObject):
    state_changed = Signal(str)
    loaded = Signal(object)
    unloaded = Signal()
    text_analyzed = Signal(object)
    generated = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.state = "unloaded"
        self._process = QProcess(self)
        self._buffer = bytearray()
        self._stderr = bytearray()
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
        python = Path(settings.index_tts_python)
        script = worker_script_path()
        root = Path(settings.index_tts_root)
        required = [
            python,
            script,
            root,
            Path(settings.index_tts_config),
            Path(settings.index_tts_model_dir),
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            self.failed.emit("IndexTTS2 路径不存在：\n" + "\n".join(missing))
            return
        self._set_state("loading")
        self._stderr.clear()
        if self._process.state() == QProcess.ProcessState.NotRunning:
            self._process.setWorkingDirectory(str(root))
            self._process.start(str(python), ["-u", str(script)])
            if not self._process.waitForStarted(5000):
                self._set_state("error")
                self.failed.emit(self._process.errorString())
                return
        self._send(
            "load",
            root=str(root),
            config=settings.index_tts_config,
            model_dir=settings.index_tts_model_dir,
            device=settings.index_tts_device,
            fp16=settings.index_tts_fp16,
            cuda_kernel=settings.index_tts_cuda_kernel,
            deepspeed=settings.index_tts_deepspeed,
            accel=settings.index_tts_accel,
            torch_compile=settings.index_tts_torch_compile,
        )

    def analyze_text(self, text: str) -> int | None:
        if self.state != "loaded":
            self.failed.emit("请先加载语音引擎。")
            return None
        return self._send("analyze_text", text=text)

    def generate(
        self,
        reference: Path,
        text: str,
        output: Path,
        settings: AppSettings,
    ) -> None:
        if self.state != "loaded":
            self.failed.emit("请先加载语音引擎。")
            return
        self._send(
            "generate",
            reference=str(reference),
            text=text,
            output=str(output),
            temperature=settings.index_tts_temperature,
            top_p=settings.index_tts_top_p,
            top_k=settings.index_tts_top_k,
            num_beams=settings.index_tts_num_beams,
            repetition_penalty=settings.index_tts_repetition_penalty,
            max_mel_tokens=settings.index_tts_max_mel_tokens,
            max_text_tokens=settings.index_tts_max_text_tokens,
            interval_silence=settings.index_tts_interval_silence,
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
        if not self._process.waitForFinished(3000):
            self._process.kill()
            self._process.waitForFinished(1000)

    def _send(self, command: str, **payload) -> int:
        request_id = self._next_id
        self._next_id += 1
        self._pending[request_id] = command
        message = {"id": request_id, "command": command, **payload}
        self._process.write(
            (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        )
        return request_id

    def _read_stdout(self) -> None:
        self._buffer.extend(bytes(self._process.readAllStandardOutput()))
        while b"\n" in self._buffer:
            raw, _, remainder = self._buffer.partition(b"\n")
            self._buffer = bytearray(remainder)
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                LOGGER.warning("Invalid IndexTTS worker response: %r", raw)
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
        elif event == "analyzed":
            self.text_analyzed.emit(message)
        elif event == "generated":
            self.generated.emit(message)
        elif event == "error":
            if self.state == "loading":
                self._set_state("error")
            error = str(message.get("error") or "IndexTTS2 worker failed")
            worker_traceback = str(message.get("traceback") or "").strip()
            if worker_traceback:
                LOGGER.error("IndexTTS2 worker traceback:\n%s", worker_traceback)
            stderr = self._stderr.decode("utf-8", errors="replace").strip()
            if stderr:
                LOGGER.error("IndexTTS2 worker stderr:\n%s", stderr)
            self.failed.emit(error)

    def _read_stderr(self) -> None:
        data = bytes(self._process.readAllStandardError())
        self._stderr.extend(data)
        if len(self._stderr) > 1_000_000:
            del self._stderr[:-500_000]

    def _process_finished(self, _code: int, _status) -> None:
        expected = self.state in {"unloading", "unloaded"}
        self._set_state("unloaded")
        self._pending.clear()
        if not expected:
            self.failed.emit("IndexTTS2 worker 已退出。")
