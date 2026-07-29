import json
from pathlib import Path

from tts_dataset_studio.domain.models import (
    ExportRegion,
    GeneratedAudioClip,
    MediaAsset,
    Project,
    SubtitleCue,
    SubtitleTrack,
)
from tts_dataset_studio.services.project_io import (
    cleanup_unreferenced_generated_audio,
    load_project,
    save_autosave,
    save_project,
)


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


def test_loading_project_merges_legacy_parallel_bilingual_cues(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy.ttds"
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [
                    {
                        "path": str(tmp_path / "missing.mp4"),
                        "display_name": "missing.mp4",
                        "subtitle_tracks": [
                            {
                                "name": "双语",
                                "source_path": str(tmp_path / "episode.ass"),
                                "cues": [
                                    {
                                        "start_ms": 1000,
                                        "end_ms": 2500,
                                        "text": "请多关照",
                                    },
                                    {
                                        "start_ms": 1000,
                                        "end_ms": 2500,
                                        "text": "よろしくお願いします",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    restored = load_project(source)

    assert len(restored.assets[0].subtitle_tracks[0].cues) == 1
    assert (
        restored.assets[0].subtitle_tracks[0].cues[0].text
        == "请多关照\nよろしくお願いします"
    )


def test_generated_audio_is_copied_beside_project_and_round_trips(
    tmp_path: Path,
) -> None:
    source = tmp_path / "cache" / "generated.wav"
    source.parent.mkdir()
    source.write_bytes(b"RIFF generated audio")
    asset = MediaAsset("audio.wav", "audio.wav")
    clip = GeneratedAudioClip(
        path=str(source),
        start_ms=1000,
        source_offset_ms=50,
        duration_ms=900,
        source_duration_ms=1200,
        reference_region_id="region",
        text="测试",
    )
    asset.generated_track.clips.append(clip)
    project = Project(assets=[asset], active_asset_id=asset.id)
    project_path = tmp_path / "demo.ttds"

    save_project(project, project_path)
    restored = load_project(project_path)
    restored_clip = restored.assets[0].generated_track.clips[0]

    expected = tmp_path / "demo.ttds.assets" / "generated" / f"{clip.id}.wav"
    assert expected.read_bytes() == b"RIFF generated audio"
    assert Path(restored_clip.path) == expected.resolve()
    assert restored_clip.source_offset_ms == 50
    assert restored_clip.duration_ms == 900


def test_cleanup_generated_audio_only_removes_sidecar_orphans(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "demo.ttds"
    managed = tmp_path / "demo.ttds.assets" / "generated"
    managed.mkdir(parents=True)
    referenced = managed / "keep.wav"
    orphan = managed / "orphan.wav"
    unrelated = managed / "notes.txt"
    outside = tmp_path / "outside.wav"
    for path in (referenced, orphan, unrelated, outside):
        path.write_bytes(b"data")
    clip = GeneratedAudioClip(
        path=str(referenced),
        start_ms=0,
        source_offset_ms=0,
        duration_ms=100,
        source_duration_ms=100,
        reference_region_id="region",
        text="hello",
    )
    asset = MediaAsset("source.wav", "source.wav")
    asset.generated_track.clips.append(clip)
    project = Project(
        assets=[asset],
        active_asset_id=asset.id,
        project_path=str(project_path),
    )

    assert cleanup_unreferenced_generated_audio(project) == 1
    assert referenced.exists()
    assert unrelated.exists()
    assert outside.exists()
    assert not orphan.exists()
