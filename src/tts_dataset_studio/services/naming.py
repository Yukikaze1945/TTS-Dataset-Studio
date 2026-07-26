from __future__ import annotations

import re
from pathlib import Path

from tts_dataset_studio.domain.models import ExportPreset, ExportRegion, MediaAsset, SubtitleCue

WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def format_timecode(milliseconds: int) -> str:
    total_seconds, millis = divmod(max(0, milliseconds), 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}-{minutes:02d}-{seconds:02d}-{millis:03d}"


def sanitize_filename(value: str, max_length: int = 120) -> str:
    value = INVALID.sub("_", " ".join(value.split())).strip(" .")
    value = re.sub(r"_+", "_", value)
    if not value:
        value = "clip"
    if value.upper() in WINDOWS_RESERVED:
        value = f"_{value}"
    return value[:max_length].rstrip(" .") or "clip"


def cleaned_source_name(asset: MediaAsset, preset: ExportPreset) -> str:
    source = Path(asset.display_name).stem
    if preset.regex_pattern:
        try:
            source = re.sub(preset.regex_pattern, preset.regex_replacement, source)
        except re.error as exc:
            raise ValueError(f"命名正则无效：{exc}") from exc
    return sanitize_filename(source)


def choose_cue(asset: MediaAsset, region: ExportRegion) -> SubtitleCue | None:
    track = asset.export_track
    return track.cue_for_region(region.start_ms, region.end_ms) if track else None


def base_name_for_region(
    asset: MediaAsset,
    region: ExportRegion,
    preset: ExportPreset,
    index: int,
) -> tuple[str, str | None]:
    cue = choose_cue(asset, region)
    if cue:
        return sanitize_filename(cue.text), cue.text
    variables = {
        "source": cleaned_source_name(asset, preset),
        "index": index,
        "start": format_timecode(region.start_ms),
        "end": format_timecode(region.end_ms),
        "duration": region.end_ms - region.start_ms,
    }
    try:
        value = preset.naming_template.format(**variables)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"命名模板无效：{exc}") from exc
    return sanitize_filename(value), None


def unique_output_path(folder: Path, base_name: str, extension: str) -> Path:
    candidate = folder / f"{base_name}.{extension.lstrip('.')}"
    counter = 2
    while candidate.exists() or candidate.with_suffix(".txt").exists():
        candidate = folder / f"{base_name}_{counter:03d}.{extension.lstrip('.')}"
        counter += 1
    return candidate

