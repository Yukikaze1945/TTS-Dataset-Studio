from pathlib import Path

from tts_dataset_studio.domain.models import (
    ExportRegion,
    MediaAsset,
    Project,
    SubtitleCue,
    SubtitleTrack,
)
from tts_dataset_studio.services.project_io import load_project, save_autosave, save_project


def test_project_round_trip_uses_portable_paths(tmp_path: Path) -> None:
    media = tmp_path / "episode.wav"
    media.write_bytes(b"RIFF")
    subtitle = tmp_path / "episode.ja.srt"
    subtitle.write_text("", encoding="utf-8")
    track = SubtitleTrack(
        "ja",
        source_path=str(subtitle),
        cues=[SubtitleCue(0, 1000, "こんにちは")],
    )
    asset = MediaAsset.from_path(media)
    asset.subtitle_tracks = [track]
    asset.export_track_id = track.id
    asset.regions = [ExportRegion(0, 1000)]
    project = Project(assets=[asset], active_asset_id=asset.id)
    path = tmp_path / "sample.ttds"

    save_project(project, path)
    restored = load_project(path)

    assert restored.active_asset is not None
    assert Path(restored.active_asset.path) == media
    assert restored.active_asset.subtitle_tracks[0].cues[0].text == "こんにちは"
    assert restored.active_asset.regions[0].end_ms == 1000


def test_loading_autosave_preserves_real_project_path(tmp_path: Path) -> None:
    original = tmp_path / "real-project.ttds"
    project = Project(project_path=str(original))
    autosave = tmp_path / "real-project.ttds.autosave"

    save_autosave(project, autosave)
    restored = load_project(autosave)

    assert restored.project_path == str(original)
    assert not restored.project_path.endswith(".autosave")
