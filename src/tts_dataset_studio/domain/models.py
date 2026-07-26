from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


def new_id() -> str:
    return uuid4().hex


@dataclass(slots=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str
    speaker: str = ""
    origin: str = ""
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        self.start_ms = max(0, int(self.start_ms))
        self.end_ms = max(self.start_ms + 1, int(self.end_ms))
        self.text = self.text.strip()


@dataclass(slots=True)
class SubtitleTrack:
    name: str
    source_path: str = ""
    cues: list[SubtitleCue] = field(default_factory=list)
    visible: bool = True
    id: str = field(default_factory=new_id)

    def cue_for_region(self, start_ms: int, end_ms: int) -> SubtitleCue | None:
        """Choose the cue with greatest overlap, then earliest start and track order."""
        ranked: list[tuple[int, int, int, SubtitleCue]] = []
        for order, cue in enumerate(self.cues):
            overlap = max(0, min(end_ms, cue.end_ms) - max(start_ms, cue.start_ms))
            if overlap:
                ranked.append((-overlap, cue.start_ms, order, cue))
        return min(ranked, default=(0, 0, 0, None))[3]


@dataclass(slots=True)
class ExportRegion:
    start_ms: int
    end_ms: int
    label: str = ""
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        self.start_ms = max(0, int(self.start_ms))
        self.end_ms = max(self.start_ms + 1, int(self.end_ms))


@dataclass(slots=True)
class MediaAsset:
    path: str
    display_name: str
    duration_ms: int = 0
    has_video: bool = False
    has_audio: bool = True
    sample_rate: int | None = None
    channels: int | None = None
    size: int = 0
    modified_ns: int = 0
    gain_db: float = 0.0
    gain_bypassed: bool = False
    subtitle_tracks: list[SubtitleTrack] = field(default_factory=list)
    export_track_id: str | None = None
    regions: list[ExportRegion] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    @classmethod
    def from_path(cls, path: Path) -> MediaAsset:
        stat = path.stat()
        return cls(
            path=str(path.resolve()),
            display_name=path.name,
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
        )

    @property
    def export_track(self) -> SubtitleTrack | None:
        if self.export_track_id:
            for track in self.subtitle_tracks:
                if track.id == self.export_track_id:
                    return track
        return self.subtitle_tracks[0] if self.subtitle_tracks else None


@dataclass(slots=True)
class ExportPreset:
    name: str = "通用 TTS"
    container: str = "wav"
    sample_rate: int | None = 24000
    channels: int | None = 1
    codec: str = "pcm_s16le"
    bit_depth: str = "16"
    mp3_bitrate: str = "192k"
    flac_compression: int = 5
    write_txt: bool = True
    gain_db: float = 0.0
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    peak_normalize: bool = False
    peak_target_db: float = -1.0
    output_dir: str = ""
    naming_template: str = "{source}_{index:04d}_{start}"
    regex_pattern: str = ""
    regex_replacement: str = ""
    id: str = field(default_factory=new_id)


@dataclass(slots=True)
class Project:
    name: str = "未命名工程"
    assets: list[MediaAsset] = field(default_factory=list)
    active_asset_id: str | None = None
    presets: list[ExportPreset] = field(default_factory=lambda: [ExportPreset()])
    active_preset_id: str | None = None
    schema_version: int = 1
    project_path: str = ""

    def __post_init__(self) -> None:
        if self.presets and not self.active_preset_id:
            self.active_preset_id = self.presets[0].id

    @property
    def active_asset(self) -> MediaAsset | None:
        for asset in self.assets:
            if asset.id == self.active_asset_id:
                return asset
        return self.assets[0] if self.assets else None

    @property
    def active_preset(self) -> ExportPreset:
        for preset in self.presets:
            if preset.id == self.active_preset_id:
                return preset
        if not self.presets:
            self.presets.append(ExportPreset())
        return self.presets[0]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
