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
            "window": "#0e1116",
            "surface": "#151a22",
            "raised": "#1c222d",
            "input": "#11161e",
            "border": "#2a3340",
            "text": "#f3f5f8",
            "muted": "#98a2b3",
            "accent": "#6c7cff",
            "accent_hover": "#8290ff",
            "accent_soft": "#202849",
            "selected": "#28335f",
            "audio": "#58d5be",
            "danger": "#ef646e",
            "tooltip": "#202631",
        }
        if dark
        else {
            "window": "#f4f6f9",
            "surface": "#ffffff",
            "raised": "#edf0f5",
            "input": "#ffffff",
            "border": "#d9dee7",
            "text": "#151922",
            "muted": "#657083",
            "accent": "#5365e8",
            "accent_hover": "#4557d5",
            "accent_soft": "#e8ebff",
            "selected": "#dfe4ff",
            "audio": "#168b78",
            "danger": "#d94753",
            "tooltip": "#252b36",
        }
    )
    c = colors
    return f"""
QWidget {{
    background: {c["window"]};
    color: {c["text"]};
    font-family: "Segoe UI Variable Text", "Microsoft YaHei UI", "Segoe UI";
    font-size: 10pt;
}}
QMainWindow, QDialog {{ background: {c["window"]}; }}
QFrame#panel, QFrame#previewPanel, QFrame#timelinePanel,
QFrame#libraryPanel, QFrame#propertyDrawer {{
    background: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
}}
QFrame#libraryPanel {{
    border-radius: 10px;
}}
QFrame#propertyDrawer {{
    border-left: 1px solid {c["border"]};
}}
QFrame#topBar {{
    background: {c["window"]};
    border: 0;
    border-bottom: 1px solid {c["border"]};
    border-radius: 0;
}}
QFrame#contextBar {{
    background: {c["accent_soft"]};
    border: 1px solid {c["accent"]};
    border-radius: 10px;
}}
QFrame#taskBar {{
    background: {c["surface"]};
    border-top: 1px solid {c["border"]};
}}
QWidget#emptyWorkspace {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {c["window"]},
        stop: 0.52 {c["window"]},
        stop: 1 {c["accent_soft"]}
    );
}}
QFrame#welcomeStep {{
    background: transparent;
    border: 0;
    border-left: 1px solid {c["border"]};
    border-radius: 0;
}}
QFrame#brandMark {{
    background: {c["accent"]};
    border: 0;
    border-radius: 10px;
}}
QFrame#signalBar {{
    background: white;
    border: 0;
    border-radius: 1px;
}}
QLabel#welcomeProduct {{
    color: {c["text"]};
    font-family: "Segoe UI Variable Display", "Microsoft YaHei UI";
    font-size: 12pt;
    font-weight: 650;
}}
QLabel#welcomeTitle {{
    color: {c["text"]};
    font-family: "Segoe UI Variable Display", "Microsoft YaHei UI";
    font-size: 27pt;
    font-weight: 650;
}}
QLabel#welcomeSubtitle {{
    color: {c["muted"]};
    font-size: 10.5pt;
    line-height: 1.5;
}}
QLabel#stepNumber {{
    color: {c["accent"]};
    font-family: "Cascadia Mono", "Consolas";
    font-size: 8.5pt;
    font-weight: 700;
}}
QLabel#stepTitle {{
    color: {c["text"]};
    font-weight: 650;
}}
QLabel#muted, QLabel#eyebrow {{
    color: {c["muted"]};
    font-size: 9pt;
}}
QLabel#title {{
    color: {c["text"]};
    font-family: "Segoe UI Variable Display", "Microsoft YaHei UI";
    font-size: 12pt;
    font-weight: 650;
}}
QLabel#settingsTitle {{
    color: {c["text"]};
    font-family: "Segoe UI Variable Display", "Microsoft YaHei UI";
    font-size: 20pt;
    font-weight: 650;
}}
QLabel#timecode {{
    color: {c["text"]};
    font-family: "Cascadia Mono", "Consolas";
    font-size: 12pt;
    font-weight: 600;
}}
QLabel#contextSummary {{
    color: {c["text"]};
    padding-left: 4px;
    font-weight: 600;
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
    border-radius: 7px;
    padding: 7px 12px;
}}
QPushButton:hover, QToolButton:hover {{
    background: {c["border"]};
    border-color: {c["border"]};
}}
QPushButton:pressed, QToolButton:pressed {{
    background: {c["selected"]};
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {c["muted"]};
    background: transparent;
    border-color: transparent;
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
QPushButton#secondaryAction {{
    color: {c["text"]};
    background: {c["raised"]};
    border: 1px solid {c["border"]};
    font-weight: 600;
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
QPushButton#timelineTool:checked {{
    color: {c["text"]};
    background: {c["accent_soft"]};
    border: 1px solid {c["accent"]};
}}
QPushButton#danger {{
    color: white;
    background: {c["danger"]};
}}
QPushButton#destructiveAction {{
    color: {c["danger"]};
    background: transparent;
    border: 1px solid transparent;
}}
QPushButton#destructiveAction:hover {{
    color: white;
    background: {c["danger"]};
}}
QToolButton#projectMenu {{
    background: {c["raised"]};
    border: 1px solid {c["border"]};
    padding: 6px 11px;
    font-weight: 600;
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
QFrame#settingsNav {{
    background: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
}}
QListWidget#settingsNavList {{
    background: transparent;
    border: 0;
}}
QListWidget#settingsNavList::item {{
    min-height: 24px;
    padding: 9px 10px;
    margin: 1px 0;
}}
QListWidget#settingsNavList::item:selected {{
    color: {c["text"]};
    background: {c["accent_soft"]};
    border-left: 3px solid {c["accent"]};
}}
QListWidget::item, QTreeWidget::item {{
    padding: 8px 9px;
    border-radius: 6px;
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
QTabWidget#libraryTabs::pane {{
    border: 0;
    background: transparent;
}}
QTabWidget#libraryTabs QTabBar::tab {{
    min-width: 62px;
    padding: 8px 10px;
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
    border-top: 1px solid {c["border"]};
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
QSplitter::handle {{
    background: {c["window"]};
    width: 6px;
    height: 6px;
}}
QSplitter::handle:hover {{ background: {c["accent_soft"]}; }}
QMenu {{
    background: {c["surface"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    border-radius: 5px;
    padding: 7px 28px 7px 10px;
}}
QMenu::item:selected {{ background: {c["selected"]}; }}
QToolTip {{
    background: {c["tooltip"]};
    color: white;
    border: 0;
    padding: 5px;
}}
"""


APP_STYLE = build_stylesheet("dark")
