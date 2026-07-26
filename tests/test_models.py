from tts_dataset_studio.domain.models import SubtitleCue, SubtitleTrack


def test_cue_for_region_chooses_largest_overlap() -> None:
    short = SubtitleCue(500, 1200, "short")
    long = SubtitleCue(1000, 3000, "long")
    track = SubtitleTrack("JP", cues=[short, long])

    assert track.cue_for_region(800, 2400) is long


def test_cue_for_region_uses_earliest_start_as_tie_breaker() -> None:
    later = SubtitleCue(1000, 2000, "later")
    earlier = SubtitleCue(500, 1500, "earlier")
    track = SubtitleTrack("JP", cues=[later, earlier])

    assert track.cue_for_region(1000, 1500) is earlier

