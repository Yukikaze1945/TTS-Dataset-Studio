from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class WorkspaceState(QObject):
    asset_changed = Signal(object)
    selection_changed = Signal(str, str)
    focus_changed = Signal(str, str)
    task_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.active_asset_id: str | None = None
        self.selection_kind = "none"
        self.selection_summary = ""
        self.focus_kind = "none"
        self.focus_summary = ""
        self.task_kind = ""

    def set_asset(self, asset_id: str | None) -> None:
        if self.active_asset_id == asset_id:
            return
        self.active_asset_id = asset_id
        self.asset_changed.emit(asset_id)

    def set_selection(self, kind: str, summary: str = "") -> None:
        if (kind, summary) == (self.selection_kind, self.selection_summary):
            return
        self.selection_kind = kind
        self.selection_summary = summary
        self.selection_changed.emit(kind, summary)

    def set_focus(self, kind: str, summary: str = "") -> None:
        """Track a secondary timeline focus without replacing the source selection."""
        if (kind, summary) == (self.focus_kind, self.focus_summary):
            return
        self.focus_kind = kind
        self.focus_summary = summary
        self.focus_changed.emit(kind, summary)

    def set_task(self, kind: str) -> None:
        if self.task_kind == kind:
            return
        self.task_kind = kind
        self.task_changed.emit(kind)


class EmptyWorkspace(QWidget):
    import_requested = Signal()
    open_project_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("emptyWorkspace")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 32, 40, 44)
        outer.addStretch(3)

        hero = QWidget()
        hero.setMaximumWidth(760)
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand_row.addStretch()
        mark = QFrame()
        mark.setObjectName("brandMark")
        mark.setFixedSize(38, 38)
        mark_layout = QHBoxLayout(mark)
        mark_layout.setContentsMargins(8, 8, 8, 8)
        mark_layout.setSpacing(2)
        for height in (8, 15, 22, 13, 18):
            bar = QFrame()
            bar.setObjectName("signalBar")
            bar.setFixedSize(3, height)
            mark_layout.addWidget(
                bar,
                0,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            )
        brand_row.addWidget(mark)
        product = QLabel("TTS Dataset Studio")
        product.setObjectName("welcomeProduct")
        brand_row.addWidget(product)
        brand_row.addStretch()
        layout.addLayout(brand_row)

        title = QLabel("把声音，变成可以训练的数据")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        subtitle = QLabel(
            "拖入音频或视频，字幕、波形和时间线会自动准备好。"
            "\n选择一句话，就可以试听、识别、生成语音或直接导出。"
        )
        subtitle.setObjectName("welcomeSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(subtitle)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button = QPushButton("选择音视频")
        button.setObjectName("primaryAction")
        button.setMinimumSize(210, 44)
        button.clicked.connect(self.import_requested)
        button_row.addWidget(button)
        open_button = QPushButton("打开工程")
        open_button.setObjectName("secondaryAction")
        open_button.setMinimumHeight(44)
        open_button.clicked.connect(self.open_project_requested)
        button_row.addWidget(open_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        hint = QLabel("也可以直接拖入 WAV、FLAC、MP3、MP4、MKV 等文件")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(hint)

        steps = QHBoxLayout()
        steps.setContentsMargins(0, 18, 0, 0)
        steps.setSpacing(0)
        for number, name, detail in (
            ("01", "导入素材", "自动准备字幕与波形"),
            ("02", "选择声音", "点击字幕或划定区间"),
            ("03", "开始制作", "试听、识别、生成或导出"),
        ):
            item = QFrame()
            item.setObjectName("welcomeStep")
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(20, 14, 20, 14)
            item_layout.setSpacing(4)
            number_label = QLabel(number)
            number_label.setObjectName("stepNumber")
            name_label = QLabel(name)
            name_label.setObjectName("stepTitle")
            detail_label = QLabel(detail)
            detail_label.setObjectName("muted")
            detail_label.setWordWrap(True)
            item_layout.addWidget(number_label)
            item_layout.addWidget(name_label)
            item_layout.addWidget(detail_label)
            steps.addWidget(item, 1)
        layout.addLayout(steps)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(hero)
        row.addStretch()
        outer.addLayout(row)
        outer.addStretch(4)


class ContextActionBar(QFrame):
    play_requested = Signal()
    transcribe_requested = Signal()
    generate_requested = Signal()
    export_requested = Signal()
    process_requested = Signal(str)
    delete_requested = Signal()
    edit_requested = Signal()
    locate_source_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("contextBar")
        self._kind = "none"
        self._summary = ""
        self._focus_kind = "none"
        self._focus_summary = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(7)

        summary_layout = QVBoxLayout()
        summary_layout.setContentsMargins(0, 0, 8, 0)
        summary_layout.setSpacing(1)
        self.summary = QLabel("")
        self.summary.setObjectName("contextSummary")
        self.detail = QLabel("")
        self.detail.setObjectName("contextDetail")
        summary_layout.addWidget(self.summary)
        summary_layout.addWidget(self.detail)
        layout.addLayout(summary_layout, 1)

        self.play_button = self._button("试听", "Enter", self.play_requested)
        self.play_button.setToolTip(
            "试听所选时间范围；实际声音遵循轨道 Mute / Solo"
        )
        self.edit_button = self._button("编辑", "", self.edit_requested)
        self.asr_button = self._button("识别字幕", "", self.transcribe_requested)
        self.tts_button = self._button("生成语音", "G", self.generate_requested)
        self.process_button = QToolButton()
        self.process_button.setText("处理音频")
        self.process_button.setObjectName("secondaryAction")
        self.process_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        process_menu = QMenu(self.process_button)
        for text, engine in (
            ("快速降噪 · DPDFNet", "dpdfnet"),
            ("去除 BGM · BS-RoFormer", "separator"),
            ("录音室修复（实验）· StuPASE", "stupase"),
        ):
            action = process_menu.addAction(text)
            action.triggered.connect(
                lambda _checked=False, value=engine: self.process_requested.emit(value)
            )
        self.process_button.setMenu(process_menu)
        self.locate_button = self._button(
            "定位源片段",
            "",
            self.locate_source_requested,
        )
        self.delete_button = self._button("删除", "X", self.delete_requested)
        self.export_button = self._button("导出", "E", self.export_requested, primary=True)
        self.export_button.setToolTip(
            "导出当前可听轨道：Mute 排除，Solo 优先，多条可听轨道会混音"
        )
        self.asr_button.setObjectName("secondaryAction")
        self.tts_button.setObjectName("secondaryAction")
        self.locate_button.setObjectName("quietAction")
        self.delete_button.setObjectName("destructiveAction")
        for button in (
            self.play_button,
            self.edit_button,
            self.locate_button,
            self.asr_button,
            self.tts_button,
            self.process_button,
            self.delete_button,
            self.export_button,
        ):
            layout.addWidget(button)
        self.set_selection("none")

    def _button(self, text: str, shortcut: str, signal, primary: bool = False) -> QPushButton:
        label = f"{text}  {shortcut}" if shortcut else text
        button = QPushButton(label)
        if primary:
            button.setObjectName("primaryAction")
        button.clicked.connect(signal)
        return button

    def set_selection(self, kind: str, summary: str = "") -> None:
        self._kind = kind
        self._summary = summary
        self._refresh()

    def set_focus(self, kind: str, summary: str = "") -> None:
        self._focus_kind = kind
        self._focus_summary = summary
        self._refresh()

    def _refresh(self) -> None:
        has_source = self._kind in {"region", "cue"}
        has_generated_focus = self._focus_kind == "generated"
        visible = has_source or has_generated_focus
        self.setVisible(visible)
        if not visible:
            return

        if has_source:
            self.summary.setText(self._summary)
            self.detail.setText(
                f"已聚焦 {self._focus_summary}；处理和导出仍作用于源片段"
                if has_generated_focus
                else "接下来可直接识别、生成、处理或导出"
            )
        else:
            self.summary.setText(self._focus_summary)
            self.detail.setText("这是生成/增强结果；定位源片段后可继续处理")

        unavailable_hint = "先点击字幕，或按 I / O 创建源片段"
        available_hints = {
            self.asr_button: "识别所选源片段并写入字幕轨",
            self.tts_button: "用所选源片段作为参考生成语音（G）",
            self.process_button: "降噪、去 BGM 或修复所选源片段",
            self.export_button: (
                "导出当前可听轨道：Mute 排除，Solo 优先，"
                "多条可听轨道会混音（E）"
            ),
        }
        for button, available_hint in available_hints.items():
            button.setVisible(True)
            button.setEnabled(has_source)
            button.setToolTip(
                available_hint if has_source else unavailable_hint
            )

        self.play_button.setEnabled(has_source or has_generated_focus)
        self.edit_button.setVisible(self._kind == "cue")
        self.locate_button.setVisible(has_generated_focus)
        self.delete_button.setVisible(has_source or has_generated_focus)
        self.delete_button.setText(
            "删除结果  X" if has_generated_focus else "删除片段  X"
        )
        self.delete_button.setToolTip(
            "删除聚焦的生成/增强结果"
            if has_generated_focus
            else "删除选中的源片段"
        )


class TaskNoticeBar(QFrame):
    cancel_requested = Signal()
    action_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("taskBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        self.message = QLabel("")
        self.message.setObjectName("muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(4)
        self.progress.setMaximumWidth(260)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("quietAction")
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.action_button = QPushButton("打开目录")
        self.action_button.setObjectName("quietAction")
        self.action_button.clicked.connect(self.action_requested)
        layout.addWidget(self.message, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.action_button)
        layout.addWidget(self.cancel_button)
        self.action_button.hide()
        self.setVisible(False)

    def start(self, message: str, cancellable: bool = True) -> None:
        self.message.setText(message)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.cancel_button.setVisible(cancellable)
        self.action_button.hide()
        self.setVisible(True)

    def set_progress(self, value: int) -> None:
        self.progress.setValue(max(0, min(100, value)))

    def finish(self, message: str, show_action: bool = False) -> None:
        self.message.setText(message)
        self.progress.setValue(100)
        self.cancel_button.hide()
        self.action_button.setVisible(show_action)

    def clear(self) -> None:
        self.hide()
