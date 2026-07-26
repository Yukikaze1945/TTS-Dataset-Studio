from __future__ import annotations

import hashlib
import json
import math
import struct
import subprocess
from pathlib import Path

from platformdirs import user_cache_path

from tts_dataset_studio.services.media import ToolPaths


def _cache_path(source: Path, size: int, modified_ns: int) -> Path:
    signature = f"{source.resolve()}|{size}|{modified_ns}".encode()
    digest = hashlib.sha256(signature).hexdigest()
    folder = user_cache_path("TTS Dataset Studio", "OpenAI") / "waveforms"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}.json"


def generate_waveform(
    source: Path,
    size: int,
    modified_ns: int,
    tools: ToolPaths | None = None,
) -> list[float]:
    cache = _cache_path(source, size, modified_ns)
    if cache.exists():
        try:
            return [float(value) for value in json.loads(cache.read_text(encoding="utf-8"))]
        except (ValueError, OSError):
            cache.unlink(missing_ok=True)
    tools = tools or ToolPaths.discover()
    process = subprocess.Popen(
        [
            tools.ffmpeg,
            "-v",
            "error",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "f32le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert process.stdout is not None
    peaks: list[float] = []
    pending = b""
    bucket: list[float] = []
    while chunk := process.stdout.read(64 * 1024):
        chunk = pending + chunk
        usable = len(chunk) - (len(chunk) % 4)
        pending = chunk[usable:]
        for (value,) in struct.iter_unpack("<f", chunk[:usable]):
            bucket.append(abs(value) if math.isfinite(value) else 0.0)
            if len(bucket) == 400:
                peaks.append(min(1.0, max(bucket)))
                bucket.clear()
    if bucket:
        peaks.append(min(1.0, max(bucket)))
    return_code = process.wait()
    if return_code:
        error = (process.stderr.read() if process.stderr else b"").decode(errors="replace")
        raise RuntimeError(error.strip() or "波形生成失败")
    cache.write_text(json.dumps(peaks, separators=(",", ":")), encoding="utf-8")
    return peaks

