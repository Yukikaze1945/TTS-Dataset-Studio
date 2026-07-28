from __future__ import annotations

import html
import re
from pathlib import Path

from tts_dataset_studio.domain.models import SubtitleCue, SubtitleTrack

SUPPORTED_SUBTITLES = {".srt", ".ass", ".vtt"}

_ASS_TAG = re.compile(r"\{[^}]*}")
_HTML_TAG = re.compile(r"<[^>]+>")


def clean_subtitle_text(value: str) -> str:
    value = _ASS_TAG.sub("", value)
    value = _HTML_TAG.sub("", value)
    value = value.replace(r"\N", "\n").replace(r"\n", "\n")
    lines = [
        " ".join(line.split())
        for line in html.unescape(value).splitlines()
    ]
    return "\n".join(line for line in lines if line)


def _clock_to_ms(value: str) -> int:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"无效时间码：{value}")
    seconds_value = float(seconds)
    return round((int(hours) * 3600 + int(minutes) * 60 + seconds_value) * 1000)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "shift_jis"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_srt_or_vtt(content: str) -> list[SubtitleCue]:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", content)
    cues: list[SubtitleCue] = []
    timing = re.compile(
        r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3})\s*-->\s*"
        r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3})"
    )
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        match_index = next((i for i, line in enumerate(lines) if timing.search(line)), None)
        if match_index is None:
            continue
        match = timing.search(lines[match_index])
        assert match is not None
        text = clean_subtitle_text("\n".join(lines[match_index + 1 :]))
        if text:
            cues.append(
                SubtitleCue(
                    _clock_to_ms(match.group("start")),
                    _clock_to_ms(match.group("end")),
                    text,
                )
            )
    return cues


def _parse_ass(content: str) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    in_events = False
    format_fields: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.lower() == "[events]":
            in_events = True
            continue
        if line.startswith("[") and line.endswith("]"):
            in_events = False
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            format_fields = [part.strip().lower() for part in line.split(":", 1)[1].split(",")]
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        if not format_fields:
            format_fields = [
                "layer",
                "start",
                "end",
                "style",
                "name",
                "marginl",
                "marginr",
                "marginv",
                "effect",
                "text",
            ]
        parts = line.split(":", 1)[1].lstrip().split(",", len(format_fields) - 1)
        if len(parts) != len(format_fields):
            continue
        row = dict(zip(format_fields, parts, strict=True))
        text = clean_subtitle_text(row.get("text", ""))
        if text and row.get("start") and row.get("end"):
            cues.append(SubtitleCue(_clock_to_ms(row["start"]), _clock_to_ms(row["end"]), text))
    return cues


def parse_subtitle(path: Path) -> SubtitleTrack:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUBTITLES:
        raise ValueError(f"不支持的字幕格式：{suffix}")
    content = _read_text(path)
    cues = _parse_ass(content) if suffix == ".ass" else _parse_srt_or_vtt(content)
    if not cues:
        raise ValueError(f"字幕中没有找到有效条目：{path.name}")
    return SubtitleTrack(name=_track_name(path), source_path=str(path.resolve()), cues=cues)


def _track_name(path: Path) -> str:
    suffixes = path.stem.split(".")
    return suffixes[-1] if len(suffixes) > 1 else path.stem


def find_matching_subtitles(media_path: Path) -> list[Path]:
    stem = media_path.stem.casefold()
    results: list[Path] = []
    for candidate in media_path.parent.iterdir():
        if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_SUBTITLES:
            continue
        candidate_stem = candidate.stem.casefold()
        if candidate_stem == stem or candidate_stem.startswith(stem + "."):
            results.append(candidate)
    return sorted(results, key=lambda value: value.name.casefold())


def _format_srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(max(0, milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _format_vtt_time(milliseconds: int) -> str:
    return _format_srt_time(milliseconds).replace(",", ".")


def _format_ass_time(milliseconds: int) -> str:
    centiseconds = round(max(0, milliseconds) / 10)
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def _ass_text(value: str) -> str:
    return value.replace("\n", r"\N")


def serialize_subtitle(track: SubtitleTrack, suffix: str) -> str:
    suffix = suffix.lower()
    cues = sorted(track.cues, key=lambda cue: (cue.start_ms, cue.end_ms))
    if suffix == ".srt":
        blocks = [
            (
                f"{index}\n"
                f"{_format_srt_time(cue.start_ms)} --> {_format_srt_time(cue.end_ms)}\n"
                f"{cue.text}"
            )
            for index, cue in enumerate(cues, 1)
        ]
        return "\n\n".join(blocks) + ("\n" if blocks else "")
    if suffix == ".vtt":
        blocks = [
            (
                f"{_format_vtt_time(cue.start_ms)} --> {_format_vtt_time(cue.end_ms)}\n"
                f"{cue.text}"
            )
            for cue in cues
        ]
        return "WEBVTT\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")
    if suffix == ".ass":
        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Microsoft YaHei UI,48,&H00FFFFFF,&H000000FF,"
            "&H00000000,&H96000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,42,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text\n"
        )
        events = [
            (
                f"Dialogue: 0,{_format_ass_time(cue.start_ms)},"
                f"{_format_ass_time(cue.end_ms)},Default,,0,0,0,,"
                f"{_ass_text(cue.text)}"
            )
            for cue in cues
        ]
        return header + "\n".join(events) + ("\n" if events else "")
    raise ValueError(f"不支持的字幕导出格式：{suffix}")


def export_subtitle(track: SubtitleTrack, path: Path) -> None:
    if path.suffix.lower() not in SUPPORTED_SUBTITLES:
        raise ValueError(f"不支持的字幕导出格式：{path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            serialize_subtitle(track, path.suffix),
            encoding="utf-8-sig",
            newline="\n",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
