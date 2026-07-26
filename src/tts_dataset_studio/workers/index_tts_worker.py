from __future__ import annotations

import contextlib
import gc
import json
import sys
import traceback
import wave
from pathlib import Path

PROTOCOL_INPUT = sys.stdin.buffer
PROTOCOL_OUTPUT = sys.stdout.buffer
MODEL = None
TOKENIZER = None


def emit(payload: dict) -> None:
    PROTOCOL_OUTPUT.write(
        (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    )
    PROTOCOL_OUTPUT.flush()


def runtime_info(model) -> dict:
    import torch

    device = str(model.device)
    info: dict[str, object] = {
        "device": device,
        "fp16": bool(model.use_fp16),
        "torch": torch.__version__,
    }
    if torch.cuda.is_available():
        index = torch.cuda.current_device()
        info.update(
            gpu=torch.cuda.get_device_name(index),
            memory_allocated=torch.cuda.memory_allocated(index),
            memory_reserved=torch.cuda.memory_reserved(index),
            memory_total=torch.cuda.get_device_properties(index).total_memory,
        )
    return info


def load_model(message: dict) -> dict:
    global MODEL, TOKENIZER

    root = Path(message["root"]).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from indextts.infer_v2 import IndexTTS2

    device = message.get("device") or "cuda:0"
    MODEL = IndexTTS2(
        cfg_path=str(Path(message["config"]).resolve()),
        model_dir=str(Path(message["model_dir"]).resolve()),
        use_fp16=bool(message.get("fp16", True)),
        device=None if device == "auto" else device,
        use_cuda_kernel=bool(message.get("cuda_kernel", False)),
        use_deepspeed=bool(message.get("deepspeed", False)),
        use_accel=bool(message.get("accel", False)),
        use_torch_compile=bool(message.get("torch_compile", False)),
    )
    TOKENIZER = MODEL.tokenizer
    return {"event": "loaded", "runtime": runtime_info(MODEL)}


def analyze_text(message: dict) -> dict:
    if TOKENIZER is None:
        raise RuntimeError("IndexTTS2 model is not loaded")
    text = str(message.get("text") or "").strip()
    tokens = TOKENIZER.tokenize(text)
    token_ids = TOKENIZER.convert_tokens_to_ids(tokens)
    unknown = [
        token
        for token, token_id in zip(tokens, token_ids, strict=True)
        if token_id == TOKENIZER.unk_token_id
    ]
    return {
        "event": "analyzed",
        "text": text,
        "token_count": len(token_ids),
        "unknown_count": len(unknown),
        "unknown_tokens": unknown,
    }


def generate(message: dict) -> dict:
    if MODEL is None:
        raise RuntimeError("IndexTTS2 model is not loaded")
    output = Path(message["output"]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    MODEL.infer(
        spk_audio_prompt=str(Path(message["reference"]).resolve()),
        text=str(message["text"]),
        output_path=str(output),
        emo_audio_prompt=None,
        use_emo_text=False,
        interval_silence=int(message.get("interval_silence", 200)),
        max_text_tokens_per_segment=int(message.get("max_text_tokens", 120)),
        temperature=float(message.get("temperature", 0.8)),
        top_p=float(message.get("top_p", 0.8)),
        top_k=int(message.get("top_k", 30)),
        num_beams=int(message.get("num_beams", 3)),
        repetition_penalty=float(message.get("repetition_penalty", 10.0)),
        max_mel_tokens=int(message.get("max_mel_tokens", 1500)),
        verbose=False,
    )
    if not output.is_file() or output.stat().st_size <= 44:
        raise RuntimeError("IndexTTS2 did not produce a valid WAV file")
    with wave.open(str(output), "rb") as stream:
        sample_rate = stream.getframerate()
        duration_ms = round(stream.getnframes() / max(1, sample_rate) * 1000)
    return {
        "event": "generated",
        "output": str(output),
        "duration_ms": duration_ms,
        "sample_rate": sample_rate,
    }


def unload_model() -> dict:
    global MODEL, TOKENIZER

    MODEL = None
    TOKENIZER = None
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except ImportError:
        pass
    return {"event": "unloaded"}


def dispatch(message: dict) -> dict:
    command = message.get("command")
    if command == "load":
        return load_model(message)
    if command == "analyze_text":
        return analyze_text(message)
    if command == "generate":
        return generate(message)
    if command in {"unload", "shutdown"}:
        return unload_model()
    raise ValueError(f"Unknown command: {command}")


def main() -> None:
    for raw_bytes in PROTOCOL_INPUT:
        message: dict = {}
        try:
            message = json.loads(raw_bytes.decode("utf-8"))
            with contextlib.redirect_stdout(sys.stderr):
                response = dispatch(message)
            response["id"] = message.get("id")
            emit(response)
            if message.get("command") == "shutdown":
                break
        except Exception as exc:  # noqa: BLE001
            emit(
                {
                    "id": message.get("id"),
                    "event": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            )


if __name__ == "__main__":
    main()
