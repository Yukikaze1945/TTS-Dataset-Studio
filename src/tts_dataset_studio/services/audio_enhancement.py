from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from threading import Event

from tts_dataset_studio.domain.app_settings import AppSettings
from tts_dataset_studio.domain.models import ExportRegion, MediaAsset
from tts_dataset_studio.services.media import ToolPaths

ENGINE_LABELS = {
    "dpdfnet": "快速降噪",
    "separator": "去除 BGM",
    "stupase": "录音室修复",
}


def worker_script_path() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "workers" / "audio_enhancement_worker.py"
    return Path(__file__).resolve().parents[1] / "workers" / "audio_enhancement_worker.py"


def engine_python(settings: AppSettings, engine: str) -> Path:
    value = {
        "dpdfnet": settings.dpdfnet_python,
        "separator": settings.separator_python,
        "stupase": settings.stupase_python,
    }[engine]
    python = Path(value)
    if not python.is_file():
        raise FileNotFoundError(
            f"{ENGINE_LABELS[engine]} 环境未安装或 Python 路径无效：\n"
            f"{python if value else '尚未配置'}"
        )
    return python


def extract_region_audio(
    asset: MediaAsset,
    region: ExportRegion,
    destination: Path,
    tools: ToolPaths | None = None,
) -> Path:
    tools = tools or ToolPaths.discover()
    destination.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [
            tools.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{region.start_ms / 1000:.6f}",
            "-t",
            f"{(region.end_ms - region.start_ms) / 1000:.6f}",
            "-i",
            asset.path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            "-y",
            str(destination),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if process.returncode:
        destination.unlink(missing_ok=True)
        raise RuntimeError(process.stderr.strip() or "音频处理临时片段提取失败")
    return destination


def build_engine_command(
    settings: AppSettings,
    engine: str,
    source: Path,
    destination: Path,
) -> tuple[list[str], Path | None]:
    python = engine_python(settings, engine)
    command = [
        str(python),
        "-u",
        str(worker_script_path()),
        "--engine",
        engine,
        "--input",
        str(source),
        "--output",
        str(destination),
    ]
    working_directory = None
    if engine == "dpdfnet":
        command.extend(
            [
                "--model",
                settings.dpdfnet_model,
                "--attn-limit-db",
                str(settings.dpdfnet_attn_limit_db),
            ]
        )
    elif engine == "separator":
        command.extend(["--model", settings.separator_model])
        if settings.separator_model_dir:
            command.extend(["--model-dir", settings.separator_model_dir])
        if settings.separator_use_autocast:
            command.append("--use-autocast")
    else:
        root = Path(settings.stupase_root)
        if not (root / "stupase" / "inference" / "inference.py").is_file():
            raise FileNotFoundError(
                "StuPASE 安装目录无效，请在设置中选择官方 pase 仓库根目录。"
            )
        command.extend(
            [
                "--root",
                str(root),
                "--device",
                settings.stupase_device,
            ]
        )
        if settings.stupase_model_dir:
            command.extend(["--model-dir", settings.stupase_model_dir])
        working_directory = root
    return command, working_directory


def run_engine(
    settings: AppSettings,
    engine: str,
    source: Path,
    destination: Path,
    cancel_event: Event | None = None,
) -> Path:
    cancel_event = cancel_event or Event()
    command, working_directory = build_engine_command(
        settings,
        engine,
        source,
        destination,
    )
    process = subprocess.Popen(
        command,
        cwd=str(working_directory) if working_directory else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    while process.poll() is None:
        if cancel_event.is_set():
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            destination.unlink(missing_ok=True)
            raise InterruptedError("音频处理已取消")
        time.sleep(0.1)
    stdout_bytes, stderr_bytes = process.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
    payload: dict = {}
    if stdout:
        try:
            payload = json.loads(stdout.splitlines()[-1])
        except json.JSONDecodeError:
            payload = {}
    if process.returncode or not payload.get("ok"):
        destination.unlink(missing_ok=True)
        detail = str(payload.get("error") or "").strip()
        trace = str(payload.get("traceback") or "").strip()
        raise RuntimeError(
            "\n\n".join(
                part
                for part in (detail, trace, stderr, stdout if not payload else "")
                if part
            )
            or f"{ENGINE_LABELS[engine]}失败"
        )
    if not destination.is_file() or destination.stat().st_size <= 44:
        raise RuntimeError(f"{ENGINE_LABELS[engine]}没有生成有效音频")
    return destination
