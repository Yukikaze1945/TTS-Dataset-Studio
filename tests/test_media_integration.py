from __future__ import annotations

import json
import re
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


def test_export_real_audio_follows_enhancement_solo_state(
    tmp_path: Path,
) -> None:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    source = tmp_path / "silent-source.wav"
    enhanced = tmp_path / "enhanced.wav"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            "1.2",
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=1.2",
            "-ar",
            "48000",
            str(enhanced),
        ],
        check=True,
    )
    asset = probe_media(source)
    track = asset.enhancement_track
    track.muted = False
    track.solo = True
    track.clips.append(
        GeneratedAudioClip(
            path=str(enhanced),
            start_ms=0,
            source_offset_ms=0,
            duration_ms=1200,
            source_duration_ms=1200,
            reference_region_id="region",
            text="enhanced",
            engine="separator",
        )
    )
    preset = ExportPreset(
        output_dir=str(tmp_path / "dataset"),
        write_txt=False,
        peak_normalize=True,
    )

    result = export_region(
        asset,
        ExportRegion(100, 900),
        preset,
        1,
        Event(),
    )

    detected = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(result.audio_path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", detected.stderr)
    assert match
    assert float(match.group(1)) == pytest.approx(-1.0, abs=0.2)


def test_probe_imports_editable_embedded_subtitle_track(tmp_path: Path) -> None:
    subtitle = tmp_path / "embedded.srt"
    subtitle.write_text(
        "1\n00:00:00,100 --> 00:00:00,900\n内嵌字幕测试\n",
        encoding="utf-8",
    )
    source = tmp_path / "episode.mkv"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:d=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2",
            "-i",
            str(subtitle),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:s",
            "-c:v",
            "mpeg4",
            "-c:a",
            "pcm_s16le",
            "-c:s",
            "srt",
            "-metadata:s:s:0",
            "language=jpn",
            "-metadata:s:s:0",
            "title=Japanese",
            "-shortest",
            str(source),
        ],
        check=True,
    )

    asset = probe_media(source)

    assert asset.has_video
    assert len(asset.subtitle_tracks) == 1
    assert asset.subtitle_tracks[0].name == "内嵌字幕 1 · jpn · Japanese"
    assert asset.subtitle_tracks[0].source_path == ""
    assert asset.subtitle_tracks[0].cues[0].text == "内嵌字幕测试"


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
    payload = json.loads(probe.stdout)
    duration = float(payload["format"]["duration"])
    assert duration == pytest.approx(1.2, abs=0.05)
    stream_probe = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=sample_rate,channels",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(stream_probe.stdout)["streams"][0]
    assert stream["sample_rate"] == "48000"
    assert stream["channels"] == 2
