from __future__ import annotations

import logging
import sys
from pathlib import Path

from platformdirs import user_log_path
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from tts_dataset_studio.domain.app_settings import AppSettings
from tts_dataset_studio.services.project_io import load_project
from tts_dataset_studio.ui.main_window import MainWindow
from tts_dataset_studio.ui.theme import build_stylesheet


def configure_logging() -> None:
    folder = user_log_path("TTS Dataset Studio", "OpenAI")
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(folder / "studio.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def load_application_fonts() -> None:
    windows_fonts = Path("C:/Windows/Fonts")
    for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
        font_path = windows_fonts / filename
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))


def main() -> int:
    configure_logging()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    load_application_fonts()
    app.setApplicationName("TTS Dataset Studio")
    app.setOrganizationName("OpenAI")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    settings = AppSettings.load(QSettings("OpenAI", "TTS Dataset Studio"))
    app.setStyleSheet(build_stylesheet(settings.theme))
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if path.suffix.lower() == ".ttds":
            window.project = load_project(path)
            for asset in window.project.assets:
                marker = "VIDEO" if asset.has_video else "AUDIO"
                window.asset_list.addItem(f"{marker}  {asset.display_name}")
            if window.project.active_asset:
                row = window.project.assets.index(window.project.active_asset)
                window.asset_list.setCurrentRow(row)
                window._activate_asset(window.project.active_asset)
        elif path.exists():
            window.import_paths([str(path)])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
