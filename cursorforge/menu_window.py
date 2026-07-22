"""
menu_window.py
==============
CursorForge main menu window.

Layout:
  +-----------------------------------+
  |  Title + subtitle                 |
  |  [    live preview (sticky)    ]  |
  |  --- Shape grid (14 shapes) ---   |
  |  --- Fill mode tabs ---           |
  |    Solid | Gradient | Image | Glass|
  |  --- Effects ---                  |
  |    Glow / Shadow / Outline / HL   |
  |  --- Size & Rotation ---          |
  |  --- Animations ---               |
  |    Pulse / Color cycle / Spin /   |
  |    Trail                          |
  |  --- Motion ---                   |
  |    Squish / Inertia               |
  |  [APPLY] [RESTORE] [PRESETS]      |
  +-----------------------------------+
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, QSize
from PyQt5.QtGui import (
    QPainter, QColor, QPixmap, QIcon, QImage, QLinearGradient,
    QRadialGradient, QPen, QBrush,
)
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QComboBox,
    QCheckBox, QGroupBox, QSlider, QStatusBar, QMessageBox,
    QSystemTrayIcon, QMenu, QAction, QFileDialog, QFrame,
    QFormLayout, QScrollArea, QTabWidget, QColorDialog, QInputDialog,
    QSizePolicy, QButtonGroup,
)

from theme import DARK_NEON_QSS
from cursor_painter import CursorConfig, CursorPainter, RGB
from overlay import CursorOverlay, IS_WINDOWS
import shapes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_app_icon() -> QPixmap:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#00f0ff"), 3))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(8, 8, 48, 48)
    p.setBrush(QColor("#ff2d95"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(22, 22, 20, 20)
    p.end()
    return pm


def _color_button_style(rgb: RGB) -> str:
    r, g, b = rgb
    return f"background-color: rgb({r},{g},{b}); border: 2px solid #2a2a3a; border-radius: 6px;"


def _app_data_dir() -> Path:
    base = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "CursorForge") \
        if IS_WINDOWS else os.path.dirname(os.path.abspath(sys.argv[0]))
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _make_fake_screen_image(w: int = 240, h: int = 240) -> QImage:
    """Generate a colorful background image to demo the glass refraction
    effect in the menu preview (where we can't capture the real screen)."""
    pm = QPixmap(w, h)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    # Diagonal multi-color gradient
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0.0, QColor(255, 80, 120))
    grad.setColorAt(0.33, QColor(255, 200, 80))
    grad.setColorAt(0.66, QColor(80, 220, 200))
    grad.setColorAt(1.0, QColor(120, 100, 255))
    p.fillRect(0, 0, w, h, QBrush(grad))
    # Some distinct shapes so refraction is visible
    p.setBrush(QColor(255, 255, 255, 230))
    p.setPen(Qt.NoPen)
    p.drawEllipse(40, 50, 50, 50)
    p.drawRect(140, 30, 60, 80)
    p.drawEllipse(160, 160, 60, 40)
    # Grid lines (so distortion is obvious)
    p.setPen(QPen(QColor(0, 0, 0, 80), 1))
    for x in range(0, w, 20):
        p.drawLine(x, 0, x, h)
    for y in range(0, h, 20):
        p.drawLine(0, y, w, y)
    # Text "BEHIND CURSOR" so refraction is obvious
    p.setPen(QPen(QColor(20, 20, 30, 220), 1))
    font = p.font()
    font.setPointSize(10)
    font.setBold(True)
    p.setFont(font)
    p.drawText(20, 130, "GLASS REFRACTION DEMO")
    p.end()
    return pm.toImage()


# ---------------------------------------------------------------------------
# Live preview widget
# ---------------------------------------------------------------------------
class CursorPreview(QFrame):
    """Sticky preview that paints the cursor centered. Includes:
      - Optional animated circular motion (to demo squish + inertia)
      - Fake "screen behind" image for glass refraction demo"""

    def __init__(self, painter: CursorPainter, parent=None):
        super().__init__(parent)
        self.painter = painter
        self.setObjectName("previewFrame")
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._animate = False
        self._anim_start = time.monotonic()
        self._fake_screen = _make_fake_screen_image()

        # Animate at 60 FPS
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    def set_animate(self, on: bool):
        self._animate = on
        if on:
            self._anim_start = time.monotonic()
            self.painter.reset_animations()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # Background: dark with grid
        p.fillRect(self.rect(), QColor("#0d0d18"))
        grid_color = QColor("#15151f")
        pen = QPen(grid_color, 1)
        p.setPen(pen)
        step = 20
        for x in range(0, self.width(), step):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), step):
            p.drawLine(0, y, self.width(), y)

        cx = self.width() / 2
        cy = self.height() / 2

        if self._animate:
            # Circular motion: cursor moves in a circle of radius R
            t = time.monotonic() - self._anim_start
            R = min(self.width(), self.height()) * 0.25
            # Angular velocity ~1.5 rad/sec (one revolution every ~4 sec)
            omega = 1.5
            # Use a square path with sharp stops so inertia/squish is visible
            phase = (t * omega) % (2 * math.pi)
            # Sine for smooth motion
            mx = cx + R * math.cos(phase)
            my = cy + R * math.sin(phase)
            # Update motion physics with simulated cursor position
            vx, vy = self.painter.update_motion(mx, my)
            dx, dy = self.painter.get_drawing_offset()
            # Draw the fake screen behind cursor (so glass refracts something)
            if self.painter.config.fill_mode == "glass":
                p.drawImage(QRectF(mx - 60, my - 60, 120, 120),
                            self._fake_screen,
                            QRectF(0, 0, self._fake_screen.width(),
                                   self._fake_screen.height()))
            # Pass a crop of the fake screen as the "screen capture" for glass
            sc = None
            if self.painter.config.fill_mode == "glass":
                # Crop a 120x120 region centered on cursor (in widget coords)
                cap = QImage(120, 120, QImage.Format_ARGB32)
                cap.fill(QColor(20, 20, 30, 255))
                cp = QPainter(cap)
                cp.setRenderHint(QPainter.SmoothPixmapTransform, True)
                src_rect = QRectF(mx - 60, my - 60, 120, 120)
                cp.drawImage(QRectF(0, 0, 120, 120), self._fake_screen, src_rect)
                cp.end()
                sc = cap
            self.painter.paint(p, mx + dx, my + dy,
                               vx=vx, vy=vy, screen_capture=sc)
        else:
            # Static: cursor at center
            # For glass, show a slice of the fake screen behind
            if self.painter.config.fill_mode == "glass":
                p.drawImage(QRectF(cx - 60, cy - 60, 120, 120),
                            self._fake_screen,
                            QRectF(0, 0, self._fake_screen.width(),
                                   self._fake_screen.height()))
            sc = None
            if self.painter.config.fill_mode == "glass":
                cap = QImage(120, 120, QImage.Format_ARGB32)
                cap.fill(QColor(20, 20, 30, 255))
                cp = QPainter(cap)
                cp.drawImage(QRectF(0, 0, 120, 120), self._fake_screen,
                             QRectF(self._fake_screen.width() / 2 - 60,
                                    self._fake_screen.height() / 2 - 60,
                                    120, 120))
                cp.end()
                sc = cap
            self.painter.paint(p, cx, cy, screen_capture=sc)


# ---------------------------------------------------------------------------
# Color button
# ---------------------------------------------------------------------------
class ColorButton(QPushButton):
    def __init__(self, rgb: RGB = (255, 255, 255), parent=None):
        super().__init__(parent)
        self.setObjectName("colorBtn")
        self._rgb = rgb
        self._update_style()
        self.clicked.connect(self._open)

    def _update_style(self):
        self.setStyleSheet(_color_button_style(self._rgb))
        self.setText(f"  RGB{self._rgb}  ")

    def _open(self):
        c = QColorDialog.getColor(
            QColor(*self._rgb), self, "Pick color",
            QColorDialog.ShowAlphaChannel,
        )
        if c.isValid():
            self._rgb = (c.red(), c.green(), c.blue())
            self._update_style()

    def color(self) -> RGB:
        return self._rgb

    def set_color(self, rgb: RGB):
        self._rgb = rgb
        self._update_style()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MenuWindow(QMainWindow):
    SHAPES = shapes.SHAPE_NAMES

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CursorForge")
        self.setMinimumSize(640, 900)
        self.resize(640, 960)
        self.setStyleSheet(DARK_NEON_QSS)

        self.icon = QIcon(_make_app_icon())
        self.setWindowIcon(self.icon)

        self.cursor_painter = CursorPainter()
        self.overlay = CursorOverlay(self.cursor_painter)
        # Ball physics overlay (separate window, click-through toggle)
        from ball_overlay import BallOverlay
        self.ball_overlay = BallOverlay()

        self._build_ui()
        self._build_tray()

        QTimer.singleShot(100, self.overlay.show)
        self.settings_path = _app_data_dir() / "cursorforge.json"
        QTimer.singleShot(150, self._load_settings)

    # ---------- UI ----------
    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        central = QWidget()
        scroll.setWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(12)

        # --- Header ---
        title = QLabel("CURSORFORGE")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        sub = QLabel("custom cursor studio  ·  glass · gradient · image · motion")
        sub.setObjectName("subtitleLabel")
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)

        # --- Live preview + animate toggle ---
        self.preview = CursorPreview(self.cursor_painter)
        layout.addWidget(self.preview)

        anim_row = QHBoxLayout()
        self.animate_cb = QCheckBox("Animate preview (test motion + glass)")
        self.animate_cb.toggled.connect(self.preview.set_animate)
        anim_row.addWidget(self.animate_cb)
        anim_row.addStretch()
        layout.addLayout(anim_row)

        # --- Shape grid ---
        shape_group = QGroupBox("SHAPE")
        sg = QGridLayout(shape_group)
        sg.setSpacing(6)
        self.shape_buttons = QButtonGroup(self)
        self.shape_buttons.setExclusive(True)
        cols = 4
        for i, name in enumerate(self.SHAPES):
            b = QPushButton(name)
            b.setObjectName("shapeBtn")
            b.setCheckable(True)
            if name == self.cursor_painter.config.shape:
                b.setChecked(True)
            b.clicked.connect(lambda _, n=name: self._set_shape(n))
            self.shape_buttons.addButton(b)
            sg.addWidget(b, i // cols, i % cols)
        layout.addWidget(shape_group)

        # --- Fill mode tabs ---
        fill_group = QGroupBox("FILL")
        fl = QVBoxLayout(fill_group)
        self.fill_tabs = QTabWidget()

        # Solid tab
        solid_tab = QWidget()
        stl = QHBoxLayout(solid_tab)
        stl.addWidget(QLabel("Color:"))
        self.solid_color_btn = ColorButton(self.cursor_painter.config.color)
        self.solid_color_btn.clicked.connect(
            lambda: self._sync_to_config({"color": self.solid_color_btn.color()})
        )
        stl.addWidget(self.solid_color_btn, 1)
        self.fill_tabs.addTab(solid_tab, "Solid")

        # Gradient tab
        grad_tab = QWidget()
        gl = QVBoxLayout(grad_tab)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Type:"))
        self.grad_type = QComboBox()
        self.grad_type.addItems(["linear", "radial", "conic"])
        row1.addWidget(self.grad_type)
        row1.addWidget(QLabel("Angle:"))
        self.grad_angle = QSpinBox()
        self.grad_angle.setRange(0, 360)
        self.grad_angle.setValue(45)
        row1.addWidget(self.grad_angle)
        row1.addStretch()
        gl.addLayout(row1)
        self.grad_color_btns = []
        for i, (pos, rgb) in enumerate(self.cursor_painter.config.gradient_stops):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"Stop {i+1}:"))
            cb = ColorButton(rgb)
            self.grad_color_btns.append(cb)
            row.addWidget(cb, 1)
            gl.addLayout(row)
        self.grad_type.currentTextChanged.connect(self._sync_grad)
        self.grad_angle.valueChanged.connect(self._sync_grad)
        for cb in self.grad_color_btns:
            cb.clicked.connect(self._sync_grad)
        self.fill_tabs.addTab(grad_tab, "Gradient")

        # Image tab
        img_tab = QWidget()
        il = QVBoxLayout(img_tab)
        row = QHBoxLayout()
        row.addWidget(QLabel("Image:"))
        self.img_path_label = QLabel("(none - click Browse)")
        self.img_path_label.setObjectName("hintLabel")
        row.addWidget(self.img_path_label, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._pick_image)
        row.addWidget(browse)
        il.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Mode:"))
        self.img_mode = QComboBox()
        self.img_mode.addItems(["replace", "attached"])
        row2.addWidget(self.img_mode)
        row2.addWidget(QLabel("Scale:"))
        self.img_scale = QDoubleSpinBox()
        self.img_scale.setRange(0.1, 5.0)
        self.img_scale.setSingleStep(0.1)
        self.img_scale.setValue(1.0)
        row2.addWidget(self.img_scale)
        row2.addStretch()
        il.addLayout(row2)
        self.img_mode.currentTextChanged.connect(self._sync_img)
        self.img_scale.valueChanged.connect(self._sync_img)
        self.fill_tabs.addTab(img_tab, "Image")

        # Glass tab (new)
        glass_tab = QWidget()
        glas = QFormLayout(glass_tab)
        glas.setSpacing(8)
        # Tint color
        tint_row = QHBoxLayout()
        tint_row.addWidget(QLabel("Tint:"))
        self.glass_tint_btn = ColorButton(self.cursor_painter.config.glass_tint)
        tint_row.addWidget(self.glass_tint_btn, 1)
        glas.addRow(tint_row)
        self.glass_tint_amount = self._slider_row(glas, "Tint amount:", 0, 100, 10)
        self.glass_refraction = self._slider_row(glas, "Refraction (bulge):", 0, 100, 45)
        self.glass_magnification = self._slider_row(glas, "Magnification:", 0, 100, 30)
        self.glass_edge = self._slider_row(glas, "Edge brightness:", 0, 100, 70)
        self.glass_edge_width = self._slider_row(glas, "Edge width:", 1, 6, 2)
        self.glass_specular_cb = QCheckBox("Specular highlight (glossy spot)")
        self.glass_specular_cb.setChecked(True)
        glas.addRow(self.glass_specular_cb)
        # Wire glass controls
        self.glass_tint_btn.clicked.connect(self._sync_glass)
        self.glass_tint_amount.valueChanged.connect(self._sync_glass)
        self.glass_refraction.valueChanged.connect(self._sync_glass)
        self.glass_magnification.valueChanged.connect(self._sync_glass)
        self.glass_edge.valueChanged.connect(self._sync_glass)
        self.glass_edge_width.valueChanged.connect(self._sync_glass)
        self.glass_specular_cb.toggled.connect(self._sync_glass)
        self.fill_tabs.addTab(glass_tab, "Glass")

        self.fill_tabs.currentChanged.connect(self._on_fill_tab_changed)
        self.fill_tabs.setCurrentIndex(0)
        fl.addWidget(self.fill_tabs)
        layout.addWidget(fill_group)

        # --- Effects ---
        eff_group = QGroupBox("EFFECTS")
        el = QFormLayout(eff_group)
        el.setSpacing(8)
        self.glow_intensity = self._slider_row(el, "Glow intensity:", 0, 100, 60)
        self.glow_radius = self._slider_row(el, "Glow radius:", 0, 80, 24)
        self.shadow_intensity = self._slider_row(el, "Shadow intensity:", 0, 100, 35)
        self.shadow_off_x = self._slider_row(el, "Shadow offset X:", -20, 20, 3)
        self.shadow_off_y = self._slider_row(el, "Shadow offset Y:", -20, 20, 3)
        self.outline_width = self._slider_row(el, "Outline width:", 0, 10, 0)
        outline_row = QHBoxLayout()
        outline_row.addWidget(QLabel("Outline color:"))
        self.outline_color_btn = ColorButton(self.cursor_painter.config.outline_color)
        outline_row.addWidget(self.outline_color_btn, 1)
        el.addRow(outline_row)
        self.highlight_cb = QCheckBox("Inner highlight (glossy)")
        self.highlight_cb.setChecked(True)
        el.addRow(self.highlight_cb)
        layout.addWidget(eff_group)

        # --- Size & Rotation ---
        sr_group = QGroupBox("SIZE & ROTATION")
        srl = QFormLayout(sr_group)
        self.size_slider = self._slider_row(srl, "Size:", 4, 120, 32)
        self.rotation_slider = self._slider_row(srl, "Rotation:", 0, 360, 0)
        layout.addWidget(sr_group)

        # --- Animations ---
        anim_group = QGroupBox("ANIMATION")
        al = QFormLayout(anim_group)
        al.setSpacing(8)
        pulse_row = QHBoxLayout()
        self.pulse_cb = QCheckBox("Pulse (size breathing)")
        pulse_row.addWidget(self.pulse_cb)
        pulse_row.addWidget(QLabel("Speed:"))
        self.pulse_speed = self._slider_inline(0, 100, 50)
        pulse_row.addWidget(self.pulse_speed)
        pulse_row.addWidget(QLabel("Amount:"))
        self.pulse_amount = self._slider_inline(0, 100, 25)
        pulse_row.addWidget(self.pulse_amount)
        al.addRow(pulse_row)

        cc_row = QHBoxLayout()
        self.cc_cb = QCheckBox("Color cycle (rainbow hue rotation)")
        cc_row.addWidget(self.cc_cb)
        cc_row.addWidget(QLabel("Speed:"))
        self.cc_speed = self._slider_inline(0, 100, 30)
        cc_row.addWidget(self.cc_speed)
        al.addRow(cc_row)

        spin_row = QHBoxLayout()
        self.spin_cb = QCheckBox("Spin (continuous rotation)")
        spin_row.addWidget(self.spin_cb)
        spin_row.addWidget(QLabel("Speed:"))
        self.spin_speed = self._slider_inline(0, 100, 50)
        spin_row.addWidget(self.spin_speed)
        al.addRow(spin_row)

        trail_row = QHBoxLayout()
        self.trail_cb = QCheckBox("Trail (motion ghosts)")
        trail_row.addWidget(self.trail_cb)
        trail_row.addWidget(QLabel("Length:"))
        self.trail_length = self._slider_inline(2, 40, 12)
        trail_row.addWidget(self.trail_length)
        trail_row.addWidget(QLabel("Fade:"))
        self.trail_fade = self._slider_inline(0, 100, 60)
        trail_row.addWidget(self.trail_fade)
        al.addRow(trail_row)
        layout.addWidget(anim_group)

        # --- Motion (new) ---
        motion_group = QGroupBox("MOTION")
        ml = QFormLayout(motion_group)
        ml.setSpacing(8)

        # Squish
        squish_row = QHBoxLayout()
        self.squish_cb = QCheckBox("Velocity squish (stretch in motion direction)")
        self.squish_cb.setChecked(True)
        squish_row.addWidget(self.squish_cb)
        squish_row.addWidget(QLabel("Amount:"))
        self.squish_amount = self._slider_inline(0, 100, 50)
        squish_row.addWidget(self.squish_amount)
        ml.addRow(squish_row)
        self.squish_threshold = self._slider_row(ml, "Squish threshold (px/sec):", 50, 2000, 200)

        # Inertia
        inertia_row = QHBoxLayout()
        self.inertia_cb = QCheckBox("Inertia (overshoot + ease back on stop)")
        self.inertia_cb.setChecked(True)
        inertia_row.addWidget(self.inertia_cb)
        inertia_row.addWidget(QLabel("Amount:"))
        self.inertia_amount = self._slider_inline(0, 100, 50)
        inertia_row.addWidget(self.inertia_amount)
        ml.addRow(inertia_row)
        layout.addWidget(motion_group)

        # --- Buttons ---
        btns = QHBoxLayout()
        self.apply_btn = QPushButton("APPLY (live)")
        self.apply_btn.setObjectName("startBtn")
        self.apply_btn.clicked.connect(self._apply_live)
        btns.addWidget(self.apply_btn)
        self.restore_btn = QPushButton("RESTORE SYSTEM CURSOR")
        self.restore_btn.setObjectName("stopBtn")
        self.restore_btn.clicked.connect(self._restore)
        btns.addWidget(self.restore_btn)
        layout.addLayout(btns)

        # --- Toggle cursor effect button ---
        self.toggle_btn = QPushButton("HIDE CURSOR EFFECT")
        self.toggle_btn.setObjectName("toggleBtn")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.clicked.connect(self._toggle_effect)
        layout.addWidget(self.toggle_btn)

        # --- Ball Physics section ---
        ball_group = QGroupBox("BALL PHYSICS")
        ball_layout = QVBoxLayout(ball_group)
        ball_layout.setContentsMargins(12, 10, 12, 12)
        ball_layout.setSpacing(8)

        ball_header = QHBoxLayout()
        ball_header.addWidget(QLabel(""))
        ball_header.addStretch()
        self.ball_enable_cb = QCheckBox("Enable ball mode")
        self.ball_enable_cb.toggled.connect(self._toggle_balls)
        ball_header.addWidget(self.ball_enable_cb)
        ball_layout.addLayout(ball_header)

        ball_hint = QLabel("Click anywhere to spawn a ball. Drag a ball to throw it.\n"
                           "Balls bounce off screen edges + each other. Despawn after 5s idle.")
        ball_hint.setStyleSheet("color: #8888aa; font-size: 10px;")
        ball_hint.setWordWrap(True)
        ball_layout.addWidget(ball_hint)

        ball_form = QFormLayout()
        ball_form.setLabelAlignment(Qt.AlignRight)
        self.ball_size_slider = self._slider_row(ball_form, "Ball size:", 8, 80, 28)
        self.ball_bounce_slider = self._slider_row(ball_form, "Bounciness:", 0, 100, 65)
        self.ball_gravity_slider = self._slider_row(ball_form, "Gravity:", 0, 100, 50)

        # Ball color row
        color_row = QHBoxLayout()
        self.ball_color_btn = ColorButton((255, 80, 120))
        color_row.addWidget(self.ball_color_btn)
        self.ball_random_color_cb = QCheckBox("Random colors")
        self.ball_random_color_cb.setChecked(True)
        color_row.addWidget(self.ball_random_color_cb)
        color_row.addStretch()
        ball_form.addRow("Ball color:", color_row)

        # Clear balls button
        clear_row = QHBoxLayout()
        self.clear_balls_btn = QPushButton("Clear all balls")
        self.clear_balls_btn.clicked.connect(self._clear_balls)
        clear_row.addWidget(self.clear_balls_btn)
        clear_row.addStretch()
        ball_form.addRow("", clear_row)

        ball_layout.addLayout(ball_form)
        layout.addWidget(ball_group)

        # Wire ball controls
        self.ball_size_slider.valueChanged.connect(self._sync_ball_config)
        self.ball_bounce_slider.valueChanged.connect(self._sync_ball_config)
        self.ball_gravity_slider.valueChanged.connect(self._sync_ball_config)
        self.ball_color_btn.clicked.connect(self._sync_ball_config)
        self.ball_random_color_cb.toggled.connect(self._sync_ball_config)
        self._sync_ball_config()

        btns2 = QHBoxLayout()
        save_btn = QPushButton("Save preset")
        save_btn.clicked.connect(self._save_preset)
        btns2.addWidget(save_btn)
        load_btn = QPushButton("Load preset")
        load_btn.clicked.connect(self._load_preset)
        btns2.addWidget(load_btn)
        reset_btn = QPushButton("Reset to defaults")
        reset_btn.clicked.connect(self._reset_defaults)
        btns2.addWidget(reset_btn)
        layout.addLayout(btns2)

        layout.addStretch()
        # Version footer label - visible at the bottom of the scroll area,
        # above the status bar. Includes the GitHub repo link.
        from splash import APP_VERSION as _SPLASH_VER, GITHUB_REPO as _GITHUB
        self._version_label = QLabel(
            f'<style>a {{ color: #00f0ff; text-decoration: none; }}</style>'
            f'<div style="color: #5a5a7a; font-size: 10px; padding: 8px;">'
            f'CursorForge v{_SPLASH_VER} &nbsp;-&nbsp; custom cursor studio &nbsp;|&nbsp; '
            f'<a href="{_GITHUB}">{_GITHUB}</a>'
            f'</div>'
        )
        self._version_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self._version_label.setOpenExternalLinks(True)
        self._version_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(self._version_label)

        self.setCentralWidget(scroll)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel("Ready")
        self.status.addPermanentWidget(self.status_label)
        # Also add the version as a permanent widget on the right of the
        # status bar so it's always visible regardless of scroll position.
        self._status_version = QLabel(f"v{_SPLASH_VER}")
        self._status_version.setStyleSheet(
            "color: #00f0ff; padding: 0 8px; font-weight: bold;"
        )
        self.status.addPermanentWidget(self._status_version)
        # GitHub link in the status bar (clickable)
        self._status_github = QLabel(
            f'<style>a {{ color: #7a7a9a; text-decoration: none; }}</style>'
            f'<a href="{_GITHUB}">GitHub</a>'
        )
        self._status_github.setOpenExternalLinks(True)
        self._status_github.setStyleSheet("padding: 0 8px;")
        self.status.addPermanentWidget(self._status_github)

        self._wire_all_controls()

    def _slider_row(self, form: QFormLayout, label: str, lo: int, hi: int, default: int) -> QSlider:
        row = QHBoxLayout()
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(default)
        v = QLabel(str(default))
        v.setMinimumWidth(40)
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        s.valueChanged.connect(lambda n: v.setText(str(n)))
        row.addWidget(s, 1)
        row.addWidget(v)
        form.addRow(label, row)
        return s

    def _slider_inline(self, lo: int, hi: int, default: int) -> QSlider:
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(default)
        s.setFixedWidth(100)
        return s

    # ---------- tray ----------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip("CursorForge")
        menu = QMenu()
        show = QAction("Show", self)
        show.triggered.connect(self._show_normal)
        menu.addAction(show)
        toggle = QAction("Toggle overlay", self)
        toggle.triggered.connect(self._toggle_overlay)
        menu.addAction(toggle)
        restore = QAction("Restore system cursor", self)
        restore.triggered.connect(self._restore)
        menu.addAction(restore)
        menu.addSeparator()
        quit_a = QAction("Quit", self)
        quit_a.triggered.connect(self._quit)
        menu.addAction(quit_a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _show_normal(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_normal()

    def _toggle_overlay(self):
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            self.overlay.show()

    # ---------- toggle cursor effect ----------
    def _toggle_effect(self):
        """Toggle the whole custom cursor effect on/off via the button."""
        if self.toggle_btn.isChecked():
            # Show cursor effect
            if not self.overlay.isVisible():
                self.overlay.show()
            self.toggle_btn.setText("HIDE CURSOR EFFECT")
            self.status_label.setText("Cursor effect ON")
        else:
            # Hide cursor effect
            if self.overlay.isVisible():
                self.overlay.hide()
            self.toggle_btn.setText("SHOW CURSOR EFFECT")
            self.status_label.setText("Cursor effect OFF")

    # ---------- ball physics ----------
    def _toggle_balls(self, on: bool):
        self.ball_overlay.set_enabled(on)
        if on:
            self.status_label.setText("Ball mode ON — click to spawn, drag to throw")
        else:
            self.status_label.setText("Ball mode OFF")

    def _sync_ball_config(self):
        self.ball_overlay.set_ball_size(self.ball_size_slider.value())
        self.ball_overlay.set_ball_bounciness(self.ball_bounce_slider.value())
        self.ball_overlay.set_ball_gravity(self.ball_gravity_slider.value())
        self.ball_overlay.set_ball_color(self.ball_color_btn.color())
        self.ball_overlay.set_random_colors(self.ball_random_color_cb.isChecked())

    def _clear_balls(self):
        self.ball_overlay.balls.clear()
        self.status_label.setText("Cleared all balls")

    # ---------- shape / fill ----------
    def _set_shape(self, name: str):
        self._sync_to_config({"shape": name})

    def _on_fill_tab_changed(self, idx: int):
        mode = ["solid", "gradient", "image", "glass"][idx]
        self._sync_to_config({"fill_mode": mode})

    def _sync_grad(self):
        stops = []
        for i, cb in enumerate(self.grad_color_btns):
            pos = i / max(1, len(self.grad_color_btns) - 1)
            stops.append((pos, cb.color()))
        self._sync_to_config({
            "gradient_type": self.grad_type.currentText(),
            "gradient_angle": self.grad_angle.value(),
            "gradient_stops": stops,
        })

    def _sync_img(self):
        self._sync_to_config({
            "image_mode": self.img_mode.currentText(),
            "image_scale": self.img_scale.value(),
        })

    def _sync_glass(self):
        self._sync_to_config({
            "glass_tint": self.glass_tint_btn.color(),
            "glass_tint_amount": self.glass_tint_amount.value(),
            "glass_refraction": self.glass_refraction.value(),
            "glass_magnification": self.glass_magnification.value(),
            "glass_edge": self.glass_edge.value(),
            "glass_edge_width": self.glass_edge_width.value(),
            "glass_specular": self.glass_specular_cb.isChecked(),
        })

    def _sync_anim(self):
        self._sync_to_config({
            "pulse": self.pulse_cb.isChecked(),
            "pulse_speed": self.pulse_speed.value(),
            "pulse_amount": self.pulse_amount.value(),
            "color_cycle": self.cc_cb.isChecked(),
            "color_cycle_speed": self.cc_speed.value(),
            "spin": self.spin_cb.isChecked(),
            "spin_speed": self.spin_speed.value(),
            "trail": self.trail_cb.isChecked(),
            "trail_length": self.trail_length.value(),
            "trail_fade": self.trail_fade.value(),
        })

    def _sync_motion(self):
        self._sync_to_config({
            "motion_squish": self.squish_cb.isChecked(),
            "motion_squish_amount": self.squish_amount.value(),
            "motion_squish_threshold": self.squish_threshold.value(),
            "motion_inertia": self.inertia_cb.isChecked(),
            "motion_inertia_amount": self.inertia_amount.value(),
        })

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*.*)",
        )
        if path:
            self.cursor_painter.config.image_path = path
            self.img_path_label.setText(os.path.basename(path))
            self.img_path_label.setToolTip(path)

    # ---------- wire all controls ----------
    def _wire_all_controls(self):
        # Effects
        self.glow_intensity.valueChanged.connect(
            lambda v: self._sync_to_config({"glow_intensity": v}))
        self.glow_radius.valueChanged.connect(
            lambda v: self._sync_to_config({"glow_radius": v}))
        self.shadow_intensity.valueChanged.connect(
            lambda v: self._sync_to_config({"shadow_intensity": v}))
        self.shadow_off_x.valueChanged.connect(
            lambda v: self._sync_to_config({"shadow_offset_x": v}))
        self.shadow_off_y.valueChanged.connect(
            lambda v: self._sync_to_config({"shadow_offset_y": v}))
        self.outline_width.valueChanged.connect(
            lambda v: self._sync_to_config({"outline_width": v}))
        self.outline_color_btn.clicked.connect(
            lambda: self._sync_to_config({"outline_color": self.outline_color_btn.color()}))
        self.highlight_cb.toggled.connect(
            lambda v: self._sync_to_config({"highlight": v}))
        # Size & rotation
        self.size_slider.valueChanged.connect(
            lambda v: self._sync_to_config({"size": v}))
        self.rotation_slider.valueChanged.connect(
            lambda v: self._sync_to_config({"rotation": v}))
        # Animations
        self.pulse_cb.toggled.connect(self._sync_anim)
        self.pulse_speed.valueChanged.connect(self._sync_anim)
        self.pulse_amount.valueChanged.connect(self._sync_anim)
        self.cc_cb.toggled.connect(self._sync_anim)
        self.cc_speed.valueChanged.connect(self._sync_anim)
        self.spin_cb.toggled.connect(self._sync_anim)
        self.spin_speed.valueChanged.connect(self._sync_anim)
        self.trail_cb.toggled.connect(self._sync_anim)
        self.trail_length.valueChanged.connect(self._sync_anim)
        self.trail_fade.valueChanged.connect(self._sync_anim)
        # Motion
        self.squish_cb.toggled.connect(self._sync_motion)
        self.squish_amount.valueChanged.connect(self._sync_motion)
        self.squish_threshold.valueChanged.connect(self._sync_motion)
        self.inertia_cb.toggled.connect(self._sync_motion)
        self.inertia_amount.valueChanged.connect(self._sync_motion)
        # Solid color
        self.solid_color_btn.clicked.connect(
            lambda: self._sync_to_config({"color": self.solid_color_btn.color()}))

    def _sync_to_config(self, updates: dict):
        cfg = self.cursor_painter.config
        for k, v in updates.items():
            setattr(cfg, k, v)
        if any(k in updates for k in ("pulse", "color_cycle", "spin", "trail")):
            self.cursor_painter.reset_animations()
        self._set_status(f"Live · shape={cfg.shape} · size={cfg.size} · "
                         f"fill={cfg.fill_mode}")

    def _set_status(self, text: str):
        self.status_label.setText(text)

    # ---------- apply / restore ----------
    def _apply_live(self):
        if not self.overlay.isVisible():
            self.overlay.show()
        self.cursor_painter.reset_animations()
        self._set_status("Live cursor active")

    def _restore(self):
        if self.overlay.isVisible():
            self.overlay.hide()
        self._set_status("System cursor restored")

    # ---------- presets ----------
    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        presets = self._load_presets_dict()
        presets[name] = self._config_to_dict()
        self._save_presets_dict(presets)
        self._set_status(f"Saved preset: {name}")

    def _load_preset(self):
        presets = self._load_presets_dict()
        if not presets:
            QMessageBox.information(self, "No presets", "No saved presets yet.")
            return
        name, ok = QInputDialog.getItem(
            self, "Load preset", "Choose preset:", list(presets.keys()), 0, False
        )
        if not ok or not name:
            return
        self._apply_dict_to_config(presets[name])
        self._set_status(f"Loaded preset: {name}")

    def _reset_defaults(self):
        if QMessageBox.question(
            self, "Reset", "Reset all settings to defaults?"
        ) != QMessageBox.Yes:
            return
        self._apply_dict_to_config({})
        self._set_status("Reset to defaults")

    def _config_to_dict(self) -> dict:
        cfg = self.cursor_painter.config
        d = {}
        for k in cfg.__dataclass_fields__:
            v = getattr(cfg, k)
            if isinstance(v, tuple):
                d[k] = list(v)
            elif isinstance(v, list):
                d[k] = [(p, list(c)) for p, c in v]
            else:
                d[k] = v
        return d

    def _apply_dict_to_config(self, d: dict):
        cfg = self.cursor_painter.config
        defaults = CursorConfig()
        for k in cfg.__dataclass_fields__:
            if k not in d:
                v = getattr(defaults, k)
            else:
                v = d[k]
            if k in ("color", "outline_color", "glass_tint") and isinstance(v, list):
                v = tuple(v)
            if k == "gradient_stops" and isinstance(v, list):
                v = [(float(p), tuple(c)) for p, c in v]
            setattr(cfg, k, v)
        self._sync_ui_from_config()

    def _sync_ui_from_config(self):
        cfg = self.cursor_painter.config
        for w in [self.glow_intensity, self.glow_radius, self.shadow_intensity,
                  self.shadow_off_x, self.shadow_off_y, self.outline_width,
                  self.size_slider, self.rotation_slider, self.pulse_speed,
                  self.pulse_amount, self.cc_speed, self.spin_speed,
                  self.trail_length, self.trail_fade, self.grad_angle,
                  self.img_scale, self.glass_tint_amount, self.glass_refraction,
                  self.glass_magnification, self.glass_edge, self.glass_edge_width,
                  self.squish_amount, self.squish_threshold, self.inertia_amount]:
            w.blockSignals(True)

        self.glow_intensity.setValue(cfg.glow_intensity)
        self.glow_radius.setValue(cfg.glow_radius)
        self.shadow_intensity.setValue(cfg.shadow_intensity)
        self.shadow_off_x.setValue(cfg.shadow_offset_x)
        self.shadow_off_y.setValue(cfg.shadow_offset_y)
        self.outline_width.setValue(cfg.outline_width)
        self.outline_color_btn.set_color(cfg.outline_color)
        self.highlight_cb.setChecked(cfg.highlight)
        self.size_slider.setValue(cfg.size)
        self.rotation_slider.setValue(cfg.rotation)
        self.pulse_cb.setChecked(cfg.pulse)
        self.pulse_speed.setValue(cfg.pulse_speed)
        self.pulse_amount.setValue(cfg.pulse_amount)
        self.cc_cb.setChecked(cfg.color_cycle)
        self.cc_speed.setValue(cfg.color_cycle_speed)
        self.spin_cb.setChecked(cfg.spin)
        self.spin_speed.setValue(cfg.spin_speed)
        self.trail_cb.setChecked(cfg.trail)
        self.trail_length.setValue(cfg.trail_length)
        self.trail_fade.setValue(cfg.trail_fade)

        # Glass
        self.glass_tint_btn.set_color(cfg.glass_tint)
        self.glass_tint_amount.setValue(cfg.glass_tint_amount)
        self.glass_refraction.setValue(cfg.glass_refraction)
        self.glass_magnification.setValue(cfg.glass_magnification)
        self.glass_edge.setValue(cfg.glass_edge)
        self.glass_edge_width.setValue(cfg.glass_edge_width)
        self.glass_specular_cb.setChecked(cfg.glass_specular)

        # Motion
        self.squish_cb.setChecked(cfg.motion_squish)
        self.squish_amount.setValue(cfg.motion_squish_amount)
        self.squish_threshold.setValue(cfg.motion_squish_threshold)
        self.inertia_cb.setChecked(cfg.motion_inertia)
        self.inertia_amount.setValue(cfg.motion_inertia_amount)

        # Shape
        for btn in self.shape_buttons.buttons():
            btn.setChecked(btn.text() == cfg.shape)

        # Fill mode
        idx = {"solid": 0, "gradient": 1, "image": 2, "glass": 3}.get(cfg.fill_mode, 0)
        self.fill_tabs.setCurrentIndex(idx)
        self.solid_color_btn.set_color(cfg.color)
        self.grad_type.setCurrentText(cfg.gradient_type)
        self.grad_angle.setValue(cfg.gradient_angle)
        for i, cb in enumerate(self.grad_color_btns):
            if i < len(cfg.gradient_stops):
                cb.set_color(cfg.gradient_stops[i][1])
        if cfg.image_path:
            self.img_path_label.setText(os.path.basename(cfg.image_path))
        self.img_mode.setCurrentText(cfg.image_mode)
        self.img_scale.setValue(cfg.image_scale)

        for w in [self.glow_intensity, self.glow_radius, self.shadow_intensity,
                  self.shadow_off_x, self.shadow_off_y, self.outline_width,
                  self.size_slider, self.rotation_slider, self.pulse_speed,
                  self.pulse_amount, self.cc_speed, self.spin_speed,
                  self.trail_length, self.trail_fade, self.grad_angle,
                  self.img_scale, self.glass_tint_amount, self.glass_refraction,
                  self.glass_magnification, self.glass_edge, self.glass_edge_width,
                  self.squish_amount, self.squish_threshold, self.inertia_amount]:
            w.blockSignals(False)

        self.cursor_painter.reset_animations()

    # ---------- persistence ----------
    def _load_presets_dict(self) -> dict:
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return data.get("presets", {})
        except Exception:
            return {}

    def _save_presets_dict(self, presets: dict):
        try:
            data = {}
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except Exception:
                pass
            data["presets"] = presets
            data["last_config"] = self._config_to_dict()
            self.settings_path.write_text(json.dumps(data, indent=2),
                                          encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))

    def _load_settings(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            return
        last = data.get("last_config")
        if last:
            self._apply_dict_to_config(last)

    def _save_settings(self):
        try:
            data = {}
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except Exception:
                pass
            data["last_config"] = self._config_to_dict()
            self.settings_path.write_text(json.dumps(data, indent=2),
                                          encoding="utf-8")
        except Exception:
            pass

    # ---------- close / quit ----------
    def closeEvent(self, event):
        if self.tray.isVisible():
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "CursorForge",
                "Still running in tray. Right-click for options.",
                QSystemTrayIcon.Information, 2000,
            )
            return
        self._quit()
        event.accept()

    def _quit(self):
        self._save_settings()
        try:
            self.overlay.close()
        except Exception:
            pass
        try:
            self.ball_overlay.close()
        except Exception:
            pass
        try:
            self.tray.hide()
        except Exception:
            pass
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()
