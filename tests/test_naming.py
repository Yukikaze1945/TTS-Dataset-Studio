from pathlib import Path

from tts_dataset_studio.domain.models import (
    ExportPreset,
    ExportRegion,
    MediaAsset,
    SubtitleCue,
    SubtitleTrack,
)
from tts_dataset_studio.services.naming import (
    base_name_for_region,
    sanitize_filename,
    unique_output_path,
)


def test_subtitle_text_wins_for_name() -> None:
    track = SubtitleTrack("ja", cues=[SubtitleCue(0, 2000, 'こんにちは: 世界?')])
    asset = MediaAsset("x.wav", "x.wav", subtitle_tracks=[track], export_track_id=track.id)

    name, text = base_name_for_region(asset, ExportRegion(100, 1800), ExportPreset(), 1)

    assert name == "こんにちは_ 世界_"
    assert text == "こんにちは: 世界?"


def test_template_and_regex_are_used_without_subtitle() -> None:
    asset = MediaAsset("show_EP01.wav", "show_EP01.wav")
    preset = ExportPreset(
        naming_template="{source}_{index:03d}_{start}",
        regex_pattern=r"_EP\d+$",
        regex_replacement="",
    )

    name, text = base_name_for_region(asset, ExportRegion(1000, 2000), preset, 7)

    assert name == "show_007_00-00-01-000"
    assert text is None


def test_reserved_and_duplicate_names_are_safe(tmp_path: Path) -> None:
    assert sanitize_filename("CON") == "_CON"
    (tmp_path / "clip.wav").touch()
    assert unique_output_path(tmp_path, "clip", "wav").name == "clip_002.wav"
