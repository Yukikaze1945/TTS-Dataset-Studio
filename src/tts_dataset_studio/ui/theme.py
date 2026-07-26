APP_STYLE = """
QWidget {
    background: #11151b;
    color: #d9e1ea;
    font-family: "Microsoft YaHei UI";
    font-size: 10pt;
}
QMainWindow, QDialog { background: #0d1117; }
QFrame#panel {
    background: #161c24;
    border: 1px solid #28313d;
    border-radius: 8px;
}
QLabel#eyebrow {
    color: #718096;
    font-size: 8pt;
    font-weight: 700;
}
QLabel#title {
    color: #f3f7fb;
    font-size: 15pt;
    font-weight: 650;
    font-family: "Microsoft YaHei UI";
}
QLabel#timecode {
    color: #8de6d2;
    font-family: "Consolas";
    font-size: 17pt;
    font-weight: 650;
}
QPushButton, QToolButton {
    background: #202936;
    border: 1px solid #344152;
    border-radius: 5px;
    padding: 6px 10px;
}
QPushButton:hover, QToolButton:hover { background: #293649; border-color: #4a5d75; }
QPushButton:pressed, QToolButton:pressed { background: #16202d; }
QPushButton#accent {
    color: #061311;
    background: #62d5be;
    border-color: #78e7d1;
    font-weight: 700;
}
QPushButton#accent:hover { background: #81e8d4; }
QPushButton#danger {
    color: #ffffff;
    background: #b93a47;
    border-color: #e35b69;
    font-weight: 700;
}
QPushButton#danger:hover { background: #d14756; }
QPushButton#asrLoading {
    color: #8993a0;
    background: #252b34;
    border-color: #343c47;
}
QPushButton#timelineTool {
    background: #151d27;
    border-color: #2d3948;
    color: #c6d2df;
    font-family: "Microsoft YaHei UI";
    font-size: 9pt;
    padding: 4px 8px;
}
QPushButton#timelineTool:hover {
    color: #f2fffc;
    background: #234039;
    border-color: #55bdaa;
}
QLabel#selectionStatus {
    color: #ffca78;
    background: #211b13;
    border: 1px solid #5c4729;
    border-radius: 4px;
    padding: 4px 9px;
    font-family: "Consolas", "Microsoft YaHei UI";
}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #0d1218;
    border: 1px solid #313c4a;
    border-radius: 5px;
    padding: 5px 7px;
    selection-background-color: #277d70;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus { border-color: #62d5be; }
QListWidget, QTreeWidget {
    background: #10161d;
    border: 0;
    outline: 0;
}
QListWidget::item, QTreeWidget::item { padding: 7px 5px; border-radius: 4px; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #25433f; color: #eafffa; }
QHeaderView::section {
    background: #171f29;
    color: #8795a7;
    border: 0;
    border-bottom: 1px solid #2b3542;
    padding: 6px;
}
QSlider::groove:horizontal { height: 4px; background: #2a3543; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; margin: -5px 0; border-radius: 7px; background: #62d5be;
}
QProgressBar {
    background: #0b1016; border: 1px solid #2c3745; border-radius: 4px; text-align: center;
}
QProgressBar::chunk { background: #3db39e; border-radius: 3px; }
QScrollBar { background: #11171f; width: 11px; height: 11px; }
QScrollBar::handle { background: #344151; border-radius: 5px; min-width: 28px; min-height: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QSplitter::handle { background: #252f3b; }
QToolTip { background: #202936; color: #fff; border: 1px solid #46566b; }
"""
