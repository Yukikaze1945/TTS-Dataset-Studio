from pathlib import Path

import pytest

from tts_dataset_studio.domain.models import SubtitleCue, SubtitleTrack
from tts_dataset_studio.services.subtitles import (
    export_subtitle,
    find_matching_subtitles,
    parse_subtitle,
)


def test_parse_srt_and_clean_markup(tmp_path: Path) -> None:
    source = tmp_path / "episode.ja.srt"
    source.write_text(
        "1\n00:00:01,200 --> 00:00:03,400\n<b>こんにちは</b>\\N世界\n",
        encoding="utf-8",
    )

    track = parse_subtitle(source)

    assert track.name == "ja"
    assert track.cues[0].start_ms == 1200
    assert track.cues[0].text == "こんにちは\n世界"


def test_parse_ass_dialogue(tmp_path: Path) -> None:
    source = tmp_path / "episode.ass"
    source.write_text(
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,"
        "{\\i1}中文\\N{\\r}日本語\n",
        encoding="utf-8",
    )

    track = parse_subtitle(source)

    assert track.cues[0].end_ms == 2500
    assert track.cues[0].text == "中文\n日本語"


def test_find_matching_subtitles_respects_stem_boundary(tmp_path: Path) -> None:
    media = tmp_path / "episode.mp4"
    media.touch()
    wanted = [tmp_path / "episode.srt", tmp_path / "episode.zh-CN.srt"]
    ignored = [tmp_path / "episode2.srt", tmp_path / "other.ass"]
    for path in wanted + ignored:
        path.touch()

    assert find_matching_subtitles(media) == wanted


@pytest.mark.parametrize("suffix", [".srt", ".vtt", ".ass"])
def test_complete_edited_track_can_round_trip_through_export(
    tmp_path: Path,
    suffix: str,
) -> None:
    track = SubtitleTrack(
        "edited",
        cues=[
            SubtitleCue(1000, 2340, "第一句"),
            SubtitleCue(3000, 4560, "Second line"),
        ],
    )
    output = tmp_path / f"edited{suffix}"

    export_subtitle(track, output)
    restored = parse_subtitle(output)

    assert output.read_bytes().startswith(b"\xef\xbb\xbf")
    assert [(cue.start_ms, cue.end_ms, cue.text) for cue in restored.cues] == [
        (1000, 2340, "第一句"),
        (3000, 4560, "Second line"),
    ]
