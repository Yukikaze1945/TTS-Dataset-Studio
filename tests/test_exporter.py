from pathlib import Path

from tts_dataset_studio.domain.models import ExportPreset, ExportRegion, MediaAsset
from tts_dataset_studio.services.exporter import build_ffmpeg_command
from tts_dataset_studio.services.media import ToolPaths


def test_build_ffmpeg_command_uses_requested_audio_settings(tmp_path: Path) -> None:
    asset = MediaAsset("input.wav", "input.wav", gain_db=-3.0)
    region = ExportRegion(1000, 3500)
    preset = ExportPreset(
        sample_rate=24000,
        channels=1,
        gain_db=1.0,
        fade_in_ms=50,
        fade_out_ms=100,
    )
    tools = ToolPaths("ffmpeg", "ffprobe", None)

    command = build_ffmpeg_command(tools, asset, region, preset, tmp_path / "out.wav")

    assert command[0] == "ffmpeg"
    assert command[command.index("-ar") + 1] == "24000"
    assert command[command.index("-ac") + 1] == "1"
    assert "volume=-2.000dB" in command[command.index("-af") + 1]
    assert command[-1].endswith("out.wav")
