from __future__ import annotations

import copy
from collections.abc import Callable

from PySide6.QtGui import QUndoCommand

from tts_dataset_studio.domain.models import (
    ExportRegion,
    GeneratedAudioClip,
    GeneratedAudioTrack,
    MediaAsset,
    SubtitleCue,
    SubtitleTrack,
)


class TextCommand(QUndoCommand):
    COMMAND_ID = 1001

    def __init__(
        self,
        cue: SubtitleCue,
        before: str,
        after: str,
        refresh: Callable[[], None],
    ) -> None:
        super().__init__("编辑字幕文本")
        self.cue = cue
        self.before = before
        self.after = after
        self.refresh = refresh

    def id(self) -> int:
        return self.COMMAND_ID

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802
        if not isinstance(other, TextCommand) or other.cue is not self.cue:
            return False
        self.after = other.after
        return True

    def undo(self) -> None:
        self.cue.text = self.before
        self.refresh()

    def redo(self) -> None:
        self.cue.text = self.after
        self.refresh()


class TimeRangeCommand(QUndoCommand):
    def __init__(
        self,
        item: SubtitleCue | ExportRegion,
        before: tuple[int, int],
        after: tuple[int, int],
        refresh: Callable[[], None],
        label: str = "调整时间",
    ) -> None:
        super().__init__(label)
        self.item = item
        self.before = before
        self.after = after
        self.refresh = refresh

    def _apply(self, value: tuple[int, int]) -> None:
        self.item.start_ms, self.item.end_ms = value
        self.refresh()

    def undo(self) -> None:
        self._apply(self.before)

    def redo(self) -> None:
        self._apply(self.after)


class RegionListCommand(QUndoCommand):
    def __init__(
        self,
        regions: list[ExportRegion],
        region: ExportRegion,
        add: bool,
        refresh: Callable[[], None],
    ) -> None:
        super().__init__("添加导出区间" if add else "删除导出区间")
        self.regions = regions
        self.region = region
        self.add = add
        self.refresh = refresh

    def _set_present(self, present: bool) -> None:
        if present and self.region not in self.regions:
            self.regions.append(self.region)
        elif not present and self.region in self.regions:
            self.regions.remove(self.region)
        self.refresh()

    def undo(self) -> None:
        self._set_present(not self.add)

    def redo(self) -> None:
        self._set_present(self.add)


class SubtitleTracksCommand(QUndoCommand):
    def __init__(
        self,
        asset: MediaAsset,
        before: list[SubtitleTrack],
        after: list[SubtitleTrack],
        refresh: Callable[[], None],
    ) -> None:
        super().__init__("生成 MOSS ASR 字幕")
        self.asset = asset
        self.before = copy.deepcopy(before)
        self.after = copy.deepcopy(after)
        self.refresh = refresh

    def _apply(self, tracks: list[SubtitleTrack]) -> None:
        self.asset.subtitle_tracks = copy.deepcopy(tracks)
        self.refresh()

    def undo(self) -> None:
        self._apply(self.before)

    def redo(self) -> None:
        self._apply(self.after)


class GeneratedClipsCommand(QUndoCommand):
    def __init__(
        self,
        track: GeneratedAudioTrack,
        before: list[GeneratedAudioClip],
        after: list[GeneratedAudioClip],
        refresh: Callable[[], None],
        label: str = "更新 AI 生成音轨",
    ) -> None:
        super().__init__(label)
        self.track = track
        self.before = copy.deepcopy(before)
        self.after = copy.deepcopy(after)
        self.refresh = refresh

    def _apply(self, clips: list[GeneratedAudioClip]) -> None:
        self.track.clips = copy.deepcopy(clips)
        self.refresh()

    def undo(self) -> None:
        self._apply(self.before)

    def redo(self) -> None:
        self._apply(self.after)


class GeneratedClipEditCommand(QUndoCommand):
    def __init__(
        self,
        clip: GeneratedAudioClip,
        before: tuple[int, int, int],
        after: tuple[int, int, int],
        refresh: Callable[[], None],
    ) -> None:
        super().__init__("调整 AI 音频片段")
        self.clip = clip
        self.before = before
        self.after = after
        self.refresh = refresh

    def _apply(self, value: tuple[int, int, int]) -> None:
        self.clip.start_ms, self.clip.source_offset_ms, self.clip.duration_ms = value
        self.refresh()

    def undo(self) -> None:
        self._apply(self.before)

    def redo(self) -> None:
        self._apply(self.after)
