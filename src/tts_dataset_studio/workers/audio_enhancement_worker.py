from __future__ import annotations

import argparse
import contextlib
import json
import os
import runpy
import shutil
import sys
import tempfile
import traceback
from pathlib import Path


def _dpdfnet(args: argparse.Namespace) -> None:
    import dpdfnet
    import soundfile as sf

    audio, sample_rate = sf.read(args.input, always_2d=False)
    enhanced = dpdfnet.enhance(
        audio,
        sample_rate=sample_rate,
        model=args.model,
        attn_limit_db=args.attn_limit_db,
    )
    sf.write(args.output, enhanced, sample_rate, subtype="PCM_16")


def _separator(args: argparse.Namespace) -> None:
    import librosa
    import numpy as np
    import soundfile as sf
    from audio_separator.separator import Separator

    output = Path(args.output).resolve()
    separator = Separator(
        output_dir=str(output.parent),
        model_file_dir=args.model_dir or None,
        output_format="WAV",
        output_single_stem="Vocals",
        sample_rate=48000,
        use_soundfile=True,
        use_autocast=args.use_autocast,
    )
    separator.load_model(model_filename=args.model)
    audio, sample_rate = sf.read(args.input, always_2d=True)
    original_duration = len(audio) / max(1, sample_rate)
    staged_input = Path(args.input)
    padding_folder = None
    if original_duration < 12:
        padding_folder = tempfile.TemporaryDirectory(prefix="separator-padding-")
        staged_input = Path(padding_folder.name) / "input.wav"
        padding = np.zeros(
            (max(0, round(12 * sample_rate) - len(audio)), audio.shape[1]),
            dtype=audio.dtype,
        )
        sf.write(staged_input, np.concatenate([audio, padding]), sample_rate)
    try:
        files = separator.separate(
            str(staged_input),
            {"Vocals": output.stem},
        )
    finally:
        if padding_folder is not None:
            padding_folder.cleanup()
    candidates = [
        Path(item) if Path(item).is_absolute() else output.parent / item for item in files
    ]
    produced = next(
        (
            path
            for path in candidates
            if path.is_file() and "instrumental" not in path.name.casefold()
        ),
        None,
    )
    if produced is None:
        produced = next(
            (path for path in output.parent.glob(f"{output.stem}*") if path.is_file()),
            None,
        )
    if produced is None:
        raise RuntimeError("BS-RoFormer did not produce a vocals stem")
    separated, output_rate = sf.read(produced, always_2d=True)
    if output_rate != 48000:
        separated = librosa.resample(
            separated.T.astype(np.float32, copy=False),
            orig_sr=output_rate,
            target_sr=48000,
            axis=-1,
        ).T
        output_rate = 48000
    target_frames = round(original_duration * output_rate)
    separated = separated[:target_frames]
    if len(separated) < target_frames:
        separated = np.pad(
            separated,
            ((0, target_frames - len(separated)), (0, 0)),
        )
    sf.write(output, separated, output_rate, subtype="PCM_16")
    if produced.resolve() != output:
        produced.unlink(missing_ok=True)


def _stupase(args: argparse.Namespace) -> None:
    import librosa
    import numpy as np
    import soundfile as sf

    root = Path(args.root).resolve()
    module_root = root / "stupase"
    if not (module_root / "inference" / "inference.py").is_file():
        raise FileNotFoundError(f"StuPASE inference module not found: {module_root}")
    with (
        tempfile.TemporaryDirectory(prefix="stupase-input-") as input_dir,
        tempfile.TemporaryDirectory(prefix="stupase-output-") as output_dir,
    ):
        staged = Path(input_dir) / "input.wav"
        audio, sample_rate = sf.read(args.input, always_2d=True)
        mono = np.mean(audio, axis=1)
        if sample_rate != 16000:
            mono = librosa.resample(
                mono.astype(np.float32, copy=False),
                orig_sr=sample_rate,
                target_sr=16000,
            )
        sf.write(staged, mono, 16000, subtype="PCM_16")
        previous_cwd = Path.cwd()
        previous_argv = list(sys.argv)
        try:
            os.chdir(module_root)
            sys.path.insert(0, str(module_root))
            sys.argv = [
                "inference.inference",
                "-I",
                input_dir,
                "-O",
                output_dir,
                "-D",
                args.device,
            ]
            if args.model_dir:
                sys.argv.extend(["--download_dir", args.model_dir])
            runpy.run_module("inference.inference", run_name="__main__")
        finally:
            os.chdir(previous_cwd)
            sys.argv = previous_argv
        produced = next(Path(output_dir).rglob("*.wav"), None)
        if produced is None:
            raise RuntimeError("StuPASE did not produce an enhanced WAV")
        shutil.copy2(produced, args.output)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("dpdfnet", "separator", "stupase"), required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--model-dir", default="")
    parser.add_argument("--attn-limit-db", type=float, default=12.0)
    parser.add_argument("--use-autocast", action="store_true")
    parser.add_argument("--root", default="")
    parser.add_argument("--device", default="cuda:0")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.redirect_stdout(sys.stderr):
            if args.engine == "dpdfnet":
                _dpdfnet(args)
            elif args.engine == "separator":
                _separator(args)
            else:
                _stupase(args)
        if not output.is_file() or output.stat().st_size <= 44:
            raise RuntimeError("Audio enhancement output is missing or empty")
        print(json.dumps({"ok": True, "output": str(output)}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
