from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def send(process: subprocess.Popen[str], payload: dict) -> dict:
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    process.stdin.flush()
    response = process.stdout.readline()
    if not response:
        raise RuntimeError("IndexTTS2 worker exited without a response")
    return json.loads(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    project_root = Path(__file__).resolve().parents[1]
    worker = (
        project_root
        / "src"
        / "tts_dataset_studio"
        / "workers"
        / "index_tts_worker.py"
    )
    python = root / ".venv" / "Scripts" / "python.exe"
    config = root / "checkpoints" / "config.yaml"
    model_dir = root / "checkpoints"
    reference = root / "examples" / "voice_01.wav"
    output = args.output or (
        Path(tempfile.gettempdir()) / "tts-studio-index-smoke.wav"
    )
    for required in (worker, python, config, model_dir, reference):
        if not required.exists():
            raise FileNotFoundError(required)
    process = subprocess.Popen(
        [str(python), "-u", str(worker)],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        loaded = send(
            process,
            {
                "id": 1,
                "command": "load",
                "root": str(root),
                "config": str(config),
                "model_dir": str(model_dir),
                "device": "cuda:0",
                "fp16": True,
                "cuda_kernel": False,
                "deepspeed": False,
                "accel": False,
                "torch_compile": False,
            },
        )
        if loaded.get("event") != "loaded":
            raise RuntimeError(loaded.get("error"))
        chinese = send(
            process,
            {"id": 2, "command": "analyze_text", "text": "今天天气很好。"},
        )
        japanese = send(
            process,
            {"id": 3, "command": "analyze_text", "text": "今日はいい天気ですね。"},
        )
        generated = send(
            process,
            {
                "id": 4,
                "command": "generate",
                "reference": str(reference),
                "text": "今天天气很好。",
                "output": str(output),
                "temperature": 0.8,
                "top_p": 0.8,
                "top_k": 30,
                "num_beams": 3,
                "repetition_penalty": 10.0,
                "max_mel_tokens": 1500,
                "max_text_tokens": 120,
                "interval_silence": 200,
            },
        )
        if generated.get("event") != "generated" or not output.is_file():
            raise RuntimeError(generated.get("error"))
        send(process, {"id": 5, "command": "shutdown"})
        process.wait(timeout=10)
        print("INDEX_TTS_GPU_OK")
        print(f"GPU={loaded['runtime'].get('gpu')}")
        print(f"CN_UNKNOWN={chinese.get('unknown_count')}")
        print(f"JP_UNKNOWN={japanese.get('unknown_count')}")
        print(f"DURATION_MS={generated.get('duration_ms')}")
        print(f"OUTPUT={output}")
        return 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
