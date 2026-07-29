from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tts_dataset_studio.domain.app_settings import AppSettings
from tts_dataset_studio.services.media import ToolPaths


class AdvancedSettingsDialog(QDialog):
    settings_applied = Signal(object)
    unload_asr_requested = Signal()
    unload_tts_requested = Signal()

    def __init__(
        self,
        store: QSettings,
        parent=None,
        engine_states: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.engine_states = engine_states or {}
        self.settings_value = AppSettings.load(store)
        self.setWindowTitle("设置")
        self.setMinimumSize(780, 580)
        self.resize(880, 680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)

        title = QLabel("设置")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)
        description = QLabel("常用选项保持简单；引擎路径、编码与缓存参数按分类集中管理。")
        description.setObjectName("muted")
        layout.addWidget(description)

        body = QHBoxLayout()
        body.setSpacing(14)
        navigation = QFrame()
        navigation.setObjectName("settingsNav")
        navigation.setFixedWidth(190)
        navigation_layout = QVBoxLayout(navigation)
        navigation_layout.setContentsMargins(6, 6, 6, 6)
        self.settings_nav = QListWidget()
        self.settings_nav.setObjectName("settingsNavList")
        self.settings_nav.addItems(
            ["常规与外观", "导出与命名", "播放与时间线", "字幕", "AI 引擎"]
        )
        navigation_layout.addWidget(self.settings_nav)
        body.addWidget(navigation)

        self.settings_stack = QStackedWidget()
        for page in (
            self._build_general_tab(),
            self._build_save_tab(),
            self._build_tools_tab(),
            self._build_subtitle_tab(),
            self._build_ai_tab(),
        ):
            self.settings_stack.addWidget(page)
        self.settings_nav.currentRowChanged.connect(
            self.settings_stack.setCurrentIndex
        )
        self.settings_nav.setCurrentRow(0)
        body.addWidget(self.settings_stack, 1)
        layout.addLayout(body, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self._restore_defaults
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("应用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText(
            "恢复默认"
        )
        layout.addWidget(buttons)
        self._load(self.settings_value)

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.theme = QComboBox()
        self.theme.addItem("跟随 Windows", "system")
        self.theme.addItem("浅色", "light")
        self.theme.addItem("深色", "dark")
        note = QLabel("主题在点击“应用”后立即生效。界面布局会随窗口宽度自动调整。")
        note.setWordWrap(True)
        form.addRow("外观主题", self.theme)
        form.addRow("", note)
        return tab

    def _path_row(self, edit: QLineEdit) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        button = QPushButton("浏览…")
        button.clicked.connect(lambda: self._choose_folder(edit))
        layout.addWidget(button)
        return row

    def _scroll_page(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setWidget(content)
        return scroll

    def _build_save_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.audio_mode = QComboBox()
        self.audio_mode.addItem("源素材目录", "source")
        self.audio_mode.addItem("自定义目录", "custom")
        self.audio_dir = QLineEdit()
        self.still_mode = QComboBox()
        self.still_mode.addItem("源素材目录", "source")
        self.still_mode.addItem("自定义目录", "custom")
        self.still_dir = QLineEdit()
        self.still_format = QComboBox()
        self.still_format.addItems(["png", "jpeg"])
        self.jpeg_quality = QSpinBox()
        self.jpeg_quality.setRange(1, 100)
        self.audio_template = QLineEdit()
        self.export_format = QComboBox()
        self.export_format.addItems(["wav", "flac", "mp3"])
        self.export_sample_rate = QComboBox()
        for label, rate in (
            ("原始", 0),
            ("16 kHz", 16000),
            ("22.05 kHz", 22050),
            ("24 kHz", 24000),
            ("32 kHz", 32000),
            ("44.1 kHz", 44100),
            ("48 kHz", 48000),
        ):
            self.export_sample_rate.addItem(label, rate)
        self.export_channels = QComboBox()
        self.export_channels.addItem("原始", 0)
        self.export_channels.addItem("单声道", 1)
        self.export_channels.addItem("立体声", 2)
        self.export_codec = QComboBox()
        self.export_codec.addItems(
            ["pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"]
        )
        self.export_txt = QCheckBox("生成同名 UTF-8 TXT")
        self.export_normalize = QCheckBox("峰值归一化至 -1 dBFS")
        self.export_fade_in = QSpinBox()
        self.export_fade_in.setRange(0, 5000)
        self.export_fade_in.setSuffix(" ms")
        self.export_fade_out = QSpinBox()
        self.export_fade_out.setRange(0, 5000)
        self.export_fade_out.setSuffix(" ms")
        self.export_regex = QLineEdit()
        self.export_regex_replacement = QLineEdit()
        self.still_template = QLineEdit()
        self.open_after = QCheckBox("导出后打开文件夹")
        self.confirm_before_export = QCheckBox("导出前显示确认面板")
        form.addRow("音频默认位置", self.audio_mode)
        form.addRow("音频自定义目录", self._path_row(self.audio_dir))
        form.addRow("静帧默认位置", self.still_mode)
        form.addRow("静帧自定义目录", self._path_row(self.still_dir))
        form.addRow("静帧格式", self.still_format)
        form.addRow("JPEG 质量", self.jpeg_quality)
        form.addRow("音频格式", self.export_format)
        form.addRow("采样率", self.export_sample_rate)
        form.addRow("声道", self.export_channels)
        form.addRow("WAV 编码", self.export_codec)
        form.addRow("", self.export_txt)
        form.addRow("", self.export_normalize)
        form.addRow("淡入", self.export_fade_in)
        form.addRow("淡出", self.export_fade_out)
        form.addRow("音频命名模板", self.audio_template)
        form.addRow("源名正则", self.export_regex)
        form.addRow("替换文本", self.export_regex_replacement)
        form.addRow("静帧命名模板", self.still_template)
        form.addRow("", self.confirm_before_export)
        form.addRow("", self.open_after)
        return self._scroll_page(tab)

    def _build_tools_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        try:
            tools = ToolPaths.discover()
            status = (
                f"mpv: {tools.mpv or '不可用'}\n"
                f"FFmpeg: {tools.ffmpeg}\nffprobe: {tools.ffprobe}"
            )
        except FileNotFoundError as exc:
            status = str(exc)
        self.tools_status = QLabel(status)
        self.scrub_hz = QSpinBox()
        self.scrub_hz.setRange(10, 120)
        self.scrub_hz.setSuffix(" Hz")
        self.follow_playhead = QCheckBox("播放头离开视野时自动跟随")
        self.cache_dir = QLineEdit()
        form.addRow("工具状态", self.tools_status)
        form.addRow("拖动预览频率", self.scrub_hz)
        form.addRow("", self.follow_playhead)
        form.addRow("缓存目录", self._path_row(self.cache_dir))
        return self._scroll_page(tab)

    def _build_subtitle_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        note = QLabel(
            "外部字幕与视频内嵌字幕会自动加入素材侧栏。"
            "导出字幕轨、显示状态和文本编辑属于工程设置，会随 .ttds 保存。"
        )
        note.setWordWrap(True)
        form.addRow("自动检测", note)
        return tab

    def _build_ai_tab(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._build_asr_tab(), "语音识别")
        tabs.addTab(self._build_index_tts_tab(), "语音生成")
        tabs.addTab(self._build_audio_processing_tab(), "音频处理")
        return tabs

    def _build_asr_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.moss_root = QLineEdit()
        self.moss_python = QLineEdit()
        self.moss_model = QLineEdit()
        self.moss_device = QComboBox()
        self.moss_device.addItems(["cuda", "auto", "cpu"])
        self.moss_dtype = QComboBox()
        self.moss_dtype.addItems(["bf16", "fp16", "fp32"])
        self.moss_prompt = QPlainTextEdit()
        self.moss_prompt.setMaximumHeight(90)
        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(128, 32768)
        self.max_length = QSpinBox()
        self.max_length.setRange(4096, 1_000_000)
        self.moss_temp = QLineEdit()
        self.track_name = QLineEdit()
        self.unload_on_exit = QCheckBox("退出程序时卸载模型")
        asr_state = QLabel(self._engine_status_text(self.engine_states.get("asr")))
        unload_button = QPushButton("卸载语音识别模型")
        unload_button.setEnabled(self.engine_states.get("asr") == "loaded")
        unload_button.clicked.connect(self.unload_asr_requested)
        test_button = QPushButton("检测环境")
        test_button.clicked.connect(self._test_asr_environment)
        form.addRow("MOSS 安装目录", self._path_row(self.moss_root))
        form.addRow("Python", self.moss_python)
        form.addRow("模型路径", self.moss_model)
        form.addRow("设备", self.moss_device)
        form.addRow("精度", self.moss_dtype)
        form.addRow("Prompt", self.moss_prompt)
        form.addRow("最大生成 Token", self.max_tokens)
        form.addRow("最大上下文长度", self.max_length)
        form.addRow("临时目录", self._path_row(self.moss_temp))
        form.addRow("字幕轨名称", self.track_name)
        form.addRow("", self.unload_on_exit)
        form.addRow("当前状态", asr_state)
        form.addRow("", unload_button)
        form.addRow("", test_button)
        return tab

    def _build_index_tts_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.index_root = QLineEdit()
        self.index_python = QLineEdit()
        self.index_config = QLineEdit()
        self.index_model_dir = QLineEdit()
        self.index_device = QComboBox()
        self.index_device.addItems(["cuda:0", "auto", "cpu"])
        self.index_fp16 = QCheckBox("使用 FP16")
        self.index_cuda_kernel = QCheckBox("使用 CUDA kernel")
        self.index_deepspeed = QCheckBox("使用 DeepSpeed")
        self.index_accel = QCheckBox("使用 GPT 加速引擎")
        self.index_torch_compile = QCheckBox("使用 torch.compile")
        self.index_temperature = QDoubleSpinBox()
        self.index_temperature.setRange(0.1, 2.0)
        self.index_temperature.setSingleStep(0.1)
        self.index_top_p = QDoubleSpinBox()
        self.index_top_p.setRange(0.0, 1.0)
        self.index_top_p.setSingleStep(0.05)
        self.index_top_k = QSpinBox()
        self.index_top_k.setRange(0, 100)
        self.index_beams = QSpinBox()
        self.index_beams.setRange(1, 10)
        self.index_repetition = QDoubleSpinBox()
        self.index_repetition.setRange(0.1, 20.0)
        self.index_repetition.setSingleStep(0.1)
        self.index_max_mel = QSpinBox()
        self.index_max_mel.setRange(50, 5000)
        self.index_max_text = QSpinBox()
        self.index_max_text.setRange(20, 1000)
        self.index_silence = QSpinBox()
        self.index_silence.setRange(0, 5000)
        self.index_silence.setSuffix(" ms")
        self.index_temp = QLineEdit()
        self.index_unload_on_exit = QCheckBox("退出程序时卸载语音引擎")
        tts_state = QLabel(self._engine_status_text(self.engine_states.get("tts")))
        unload_button = QPushButton("卸载语音生成引擎")
        unload_button.setEnabled(self.engine_states.get("tts") == "loaded")
        unload_button.clicked.connect(self.unload_tts_requested)
        test_button = QPushButton("检测 IndexTTS2 环境")
        test_button.clicked.connect(self._test_index_tts_environment)
        form.addRow("IndexTTS 安装目录", self._path_row(self.index_root))
        form.addRow("Python", self.index_python)
        form.addRow("配置文件", self.index_config)
        form.addRow("权重目录", self._path_row(self.index_model_dir))
        form.addRow("设备", self.index_device)
        form.addRow("", self.index_fp16)
        form.addRow("", self.index_cuda_kernel)
        form.addRow("", self.index_deepspeed)
        form.addRow("", self.index_accel)
        form.addRow("", self.index_torch_compile)
        form.addRow("Temperature", self.index_temperature)
        form.addRow("Top P", self.index_top_p)
        form.addRow("Top K", self.index_top_k)
        form.addRow("Beams", self.index_beams)
        form.addRow("重复惩罚", self.index_repetition)
        form.addRow("最大 Mel Token", self.index_max_mel)
        form.addRow("每段最大文本 Token", self.index_max_text)
        form.addRow("段间静音", self.index_silence)
        form.addRow("临时目录", self._path_row(self.index_temp))
        form.addRow("", self.index_unload_on_exit)
        form.addRow("当前状态", tts_state)
        form.addRow("", unload_button)
        form.addRow("", test_button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(tab)
        return scroll

    def _build_audio_processing_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        note = QLabel(
            "三个引擎都在外部独立环境中运行，下载版不会内置模型。"
            "处理结果只会加入“增强音轨”，不会覆盖原素材。"
        )
        note.setWordWrap(True)
        self.enhancement_temp = QLineEdit()
        form.addRow("说明", note)
        form.addRow("临时目录", self._path_row(self.enhancement_temp))

        self.dpdfnet_python = QLineEdit()
        self.dpdfnet_model = QComboBox()
        self.dpdfnet_model.addItems(
            ["dpdfnet8_48khz_hr", "dpdfnet2_48khz_hr"]
        )
        self.dpdfnet_limit = QDoubleSpinBox()
        self.dpdfnet_limit.setRange(0.0, 30.0)
        self.dpdfnet_limit.setSuffix(" dB")
        dpdfnet_test = QPushButton("检测 DPDFNet")
        dpdfnet_test.clicked.connect(self._test_dpdfnet_environment)
        form.addRow(QLabel("快速降噪 · DPDFNet"))
        form.addRow("Python", self.dpdfnet_python)
        form.addRow("模型", self.dpdfnet_model)
        form.addRow("抑制上限", self.dpdfnet_limit)
        form.addRow("", dpdfnet_test)

        self.separator_python = QLineEdit()
        self.separator_model = QLineEdit()
        self.separator_model_dir = QLineEdit()
        self.separator_autocast = QCheckBox("使用 CUDA autocast")
        separator_test = QPushButton("检测 Audio Separator")
        separator_test.clicked.connect(self._test_separator_environment)
        form.addRow(QLabel("去除 BGM · BS-RoFormer"))
        form.addRow("Python", self.separator_python)
        form.addRow("模型文件名", self.separator_model)
        form.addRow("模型缓存目录", self._path_row(self.separator_model_dir))
        form.addRow("", self.separator_autocast)
        form.addRow("", separator_test)

        self.stupase_root = QLineEdit()
        self.stupase_python = QLineEdit()
        self.stupase_model_dir = QLineEdit()
        self.stupase_device = QComboBox()
        self.stupase_device.addItems(["cuda:0", "cpu"])
        warning = QLabel(
            "StuPASE 是 16 kHz 生成式修复，可能改变齿音、气声和角色音色，"
            "建议只用于抢救素材并与原声 A/B。"
        )
        warning.setWordWrap(True)
        stupase_test = QPushButton("检测 StuPASE")
        stupase_test.clicked.connect(self._test_stupase_environment)
        form.addRow(QLabel("录音室修复（实验）· StuPASE"))
        form.addRow("仓库目录", self._path_row(self.stupase_root))
        form.addRow("Python", self.stupase_python)
        form.addRow("模型目录", self._path_row(self.stupase_model_dir))
        form.addRow("设备", self.stupase_device)
        form.addRow("注意", warning)
        form.addRow("", stupase_test)
        return self._scroll_page(tab)

    @staticmethod
    def _engine_status_text(state: str | None) -> str:
        return {
            "loaded": "已加载",
            "loading": "加载中",
            "unloading": "卸载中",
            "error": "加载失败",
        }.get(state or "", "未加载")

    def _choose_folder(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择目录", edit.text())
        if folder:
            edit.setText(folder)

    def _load(self, value: AppSettings) -> None:
        self.theme.setCurrentIndex(self.theme.findData(value.theme))
        self.confirm_before_export.setChecked(value.confirm_before_export)
        self.audio_mode.setCurrentIndex(self.audio_mode.findData(value.audio_output_mode))
        self.audio_dir.setText(value.audio_output_dir)
        self.still_mode.setCurrentIndex(self.still_mode.findData(value.still_output_mode))
        self.still_dir.setText(value.still_output_dir)
        self.still_format.setCurrentText(value.still_format)
        self.jpeg_quality.setValue(value.jpeg_quality)
        self.audio_template.setText(value.audio_naming_template)
        self.export_format.setCurrentText(value.export_container)
        self.export_sample_rate.setCurrentIndex(
            max(0, self.export_sample_rate.findData(value.export_sample_rate))
        )
        self.export_channels.setCurrentIndex(
            max(0, self.export_channels.findData(value.export_channels))
        )
        self.export_codec.setCurrentText(value.export_codec)
        self.export_txt.setChecked(value.export_write_txt)
        self.export_normalize.setChecked(value.export_peak_normalize)
        self.export_fade_in.setValue(value.export_fade_in_ms)
        self.export_fade_out.setValue(value.export_fade_out_ms)
        self.export_regex.setText(value.export_regex_pattern)
        self.export_regex_replacement.setText(value.export_regex_replacement)
        self.still_template.setText(value.still_naming_template)
        self.open_after.setChecked(value.open_after_export)
        self.scrub_hz.setValue(value.scrub_hz)
        self.follow_playhead.setChecked(value.follow_playhead)
        self.cache_dir.setText(value.cache_dir)
        self.moss_root.setText(value.moss_root)
        self.moss_python.setText(value.moss_python)
        self.moss_model.setText(value.moss_model)
        self.moss_device.setCurrentText(value.moss_device)
        self.moss_dtype.setCurrentText(value.moss_dtype)
        self.moss_prompt.setPlainText(value.moss_prompt)
        self.max_tokens.setValue(value.moss_max_new_tokens)
        self.max_length.setValue(value.moss_max_length)
        self.moss_temp.setText(value.moss_temp_dir)
        self.track_name.setText(value.moss_track_name)
        self.unload_on_exit.setChecked(value.unload_asr_on_exit)
        self.index_root.setText(value.index_tts_root)
        self.index_python.setText(value.index_tts_python)
        self.index_config.setText(value.index_tts_config)
        self.index_model_dir.setText(value.index_tts_model_dir)
        self.index_device.setCurrentText(value.index_tts_device)
        self.index_fp16.setChecked(value.index_tts_fp16)
        self.index_cuda_kernel.setChecked(value.index_tts_cuda_kernel)
        self.index_deepspeed.setChecked(value.index_tts_deepspeed)
        self.index_accel.setChecked(value.index_tts_accel)
        self.index_torch_compile.setChecked(value.index_tts_torch_compile)
        self.index_temperature.setValue(value.index_tts_temperature)
        self.index_top_p.setValue(value.index_tts_top_p)
        self.index_top_k.setValue(value.index_tts_top_k)
        self.index_beams.setValue(value.index_tts_num_beams)
        self.index_repetition.setValue(value.index_tts_repetition_penalty)
        self.index_max_mel.setValue(value.index_tts_max_mel_tokens)
        self.index_max_text.setValue(value.index_tts_max_text_tokens)
        self.index_silence.setValue(value.index_tts_interval_silence)
        self.index_temp.setText(value.index_tts_temp_dir)
        self.index_unload_on_exit.setChecked(value.unload_index_tts_on_exit)
        self.enhancement_temp.setText(value.enhancement_temp_dir)
        self.dpdfnet_python.setText(value.dpdfnet_python)
        self.dpdfnet_model.setCurrentText(value.dpdfnet_model)
        self.dpdfnet_limit.setValue(value.dpdfnet_attn_limit_db)
        self.separator_python.setText(value.separator_python)
        self.separator_model.setText(value.separator_model)
        self.separator_model_dir.setText(value.separator_model_dir)
        self.separator_autocast.setChecked(value.separator_use_autocast)
        self.stupase_root.setText(value.stupase_root)
        self.stupase_python.setText(value.stupase_python)
        self.stupase_model_dir.setText(value.stupase_model_dir)
        self.stupase_device.setCurrentText(value.stupase_device)

    def value(self) -> AppSettings:
        return replace(
            self.settings_value,
            theme=str(self.theme.currentData()),
            confirm_before_export=self.confirm_before_export.isChecked(),
            audio_output_mode=str(self.audio_mode.currentData()),
            audio_output_dir=self.audio_dir.text().strip(),
            still_output_mode=str(self.still_mode.currentData()),
            still_output_dir=self.still_dir.text().strip(),
            still_format=self.still_format.currentText(),
            jpeg_quality=self.jpeg_quality.value(),
            audio_naming_template=self.audio_template.text().strip(),
            export_container=self.export_format.currentText(),
            export_sample_rate=int(self.export_sample_rate.currentData()),
            export_channels=int(self.export_channels.currentData()),
            export_codec=self.export_codec.currentText(),
            export_write_txt=self.export_txt.isChecked(),
            export_peak_normalize=self.export_normalize.isChecked(),
            export_fade_in_ms=self.export_fade_in.value(),
            export_fade_out_ms=self.export_fade_out.value(),
            export_regex_pattern=self.export_regex.text(),
            export_regex_replacement=self.export_regex_replacement.text(),
            still_naming_template=self.still_template.text().strip(),
            open_after_export=self.open_after.isChecked(),
            scrub_hz=self.scrub_hz.value(),
            follow_playhead=self.follow_playhead.isChecked(),
            cache_dir=self.cache_dir.text().strip(),
            moss_root=self.moss_root.text().strip(),
            moss_python=self.moss_python.text().strip(),
            moss_model=self.moss_model.text().strip(),
            moss_device=self.moss_device.currentText(),
            moss_dtype=self.moss_dtype.currentText(),
            moss_prompt=self.moss_prompt.toPlainText().strip(),
            moss_max_new_tokens=self.max_tokens.value(),
            moss_max_length=self.max_length.value(),
            moss_temp_dir=self.moss_temp.text().strip(),
            moss_track_name=self.track_name.text().strip() or "MOSS ASR",
            unload_asr_on_exit=self.unload_on_exit.isChecked(),
            index_tts_root=self.index_root.text().strip(),
            index_tts_python=self.index_python.text().strip(),
            index_tts_config=self.index_config.text().strip(),
            index_tts_model_dir=self.index_model_dir.text().strip(),
            index_tts_device=self.index_device.currentText(),
            index_tts_fp16=self.index_fp16.isChecked(),
            index_tts_cuda_kernel=self.index_cuda_kernel.isChecked(),
            index_tts_deepspeed=self.index_deepspeed.isChecked(),
            index_tts_accel=self.index_accel.isChecked(),
            index_tts_torch_compile=self.index_torch_compile.isChecked(),
            index_tts_temperature=self.index_temperature.value(),
            index_tts_top_p=self.index_top_p.value(),
            index_tts_top_k=self.index_top_k.value(),
            index_tts_num_beams=self.index_beams.value(),
            index_tts_repetition_penalty=self.index_repetition.value(),
            index_tts_max_mel_tokens=self.index_max_mel.value(),
            index_tts_max_text_tokens=self.index_max_text.value(),
            index_tts_interval_silence=self.index_silence.value(),
            index_tts_temp_dir=self.index_temp.text().strip(),
            unload_index_tts_on_exit=self.index_unload_on_exit.isChecked(),
            enhancement_temp_dir=self.enhancement_temp.text().strip(),
            dpdfnet_python=self.dpdfnet_python.text().strip(),
            dpdfnet_model=self.dpdfnet_model.currentText(),
            dpdfnet_attn_limit_db=self.dpdfnet_limit.value(),
            separator_python=self.separator_python.text().strip(),
            separator_model=self.separator_model.text().strip(),
            separator_model_dir=self.separator_model_dir.text().strip(),
            separator_use_autocast=self.separator_autocast.isChecked(),
            stupase_root=self.stupase_root.text().strip(),
            stupase_python=self.stupase_python.text().strip(),
            stupase_model_dir=self.stupase_model_dir.text().strip(),
            stupase_device=self.stupase_device.currentText(),
        )

    def _apply(self) -> None:
        self.settings_value = self.value()
        self.settings_value.save(self.store)
        self.settings_applied.emit(self.settings_value)

    def _accept(self) -> None:
        self._apply()
        self.accept()

    def _restore_defaults(self) -> None:
        self.settings_value = AppSettings()
        self._load(self.settings_value)

    def _test_asr_environment(self) -> None:
        value = self.value()
        python = Path(value.moss_python)
        model = Path(value.moss_model)
        if not python.exists():
            QMessageBox.critical(self, "环境检测失败", f"Python 不存在：\n{python}")
            return
        code = (
            "import json,torch,moss_transcribe_diarize;"
            "print(json.dumps({'torch':torch.__version__,'cuda':torch.cuda.is_available(),"
            "'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}))"
        )
        try:
            process = subprocess.run(
                [str(python), "-c", code],
                cwd=value.moss_root,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if process.returncode:
                raise RuntimeError(process.stderr.strip())
            info = json.loads(process.stdout.strip().splitlines()[-1])
            model_status = "本地目录有效" if model.exists() else "模型 ID/缓存模式"
            QMessageBox.information(
                self,
                "环境检测成功",
                f"Torch {info['torch']}\nCUDA: {info['cuda']}\n"
                f"GPU: {info['gpu']}\n模型: {model_status}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "环境检测失败", str(exc))

    def _test_index_tts_environment(self) -> None:
        value = self.value()
        python = Path(value.index_tts_python)
        root = Path(value.index_tts_root)
        config = Path(value.index_tts_config)
        model_dir = Path(value.index_tts_model_dir)
        missing = [
            str(path)
            for path in (python, root, config, model_dir)
            if not path.exists()
        ]
        if missing:
            QMessageBox.critical(
                self,
                "环境检测失败",
                "以下路径不存在：\n" + "\n".join(missing),
            )
            return
        code = (
            "import json,torch,indextts;"
            "print(json.dumps({'torch':torch.__version__,"
            "'cuda':torch.cuda.is_available(),"
            "'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() "
            "else 'CPU'}))"
        )
        try:
            process = subprocess.run(
                [str(python), "-c", code],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if process.returncode:
                raise RuntimeError(process.stderr.strip())
            info = json.loads(process.stdout.strip().splitlines()[-1])
            QMessageBox.information(
                self,
                "IndexTTS2 环境检测成功",
                f"Torch {info['torch']}\nCUDA: {info['cuda']}\nGPU: {info['gpu']}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "环境检测失败", str(exc))

    def _test_dpdfnet_environment(self) -> None:
        self._test_audio_python(
            self.dpdfnet_python.text(),
            "import dpdfnet,onnxruntime,soundfile;"
            "print('DPDFNet OK · ONNX Runtime '+onnxruntime.__version__)",
            "DPDFNet",
        )

    def _test_separator_environment(self) -> None:
        self._test_audio_python(
            self.separator_python.text(),
            "import torch,audio_separator;"
            "print('Audio Separator OK · CUDA '+str(torch.cuda.is_available()))",
            "Audio Separator",
        )

    def _test_stupase_environment(self) -> None:
        root = Path(self.stupase_root.text().strip())
        module = root / "stupase" / "inference" / "inference.py"
        if not module.is_file():
            QMessageBox.critical(
                self,
                "环境检测失败",
                f"找不到 StuPASE 推理入口：\n{module}",
            )
            return
        self._test_audio_python(
            self.stupase_python.text(),
            "import torch,torchaudio;print('StuPASE Python OK · CUDA '+"
            "str(torch.cuda.is_available()))",
            "StuPASE",
            cwd=root,
        )

    def _test_audio_python(
        self,
        python_value: str,
        code: str,
        label: str,
        cwd: Path | None = None,
    ) -> None:
        python = Path(python_value)
        if not python.is_file():
            QMessageBox.critical(
                self,
                "环境检测失败",
                f"{label} Python 不存在：\n{python if python_value else '尚未配置'}",
            )
            return
        try:
            process = subprocess.run(
                [str(python), "-c", code],
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if process.returncode:
                raise RuntimeError(process.stderr.strip() or process.stdout.strip())
            QMessageBox.information(
                self,
                f"{label} 环境检测成功",
                process.stdout.strip() or "环境可用",
            )
        except Exception as exc:
            QMessageBox.critical(self, "环境检测失败", str(exc))
