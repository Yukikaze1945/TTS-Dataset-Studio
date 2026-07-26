from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any, TypeVar

from tts_dataset_studio.domain.models import (
    ExportPreset,
    ExportRegion,
    MediaAsset,
    Project,
    SubtitleCue,
    SubtitleTrack,
)

T = TypeVar("T")


def _filtered(cls: type[T], data: dict[str, Any]) -> dict[str, Any]:
    allowed = {item.name for item in fields(cls)}
    return {key: value for key, value in data.items() if key in allowed}


def _portable_path(path_value: str, project_dir: Path) -> dict[str, str]:
    absolute = Path(path_value).resolve()
    try:
        relative = absolute.relative_to(project_dir.resolve())
        relative_value = str(relative)
    except ValueError:
        relative_value = ""
    return {"absolute": str(absolute), "relative": relative_value}


def _restore_path(value: str | dict[str, str], project_dir: Path) -> str:
    if isinstance(value, str):
        return value
    relative = value.get("relative", "")
    if relative:
        candidate = project_dir / relative
        if candidate.exists():
            return str(candidate.resolve())
    return value.get("absolute", "")


def _write_project(project: Project, destination: Path, update_path: bool) -> None:
    payload = project.to_dict()
    payload["project_path"] = (
        str(destination.resolve()) if update_path else project.project_path
    )
    for asset in payload["assets"]:
        asset["path"] = _portable_path(asset["path"], destination.parent)
        for track in asset["subtitle_tracks"]:
            if track["source_path"]:
                track["source_path"] = _portable_path(track["source_path"], destination.parent)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    if update_path:
        project.project_path = str(destination.resolve())


def save_project(project: Project, destination: Path) -> None:
    _write_project(project, destination.with_suffix(".ttds"), update_path=True)


def save_autosave(project: Project, destination: Path) -> None:
    _write_project(project, destination, update_path=False)


def load_project(source: Path) -> Project:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version", 1) != 1:
        raise ValueError(f"不支持的工程版本：{payload.get('schema_version')}")

    assets: list[MediaAsset] = []
    for raw_asset in payload.get("assets", []):
        raw_asset = dict(raw_asset)
        raw_asset["path"] = _restore_path(raw_asset["path"], source.parent)
        tracks: list[SubtitleTrack] = []
        for raw_track in raw_asset.pop("subtitle_tracks", []):
            raw_track = dict(raw_track)
            if raw_track.get("source_path"):
                raw_track["source_path"] = _restore_path(raw_track["source_path"], source.parent)
            raw_track["cues"] = [
                SubtitleCue(**_filtered(SubtitleCue, cue))
                for cue in raw_track.get("cues", [])
            ]
            tracks.append(SubtitleTrack(**_filtered(SubtitleTrack, raw_track)))
        raw_asset["subtitle_tracks"] = tracks
        raw_asset["regions"] = [
            ExportRegion(**_filtered(ExportRegion, region))
            for region in raw_asset.get("regions", [])
        ]
        assets.append(MediaAsset(**_filtered(MediaAsset, raw_asset)))

    presets = [
        ExportPreset(**_filtered(ExportPreset, raw))
        for raw in payload.get("presets", [])
    ]
    project_path = (
        str(source.resolve())
        if source.suffix.casefold() == ".ttds"
        else str(payload.get("project_path", ""))
    )
    data = _filtered(Project, payload)
    data.update(
        assets=assets,
        presets=presets or [ExportPreset()],
        project_path=project_path,
    )
    return Project(**data)
