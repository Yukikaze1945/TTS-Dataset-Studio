from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from threading import Event

import pytest

from tts_dataset_studio.domain.models import (
    ExportPreset,
    ExportRegion,
    GeneratedAudioClip,
)
from tts_dataset_studio.services.ai_monitor import build_ai_monitor_cache
from tts_dataset_studio.services.exporter import export_region
from tts_dataset_studio.services.media import probe_media

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")


def _make_tone(path: Path) -> None:
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(path),
        ],
        check=True,
    )


def test_probe_and_export_real_audio(tmp_path: Path) -> None:
    source = tmp_path / "episode.wav"
    _make_tone(source)
    (tmp_path / "episode.ja.srt").write_text(
        "1\n00:00:00,100 --> 00:00:00,900\nテスト音声\n",
        encoding="utf-8",
    )
    asset = probe_media(source)
    preset = ExportPreset(output_dir=str(tmp_path / "dataset"))

    result = export_region(asset, ExportRegion(100, 900), preset, 1, Event())

    assert result.audio_path.name == "テスト音声.wav"
    assert result.text_path and result.text_path.read_text(encoding="utf-8") == "テスト音声"
    probe = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(result.audio_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["sample_rate"] == "24000"
    assert stream["channels"] == 1
    assert stream["codec_name"] == "pcm_s16le"


def test_build_ai_monitor_cache_places_generated_clip_on_timeline(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.wav"
    generated = tmp_path / "generated.wav"
    _make_tone(source)
    _make_tone(generated)
    asset = probe_media(source)
    asset.generated_track.clips.append(
        GeneratedAudioClip(
            path=str(generated),
            start_ms=500,
            source_offset_ms=100,
            duration_ms=600,
            source_duration_ms=1200,
            reference_region_id="region",
            text="generated",
        )
    )

    output = build_ai_monitor_cache(asset, tmp_path / "monitor.flac")

    assert output.is_file()
    probe = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    assert duration == pytest.approx(1.2, abs=0.05)
