from __future__ import annotations

import copy
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from platformdirs import user_cache_path, user_data_path
from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSettings,
    Qt,
    QThread,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QResizeEvent,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tts_dataset_studio.domain.app_settings import AppSettings
from tts_dataset_studio.domain.models import (
    ExportRegion,
    GeneratedAudioClip,
    MediaAsset,
    Project,
    SubtitleCue,
    SubtitleTrack,
    new_id,
)
from tts_dataset_studio.services.ai_monitor import build_ai_monitor_cache
from tts_dataset_studio.services.asr_audio import extract_asr_audio
from tts_dataset_studio.services.asr_controller import AsrController
from tts_dataset_studio.services.exporter import ExportResult, export_region
from tts_dataset_studio.services.index_tts_controller import IndexTtsController
from tts_dataset_studio.services.media import MEDIA_EXTENSIONS, ToolPaths, probe_media
from tts_dataset_studio.services.naming import sanitize_filename
from tts_dataset_studio.services.project_io import (
    cleanup_unreferenced_generated_audio,
    load_project,
    save_autosave,
    save_project,
)
from tts_dataset_studio.services.still_export import export_still
from tts_dataset_studio.services.subtitles import (
    SUPPORTED_SUBTITLES,
    export_subtitle,
    parse_subtitle,
)
from tts_dataset_studio.services.tts_audio import extract_tts_reference
from tts_dataset_studio.services.waveform import generate_waveform
from tts_dataset_studio.ui.advanced_settings import AdvancedSettingsDialog
from tts_dataset_studio.ui.commands import (
    GeneratedClipEditCommand,
    GeneratedClipsCommand,
    RegionListCommand,
    SubtitleTracksCommand,
    TextCommand,
    TimeRangeCommand,
)
from tts_dataset_studio.ui.player import PlayerWidget
from tts_dataset_studio.ui.theme import build_stylesheet
from tts_dataset_studio.ui.timeline import (
    TimelineCanvas,
    TimelineScrollArea,
    WaveformDbScale,
)
from tts_dataset_studio.ui.widgets import AudioPreview, DropListWidget
from tts_dataset_studio.ui.workspace import (
    ContextActionBar,
    EmptyWorkspace,
    TaskNoticeBar,
    WorkspaceState,
)

LOGGER = logging.getLogger(__name__)


def _timecode(milliseconds: int) -> str:
    total_seconds, millis = divmod(max(0, milliseconds), 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


class TaskSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class WaveformTask(QRunnable):
    def __init__(self, asset: MediaAsset) -> None:
        super().__init__()
        self.asset = asset
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            peaks = generate_waveform(
                Path(self.asset.path),
                self.asset.size,
                self.asset.modified_ns,
            )
            self.signals.finished.emit((self.asset.id, peaks))
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc))


class ExportWorker(QThread):
    progress = Signal(int)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        asset: MediaAsset,
        region: ExportRegion,
        preset,
        index: int,
        default_output_dir: str = "",
    ) -> None:
        super().__init__()
        self.asset = copy.deepcopy(asset)
        self.region = copy.deepcopy(region)
        self.preset = copy.deepcopy(preset)
        self.index = index
        self.default_output_dir = default_output_dir
        self.cancel_event = Event()

    def run(self) -> None:
        try:
            result = export_region(
                self.asset,
                self.region,
                self.preset,
                self.index,
                self.cancel_event,
                self.progress.emit,
                default_output_dir=self.default_output_dir,
            )
            self.completed.emit(result)
        except InterruptedError:
            self.failed.emit("导出已取消")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self.cancel_event.set()


class StillTask(QRunnable):
    def __init__(
        self,
        asset: MediaAsset,
        position_ms: int,
        output_folder: Path,
        settings: AppSettings,
    ) -> None:
        super().__init__()
        self.asset = copy.deepcopy(asset)
        self.position_ms = position_ms
        self.output_folder = output_folder
        self.settings = copy.deepcopy(settings)
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            path = export_still(
                self.asset,
                self.position_ms,
                self.output_folder,
                self.settings.still_naming_template,
                self.settings.still_format,
                self.settings.jpeg_quality,
            )
            self.signals.finished.emit(path)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc))


class AsrExtractTask(QRunnable):
    def __init__(
        self,
        asset: MediaAsset,
        regions: list[ExportRegion],
        folder: Path,
    ) -> None:
        super().__init__()
        self.asset = copy.deepcopy(asset)
        self.regions = copy.deepcopy(regions)
        self.folder = folder
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            items = []
            for index, region in enumerate(self.regions, start=1):
                path = extract_asr_audio(
                    self.asset,
                    region,
                    self.folder / f"region_{index:04d}.wav",
                )
                items.append((region, path))
            self.signals.finished.emit(items)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc))


@dataclass(slots=True)
class TtsBatchItem:
    region: ExportRegion
    text: str
    clip_id: str = field(default_factory=new_id)
    reference: Path | None = None
    output: Path | None = None


class TtsReferenceTask(QRunnable):
    def __init__(
        self,
        asset: MediaAsset,
        items: list[TtsBatchItem],
        folder: Path,
    ) -> None:
        super().__init__()
        self.asset = copy.deepcopy(asset)
        self.items = copy.deepcopy(items)
        self.folder = folder
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            for index, item in enumerate(self.items, start=1):
                item.reference = extract_tts_reference(
                    self.asset,
                    item.region,
                    self.folder / f"reference_{index:04d}.wav",
                )
                item.output = self.folder / f"generated_{index:04d}.wav"
            self.signals.finished.emit(self.items)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc))


class GeneratedWaveformTask(QRunnable):
    def __init__(self, clip: GeneratedAudioClip) -> None:
        super().__init__()
        self.clip = copy.deepcopy(clip)
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            path = Path(self.clip.path)
            stat = path.stat()
            peaks = generate_waveform(path, stat.st_size, stat.st_mtime_ns)
            self.signals.finished.emit((self.clip.id, peaks))
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc))


class AiMonitorTask(QRunnable):
    def __init__(self, asset: MediaAsset, destination: Path, token: int) -> None:
        super().__init__()
        self.asset = copy.deepcopy(asset)
        self.destination = destination
        self.token = token
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            path = build_ai_monitor_cache(self.asset, self.destination)
            self.signals.finished.emit((self.asset.id, self.token, path))
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project = Project()
        self.workspace_state = WorkspaceState(self)
        self.settings = QSettings("OpenAI", "TTS Dataset Studio")
        self.app_settings = AppSettings.load(self.settings)
        self.project.active_preset.naming_template = (
            self.app_settings.audio_naming_template
        )
        self._apply_export_settings_to_preset()
        self.thread_pool = QThreadPool.globalInstance()
        self.waveforms: dict[str, list[float]] = {}
        self.generated_waveforms: dict[str, list[float]] = {}
        self.selected_cue: tuple[str, str] | None = None
        self.selected_region_id: str | None = None
        self.selected_region_ids: set[str] = set()
        self.selected_generated_clip_ids: set[str] = set()
        self.in_point_ms: int | None = None
        self._scrubbing_playhead = False
        self._awaiting_scrub_ms: int | None = None
        self.dirty = False
        self.export_worker: ExportWorker | None = None
        self.asr = AsrController(self)
        self.index_tts = IndexTtsController(self)
        self._asr_busy = False
        self._asr_pending_start = False
        self._asr_cancel_requested = False
        self._asr_extracting = False
        self._asr_queue: list[tuple[ExportRegion, Path]] = []
        self._asr_results: list[tuple[ExportRegion, list[dict]]] = []
        self._asr_current: tuple[ExportRegion, Path] | None = None
        self._asr_asset_id: str | None = None
        self._asr_temp_folder: Path | None = None
        self._tts_busy = False
        self._tts_pending_start = False
        self._tts_cancel_requested = False
        self._tts_extracting = False
        self._tts_asset_id: str | None = None
        self._tts_temp_folder: Path | None = None
        self._tts_analysis_queue: list[TtsBatchItem] = []
        self._tts_analysis_current: TtsBatchItem | None = None
        self._tts_analysis_results: list[dict] = []
        self._tts_queue: list[TtsBatchItem] = []
        self._tts_current: TtsBatchItem | None = None
        self._ai_monitor_token = 0
        self.undo_stack = QUndoStack(self)
        self.tools: ToolPaths | None = None
        self._build_ui()
        self.player_widget.set_scrub_hz(self.app_settings.scrub_hz)
        self.asr.state_changed.connect(self._asr_state_changed)
        self.asr.loaded.connect(self._asr_loaded)
        self.asr.unloaded.connect(self._asr_unloaded)
        self.asr.transcription_ready.connect(self._asr_transcription_ready)
        self.asr.failed.connect(self._asr_failed)
        self.index_tts.state_changed.connect(self._tts_state_changed)
        self.index_tts.loaded.connect(self._tts_loaded)
        self.index_tts.unloaded.connect(self._tts_unloaded)
        self.index_tts.text_analyzed.connect(self._tts_text_analyzed)
        self.index_tts.generated.connect(self._tts_generated)
        self.index_tts.failed.connect(self._tts_failed)
        self.setAcceptDrops(True)
        self._build_actions()
        self._check_tools()
        self._restore_geometry()
        self._set_project_title()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(30_000)
        self.autosave_timer.timeout.connect(self._write_autosave)
        self.autosave_timer.start()
        QTimer.singleShot(0, self._offer_unsaved_recovery)

    def _build_ui(self) -> None:
        self.setMinimumSize(1024, 700)
        self.resize(1360, 860)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 10, 14, 0)
        root_layout.setSpacing(8)
        root_layout.addWidget(self._build_top_bar())

        self.workspace_stack = QStackedWidget()
        self.empty_workspace = EmptyWorkspace()
        self.empty_workspace.import_requested.connect(self._choose_media)
        self.workspace_stack.addWidget(self.empty_workspace)
        self.workspace_stack.addWidget(self._build_workspace_page())
        root_layout.addWidget(self.workspace_stack, 1)

        self.task_notice = TaskNoticeBar()
        self.task_notice.cancel_requested.connect(self._cancel_active_task)
        self.task_notice.action_requested.connect(self._open_last_output_folder)
        root_layout.addWidget(self.task_notice)
        self.setCentralWidget(root)

        status = QStatusBar()
        self.status_message = QLabel("准备就绪")
        self.status_message.setObjectName("muted")
        self.backend_label = QLabel("Qt Multimedia")
        self.backend_label.setObjectName("muted")
        status.addWidget(self.status_message, 1)
        status.addPermanentWidget(self.backend_label)
        self.setStatusBar(status)
        self._show_empty_workspace()

    def _build_workspace_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.horizontal_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.library_panel = self._build_library_panel()
        self.horizontal_splitter.addWidget(self.library_panel)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        vertical_splitter.addWidget(self._build_preview_panel())
        vertical_splitter.addWidget(self._build_timeline_panel())
        vertical_splitter.setSizes([440, 310])
        content_layout.addWidget(vertical_splitter, 1)

        self.context_bar = ContextActionBar()
        self.workspace_state.selection_changed.connect(
            self.context_bar.set_selection
        )
        self.context_bar.play_requested.connect(self._play_selection)
        self.context_bar.transcribe_requested.connect(self._toggle_asr_transcription)
        self.context_bar.generate_requested.connect(self._toggle_tts_generation)
        self.context_bar.export_requested.connect(self.quick_export)
        self.context_bar.delete_requested.connect(self._delete_region)
        self.context_bar.edit_requested.connect(self._show_property_drawer)
        content_layout.addWidget(self.context_bar)
        self.horizontal_splitter.addWidget(content)

        self.property_drawer = self._build_inspector_panel()
        self.property_drawer.setMinimumWidth(300)
        self.property_drawer.setMaximumWidth(380)
        self.property_drawer.hide()
        self.horizontal_splitter.addWidget(self.property_drawer)
        self.horizontal_splitter.setStretchFactor(0, 0)
        self.horizontal_splitter.setStretchFactor(1, 1)
        self.horizontal_splitter.setStretchFactor(2, 0)
        self.horizontal_splitter.setSizes([230, 900, 0])
        layout.addWidget(self.horizontal_splitter, 1)

        self.export_button = self.context_bar.export_button
        self.asr_transcribe_button = self.context_bar.asr_button
        self.tts_generate_button = self.context_bar.tts_button
        self.asr_load_button = QPushButton(self)
        self.asr_load_button.hide()
        self.tts_load_button = QPushButton(self)
        self.tts_load_button.hide()
        return page

    def _build_top_bar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("topBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(2, 3, 2, 3)
        self.sidebar_button = QPushButton("素材")
        self.sidebar_button.setObjectName("quietAction")
        self.sidebar_button.setToolTip("展开或收起素材栏")
        self.sidebar_button.clicked.connect(self._toggle_sidebar)
        layout.addWidget(self.sidebar_button)
        self.project_title_label = QLabel("未命名工程")
        self.project_title_label.setObjectName("title")
        layout.addWidget(self.project_title_label)
        layout.addStretch()
        self.timecode_label = QLabel("00:00:00.000")
        self.timecode_label.setObjectName("timecode")
        layout.addWidget(self.timecode_label)
        layout.addSpacing(10)
        import_button = QPushButton("＋ 导入")
        import_button.setObjectName("quietAction")
        import_button.clicked.connect(self._choose_media)
        layout.addWidget(import_button)
        undo_button = QPushButton("撤销")
        undo_button.setObjectName("quietAction")
        undo_button.setToolTip("撤销  Ctrl+Z")
        undo_button.clicked.connect(self.undo_stack.undo)
        layout.addWidget(undo_button)
        redo_button = QPushButton("重做")
        redo_button.setObjectName("quietAction")
        redo_button.setToolTip("重做  Ctrl+Shift+Z")
        redo_button.clicked.connect(self.undo_stack.redo)
        layout.addWidget(redo_button)
        help_button = QPushButton("?")
        help_button.setObjectName("quietAction")
        help_button.setToolTip("快捷键")
        help_button.clicked.connect(self._show_shortcuts)
        layout.addWidget(help_button)
        settings_button = QPushButton("设置")
        settings_button.setObjectName("quietAction")
        settings_button.clicked.connect(self._show_advanced_settings)
        layout.addWidget(settings_button)
        return frame

    def _show_empty_workspace(self) -> None:
        if hasattr(self, "workspace_stack"):
            self.workspace_stack.setCurrentIndex(0)
            self.sidebar_button.setEnabled(False)

    def _show_workspace(self) -> None:
        self.workspace_stack.setCurrentIndex(1)
        self.sidebar_button.setEnabled(True)

    def _toggle_sidebar(self) -> None:
        if not self.project.assets:
            return
        self.library_panel.setVisible(not self.library_panel.isVisible())

    def _show_property_drawer(self) -> None:
        if self.width() < 1180:
            self.library_panel.hide()
        self.property_drawer.show()
        self.horizontal_splitter.setSizes(
            [230 if self.library_panel.isVisible() else 0, 760, 340]
        )

    def _cancel_active_task(self) -> None:
        if self.export_worker and self.export_worker.isRunning():
            self._cancel_export()
        elif self._asr_busy:
            self._cancel_asr_batch()
        elif self._tts_busy:
            self._cancel_tts_batch()

    def _open_last_output_folder(self) -> None:
        folder = getattr(self, "_last_output_folder", None)
        if folder and Path(folder).is_dir():
            os.startfile(folder)  # noqa: S606

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not hasattr(self, "library_panel") or not self.project.assets:
            return
        if event.size().width() < 1100:
            self.library_panel.hide()
        elif not self.property_drawer.isVisible():
            self.library_panel.show()

    def _panel(self) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        return frame, layout

    def _build_library_panel(self) -> QWidget:
        frame, layout = self._panel()
        label = QLabel("素材库")
        label.setObjectName("title")
        layout.addWidget(label)
        self.asset_list = DropListWidget()
        self.asset_list.files_dropped.connect(
            lambda paths: self.import_paths(paths, activate=False)
        )
        self.asset_list.currentRowChanged.connect(self._activate_asset_row)
        layout.addWidget(self.asset_list, 3)
        add_media = QPushButton("＋ 导入音视频")
        add_media.clicked.connect(self._choose_media)
        layout.addWidget(add_media)
        label = QLabel("字幕轨")
        label.setObjectName("eyebrow")
        layout.addWidget(label)
        self.subtitle_tree = QTreeWidget()
        self.subtitle_tree.setHeaderLabels(["显示 / 轨道", "条目"])
        self.subtitle_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.subtitle_tree.itemClicked.connect(self._subtitle_tree_clicked)
        layout.addWidget(self.subtitle_tree, 2)
        subtitle_actions = QHBoxLayout()
        add_subtitle = QPushButton("＋ 添加字幕轨")
        add_subtitle.clicked.connect(self._choose_subtitle)
        subtitle_actions.addWidget(add_subtitle)
        export_subtitle_button = QPushButton("导出完整字幕")
        export_subtitle_button.clicked.connect(self._export_subtitle_track)
        subtitle_actions.addWidget(export_subtitle_button)
        layout.addLayout(subtitle_actions)
        return frame

    def _build_preview_panel(self) -> QWidget:
        frame, layout = self._panel()
        frame.setObjectName("previewPanel")
        header = QHBoxLayout()
        label = QLabel("预览")
        label.setObjectName("title")
        header.addWidget(label)
        self.video_preview_button = QPushButton("视频")
        self.video_preview_button.setObjectName("timelineTool")
        self.video_preview_button.setCheckable(True)
        self.video_preview_button.clicked.connect(
            lambda: self._set_preview_mode("video")
        )
        self.video_preview_button.setEnabled(False)
        header.addWidget(self.video_preview_button)
        self.waveform_preview_button = QPushButton("波形")
        self.waveform_preview_button.setObjectName("timelineTool")
        self.waveform_preview_button.setCheckable(True)
        self.waveform_preview_button.clicked.connect(
            lambda: self._set_preview_mode("waveform")
        )
        self.waveform_preview_button.setChecked(True)
        header.addWidget(self.waveform_preview_button)
        header.addStretch()
        self.media_info = QLabel("NO MEDIA")
        self.media_info.setObjectName("eyebrow")
        header.addWidget(self.media_info)
        layout.addLayout(header)
        self.audio_preview = AudioPreview()
        self.player_widget = PlayerWidget(self.audio_preview)
        self.player_widget.position_changed.connect(self._on_position_changed)
        self.player_widget.error_occurred.connect(self._show_error)
        self.player_widget.warning_occurred.connect(self._playback_warning)
        self.player_widget.backend_changed.connect(self._playback_backend_changed)
        layout.addWidget(self.player_widget, 1)
        transport = QHBoxLayout()
        self.play_button = QPushButton("播放")
        self.play_button.setToolTip("播放 / 暂停  Space")
        self.play_button.clicked.connect(self._toggle_playback)
        transport.addWidget(self.play_button)
        for text, delta in (("−5s", -5000), ("−1s", -1000), ("+1s", 1000), ("+5s", 5000)):
            button = QPushButton(text)
            button.setObjectName("quietAction")
            button.clicked.connect(lambda _checked=False, value=delta: self._seek_relative(value))
            transport.addWidget(button)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.sliderMoved.connect(self._seek)
        transport.addWidget(self.position_slider, 1)
        layout.addLayout(transport)
        return frame

    def _build_inspector_panel(self) -> QWidget:
        frame, layout = self._panel()
        header = QHBoxLayout()
        title = QLabel("片段属性")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        close_button = QPushButton("×")
        close_button.setObjectName("quietAction")
        close_button.setToolTip("关闭属性")
        close_button.clicked.connect(frame.hide)
        header.addWidget(close_button)
        layout.addLayout(header)
        tabs = QTabWidget()
        tabs.setMinimumWidth(0)
        tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tabs.addTab(self._scrollable_inspector_tab(self._build_clip_tab()), "片段")
        tabs.addTab(self._scrollable_inspector_tab(self._build_export_tab()), "导出")
        tabs.setTabVisible(1, False)
        self.inspector_tabs = tabs
        layout.addWidget(tabs)
        return frame

    def _scrollable_inspector_tab(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        scroll.setWidget(content)
        return scroll

    def _build_clip_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.export_track_combo = QComboBox()
        self.export_track_combo.currentIndexChanged.connect(self._export_track_changed)
        form.addRow("导出字幕轨", self.export_track_combo)
        self.cue_start = QSpinBox()
        self.cue_start.setRange(0, 86_400_000)
        self.cue_start.setSuffix(" ms")
        self.cue_end = QSpinBox()
        self.cue_end.setRange(1, 86_400_000)
        self.cue_end.setSuffix(" ms")
        self.cue_start.editingFinished.connect(self._apply_cue_editor)
        self.cue_end.editingFinished.connect(self._apply_cue_editor)
        form.addRow("开始", self.cue_start)
        form.addRow("结束", self.cue_end)
        layout.addLayout(form)
        layout.addWidget(QLabel("字幕文本"))
        self.cue_text = QPlainTextEdit()
        self.cue_text.setPlaceholderText("选择字幕后可编辑文本")
        self.cue_text.textChanged.connect(self._apply_cue_text)
        layout.addWidget(self.cue_text, 1)
        gain_header = QHBoxLayout()
        gain_header.addWidget(QLabel("导出增益"))
        gain_header.addStretch()
        self.clip_warning = QLabel("")
        self.clip_warning.setStyleSheet("color: #ff7b72;")
        gain_header.addWidget(self.clip_warning)
        layout.addLayout(gain_header)
        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(-600, 120)
        self.gain_slider.setValue(0)
        self.gain_slider.valueChanged.connect(self._gain_slider_changed)
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-60.0, 12.0)
        self.gain_spin.setSingleStep(0.5)
        self.gain_spin.setSuffix(" dB")
        self.gain_spin.valueChanged.connect(self._gain_spin_changed)
        gain_row = QHBoxLayout()
        gain_row.addWidget(self.gain_slider, 1)
        gain_row.addWidget(self.gain_spin)
        layout.addLayout(gain_row)
        self.gain_bypass = QCheckBox("旁路增益")
        self.gain_bypass.toggled.connect(self._gain_bypass_changed)
        layout.addWidget(self.gain_bypass)
        reset = QPushButton("增益归零")
        reset.clicked.connect(lambda: self.gain_spin.setValue(0))
        layout.addWidget(reset)
        return tab

    def _build_export_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.export_form = form
        self.format_combo = QComboBox()
        self.format_combo.addItems(["wav", "flac", "mp3"])
        self.format_combo.currentTextChanged.connect(self._preset_changed)
        form.addRow("格式", self.format_combo)
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItem("原始", None)
        for rate in (16000, 22050, 24000, 32000, 44100, 48000):
            self.sample_rate_combo.addItem(f"{rate} Hz", rate)
        self.sample_rate_combo.currentIndexChanged.connect(self._preset_changed)
        form.addRow("采样率", self.sample_rate_combo)
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("原始", None)
        self.channel_combo.addItem("单声道", 1)
        self.channel_combo.addItem("立体声", 2)
        self.channel_combo.currentIndexChanged.connect(self._preset_changed)
        form.addRow("声道", self.channel_combo)
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"])
        self.codec_combo.currentTextChanged.connect(self._preset_changed)
        form.addRow("WAV 编码", self.codec_combo)
        self.txt_checkbox = QCheckBox("生成同名 UTF-8 TXT")
        self.txt_checkbox.setChecked(True)
        self.txt_checkbox.toggled.connect(self._preset_changed)
        form.addRow("", self.txt_checkbox)
        self.normalize_checkbox = QCheckBox("峰值归一化至 -1 dBFS")
        self.normalize_checkbox.toggled.connect(self._preset_changed)
        form.addRow("", self.normalize_checkbox)
        layout.addLayout(form)
        self.output_edit = QPlainTextEdit()
        self.output_edit.setMaximumHeight(54)
        self.output_edit.setPlaceholderText("默认：素材所在目录（可在高级设置中修改）")
        self.output_edit.textChanged.connect(self._preset_changed)
        layout.addWidget(QLabel("输出目录"))
        layout.addWidget(self.output_edit)
        choose = QPushButton("选择输出目录")
        choose.clicked.connect(self._choose_output_folder)
        layout.addWidget(choose)
        self.naming_edit = QPlainTextEdit()
        self.naming_edit.setMaximumHeight(54)
        self.naming_edit.setPlainText("{source}_{index:04d}_{start}")
        self.naming_edit.textChanged.connect(self._preset_changed)
        layout.addWidget(QLabel("无字幕命名模板"))
        layout.addWidget(self.naming_edit)
        regex_form = QFormLayout()
        regex_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        regex_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self.regex_pattern = QLineEdit()
        self.regex_pattern.setPlaceholderText(r"可选，例如 _EP\d+$")
        self.regex_pattern.textChanged.connect(self._preset_changed)
        self.regex_replacement = QLineEdit()
        self.regex_replacement.setPlaceholderText("替换为")
        self.regex_replacement.textChanged.connect(self._preset_changed)
        regex_form.addRow("源名正则", self.regex_pattern)
        regex_form.addRow("替换文本", self.regex_replacement)
        self.fade_in_spin = QSpinBox()
        self.fade_in_spin.setRange(0, 5000)
        self.fade_in_spin.setSuffix(" ms")
        self.fade_in_spin.valueChanged.connect(self._preset_changed)
        self.fade_out_spin = QSpinBox()
        self.fade_out_spin.setRange(0, 5000)
        self.fade_out_spin.setSuffix(" ms")
        self.fade_out_spin.valueChanged.connect(self._preset_changed)
        regex_form.addRow("淡入", self.fade_in_spin)
        regex_form.addRow("淡出", self.fade_out_spin)
        layout.addLayout(regex_form)
        self.export_progress = QProgressBar()
        self.export_progress.setValue(0)
        layout.addWidget(self.export_progress)
        self.cancel_export_button = QPushButton("取消导出")
        self.cancel_export_button.setEnabled(False)
        self.cancel_export_button.clicked.connect(self._cancel_export)
        layout.addWidget(self.cancel_export_button)
        layout.addStretch()
        return tab

    def _build_timeline_panel(self) -> QWidget:
        frame, layout = self._panel()
        frame.setObjectName("timelinePanel")
        frame.setMinimumHeight(230)
        header = QHBoxLayout()
        label = QLabel("时间线")
        label.setObjectName("title")
        header.addWidget(label)
        self.selection_status = QLabel("点击字幕，或按 I / O 选择一段声音")
        self.selection_status.setObjectName("selectionStatus")
        header.addWidget(self.selection_status, 1)
        for text, callback, tooltip in (
            ("−", lambda: self._zoom_timeline(-120), "缩小时间线"),
            ("适配", self._fit_timeline, "完整显示当前素材"),
            ("＋", lambda: self._zoom_timeline(120), "放大时间线"),
        ):
            button = QPushButton(text)
            button.setObjectName("timelineTool")
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            header.addWidget(button)
        layout.addLayout(header)
        self.timeline = TimelineCanvas()
        self.timeline.cue_selected.connect(self._cue_selected)
        self.timeline.region_selected.connect(self._region_selected)
        self.timeline.seek_requested.connect(self._seek)
        self.timeline.scrub_requested.connect(self._scrub)
        self.timeline.scrub_finished.connect(self._finish_scrub)
        self.timeline.item_changed.connect(self._timeline_item_changed)
        self.timeline.generated_clip_selected.connect(self._generated_clip_selected)
        self.timeline.generated_clip_changed.connect(
            self._timeline_generated_clip_changed
        )
        self.timeline.generated_clip_collision.connect(self._show_error)
        self.timeline_scroll = TimelineScrollArea(self.timeline)
        self.timeline_scroll.setWidgetResizable(False)
        self.timeline_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        timeline_row = QHBoxLayout()
        timeline_row.setContentsMargins(0, 0, 0, 0)
        timeline_row.setSpacing(0)
        self.waveform_db_scale = WaveformDbScale(self.timeline)
        self.waveform_db_scale.source_mute_clicked.connect(
            lambda: self._toggle_track_monitor("source", "mute")
        )
        self.waveform_db_scale.source_solo_clicked.connect(
            lambda: self._toggle_track_monitor("source", "solo")
        )
        self.waveform_db_scale.generated_mute_clicked.connect(
            lambda: self._toggle_track_monitor("generated", "mute")
        )
        self.waveform_db_scale.generated_solo_clicked.connect(
            lambda: self._toggle_track_monitor("generated", "solo")
        )
        self.waveform_db_scale.installEventFilter(self.timeline_scroll)
        timeline_row.addWidget(self.waveform_db_scale)
        timeline_row.addWidget(self.timeline_scroll, 1)
        layout.addLayout(timeline_row, 1)
        return frame

    def _build_actions(self) -> None:
        actions = [
            ("新建", QKeySequence.StandardKey.New, self.new_project),
            ("打开", QKeySequence.StandardKey.Open, self.open_project),
            ("保存", QKeySequence.StandardKey.Save, self.save_project),
            ("撤销", QKeySequence.StandardKey.Undo, self.undo_stack.undo),
            ("重做", QKeySequence.StandardKey.Redo, self.undo_stack.redo),
            ("播放/暂停", QKeySequence(Qt.Key.Key_Space), self._toggle_playback),
            ("生成语音", QKeySequence("G"), self._toggle_tts_generation),
            ("选择片段", QKeySequence("V"), self._selection_tool),
            ("设置入点", QKeySequence("I"), self._set_in_point),
            ("设置出点", QKeySequence("O"), self._set_out_point),
            ("播放区间", QKeySequence(Qt.Key.Key_Return), self._play_selection),
            ("快捷导出", QKeySequence("E"), self.quick_export),
            ("删除区间", QKeySequence("X"), self._delete_region),
            ("上一帧", QKeySequence("D"), self._previous_frame),
            ("下一帧", QKeySequence("F"), self._next_frame),
            ("保存原视频静帧", QKeySequence("C"), self._save_still),
            ("快捷键", QKeySequence("?"), self._show_shortcuts),
        ]
        menu = self.menuBar().addMenu("文件")
        self.single_key_actions: list[QAction] = []
        for text, shortcut, callback in actions:
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(callback)
            self.addAction(action)
            if text in {"快捷导出", "删除区间"}:
                if text == "快捷导出":
                    self.quick_export_action = action
                else:
                    self.delete_region_action = action
            if QKeySequence(shortcut).toString() in {"D", "F", "C", "E", "G", "X"}:
                self.single_key_actions.append(action)
            if text in {"新建", "打开", "保存"}:
                menu.addAction(action)
        menu.addSeparator()
        advanced_action = QAction("设置…", self)
        advanced_action.triggered.connect(self._show_advanced_settings)
        menu.addAction(advanced_action)
        QApplication.instance().focusChanged.connect(self._update_single_key_shortcuts)

    def _update_single_key_shortcuts(self, _old: QWidget | None, now: QWidget | None) -> None:
        editing = isinstance(
            now,
            (QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox),
        )
        for action in self.single_key_actions:
            action.setEnabled(not editing)

    def _check_tools(self) -> None:
        try:
            self.tools = ToolPaths.discover()
            self._playback_backend_changed(self.player_widget.backend_name)
        except FileNotFoundError as exc:
            LOGGER.error("Required media tools are unavailable: %s", exc)
            self.status_message.setText(f"TOOLS MISSING · {exc}")
            self.export_button.setEnabled(False)

    def _playback_backend_changed(self, name: str) -> None:
        self.backend_label.setText(f"PLAYBACK · {name}")

    def _playback_warning(self, message: str) -> None:
        LOGGER.warning(message)
        self.status_message.setText(f"PLAYBACK WARNING · {message}")

    def import_paths(self, values: list[str], activate: bool = True) -> None:
        for value in values:
            path = Path(value)
            if path.suffix.lower() in MEDIA_EXTENSIONS:
                self._import_media(path, activate=activate)
            elif path.suffix.lower() in SUPPORTED_SUBTITLES:
                self._import_subtitle(path)

    def _import_media(self, path: Path, activate: bool = True) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            asset = probe_media(path, self.tools)
            self.project.assets.append(asset)
            marker = "VIDEO" if asset.has_video else "AUDIO"
            self.asset_list.addItem(f"{marker}  {asset.display_name}")
            if activate or not self.project.active_asset_id:
                self.project.active_asset_id = asset.id
                self.asset_list.setCurrentRow(len(self.project.assets) - 1)
                self._activate_asset(asset)
            self._mark_dirty()
            subtitle_summary = (
                f" · {len(asset.subtitle_tracks)} 条字幕轨"
                if asset.subtitle_tracks
                else ""
            )
            self.status_message.setText(
                f"IMPORTED · {asset.display_name}{subtitle_summary}"
            )
        except Exception as exc:  # noqa: BLE001
            self._show_error(str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    def _import_subtitle(self, path: Path) -> None:
        asset = self.project.active_asset
        if not asset:
            self._show_error("请先导入并选择一个音视频素材。")
            return
        try:
            track = parse_subtitle(path)
            asset.subtitle_tracks.append(track)
            if not asset.export_track_id:
                asset.export_track_id = track.id
            self._refresh_subtitles()
            self._refresh_export_tracks()
            self.timeline._resize_for_content()
            self.timeline.update()
            self._mark_dirty()
        except ValueError as exc:
            self._show_error(str(exc))

    def _activate_asset_row(self, row: int) -> None:
        if 0 <= row < len(self.project.assets):
            self._activate_asset(self.project.assets[row])

    def _activate_asset(self, asset: MediaAsset) -> None:
        self._show_workspace()
        self.workspace_state.set_asset(asset.id)
        self.project.active_asset_id = asset.id
        self._scrubbing_playhead = False
        self._awaiting_scrub_ms = None
        self.selected_cue = None
        self.selected_region_id = None
        self.selected_region_ids.clear()
        self.selected_generated_clip_ids.clear()
        self.in_point_ms = None
        source_path = Path(asset.path)
        source_exists = source_path.exists()
        if source_exists:
            self.player_widget.load(source_path, asset.has_video)
            self.player_widget.set_gain(asset.gain_db, asset.gain_bypassed)
        else:
            self.player_widget.clear()
            self.status_message.setText(f"OFFLINE · 缺失素材：{asset.display_name}")
        self.position_slider.setRange(0, max(1, asset.duration_ms))
        if source_exists:
            self.media_info.setText(
                f"{_timecode(asset.duration_ms)} · {asset.sample_rate or '?'} Hz · "
                f"{asset.channels or '?'} CH"
            )
        else:
            self.media_info.setText("MISSING MEDIA · 需要重新定位")
        peaks = self.waveforms.get(asset.id, [])
        self.timeline.set_asset(asset, peaks)
        for clip in asset.generated_track.clips:
            cached = self.generated_waveforms.get(clip.id)
            if cached:
                self.timeline.set_generated_waveform(clip.id, cached)
            elif Path(clip.path).is_file():
                self._schedule_generated_waveform(clip)
        self.timeline.set_in_point(None)
        self.audio_preview.set_peaks(peaks)
        self.video_preview_button.setEnabled(asset.has_video and source_exists)
        self._set_preview_mode("video" if asset.has_video else "waveform")
        self._refresh_subtitles()
        self._refresh_export_tracks()
        self._update_preview_subtitle(0)
        self._load_gain()
        self._load_preset()
        if source_exists and not peaks:
            task = WaveformTask(asset)
            task.signals.finished.connect(self._waveform_ready)
            task.signals.failed.connect(self._show_error)
            self.thread_pool.start(task)
        self._apply_track_monitor()
        self._schedule_ai_monitor()
        self._update_selection_status()

    def _waveform_ready(self, payload: object) -> None:
        asset_id, peaks = payload
        self.waveforms[asset_id] = peaks
        if self.project.active_asset and self.project.active_asset.id == asset_id:
            self.timeline.set_waveform(peaks)
            self.audio_preview.set_peaks(peaks)
            self.status_message.setText(f"WAVEFORM READY · {len(peaks):,} peaks")

    def _schedule_generated_waveform(self, clip: GeneratedAudioClip) -> None:
        task = GeneratedWaveformTask(clip)
        task.signals.finished.connect(self._generated_waveform_ready)
        task.signals.failed.connect(
            lambda message: LOGGER.warning("Generated waveform failed: %s", message)
        )
        self.thread_pool.start(task)

    def _generated_waveform_ready(self, payload: object) -> None:
        clip_id, peaks = payload
        self.generated_waveforms[clip_id] = peaks
        asset = self.project.active_asset
        if asset and any(
            clip.id == clip_id for clip in asset.generated_track.clips
        ):
            self.timeline.set_generated_waveform(clip_id, peaks)

    def _monitor_cache_dir(self) -> Path:
        if self.app_settings.cache_dir:
            return Path(self.app_settings.cache_dir) / "ai-monitor"
        return Path(
            user_cache_path("TTS Dataset Studio", "OpenAI")
        ) / "ai-monitor"

    def _schedule_ai_monitor(self) -> None:
        asset = self.project.active_asset
        self._ai_monitor_token += 1
        token = self._ai_monitor_token
        self.player_widget.clear_ai_monitor()
        if not asset or not asset.generated_track.clips:
            return
        destination = self._monitor_cache_dir() / f"{asset.id}-{token}.flac"
        task = AiMonitorTask(asset, destination, token)
        task.signals.finished.connect(self._ai_monitor_ready)
        task.signals.failed.connect(self._ai_monitor_failed)
        self.thread_pool.start(task)
        self.status_message.setText("AI MONITOR · 正在重建监听缓存")

    def _ai_monitor_ready(self, payload: object) -> None:
        asset_id, token, path = payload
        asset = self.project.active_asset
        if not asset or asset.id != asset_id or token != self._ai_monitor_token:
            return
        self.player_widget.load_ai_monitor(path)
        for stale in self._monitor_cache_dir().glob(f"{asset.id}-*.flac"):
            if stale != path:
                stale.unlink(missing_ok=True)
        self._apply_track_monitor()
        self.status_message.setText("AI MONITOR READY · 监听缓存已同步")

    def _ai_monitor_failed(self, message: str) -> None:
        LOGGER.error("AI monitor cache failed: %s", message)
        self.status_message.setText(f"AI MONITOR ERROR · {message}")

    def _apply_track_monitor(self) -> None:
        asset = self.project.active_asset
        if not asset:
            self.player_widget.set_track_monitor(True, False)
            return
        track = asset.generated_track
        any_solo = asset.source_solo or track.solo
        source_audible = not asset.source_muted and (
            not any_solo or asset.source_solo
        )
        ai_audible = not track.muted and (not any_solo or track.solo)
        self.player_widget.set_track_monitor(source_audible, ai_audible)
        if hasattr(self, "waveform_db_scale"):
            self.waveform_db_scale.update()

    def _toggle_track_monitor(self, track_name: str, control: str) -> None:
        asset = self.project.active_asset
        if not asset:
            return
        if track_name == "source":
            target = asset
            attribute = "source_muted" if control == "mute" else "source_solo"
        else:
            target = asset.generated_track
            attribute = "muted" if control == "mute" else "solo"
        setattr(target, attribute, not bool(getattr(target, attribute)))
        self._apply_track_monitor()
        self._mark_dirty()

    def _refresh_subtitles(self) -> None:
        self.subtitle_tree.clear()
        asset = self.project.active_asset
        if not asset:
            return
        for track in asset.subtitle_tracks:
            item = QTreeWidgetItem([track.name, str(len(track.cues))])
            item.setData(0, Qt.ItemDataRole.UserRole, track.id)
            check_state = Qt.CheckState.Checked if track.visible else Qt.CheckState.Unchecked
            item.setCheckState(0, check_state)
            self.subtitle_tree.addTopLevelItem(item)

    def _refresh_export_tracks(self) -> None:
        self.export_track_combo.blockSignals(True)
        self.export_track_combo.clear()
        asset = self.project.active_asset
        if asset:
            for track in asset.subtitle_tracks:
                self.export_track_combo.addItem(track.name, track.id)
            index = self.export_track_combo.findData(asset.export_track_id)
            self.export_track_combo.setCurrentIndex(max(0, index))
        self.export_track_combo.blockSignals(False)

    def _subtitle_tree_clicked(self, item: QTreeWidgetItem) -> None:
        asset = self.project.active_asset
        if not asset:
            return
        track_id = item.data(0, Qt.ItemDataRole.UserRole)
        track = next(track for track in asset.subtitle_tracks if track.id == track_id)
        track.visible = item.checkState(0) == Qt.CheckState.Checked
        self.timeline._resize_for_content()
        self.timeline.update()
        self._update_preview_subtitle(self.player_widget.position)
        self._mark_dirty()

    def _cue_selected(
        self,
        track_id: str,
        cue_id: str,
        additive: bool = False,
        selected: bool = True,
    ) -> None:
        asset = self.project.active_asset
        if not asset:
            return
        track = next(track for track in asset.subtitle_tracks if track.id == track_id)
        cue = next(cue for cue in track.cues if cue.id == cue_id)
        self.selected_cue = (track_id, cue_id) if selected else None
        self._show_cue_in_editor(cue)
        matching = next(
            (
                region
                for region in asset.regions
                if region.start_ms == cue.start_ms and region.end_ms == cue.end_ms
            ),
            None,
        )
        if matching is None:
            matching = ExportRegion(cue.start_ms, cue.end_ms, cue.text)
            asset.regions.append(matching)
            self._mark_dirty()
        self._apply_region_selection(matching.id, additive, selected)
        self._seek(cue.start_ms)
        self.timeline.update()
        self._update_preview_subtitle(cue.start_ms)
        self._update_selection_status()

    def _show_cue_in_editor(self, cue: SubtitleCue | None) -> None:
        self.cue_start.blockSignals(True)
        self.cue_end.blockSignals(True)
        self.cue_text.blockSignals(True)
        if cue is None:
            self.cue_text.clear()
            self.cue_text.setPlaceholderText("当前字幕轨在选区内没有字幕")
        else:
            self.cue_start.setValue(cue.start_ms)
            self.cue_end.setValue(cue.end_ms)
            self.cue_text.setPlainText(cue.text)
            self.cue_text.setPlaceholderText("选择字幕后可编辑文本")
        self.cue_start.blockSignals(False)
        self.cue_end.blockSignals(False)
        self.cue_text.blockSignals(False)

    def _region_selected(
        self,
        region_id: str,
        additive: bool = False,
        selected: bool = True,
    ) -> None:
        self._apply_region_selection(region_id, additive, selected)
        self._update_selection_status()

    def _generated_clip_selected(
        self,
        clip_id: str,
        additive: bool = False,
        selected: bool = True,
    ) -> None:
        if additive:
            if selected:
                self.selected_generated_clip_ids.add(clip_id)
            else:
                self.selected_generated_clip_ids.discard(clip_id)
        else:
            self.selected_generated_clip_ids = {clip_id} if selected else set()
            self.selected_region_ids.clear()
            self.selected_region_id = None
        self._update_selection_status()

    def _apply_region_selection(
        self,
        region_id: str,
        additive: bool,
        selected: bool,
    ) -> None:
        if additive:
            if selected:
                self.selected_region_ids.add(region_id)
            else:
                self.selected_region_ids.discard(region_id)
        else:
            self.selected_region_ids = {region_id} if selected else set()
        self.selected_region_id = (
            region_id
            if selected
            else next(iter(self.selected_region_ids), None)
        )
        self.timeline.selected_region_ids = set(self.selected_region_ids)
        self.timeline.selected_region_id = self.selected_region_id
        self.timeline.update()

    def _current_cue(self):
        asset = self.project.active_asset
        if not asset or not self.selected_cue:
            return None
        track_id, cue_id = self.selected_cue
        track = next((track for track in asset.subtitle_tracks if track.id == track_id), None)
        return next((cue for cue in track.cues if cue.id == cue_id), None) if track else None

    def _apply_cue_editor(self) -> None:
        cue = self._current_cue()
        if not cue:
            return
        before = (cue.start_ms, cue.end_ms)
        after_start = min(self.cue_start.value(), self.cue_end.value() - 1)
        after = (after_start, max(after_start + 1, self.cue_end.value()))
        if before != after:
            self.undo_stack.push(
                TimeRangeCommand(cue, before, after, self._refresh_current_editor)
            )
            self._mark_dirty()

    def _apply_cue_text(self) -> None:
        cue = self._current_cue()
        new_text = self.cue_text.toPlainText().strip()
        if cue and cue.text != new_text:
            self.undo_stack.push(
                TextCommand(cue, cue.text, new_text, self._refresh_current_editor)
            )
            self._mark_dirty()

    def _refresh_current_editor(self) -> None:
        cue = self._current_cue()
        if cue:
            self.cue_text.blockSignals(True)
            self.cue_start.blockSignals(True)
            self.cue_end.blockSignals(True)
            self.cue_text.setPlainText(cue.text)
            self.cue_start.setValue(cue.start_ms)
            self.cue_end.setValue(cue.end_ms)
            self.cue_text.blockSignals(False)
            self.cue_start.blockSignals(False)
            self.cue_end.blockSignals(False)
        self.timeline.update()
        self._update_preview_subtitle(self.player_widget.position)

    def _timeline_item_changed(self, payload: object) -> None:
        item, before, after = payload
        self.undo_stack.push(
            TimeRangeCommand(item, before, after, self._refresh_current_editor)
        )
        self._mark_dirty()
        self._update_selection_status()

    def _timeline_generated_clip_changed(self, payload: object) -> None:
        clip, before, after = payload
        self.undo_stack.push(
            GeneratedClipEditCommand(
                clip,
                before,
                after,
                self._refresh_generated_track,
            )
        )
        self._mark_dirty()

    def _refresh_generated_track(self) -> None:
        asset = self.project.active_asset
        if not asset:
            return
        self.selected_generated_clip_ids.intersection_update(
            clip.id for clip in asset.generated_track.clips
        )
        self.timeline.set_asset(asset, self.waveforms.get(asset.id, []))
        self.timeline.selected_region_ids = set(self.selected_region_ids)
        self.timeline.selected_region_id = self.selected_region_id
        self.timeline.selected_generated_clip_ids = set(
            self.selected_generated_clip_ids
        )
        self.timeline.selected_generated_clip_id = next(
            iter(self.selected_generated_clip_ids),
            None,
        )
        for clip in asset.generated_track.clips:
            peaks = self.generated_waveforms.get(clip.id)
            if peaks:
                self.timeline.set_generated_waveform(clip.id, peaks)
            elif Path(clip.path).is_file():
                self._schedule_generated_waveform(clip)
        self.position_slider.setRange(0, self.timeline._timeline_duration())
        self._schedule_ai_monitor()
        self._apply_track_monitor()
        self._update_selection_status()

    def _export_track_changed(self) -> None:
        asset = self.project.active_asset
        if asset:
            track_id = self.export_track_combo.currentData()
            asset.export_track_id = track_id
            region = self._current_region() if self.selected_region_id else None
            track = next(
                (item for item in asset.subtitle_tracks if item.id == track_id),
                None,
            )
            cue = (
                track.cue_for_region(region.start_ms, region.end_ms)
                if track and region
                else None
            )
            self.selected_cue = (track.id, cue.id) if track and cue else None
            self.timeline.selected_cue_ids = {cue.id} if cue else set()
            self.timeline.selected_cue_id = cue.id if cue else None
            self._show_cue_in_editor(cue)
            self.timeline.update()
            self._mark_dirty()

    def _load_gain(self) -> None:
        asset = self.project.active_asset
        if not asset:
            return
        self.gain_spin.blockSignals(True)
        self.gain_slider.blockSignals(True)
        self.gain_bypass.blockSignals(True)
        self.gain_spin.setValue(asset.gain_db)
        self.gain_slider.setValue(round(asset.gain_db * 10))
        self.gain_bypass.setChecked(asset.gain_bypassed)
        self.gain_spin.blockSignals(False)
        self.gain_slider.blockSignals(False)
        self.gain_bypass.blockSignals(False)
        self._update_clip_warning(asset.gain_db)

    def _gain_slider_changed(self, value: int) -> None:
        self.gain_spin.setValue(value / 10)

    def _gain_spin_changed(self, value: float) -> None:
        self.gain_slider.blockSignals(True)
        self.gain_slider.setValue(round(value * 10))
        self.gain_slider.blockSignals(False)
        asset = self.project.active_asset
        if asset:
            asset.gain_db = value
            self.player_widget.set_gain(value, asset.gain_bypassed)
            self._update_clip_warning(value)
            self.timeline.update()
            self._mark_dirty()

    def _gain_bypass_changed(self, checked: bool) -> None:
        asset = self.project.active_asset
        if asset:
            asset.gain_bypassed = checked
            self.player_widget.set_gain(asset.gain_db, checked)
            self.timeline.update()
            self._mark_dirty()

    def _update_clip_warning(self, gain: float) -> None:
        self.clip_warning.setText("⚠ 可能削波" if gain > 0 else "")

    def _preset_changed(self) -> None:
        preset = self.project.active_preset
        preset.container = self.format_combo.currentText()
        preset.sample_rate = self.sample_rate_combo.currentData()
        preset.channels = self.channel_combo.currentData()
        preset.codec = self.codec_combo.currentText()
        preset.write_txt = self.txt_checkbox.isChecked()
        preset.peak_normalize = self.normalize_checkbox.isChecked()
        preset.output_dir = self.output_edit.toPlainText().strip()
        preset.naming_template = self.naming_edit.toPlainText().strip() or "{source}_{index:04d}"
        preset.regex_pattern = self.regex_pattern.text()
        preset.regex_replacement = self.regex_replacement.text()
        preset.fade_in_ms = self.fade_in_spin.value()
        preset.fade_out_ms = self.fade_out_spin.value()
        self._mark_dirty()

    def _load_preset(self) -> None:
        preset = self.project.active_preset
        controls = [
            self.format_combo,
            self.sample_rate_combo,
            self.channel_combo,
            self.codec_combo,
            self.txt_checkbox,
            self.normalize_checkbox,
            self.output_edit,
            self.naming_edit,
            self.regex_pattern,
            self.regex_replacement,
            self.fade_in_spin,
            self.fade_out_spin,
        ]
        for control in controls:
            control.blockSignals(True)
        self.format_combo.setCurrentText(preset.container)
        sample_index = self.sample_rate_combo.findData(preset.sample_rate)
        self.sample_rate_combo.setCurrentIndex(max(0, sample_index))
        channel_index = self.channel_combo.findData(preset.channels)
        self.channel_combo.setCurrentIndex(max(0, channel_index))
        self.codec_combo.setCurrentText(preset.codec)
        self.txt_checkbox.setChecked(preset.write_txt)
        self.normalize_checkbox.setChecked(preset.peak_normalize)
        self.output_edit.setPlainText(preset.output_dir)
        self.naming_edit.setPlainText(preset.naming_template)
        self.regex_pattern.setText(preset.regex_pattern)
        self.regex_replacement.setText(preset.regex_replacement)
        self.fade_in_spin.setValue(preset.fade_in_ms)
        self.fade_out_spin.setValue(preset.fade_out_ms)
        for control in controls:
            control.blockSignals(False)

    def _on_position_changed(self, position: int) -> None:
        if self._scrubbing_playhead:
            return
        if self._awaiting_scrub_ms is not None:
            if abs(position - self._awaiting_scrub_ms) > 100:
                return
            self._awaiting_scrub_ms = None
        self._display_position(position)

    def _display_position(self, position: int) -> None:
        self.timecode_label.setText(_timecode(position))
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(position)
        self.position_slider.blockSignals(False)
        self.timeline.set_playhead(position)
        if self.app_settings.follow_playhead:
            self.timeline_scroll.ensure_playhead_visible()
        asset = self.project.active_asset
        self.audio_preview.set_position(position, asset.duration_ms if asset else 0)
        self._update_preview_subtitle(position)

    def _update_preview_subtitle(self, position: int) -> None:
        asset = self.project.active_asset
        if not asset or not asset.has_video:
            self.player_widget.set_subtitle_text("")
            return
        visible_lines: list[str] = []
        for track in asset.subtitle_tracks:
            if not track.visible:
                continue
            for cue in track.cues:
                if cue.start_ms <= position < cue.end_ms:
                    text = "\n".join(
                        " ".join(line.split())
                        for line in cue.text.splitlines()
                        if line.strip()
                    )
                    if text and text not in visible_lines:
                        visible_lines.append(text)
        self.player_widget.set_subtitle_text("\n".join(visible_lines))

    def _set_preview_mode(self, mode: str) -> None:
        asset = self.project.active_asset
        if mode == "video" and (not asset or not asset.has_video):
            mode = "waveform"
        self.video_preview_button.blockSignals(True)
        self.waveform_preview_button.blockSignals(True)
        self.video_preview_button.setChecked(mode == "video")
        self.waveform_preview_button.setChecked(mode == "waveform")
        self.video_preview_button.blockSignals(False)
        self.waveform_preview_button.blockSignals(False)
        self.player_widget.set_preview_mode(mode)

    def _toggle_playback(self) -> None:
        if self.project.active_asset:
            self.player_widget.toggle()

    def _previous_frame(self) -> None:
        asset = self.project.active_asset
        if not asset or not asset.has_video or not self.player_widget.previous_frame():
            self.status_message.setText("FRAME STEP · 仅 mpv 视频预览支持逐帧")

    def _next_frame(self) -> None:
        asset = self.project.active_asset
        if not asset or not asset.has_video or not self.player_widget.next_frame():
            self.status_message.setText("FRAME STEP · 仅 mpv 视频预览支持逐帧")

    def _save_still(self) -> None:
        asset = self.project.active_asset
        if not asset or not asset.has_video:
            self._show_error("当前素材没有可保存的视频画面。")
            return
        folder = (
            Path(self.app_settings.still_output_dir)
            if self.app_settings.still_output_mode == "custom"
            and self.app_settings.still_output_dir
            else Path(asset.path).parent
        )
        task = StillTask(asset, self.timeline.playhead_ms, folder, self.app_settings)
        task.signals.finished.connect(self._still_saved)
        task.signals.failed.connect(self._show_error)
        self.thread_pool.start(task)
        self.status_message.setText("STILL · 正在保存原视频静帧")

    def _still_saved(self, path: Path) -> None:
        self.status_message.setText(f"STILL SAVED · {path.name}")
        if self.app_settings.open_after_export:
            os.startfile(path.parent)  # noqa: S606

    def _show_advanced_settings(self) -> None:
        dialog = AdvancedSettingsDialog(
            self.settings,
            self,
            {"asr": self.asr.state, "tts": self.index_tts.state},
        )
        dialog.settings_applied.connect(self._advanced_settings_applied)
        dialog.unload_asr_requested.connect(self.asr.unload_model)
        dialog.unload_tts_requested.connect(self.index_tts.unload_model)
        dialog.exec()

    def _advanced_settings_applied(self, settings: AppSettings) -> None:
        self.app_settings = settings
        self.player_widget.set_scrub_hz(settings.scrub_hz)
        QApplication.instance().setStyleSheet(build_stylesheet(settings.theme))
        self._apply_export_settings_to_preset()
        self._load_preset()
        if self.project.assets:
            self._mark_dirty()
        if self.asr.state == "loaded" or self.index_tts.state == "loaded":
            self.status_message.setText("SETTINGS · 模型参数将在下次加载时生效")

    def _apply_export_settings_to_preset(self) -> None:
        preset = self.project.active_preset
        settings = self.app_settings
        preset.container = settings.export_container
        preset.sample_rate = settings.export_sample_rate or None
        preset.channels = settings.export_channels or None
        preset.codec = settings.export_codec
        preset.write_txt = settings.export_write_txt
        preset.peak_normalize = settings.export_peak_normalize
        preset.fade_in_ms = settings.export_fade_in_ms
        preset.fade_out_ms = settings.export_fade_out_ms
        preset.naming_template = (
            settings.audio_naming_template or "{source}_{index:04d}_{start}"
        )
        preset.regex_pattern = settings.export_regex_pattern
        preset.regex_replacement = settings.export_regex_replacement

    def _seek(self, milliseconds: int) -> None:
        milliseconds = self._clamp_position(milliseconds)
        self._display_position(milliseconds)
        self.player_widget.seek(milliseconds)

    def _clamp_position(self, milliseconds: int) -> int:
        asset = self.project.active_asset
        if not asset:
            return max(0, milliseconds)
        return max(0, min(self.timeline._timeline_duration(), milliseconds))

    def _scrub(self, milliseconds: int) -> None:
        milliseconds = self._clamp_position(milliseconds)
        self._scrubbing_playhead = True
        self._awaiting_scrub_ms = None
        self._display_position(milliseconds)
        self.player_widget.scrub(milliseconds)

    def _finish_scrub(self, milliseconds: int) -> None:
        milliseconds = self._clamp_position(milliseconds)
        self._display_position(milliseconds)
        self._scrubbing_playhead = False
        self._awaiting_scrub_ms = milliseconds
        self.player_widget.finish_scrub(milliseconds)
        QTimer.singleShot(800, lambda: self._release_scrub_guard(milliseconds))

    def _release_scrub_guard(self, expected_ms: int) -> None:
        if self._awaiting_scrub_ms == expected_ms:
            self._awaiting_scrub_ms = None

    def _seek_relative(self, delta: int) -> None:
        self._seek(self.player_widget.position + delta)

    def _zoom_timeline(self, delta: int) -> None:
        self.timeline.zoom_by_wheel_delta(
            delta,
            self.timeline_scroll.viewport().width(),
        )
        QTimer.singleShot(0, self.timeline_scroll.center_on_playhead)

    def _fit_timeline(self) -> None:
        self.timeline_scroll.fit_timeline()

    def _set_in_point(self) -> None:
        if not self.project.active_asset:
            return
        self.in_point_ms = self.player_widget.position
        self.timeline.set_in_point(self.in_point_ms)
        self.status_message.setText(f"IN · {_timecode(self.in_point_ms)}")

    def _selection_tool(self) -> None:
        self.timeline.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.status_message.setText(
            "SELECT · 点击单选；Ctrl+点击多选；拖动边缘接近播放头时自动吸附"
        )

    def _set_out_point(self) -> None:
        asset = self.project.active_asset
        if not asset:
            return
        end = self.player_widget.position
        start = self.in_point_ms if self.in_point_ms is not None else max(0, end - 5000)
        if end <= start:
            self._show_error("出点必须晚于入点。")
            return
        region = ExportRegion(start, end)
        self.undo_stack.push(
            RegionListCommand(asset.regions, region, True, self.timeline.update)
        )
        self._apply_region_selection(region.id, False, True)
        self._mark_dirty()
        self.status_message.setText(f"REGION · {_timecode(start)} → {_timecode(end)}")
        self._update_selection_status()

    def _current_region(self) -> ExportRegion | None:
        asset = self.project.active_asset
        if not asset:
            return None
        if self.selected_region_id:
            for region in asset.regions:
                if region.id == self.selected_region_id:
                    return region
        return asset.regions[-1] if asset.regions else None

    def _play_selection(self) -> None:
        region = self._current_region()
        if region:
            self.player_widget.play_range(region.start_ms, region.end_ms)

    def _delete_region(self) -> None:
        asset = self.project.active_asset
        if not asset:
            return
        if self.selected_generated_clip_ids:
            self._delete_generated_clips()
            return
        target_ids = set(self.selected_region_ids)
        if not target_ids and self.selected_region_id:
            target_ids.add(self.selected_region_id)
        targets = [region for region in asset.regions if region.id in target_ids]
        if not targets:
            return
        self.undo_stack.beginMacro(f"删除 {len(targets)} 个导出区间")
        for region in targets:
            self.undo_stack.push(
                RegionListCommand(asset.regions, region, False, self.timeline.update)
            )
        self.undo_stack.endMacro()
        self.selected_region_ids.clear()
        self.selected_region_id = None
        self.timeline.selected_region_ids.clear()
        self.timeline.selected_region_id = None
        self.timeline.selected_cue_ids.clear()
        self.timeline.selected_cue_id = None
        self.timeline.update()
        self._mark_dirty()
        self._update_selection_status()

    def _delete_generated_clips(self) -> None:
        asset = self.project.active_asset
        if not asset:
            return
        track = asset.generated_track
        before = copy.deepcopy(track.clips)
        after = [
            clip
            for clip in before
            if clip.id not in self.selected_generated_clip_ids
        ]
        if len(after) == len(before):
            return
        self.undo_stack.push(
            GeneratedClipsCommand(
                track,
                before,
                after,
                self._refresh_generated_track,
                f"删除 {len(before) - len(after)} 个 AI 音频片段",
            )
        )
        self.selected_generated_clip_ids.clear()
        self._mark_dirty()

    def _update_selection_status(self) -> None:
        if not hasattr(self, "selection_status"):
            return
        self._update_asr_buttons()
        self._update_tts_buttons()
        if self.selected_generated_clip_ids and self.project.active_asset:
            clips = [
                clip
                for clip in self.project.active_asset.generated_track.clips
                if clip.id in self.selected_generated_clip_ids
            ]
            if clips:
                total_ms = sum(clip.duration_ms for clip in clips)
                self.selection_status.setText(
                    f"已选 {len(clips)} 个 AI 片段 · 总时长 {total_ms / 1000:.3f}s"
                )
                self.workspace_state.set_selection(
                    "generated",
                    f"{len(clips)} 个 AI 语音片段 · {total_ms / 1000:.2f} 秒",
                )
                return
        region = self._current_region()
        if not region or not self.selected_region_id:
            self.selection_status.setText("点击字幕，或按 I / O 选择一段声音")
            self.workspace_state.set_selection("none")
            return
        if len(self.selected_region_ids) > 1:
            total_ms = sum(
                item.end_ms - item.start_ms
                for item in self.project.active_asset.regions
                if item.id in self.selected_region_ids
            )
            self.selection_status.setText(
                f"已选 {len(self.selected_region_ids)} 个片段"
                f"  ·  总时长 {total_ms / 1000:.3f}s"
            )
            self.workspace_state.set_selection(
                "region",
                f"{len(self.selected_region_ids)} 个片段 · {total_ms / 1000:.2f} 秒",
            )
            return
        duration = (region.end_ms - region.start_ms) / 1000
        self.selection_status.setText(
            f"已选片段  {_timecode(region.start_ms)} → {_timecode(region.end_ms)}"
            f"  ·  {duration:.3f}s"
        )
        self.workspace_state.set_selection(
            "cue" if self.selected_cue else "region",
            f"{_timecode(region.start_ms)} → {_timecode(region.end_ms)} · {duration:.2f} 秒",
        )

    def _show_shortcuts(self) -> None:
        QMessageBox.information(
            self,
            "时间线快捷键",
            "V       选择片段\n"
            "I / O   设置入点 / 出点\n"
            "Enter   播放当前片段\n"
            "Space   播放 / 暂停\n"
            "X       删除当前片段\n"
            "E       快速导出\n"
            "G       使用 IndexTTS2 生成语音\n"
            "D / F   上一帧 / 下一帧\n"
            "C       保存原视频静帧\n"
            "Alt+滚轮  缩放时间线（可缩至完整素材）\n"
            "\n点击字幕块会自动建立并单选对应导出片段；\n"
            "Ctrl+点击追加或取消多选，拖动边缘会吸附播放头；\n"
            "按 I 后时间轴会显示青色 IN 标记线；\n"
            "向下拖动波形轨底边，展开后显示 dBFS 标尺与参考线；\n"
            "监看区可在“视频 / 波形”之间切换；\n"
            "增益会实时改变时间线波形，红色部分表示预计削波。",
        )

    def _toggle_asr_model(self) -> None:
        if self._asr_busy:
            return
        if self.asr.state == "loaded":
            self.asr.unload_model()
        elif self.asr.state in {"unloaded", "error"}:
            self.asr.load_model(self.app_settings)

    def _asr_state_changed(self, state: str) -> None:
        if state == "loading":
            self.asr_load_button.setText("加载中…")
            self.asr_load_button.setEnabled(False)
            self.asr_load_button.setObjectName("asrLoading")
        elif state == "loaded":
            self.asr_load_button.setText("卸载 ASR 模型")
            self.asr_load_button.setEnabled(not self._asr_busy)
            self.asr_load_button.setObjectName("danger")
        elif state == "unloading":
            self.asr_load_button.setText("卸载中…")
            self.asr_load_button.setEnabled(False)
            self.asr_load_button.setObjectName("asrLoading")
        else:
            self.asr_load_button.setText("加载 ASR 模型")
            self.asr_load_button.setEnabled(True)
            self.asr_load_button.setObjectName("")
        self.asr_load_button.style().unpolish(self.asr_load_button)
        self.asr_load_button.style().polish(self.asr_load_button)
        self._update_asr_buttons()

    def _asr_loaded(self, runtime: dict) -> None:
        gpu = runtime.get("gpu") or runtime.get("device") or "ready"
        self.status_message.setText(f"ASR LOADED · {gpu}")
        if self._asr_pending_start:
            self._asr_pending_start = False
            self._start_asr_batch()

    def _asr_unloaded(self) -> None:
        self.status_message.setText("ASR UNLOADED · 模型已释放")

    def _update_asr_buttons(self) -> None:
        if not hasattr(self, "asr_transcribe_button"):
            return
        has_selection = bool(self.selected_region_ids and self.project.active_asset)
        if self._asr_cancel_requested:
            self.asr_transcribe_button.setText("取消中…")
            self.asr_transcribe_button.setEnabled(False)
        else:
            self.asr_transcribe_button.setEnabled(
                self._asr_busy
                or (has_selection and self.asr.state not in {"loading", "unloading"})
            )
            self.asr_transcribe_button.setText(
                "取消识别" if self._asr_busy else "识别字幕"
            )
        if hasattr(self, "asr_load_button") and self.asr.state == "loaded":
            self.asr_load_button.setEnabled(not self._asr_busy)

    def _toggle_asr_transcription(self) -> None:
        if self._asr_busy:
            self._cancel_asr_batch()
        elif self.asr.state == "loaded":
            self._start_asr_batch()
        else:
            if not self.selected_region_ids:
                self._show_error("请先选择一个或多个片段。")
                return
            self._asr_pending_start = True
            self.task_notice.start("正在加载语音识别模型…", cancellable=False)
            self.asr.load_model(self.app_settings)

    def _start_asr_batch(self) -> None:
        asset = self.project.active_asset
        if not asset or self.asr.state != "loaded":
            return
        regions = sorted(
            (
                copy.deepcopy(region)
                for region in asset.regions
                if region.id in self.selected_region_ids
            ),
            key=lambda region: (region.start_ms, region.end_ms),
        )
        if not regions:
            self._show_error("请先选择一个或多个导出区间。")
            return
        base = (
            Path(self.app_settings.moss_temp_dir)
            if self.app_settings.moss_temp_dir
            else None
        )
        if base:
            base.mkdir(parents=True, exist_ok=True)
        self._asr_temp_folder = Path(
            tempfile.mkdtemp(prefix="tts-studio-asr-", dir=str(base) if base else None)
        )
        self._asr_busy = True
        self._asr_cancel_requested = False
        self._asr_asset_id = asset.id
        self._asr_results = []
        self._asr_queue = []
        self._asr_extracting = True
        self._update_asr_buttons()
        self.task_notice.start("正在准备语音识别…")
        task = AsrExtractTask(asset, regions, self._asr_temp_folder)
        task.signals.finished.connect(self._asr_audio_ready)
        task.signals.failed.connect(self._asr_failed)
        self.thread_pool.start(task)
        self.status_message.setText("ASR · 正在提取选中片段")

    def _asr_audio_ready(self, items: list[tuple[ExportRegion, Path]]) -> None:
        self._asr_extracting = False
        if not self._asr_busy:
            return
        if self._asr_cancel_requested:
            self._finish_asr_batch()
            self.status_message.setText("ASR CANCELLED · 模型保持加载")
            return
        self._asr_queue = list(items)
        self._start_next_asr()

    def _start_next_asr(self) -> None:
        if not self._asr_busy:
            return
        if not self._asr_queue:
            self._apply_asr_results()
            return
        self._asr_current = self._asr_queue.pop(0)
        completed = len(self._asr_results) + 1
        total = completed + len(self._asr_queue)
        self.task_notice.message.setText(f"正在识别字幕 {completed}/{total}")
        self.task_notice.set_progress(round((completed - 1) / total * 100))
        self.status_message.setText(f"ASR · 正在识别 {completed}/{total}")
        self.asr.transcribe(self._asr_current[1], self.app_settings)

    def _asr_transcription_ready(self, message: dict) -> None:
        if not self._asr_busy or not self._asr_current:
            return
        if self._asr_cancel_requested:
            self._asr_current = None
            self._finish_asr_batch()
            self.status_message.setText("ASR CANCELLED · 模型保持加载")
            return
        self._asr_results.append(
            (self._asr_current[0], list(message.get("segments", [])))
        )
        self._asr_current = None
        self._start_next_asr()

    def _apply_asr_results(self) -> None:
        asset = next(
            (item for item in self.project.assets if item.id == self._asr_asset_id),
            None,
        )
        if not asset:
            self._finish_asr_batch()
            return
        before = copy.deepcopy(asset.subtitle_tracks)
        after = copy.deepcopy(asset.subtitle_tracks)
        track = next(
            (item for item in after if item.name == self.app_settings.moss_track_name),
            None,
        )
        if track is None:
            track = SubtitleTrack(self.app_settings.moss_track_name)
            after.append(track)
        regions = [region for region, _segments in self._asr_results]
        track.cues = [
            cue
            for cue in track.cues
            if not any(
                max(0, min(cue.end_ms, region.end_ms) - max(cue.start_ms, region.start_ms))
                for region in regions
            )
        ]
        for region, segments in self._asr_results:
            for segment in segments:
                start = region.start_ms + round(float(segment.get("start", 0)) * 1000)
                end = region.start_ms + round(float(segment.get("end", 0)) * 1000)
                start = max(region.start_ms, min(region.end_ms - 1, start))
                end = max(start + 1, min(region.end_ms, end))
                text = str(segment.get("text") or "").strip()
                if text:
                    track.cues.append(
                        SubtitleCue(
                            start,
                            end,
                            text,
                            speaker=str(segment.get("speaker") or ""),
                            origin="moss-asr",
                        )
                    )
        track.cues.sort(key=lambda cue: (cue.start_ms, cue.end_ms))
        self.undo_stack.push(
            SubtitleTracksCommand(asset, before, after, self._refresh_after_asr)
        )
        self._mark_dirty()
        self.status_message.setText(
            f"ASR COMPLETE · 已生成 {sum(len(items) for _, items in self._asr_results)} 条字幕"
        )
        cue_count = sum(len(items) for _, items in self._asr_results)
        self.task_notice.finish(f"字幕识别完成 · 新增 {cue_count} 条")
        QTimer.singleShot(5000, self.task_notice.clear)
        self._finish_asr_batch()

    def _refresh_after_asr(self) -> None:
        asset = self.project.active_asset
        if not asset:
            return
        self._refresh_subtitles()
        self._refresh_export_tracks()
        self.timeline.set_asset(asset, self.waveforms.get(asset.id, []))
        self.timeline.update()

    def _cancel_asr_batch(self) -> None:
        self._asr_cancel_requested = True
        self._asr_queue.clear()
        self._asr_results.clear()
        if self._asr_extracting:
            self._update_asr_buttons()
            self.status_message.setText("ASR · 正在取消临时音频提取")
            return
        if self._asr_current is None:
            self._finish_asr_batch()
            self.status_message.setText("ASR CANCELLED · 模型保持加载")
            return
        self._update_asr_buttons()
        self.status_message.setText("ASR · 正在取消，当前推理结束后模型保持加载")

    def _finish_asr_batch(self) -> None:
        self._asr_busy = False
        self._asr_cancel_requested = False
        self._asr_extracting = False
        self._asr_queue.clear()
        self._asr_current = None
        self._cleanup_asr_temp()
        self._update_asr_buttons()

    def _cleanup_asr_temp(self) -> None:
        if self._asr_temp_folder:
            shutil.rmtree(self._asr_temp_folder, ignore_errors=True)
            self._asr_temp_folder = None

    def _asr_failed(self, message: str) -> None:
        LOGGER.error("ASR failed: %s", message)
        was_busy = self._asr_busy
        cancelled = self._asr_cancel_requested
        self._asr_pending_start = False
        self._asr_busy = False
        self._asr_cancel_requested = False
        self._asr_extracting = False
        self._asr_queue.clear()
        self._asr_results.clear()
        self._asr_current = None
        self._cleanup_asr_temp()
        self._update_asr_buttons()
        self.task_notice.clear()
        if not cancelled and (was_busy or self.asr.state in {"error", "unloaded"}):
            self._show_error(message)

    def _toggle_tts_model(self) -> None:
        if self._tts_busy:
            return
        if self.index_tts.state == "loaded":
            self.index_tts.unload_model()
        elif self.index_tts.state in {"unloaded", "error"}:
            self.index_tts.load_model(self.app_settings)

    def _tts_state_changed(self, state: str) -> None:
        if state == "loading":
            self.tts_load_button.setText("加载中…")
            self.tts_load_button.setEnabled(False)
            self.tts_load_button.setObjectName("asrLoading")
        elif state == "loaded":
            self.tts_load_button.setText("卸载语音引擎")
            self.tts_load_button.setEnabled(not self._tts_busy)
            self.tts_load_button.setObjectName("danger")
        elif state == "unloading":
            self.tts_load_button.setText("卸载中…")
            self.tts_load_button.setEnabled(False)
            self.tts_load_button.setObjectName("asrLoading")
        else:
            self.tts_load_button.setText("加载语音引擎")
            self.tts_load_button.setEnabled(True)
            self.tts_load_button.setObjectName("")
        self.tts_load_button.style().unpolish(self.tts_load_button)
        self.tts_load_button.style().polish(self.tts_load_button)
        self._update_tts_buttons()

    def _tts_loaded(self, runtime: dict) -> None:
        gpu = runtime.get("gpu") or runtime.get("device") or "ready"
        self.status_message.setText(f"INDEXTTS2 LOADED · {gpu}")
        if self._tts_pending_start:
            self._tts_pending_start = False
            self._start_tts_batch()

    def _tts_unloaded(self) -> None:
        self.status_message.setText("INDEXTTS2 UNLOADED · 模型已释放")

    def _update_tts_buttons(self) -> None:
        if not hasattr(self, "tts_generate_button"):
            return
        has_selection = bool(self.selected_region_ids and self.project.active_asset)
        if self._tts_cancel_requested:
            self.tts_generate_button.setText("取消中…")
            self.tts_generate_button.setEnabled(False)
        else:
            self.tts_generate_button.setText(
                "取消生成" if self._tts_busy else "生成语音"
            )
            self.tts_generate_button.setEnabled(
                self._tts_busy
                or (
                    has_selection
                    and self.index_tts.state not in {"loading", "unloading"}
                )
            )
        if self.index_tts.state == "loaded":
            self.tts_load_button.setEnabled(not self._tts_busy)

    def _toggle_tts_generation(self) -> None:
        if self._tts_busy:
            self._cancel_tts_batch()
        elif self.index_tts.state == "loaded":
            self._start_tts_batch()
        else:
            if not self.selected_region_ids:
                self._show_error("请先选择一个或多个片段。")
                return
            self._tts_pending_start = True
            self.task_notice.start("正在加载语音生成引擎…", cancellable=False)
            self.index_tts.load_model(self.app_settings)

    def _start_tts_batch(self) -> None:
        asset = self.project.active_asset
        if not asset or self.index_tts.state != "loaded":
            return
        regions = sorted(
            (
                copy.deepcopy(region)
                for region in asset.regions
                if region.id in self.selected_region_ids
            ),
            key=lambda region: (region.start_ms, region.end_ms),
        )
        if not regions:
            self._show_error("请先选择一个或多个导出区间。")
            return
        track = asset.export_track
        if not track:
            self._show_error("请先指定包含生成文本的导出字幕轨。")
            return
        items: list[TtsBatchItem] = []
        for region in regions:
            duration = region.end_ms - region.start_ms
            if duration < 500:
                self._show_error(
                    f"{_timecode(region.start_ms)} 的参考区间少于 0.5 秒。"
                )
                return
            cue = track.cue_for_region(region.start_ms, region.end_ms)
            if not cue or not cue.text.strip():
                self._show_error(
                    f"{_timecode(region.start_ms)} 的区间没有可用字幕。"
                )
                return
            items.append(TtsBatchItem(region, cue.text.strip()))
        base = (
            Path(self.app_settings.index_tts_temp_dir)
            if self.app_settings.index_tts_temp_dir
            else None
        )
        if base:
            base.mkdir(parents=True, exist_ok=True)
        self._tts_temp_folder = Path(
            tempfile.mkdtemp(
                prefix="tts-studio-index-",
                dir=str(base) if base else None,
            )
        )
        self._tts_busy = True
        self._tts_cancel_requested = False
        self._tts_extracting = False
        self._tts_asset_id = asset.id
        self._tts_analysis_queue = items
        self._tts_analysis_results = []
        self._tts_queue = []
        self._update_tts_buttons()
        self.task_notice.start("正在分析生成文本…")
        self._start_next_tts_analysis()

    def _start_next_tts_analysis(self) -> None:
        if not self._tts_busy:
            return
        if self._tts_cancel_requested:
            self._finish_tts_batch()
            self.status_message.setText(
                "INDEXTTS2 CANCELLED · 模型保持加载"
            )
            return
        if not self._tts_analysis_queue:
            self._finish_tts_analysis()
            return
        self._tts_analysis_current = self._tts_analysis_queue.pop(0)
        complete = len(self._tts_analysis_results) + 1
        total = complete + len(self._tts_analysis_queue)
        self.task_notice.message.setText(f"正在分析文本 {complete}/{total}")
        self.task_notice.set_progress(round((complete - 1) / total * 20))
        self.status_message.setText(
            f"INDEXTTS2 · 正在检查文本 {complete}/{total}"
        )
        self.index_tts.analyze_text(self._tts_analysis_current.text)

    def _tts_text_analyzed(self, message: dict) -> None:
        if not self._tts_busy or not self._tts_analysis_current:
            return
        self._tts_analysis_results.append(
            {"item": self._tts_analysis_current, **message}
        )
        self._tts_analysis_current = None
        self._start_next_tts_analysis()

    def _finish_tts_analysis(self) -> None:
        items = [
            result["item"] for result in self._tts_analysis_results
        ]
        unknown = sum(
            int(result.get("unknown_count", 0))
            for result in self._tts_analysis_results
        )
        short = sum(
            item.region.end_ms - item.region.start_ms < 3000
            for item in items
        )
        long = sum(
            item.region.end_ms - item.region.start_ms > 15_000
            for item in items
        )
        warnings = []
        if unknown:
            warnings.append(
                f"字幕中检测到 {unknown} 个未知 Token，日文等文本可能发音异常。"
            )
        if short:
            warnings.append(f"{short} 个参考片段短于 3 秒，音色稳定性可能较差。")
        if long:
            warnings.append(f"{long} 个参考片段超过 15 秒，只使用前 15 秒。")
        if warnings:
            choice = QMessageBox.question(
                self,
                "IndexTTS2 生成警告",
                "\n".join(warnings) + "\n\n仍然继续生成吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if choice != QMessageBox.StandardButton.Yes:
                self._finish_tts_batch()
                return
        asset = next(
            (
                candidate
                for candidate in self.project.assets
                if candidate.id == self._tts_asset_id
            ),
            None,
        )
        if not asset or not self._tts_temp_folder:
            self._finish_tts_batch()
            return
        self._tts_extracting = True
        task = TtsReferenceTask(asset, items, self._tts_temp_folder)
        task.signals.finished.connect(self._tts_references_ready)
        task.signals.failed.connect(self._tts_failed)
        self.thread_pool.start(task)
        self.status_message.setText("INDEXTTS2 · 正在提取参考音频")

    def _tts_references_ready(self, items: list[TtsBatchItem]) -> None:
        self._tts_extracting = False
        if not self._tts_busy:
            return
        if self._tts_cancel_requested:
            self._finish_tts_batch()
            self.status_message.setText(
                "INDEXTTS2 CANCELLED · 模型保持加载"
            )
            return
        self._tts_queue = list(items)
        self._start_next_tts_generation()

    def _start_next_tts_generation(self) -> None:
        if not self._tts_busy:
            return
        if not self._tts_queue:
            self._finish_tts_batch()
            self.status_message.setText("INDEXTTS2 COMPLETE · 批量生成完成")
            self.task_notice.finish("语音生成完成")
            QTimer.singleShot(5000, self.task_notice.clear)
            return
        self._tts_current = self._tts_queue.pop(0)
        item = self._tts_current
        if not item.reference or not item.output:
            self._tts_failed("IndexTTS2 临时文件状态无效。")
            return
        completed = (
            len(self._tts_analysis_results) - len(self._tts_queue)
        )
        total = len(self._tts_analysis_results)
        self.task_notice.message.setText(f"正在生成语音 {completed}/{total}")
        self.task_notice.set_progress(
            20 + round((completed - 1) / max(1, total) * 75)
        )
        self.status_message.setText(
            f"INDEXTTS2 · 正在生成 {completed}/{total}"
        )
        self.index_tts.generate(
            item.reference,
            item.text,
            item.output,
            self.app_settings,
        )

    def _generated_audio_dir(self) -> Path:
        if self.project.project_path:
            project_path = Path(self.project.project_path)
            return (
                project_path.with_name(project_path.name + ".assets")
                / "generated"
            )
        return (
            Path(user_cache_path("TTS Dataset Studio", "OpenAI"))
            / "generated"
            / self.project.id
        )

    def _tts_generation_params(self) -> dict[str, object]:
        settings = self.app_settings
        return {
            "temperature": settings.index_tts_temperature,
            "top_p": settings.index_tts_top_p,
            "top_k": settings.index_tts_top_k,
            "num_beams": settings.index_tts_num_beams,
            "repetition_penalty": settings.index_tts_repetition_penalty,
            "max_mel_tokens": settings.index_tts_max_mel_tokens,
            "max_text_tokens": settings.index_tts_max_text_tokens,
            "interval_silence": settings.index_tts_interval_silence,
        }

    def _tts_generated(self, message: dict) -> None:
        if not self._tts_busy or not self._tts_current:
            return
        item = self._tts_current
        asset = next(
            (
                candidate
                for candidate in self.project.assets
                if candidate.id == self._tts_asset_id
            ),
            None,
        )
        try:
            if not asset or not item.output:
                raise RuntimeError("生成完成时原素材已不存在。")
            duration_ms = max(1, int(message.get("duration_ms") or 0))
            start_ms = item.region.start_ms
            other_clips = [
                clip
                for clip in asset.generated_track.clips
                if clip.reference_region_id != item.region.id
            ]
            if any(
                start_ms < clip.end_ms
                and clip.start_ms < start_ms + duration_ms
                for clip in other_clips
            ):
                raise RuntimeError(
                    f"{_timecode(start_ms)} 处的生成结果与其他 AI 片段重叠。"
                )
            destination_dir = self._generated_audio_dir()
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / f"{item.clip_id}.wav"
            temporary = destination.with_name(destination.name + ".tmp")
            shutil.copy2(item.output, temporary)
            temporary.replace(destination)
            item.output.unlink(missing_ok=True)
            new_clip = GeneratedAudioClip(
                path=str(destination.resolve()),
                start_ms=start_ms,
                source_offset_ms=0,
                duration_ms=duration_ms,
                source_duration_ms=duration_ms,
                reference_region_id=item.region.id,
                text=item.text,
                generation_params=self._tts_generation_params(),
                id=item.clip_id,
            )
            track = asset.generated_track
            before = copy.deepcopy(track.clips)
            after = [
                clip
                for clip in before
                if clip.reference_region_id != item.region.id
            ]
            after.append(new_clip)
            after.sort(key=lambda clip: (clip.start_ms, clip.id))
            self.undo_stack.push(
                GeneratedClipsCommand(
                    track,
                    before,
                    after,
                    self._refresh_generated_track,
                    "生成 IndexTTS2 音频",
                )
            )
            self._mark_dirty()
            self.selected_generated_clip_ids = {new_clip.id}
            self.timeline.selected_generated_clip_ids = {new_clip.id}
            self.timeline.selected_generated_clip_id = new_clip.id
            self.timeline.update()
        except Exception as exc:  # noqa: BLE001
            self._tts_current = None
            self._tts_failed(str(exc))
            return
        self._tts_current = None
        if self._tts_cancel_requested:
            self._finish_tts_batch()
            self.status_message.setText(
                "INDEXTTS2 CANCELLED · 已保留完成片段，模型保持加载"
            )
        else:
            self._start_next_tts_generation()

    def _cancel_tts_batch(self) -> None:
        self._tts_cancel_requested = True
        self._tts_analysis_queue.clear()
        self._tts_queue.clear()
        self._update_tts_buttons()
        if (
            self._tts_analysis_current is None
            and self._tts_current is None
            and not self._tts_extracting
        ):
            self._finish_tts_batch()
            self.status_message.setText(
                "INDEXTTS2 CANCELLED · 模型保持加载"
            )
        else:
            self.status_message.setText(
                "INDEXTTS2 · 正在取消，当前任务完成后停止"
            )

    def _finish_tts_batch(self) -> None:
        self._tts_busy = False
        self._tts_cancel_requested = False
        self._tts_extracting = False
        self._tts_analysis_queue.clear()
        self._tts_analysis_current = None
        self._tts_analysis_results.clear()
        self._tts_queue.clear()
        self._tts_current = None
        if self._tts_temp_folder:
            shutil.rmtree(self._tts_temp_folder, ignore_errors=True)
            self._tts_temp_folder = None
        self._update_tts_buttons()

    def _tts_failed(self, message: str) -> None:
        LOGGER.error("IndexTTS2 failed: %s", message)
        was_busy = self._tts_busy
        cancelled = self._tts_cancel_requested
        self._tts_pending_start = False
        self._finish_tts_batch()
        self.task_notice.clear()
        if not cancelled and (
            was_busy or self.index_tts.state in {"error", "unloaded"}
        ):
            self._show_error(message)

    def quick_export(self) -> None:
        asset = self.project.active_asset
        region = self._current_region()
        if not asset or not region:
            self._show_error("请先点击字幕或使用 I / O 创建导出区间。")
            return
        if self.export_worker and self.export_worker.isRunning():
            return
        if self.app_settings.confirm_before_export:
            choice = QMessageBox.question(
                self,
                "确认导出",
                f"导出当前片段（{(region.end_ms - region.start_ms) / 1000:.2f} 秒）？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
        self._preset_changed()
        self.export_progress.setValue(0)
        self.cancel_export_button.setEnabled(True)
        index = asset.regions.index(region) + 1
        default_output = (
            self.app_settings.audio_output_dir
            if self.app_settings.audio_output_mode == "custom"
            else ""
        )
        self.export_worker = ExportWorker(
            asset,
            region,
            self.project.active_preset,
            index,
            default_output,
        )
        self.export_worker.progress.connect(self.export_progress.setValue)
        self.export_worker.progress.connect(self.task_notice.set_progress)
        self.export_worker.completed.connect(self._export_completed)
        self.export_worker.failed.connect(self._export_failed)
        self.export_worker.start()
        self.task_notice.start("正在导出音频…")
        self.status_message.setText("正在导出")

    def _export_completed(self, result: ExportResult) -> None:
        self.cancel_export_button.setEnabled(False)
        self.status_message.setText(f"已导出 · {result.audio_path.name}")
        self._last_output_folder = result.audio_path.parent
        self.task_notice.finish(
            f"导出完成：{result.audio_path.name}",
            show_action=True,
        )
        if self.app_settings.open_after_export:
            os.startfile(result.audio_path.parent)  # noqa: S606

    def _export_failed(self, message: str) -> None:
        self.cancel_export_button.setEnabled(False)
        self.task_notice.clear()
        self._show_error(message)

    def _cancel_export(self) -> None:
        if self.export_worker:
            self.export_worker.cancel()

    def _choose_media(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "导入音视频",
            "",
            "媒体文件 (*.wav *.flac *.mp3 *.m4a *.aac *.ogg *.opus *.mp4 *.mkv *.mov "
            "*.webm *.avi *.m4v)",
        )
        self.import_paths(paths)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.import_paths(paths, activate=True)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _choose_subtitle(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "添加字幕轨", "", "字幕 (*.srt *.ass *.vtt)")
        if path:
            self._import_subtitle(Path(path))

    def _export_subtitle_track(self) -> None:
        asset = self.project.active_asset
        if not asset or not asset.subtitle_tracks:
            self._show_error("当前素材没有可导出的字幕轨。")
            return
        item = self.subtitle_tree.currentItem()
        track_id = item.data(0, Qt.ItemDataRole.UserRole) if item else asset.export_track_id
        track = next(
            (track for track in asset.subtitle_tracks if track.id == track_id),
            asset.export_track,
        )
        if not track:
            return
        default_folder = Path(asset.path).parent if asset.path else Path.cwd()
        default_path = default_folder / f"{sanitize_filename(track.name)}.srt"
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出完整字幕轨",
            str(default_path),
            "SubRip (*.srt);;WebVTT (*.vtt);;ASS (*.ass)",
        )
        if not path:
            return
        output = Path(path)
        if not output.suffix:
            suffix_by_filter = {
                "SubRip (*.srt)": ".srt",
                "WebVTT (*.vtt)": ".vtt",
                "ASS (*.ass)": ".ass",
            }
            output = output.with_suffix(suffix_by_filter.get(selected_filter, ".srt"))
        try:
            export_subtitle(track, output)
        except (OSError, ValueError) as exc:
            self._show_error(str(exc))
            return
        self.status_message.setText(f"SUBTITLE EXPORTED · {output.name}")
        QMessageBox.information(self, "字幕导出完成", f"已导出完整字幕轨：\n{output}")

    def _choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if folder:
            self.output_edit.setPlainText(folder)

    def new_project(self) -> None:
        if self._tts_busy:
            QMessageBox.information(
                self,
                "语音生成进行中",
                "当前 CUDA 推理无法强制取消。请等待当前语音完成并停止队列后再新建工程。",
            )
            return
        if not self._confirm_discard():
            return
        if not self.dirty:
            cleanup_unreferenced_generated_audio(self.project)
        self.project = Project()
        self.project.active_preset.naming_template = (
            self.app_settings.audio_naming_template
        )
        self._apply_export_settings_to_preset()
        self.undo_stack.clear()
        self.waveforms.clear()
        self.generated_waveforms.clear()
        self.asset_list.clear()
        self.subtitle_tree.clear()
        self.timeline.set_asset(None)
        self.player_widget.clear_ai_monitor()
        self.selected_region_ids.clear()
        self.selected_generated_clip_ids.clear()
        self.selected_region_id = None
        self.dirty = False
        self._show_empty_workspace()
        self.workspace_state.set_asset(None)
        self.workspace_state.set_selection("none")
        self._set_project_title()

    def open_project(self) -> None:
        if self._tts_busy:
            QMessageBox.information(
                self,
                "语音生成进行中",
                "当前 CUDA 推理无法强制取消。请等待当前语音完成并停止队列后再打开工程。",
            )
            return
        if not self._confirm_discard():
            return
        if not self.dirty:
            cleanup_unreferenced_generated_audio(self.project)
        path, _ = QFileDialog.getOpenFileName(self, "打开工程", "", "TTS Dataset Studio (*.ttds)")
        if not path:
            return
        try:
            project_path = Path(path)
            autosave_path = project_path.with_name(project_path.name + ".autosave")
            source = project_path
            if (
                autosave_path.exists()
                and autosave_path.stat().st_mtime_ns > project_path.stat().st_mtime_ns
            ):
                recover = QMessageBox.question(
                    self,
                    "恢复自动保存",
                    "检测到比工程文件更新的自动保存版本，是否恢复？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if recover == QMessageBox.StandardButton.Yes:
                    source = autosave_path
            self.project = load_project(source)
            self.project.project_path = str(project_path.resolve())
            self._relink_missing_assets()
            self.undo_stack.clear()
            self.asset_list.clear()
            for asset in self.project.assets:
                marker = "VIDEO" if asset.has_video else "AUDIO"
                self.asset_list.addItem(f"{marker}  {asset.display_name}")
            if self.project.active_asset:
                row = self.project.assets.index(self.project.active_asset)
                self.asset_list.setCurrentRow(row)
                self._activate_asset(self.project.active_asset)
            self.dirty = False
            self._set_project_title()
        except Exception as exc:  # noqa: BLE001
            self._show_error(str(exc))

    def save_project(self) -> bool:
        path = self.project.project_path
        previous_autosave = self._autosave_path()
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "保存工程",
                f"{self.project.name}.ttds",
                "TTS Dataset Studio (*.ttds)",
            )
        if not path:
            return False
        try:
            save_project(self.project, Path(path))
            previous_autosave.unlink(missing_ok=True)
            self._autosave_path().unlink(missing_ok=True)
            self.dirty = False
            self._set_project_title()
            self.status_message.setText(f"SAVED · {Path(path).name}")
            return True
        except Exception as exc:  # noqa: BLE001
            self._show_error(str(exc))
            return False

    def _autosave_path(self) -> Path:
        if self.project.project_path:
            project_path = Path(self.project.project_path)
            return project_path.with_name(project_path.name + ".autosave")
        folder = user_data_path("TTS Dataset Studio", "OpenAI") / "autosave"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "unsaved.ttds.autosave"

    def _write_autosave(self) -> None:
        if not self.dirty or not self.project.assets:
            return
        try:
            save_autosave(self.project, self._autosave_path())
        except OSError as exc:
            LOGGER.warning("Autosave failed: %s", exc)

    def _offer_unsaved_recovery(self) -> None:
        if os.environ.get("TTS_DATASET_STUDIO_DISABLE_RECOVERY") == "1":
            return
        path = self._autosave_path()
        if not path.exists() or self.project.assets:
            return
        choice = QMessageBox.question(
            self,
            "恢复工程",
            "检测到上次未正常关闭的自动保存工程，是否恢复？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if choice == QMessageBox.StandardButton.Yes:
            try:
                self.project = load_project(path)
                self._relink_missing_assets()
                self.asset_list.clear()
                for asset in self.project.assets:
                    marker = "VIDEO" if asset.has_video else "AUDIO"
                    self.asset_list.addItem(f"{marker}  {asset.display_name}")
                if self.project.active_asset:
                    self._activate_asset(self.project.active_asset)
                self.dirty = True
                self._set_project_title()
            except Exception as exc:  # noqa: BLE001
                self._show_error(f"自动恢复失败：{exc}")
        else:
            path.unlink(missing_ok=True)

    def _relink_missing_assets(self) -> None:
        for asset in self.project.assets:
            if not Path(asset.path).exists():
                replacement, _ = QFileDialog.getOpenFileName(
                    self,
                    f"重新定位素材：{asset.display_name}",
                    "",
                    "媒体文件 (*.*)",
                )
                if replacement:
                    replacement_asset = probe_media(Path(replacement), self.tools)
                    asset.path = replacement_asset.path
                    asset.display_name = replacement_asset.display_name
                    asset.duration_ms = replacement_asset.duration_ms
                    asset.has_video = replacement_asset.has_video
                    asset.has_audio = replacement_asset.has_audio
                    asset.sample_rate = replacement_asset.sample_rate
                    asset.channels = replacement_asset.channels
                    asset.size = replacement_asset.size
                    asset.modified_ns = replacement_asset.modified_ns
            for track in asset.generated_audio_tracks:
                for clip in track.clips:
                    if Path(clip.path).exists():
                        continue
                    replacement, _ = QFileDialog.getOpenFileName(
                        self,
                        f"重新定位 AI 音频：{clip.text[:30]}",
                        "",
                        "音频文件 (*.wav *.flac)",
                    )
                    if replacement:
                        clip.path = str(Path(replacement).resolve())

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._set_project_title()

    def _set_project_title(self) -> None:
        name = (
            Path(self.project.project_path).stem
            if self.project.project_path
            else self.project.name
        )
        self.setWindowTitle(f"{'*' if self.dirty else ''}{name} — TTS Dataset Studio")
        if hasattr(self, "project_title_label"):
            self.project_title_label.setText(f"{'• ' if self.dirty else ''}{name}")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        choice = QMessageBox.question(
            self,
            "未保存的更改",
            "工程有未保存的更改，是否先保存？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Save:
            return self.save_project()
        return choice == QMessageBox.StandardButton.Discard

    def _show_error(self, message: str) -> None:
        LOGGER.error(message)
        self.status_message.setText(f"ERROR · {message}")
        QMessageBox.warning(self, "TTS Dataset Studio", message)

    def _restore_geometry(self) -> None:
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._confirm_discard():
            event.ignore()
            return
        if not self.dirty:
            cleanup_unreferenced_generated_audio(self.project)
        self.settings.setValue("window/geometry", self.saveGeometry())
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()
            self.export_worker.wait(3000)
        self._cleanup_asr_temp()
        self._finish_tts_batch()
        if self.app_settings.unload_asr_on_exit or self.asr.state != "unloaded":
            self.asr.shutdown()
        if (
            self.app_settings.unload_index_tts_on_exit
            or self.index_tts.state != "unloaded"
        ):
            self.index_tts.shutdown()
        self.player_widget.shutdown()
        event.accept()
