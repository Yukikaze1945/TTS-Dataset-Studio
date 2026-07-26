from __future__ import annotations

import gc
import json
import sys
import traceback
from pathlib import Path

runner = None


def normalize_prompt(value: object, default: str) -> str:
    if not isinstance(value, str):
        return default
    prompt = value.strip()
    if not prompt or "\ufffd" in prompt:
        return default
    return prompt


def respond(request_id: int | None, event: str, **payload) -> None:
    print(
        json.dumps({"id": request_id, "event": event, **payload}, ensure_ascii=False),
        flush=True,
    )


def handle(message: dict) -> None:
    global runner
    request_id = message.get("id")
    command = message.get("command")
    if command == "load":
        from moss_transcribe_diarize.app.model_runner import ModelRunner

        runner = ModelRunner(
            message["model"],
            device=message.get("device", "cuda"),
            dtype=message.get("dtype", "bf16"),
        )
        runner._ensure_loaded()
        info = runner.runtime_info()
        try:
            import torch

            info["cuda"] = torch.cuda.is_available()
            if torch.cuda.is_available():
                info["gpu"] = torch.cuda.get_device_name(0)
                info["allocated_bytes"] = torch.cuda.memory_allocated()
        except Exception:
            pass
        respond(request_id, "loaded", runtime=info)
        return
    if command == "transcribe":
        if runner is None or not runner.is_loaded:
            raise RuntimeError("MOSS model is not loaded")
        from moss_transcribe_diarize.inference_utils import DEFAULT_PROMPT
        from moss_transcribe_diarize.subtitle import subtitle_segments_from_transcript

        prompt = normalize_prompt(message.get("prompt"), DEFAULT_PROMPT)
        transcribe_options = {
            "prompt": prompt,
            "max_length": int(message.get("max_length", 131072)),
            "max_new_tokens": int(message.get("max_new_tokens", 2048)),
            "decoding": "greedy",
        }
        try:
            result = runner.transcribe(Path(message["audio"]), **transcribe_options)
        except TypeError as exc:
            # Some tokenizer builds can intermittently reject the rendered chat
            # input on their first call. Retry once with a freshly materialized
            # built-in prompt even when the first prompt was already the default.
            if "TextEncodeInput" not in str(exc):
                raise
            transcribe_options["prompt"] = f"{DEFAULT_PROMPT}"
            result = runner.transcribe(Path(message["audio"]), **transcribe_options)
        segments = [
            segment.to_dict()
            for segment in subtitle_segments_from_transcript(
                result.text,
                postprocess=False,
            )
        ]
        if not segments and result.text.strip():
            import soundfile

            duration = float(soundfile.info(message["audio"]).duration)
            segments = [
                {
                    "id": "seg_0001",
                    "start": 0.0,
                    "end": max(0.001, duration),
                    "speaker": "S01",
                    "text": result.text.strip(),
                }
            ]
        respond(request_id, "transcribed", segments=segments, result=result.to_dict())
        return
    if command in {"unload", "shutdown"}:
        runner = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        respond(request_id, "unloaded")
        if command == "shutdown":
            raise SystemExit(0)
        return
    raise ValueError(f"Unknown command: {command}")


def main() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    for line in sys.stdin:
        message: object = {}
        try:
            message = json.loads(line)
            handle(message)
        except SystemExit:
            return
        except Exception as exc:
            respond(
                message.get("id") if isinstance(message, dict) else None,
                "error",
                error=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(),
            )


if __name__ == "__main__":
    main()
