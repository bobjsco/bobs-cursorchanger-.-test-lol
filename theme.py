"""
theme.py
========
Dark Neon QSS theme for CursorForge.
Black background, neon cyan (#00f0ff) + magenta (#ff2d95) accents.
"""

DARK_NEON_QSS = """
QWidget {
    background-color: #0a0a12;
    color: #e6e6e6;
    font-family: "Segoe UI", "Inter", "SF Pro Display", sans-serif;
    font-size: 13px;
}

QMainWindow, QDialog { background-color: #0a0a12; }

QScrollArea { background-color: transparent; border: none; }
QScrollArea > QWidget > QWidget { background-color: transparent; }

QGroupBox {
    background-color: #11111c;
    border: 1px solid #1f1f2e;
    border-radius: 8px;
    margin-top: 14px;
    padding: 14px 12px 10px 12px;
    font-weight: 700;
    color: #00f0ff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
    background: #0a0a12;
}

QLabel { background: transparent; color: #c5c5d0; }
QLabel#titleLabel {
    color: #00f0ff;
    font-size: 24px;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#subtitleLabel {
    color: #ff2d95;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}
QLabel#sectionLabel {
    color: #00f0ff;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
QLabel#hintLabel {
    color: #6b6b7a;
    font-size: 11px;
}

QPushButton {
    background-color: #1a1a26;
    color: #e6e6e6;
    border: 1px solid #2a2a3a;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #22222e;
    border-color: #00f0ff;
    color: #00f0ff;
}
QPushButton:pressed {
    background-color: #00f0ff;
    color: #0a0a12;
}
QPushButton:disabled {
    background-color: #14141f;
    color: #555;
    border-color: #1f1f2e;
}
QPushButton:checked {
    background-color: #00f0ff;
    color: #0a0a12;
    border-color: #00f0ff;
}
QPushButton#startBtn {
    background-color: #00f0ff;
    color: #0a0a12;
    border: none;
    font-weight: 800;
    font-size: 14px;
    padding: 12px 22px;
}
QPushButton#startBtn:hover { background-color: #33f3ff; }
QPushButton#startBtn:disabled {
    background-color: #0a3a40;
    color: #2a5a60;
}
QPushButton#stopBtn {
    background-color: #ff2d95;
    color: #0a0a12;
    border: none;
    font-weight: 800;
    font-size: 14px;
    padding: 12px 22px;
}
QPushButton#stopBtn:hover { background-color: #ff4fa9; }
QPushButton#stopBtn:disabled {
    background-color: #401428;
    color: #602838;
}
QPushButton#toggleBtn {
    background-color: #1a1a26;
    color: #00f0ff;
    border: 2px solid #00f0ff;
    font-weight: 700;
    font-size: 13px;
    padding: 10px 22px;
}
QPushButton#toggleBtn:hover {
    background-color: #00f0ff;
    color: #0a0a12;
}
QPushButton#toggleBtn:unchecked {
    color: #ff2d95;
    border-color: #ff2d95;
}
QPushButton#toggleBtn:unchecked:hover {
    background-color: #ff2d95;
    color: #0a0a12;
}
QPushButton#shapeBtn {
    background-color: #14141f;
    border: 1px solid #2a2a3a;
    border-radius: 6px;
    padding: 10px 6px;
    font-size: 11px;
    font-weight: 600;
    color: #888;
}
QPushButton#shapeBtn:hover {
    border-color: #00f0ff;
    color: #00f0ff;
    background-color: #1a1a26;
}
QPushButton#shapeBtn:checked {
    background-color: #00f0ff;
    color: #0a0a12;
    border-color: #00f0ff;
}
QPushButton#colorBtn {
    background-color: #1a1a26;
    border: 2px solid #2a2a3a;
    border-radius: 6px;
    padding: 18px;
}
QPushButton#colorBtn:hover { border-color: #00f0ff; }

QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
    background-color: #14141f;
    color: #e6e6e6;
    border: 1px solid #2a2a3a;
    border-radius: 5px;
    padding: 6px 10px;
    selection-background-color: #00f0ff;
    selection-color: #0a0a12;
}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus {
    border-color: #00f0ff;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #14141f;
    color: #e6e6e6;
    border: 1px solid #2a2a3a;
    selection-background-color: #00f0ff;
    selection-color: #0a0a12;
    outline: none;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #00f0ff;
    margin-right: 8px;
}

QSlider::groove:horizontal {
    height: 4px;
    background: #1f1f2e;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #00f0ff;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #0a0a12;
    border: 2px solid #00f0ff;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover { background: #00f0ff; }

QCheckBox { spacing: 8px; color: #c5c5d0; background: transparent; }
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #2a2a3a;
    border-radius: 3px;
    background: #14141f;
}
QCheckBox::indicator:checked {
    background: #00f0ff;
    border-color: #00f0ff;
    image: none;
}
QCheckBox::indicator:hover { border-color: #00f0ff; }

QTabWidget::pane {
    border: 1px solid #1f1f2e;
    background: #0d0d18;
    border-radius: 6px;
    margin-top: -1px;
}
QTabBar::tab {
    background: #14141f;
    color: #888;
    padding: 8px 16px;
    border: 1px solid #1f1f2e;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    font-weight: 600;
    min-width: 80px;
}
QTabBar::tab:selected {
    background: #0d0d18;
    color: #00f0ff;
    border-color: #00f0ff;
    border-bottom: 2px solid #00f0ff;
}
QTabBar::tab:hover:!selected {
    color: #ff2d95;
    background: #1a1a26;
}

QScrollBar:vertical {
    background: #0a0a12;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #2a2a3a;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #00f0ff; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QStatusBar {
    background: #0d0d18;
    color: #6b6b7a;
    border-top: 1px solid #1f1f2e;
}

QFrame#previewFrame {
    background: #0d0d18;
    border: 1px solid #1f1f2e;
    border-radius: 10px;
}

QMenu {
    background: #14141f;
    color: #e6e6e6;
    border: 1px solid #2a2a3a;
    padding: 6px;
}
QMenu::item { padding: 6px 18px; border-radius: 4px; }
QMenu::item:selected { background: #00f0ff; color: #0a0a12; }
QMenu::separator { height: 1px; background: #2a2a3a; margin: 4px 8px; }
"""
