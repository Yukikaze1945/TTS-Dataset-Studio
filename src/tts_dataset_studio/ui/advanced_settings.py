from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tts_dataset_studio.domain.app_settings import AppSettings
from tts_dataset_studio.services.media import ToolPaths


class AdvancedSettingsDialog(QDialog):
    settings_applied = Signal(object)

    def __init__(self, store: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.settings_value = AppSettings.load(store)
        self.setWindowTitle("高级设置")
        self.resize(720, 610)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_save_tab(), "保存与命名")
        tabs.addTab(self._build_tools_tab(), "播放与工具")
        tabs.addTab(self._build_asr_tab(), "ASR")
        layout.addWidget(tabs)
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
        layout.addWidget(buttons)
        self._load(self.settings_value)

    def _path_row(self, edit: QLineEdit) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        button = QPushButton("浏览…")
        button.clicked.connect(lambda: self._choose_folder(edit))
        layout.addWidget(button)
        return row

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
        self.still_template = QLineEdit()
        self.open_after = QCheckBox("导出后打开文件夹")
        form.addRow("音频默认位置", self.audio_mode)
        form.addRow("音频自定义目录", self._path_row(self.audio_dir))
        form.addRow("静帧默认位置", self.still_mode)
        form.addRow("静帧自定义目录", self._path_row(self.still_dir))
        form.addRow("静帧格式", self.still_format)
        form.addRow("JPEG 质量", self.jpeg_quality)
        form.addRow("音频命名模板", self.audio_template)
        form.addRow("静帧命名模板", self.still_template)
        form.addRow("", self.open_after)
        return tab

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
        return tab

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
        form.addRow("", test_button)
        return tab

    def _choose_folder(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择目录", edit.text())
        if folder:
            edit.setText(folder)

    def _load(self, value: AppSettings) -> None:
        self.audio_mode.setCurrentIndex(self.audio_mode.findData(value.audio_output_mode))
        self.audio_dir.setText(value.audio_output_dir)
        self.still_mode.setCurrentIndex(self.still_mode.findData(value.still_output_mode))
        self.still_dir.setText(value.still_output_dir)
        self.still_format.setCurrentText(value.still_format)
        self.jpeg_quality.setValue(value.jpeg_quality)
        self.audio_template.setText(value.audio_naming_template)
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

    def value(self) -> AppSettings:
        return replace(
            self.settings_value,
            audio_output_mode=str(self.audio_mode.currentData()),
            audio_output_dir=self.audio_dir.text().strip(),
            still_output_mode=str(self.still_mode.currentData()),
            still_output_dir=self.still_dir.text().strip(),
            still_format=self.still_format.currentText(),
            jpeg_quality=self.jpeg_quality.value(),
            audio_naming_template=self.audio_template.text().strip(),
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
