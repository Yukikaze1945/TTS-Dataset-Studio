from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


def system_theme() -> str:
    app = QApplication.instance()
    if app is None:
        return "dark"
    lightness = app.palette().color(QPalette.ColorRole.Window).lightness()
    return "dark" if lightness < 128 else "light"


def resolve_theme(preference: str) -> str:
    return system_theme() if preference == "system" else preference


def build_stylesheet(preference: str = "system") -> str:
    dark = resolve_theme(preference) == "dark"
    colors = (
        {
            "window": "#161616",
            "surface": "#212121",
            "raised": "#2b2b2b",
            "input": "#181818",
            "border": "#393939",
            "text": "#ececec",
            "muted": "#a5a5a5",
            "accent": "#10a37f",
            "accent_hover": "#19b58d",
            "selected": "#164c40",
            "danger": "#d34b52",
            "tooltip": "#303030",
        }
        if dark
        else {
            "window": "#f7f7f8",
            "surface": "#ffffff",
            "raised": "#f0f0f0",
            "input": "#ffffff",
            "border": "#dedede",
            "text": "#202123",
            "muted": "#6f7074",
            "accent": "#0f8f70",
            "accent_hover": "#087d62",
            "selected": "#dff3ed",
            "danger": "#c53f47",
            "tooltip": "#2f3033",
        }
    )
    c = colors
    return f"""
QWidget {{
    background: {c["window"]};
    color: {c["text"]};
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 10pt;
}}
QMainWindow, QDialog {{ background: {c["window"]}; }}
QFrame#panel, QFrame#previewPanel, QFrame#timelinePanel {{
    background: {c["surface"]};
    border: 0;
    border-radius: 12px;
}}
QFrame#topBar {{
    background: transparent;
    border: 0;
}}
QFrame#contextBar {{
    background: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 12px;
}}
QFrame#taskBar {{
    background: {c["surface"]};
    border-top: 1px solid {c["border"]};
}}
QFrame#welcomeCard {{
    background: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 18px;
}}
QFrame#welcomeStep {{
    background: {c["raised"]};
    border: 0;
    border-radius: 10px;
}}
QLabel#welcomeMark {{
    color: {c["accent"]};
    font-size: 30pt;
    font-weight: 700;
}}
QLabel#welcomeTitle {{
    color: {c["text"]};
    font-size: 22pt;
    font-weight: 650;
}}
QLabel#welcomeSubtitle {{
    color: {c["muted"]};
    font-size: 11pt;
    line-height: 1.5;
}}
QLabel#stepNumber {{
    color: {c["accent"]};
    font-size: 9pt;
    font-weight: 700;
}}
QLabel#stepTitle {{ font-weight: 650; }}
QLabel#muted, QLabel#eyebrow {{
    color: {c["muted"]};
    font-size: 9pt;
}}
QLabel#title {{
    color: {c["text"]};
    font-size: 13pt;
    font-weight: 650;
}}
QLabel#timecode {{
    color: {c["text"]};
    font-family: "Cascadia Mono", "Consolas";
    font-size: 12pt;
    font-weight: 600;
}}
QLabel#contextSummary {{
    color: {c["muted"]};
    padding-left: 4px;
}}
QLabel#selectionStatus {{
    color: {c["muted"]};
    background: transparent;
    border: 0;
    padding: 3px 6px;
}}
QPushButton, QToolButton {{
    background: {c["raised"]};
    color: {c["text"]};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 7px 11px;
}}
QPushButton:hover, QToolButton:hover {{
    background: {c["border"]};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {c["selected"]};
}}
QPushButton:disabled {{
    color: {c["muted"]};
    background: transparent;
}}
QPushButton#primaryAction, QPushButton#accent {{
    color: white;
    background: {c["accent"]};
    border: 0;
    font-weight: 650;
}}
QPushButton#primaryAction:hover, QPushButton#accent:hover {{
    background: {c["accent_hover"]};
}}
QPushButton#quietAction, QPushButton#timelineTool {{
    background: transparent;
    border: 0;
    color: {c["muted"]};
    padding: 5px 8px;
}}
QPushButton#quietAction:hover, QPushButton#timelineTool:hover {{
    color: {c["text"]};
    background: {c["raised"]};
}}
QPushButton#danger {{
    color: white;
    background: {c["danger"]};
}}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c["input"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: {c["accent"]};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {c["accent"]};
}}
QListWidget, QTreeWidget, QTabWidget::pane {{
    background: {c["surface"]};
    border: 0;
    outline: 0;
}}
QListWidget::item, QTreeWidget::item {{
    padding: 8px 7px;
    border-radius: 7px;
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {c["selected"]};
    color: {c["text"]};
}}
QHeaderView::section {{
    background: {c["surface"]};
    color: {c["muted"]};
    border: 0;
    border-bottom: 1px solid {c["border"]};
    padding: 7px;
}}
QTabBar::tab {{
    background: transparent;
    color: {c["muted"]};
    border: 0;
    padding: 8px 12px;
}}
QTabBar::tab:selected {{
    color: {c["text"]};
    border-bottom: 2px solid {c["accent"]};
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {c["border"]};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: {c["accent"]};
}}
QProgressBar {{
    background: {c["border"]};
    border: 0;
    border-radius: 2px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {c["accent"]};
    border-radius: 2px;
}}
QStatusBar {{
    background: {c["window"]};
    color: {c["muted"]};
    border: 0;
}}
QScrollBar {{
    background: transparent;
    width: 10px;
    height: 10px;
}}
QScrollBar::handle {{
    background: {c["border"]};
    border-radius: 5px;
    min-width: 28px;
    min-height: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QSplitter::handle {{ background: {c["window"]}; }}
QToolTip {{
    background: {c["tooltip"]};
    color: white;
    border: 0;
    padding: 5px;
}}
"""


APP_STYLE = build_stylesheet("dark")
