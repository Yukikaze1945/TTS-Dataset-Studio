from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

MOSS_HOME_ENV = "MOSS_TRANSCRIBE_DIARIZE_HOME"
DEFAULT_MOSS_PROMPT = (
    "\u8bf7\u5c06\u97f3\u9891\u8f6c\u5199\u4e3a\u6587\u672c\uff0c"
    "\u6bcf\u4e00\u6bb5\u9700\u4ee5\u8d77\u59cb\u65f6\u95f4\u6233"
    "\u548c\u8bf4\u8bdd\u4eba\u7f16\u53f7\uff08[S01]\u3001[S02]\u3001"
    "[S03]\u2026\uff09\u5f00\u5934\uff0c\u6b63\u6587\u4e3a\u5bf9\u5e94"
    "\u7684\u8bed\u97f3\u5185\u5bb9\uff0c\u5e76\u5728\u6bb5\u672b\u6807"
    "\u6ce8\u7ed3\u675f\u65f6\u95f4\u6233\uff0c\u4ee5\u6e05\u6670\u6807"
    "\u660e\u8be5\u6bb5\u8bed\u97f3\u8303\u56f4\u3002"
)
LEGACY_MOSS_PROMPT = (
    "Transcribe the audio with precise timestamps and speaker diarization."
)


def _moss_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get(MOSS_HOME_ENV, "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())

    home = Path.home()
    candidates.extend(
        [
            home / "moss-asr" / "MOSS-Transcribe-Diarize",
            home / "MOSS-Transcribe-Diarize",
            Path(sys.executable).resolve().parent / "MOSS-Transcribe-Diarize",
        ]
    )
    if os.name == "nt":
        candidates.extend(
            drive / "moss-asr" / "MOSS-Transcribe-Diarize"
            for drive in _windows_drive_roots()
        )
    return candidates


def _windows_drive_roots() -> list[Path]:
    list_drives = getattr(os, "listdrives", None)
    if list_drives is not None:
        return [Path(drive) for drive in list_drives()]
    try:
        import ctypes

        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [
            Path(f"{letter}:\\")
            for index, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            if mask & (1 << index)
        ]
    except (AttributeError, OSError):
        anchor = Path.home().anchor
        return [Path(anchor)] if anchor else []


def detect_moss_root() -> Path | None:
    return next((path for path in _moss_root_candidates() if path.is_dir()), None)


def detect_moss_model(moss_root: Path | None = None) -> str:
    if moss_root:
        local = moss_root / "pretrained" / "moss-transcribe-diarize"
        if local.exists():
            return str(local)
    snapshots = (
        Path.home()
        / ".cache"
        / "huggingface"
        / "hub"
        / "models--OpenMOSS-Team--MOSS-Transcribe-Diarize"
        / "snapshots"
    )
    if snapshots.exists():
        candidates = sorted(
            (path for path in snapshots.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if candidates:
            return str(candidates[0])
    return "OpenMOSS-Team/MOSS-Transcribe-Diarize"


@dataclass(slots=True)
class AppSettings:
    audio_output_mode: str = "source"
    audio_output_dir: str = ""
    still_output_mode: str = "source"
    still_output_dir: str = ""
    still_format: str = "png"
    jpeg_quality: int = 95
    audio_naming_template: str = "{source}_{index:04d}_{start}"
    still_naming_template: str = "{source}_{timecode}"
    open_after_export: bool = False
    scrub_hz: int = 30
    follow_playhead: bool = True
    cache_dir: str = ""
    moss_root: str = ""
    moss_python: str = ""
    moss_model: str = ""
    moss_device: str = "cuda"
    moss_dtype: str = "bf16"
    moss_prompt: str = DEFAULT_MOSS_PROMPT
    moss_max_new_tokens: int = 2048
    moss_max_length: int = 131072
    moss_temp_dir: str = ""
    moss_track_name: str = "MOSS ASR"
    unload_asr_on_exit: bool = True

    def __post_init__(self) -> None:
        if not self.moss_root:
            detected_root = detect_moss_root()
            if detected_root:
                self.moss_root = str(detected_root)
        root = Path(self.moss_root) if self.moss_root else None
        if not self.moss_python and root:
            self.moss_python = str(root / ".venv" / "Scripts" / "python.exe")
        if not self.moss_model:
            self.moss_model = detect_moss_model(root)

    @classmethod
    def load(cls, store: QSettings) -> AppSettings:
        defaults = cls()
        values: dict[str, object] = {}
        for key, default in asdict(defaults).items():
            raw = store.value(f"advanced/{key}", default)
            if isinstance(default, bool):
                raw = str(raw).casefold() in {"1", "true", "yes"}
            elif isinstance(default, int):
                raw = int(raw)
            else:
                raw = str(raw)
            values[key] = raw
        prompt = str(values["moss_prompt"])
        if (
            prompt == LEGACY_MOSS_PROMPT
            or "\ufffd" in prompt
            or not prompt.strip()
        ):
            values["moss_prompt"] = DEFAULT_MOSS_PROMPT
        return cls(**values)

    def save(self, store: QSettings) -> None:
        for key, value in asdict(self).items():
            store.setValue(f"advanced/{key}", value)
        store.sync()
