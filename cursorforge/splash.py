"""
splash.py
=========
Custom opening splash screen for CursorForge.

A borderless, frameless, translucent, topmost window that fades in,
holds for ~1.2s with the app name + version + animated rings, then
fades out and calls the on_finished callback.

The splash does NOT block the event loop - the caller passes a
callback that is invoked when the splash is done (typically to show
the main menu window).
"""
from __future__ import annotations

import math
from typing import Optional, Callable

from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, QElapsedTimer
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QRadialGradient, QFont, QPixmap
)
from PyQt5.QtWidgets import QWidget, QApplication


# App identity - kept in sync with build_standalone_bat.py APP_VERSION.
APP_NAME = "CursorForge"
APP_VERSION = "1.1.1"
APP_TAGLINE = "custom cursor studio"
GITHUB_REPO = "https://github.com/bobjsco/bobs-cursorchanger-.-test-lol"


class SplashWindow(QWidget):
    """Animated splash screen.

    Lifecycle:
        fade_in (250ms) -> hold (1200ms) -> fade_out (300ms) -> on_finished()
    """

    def __init__(self, on_finished: Optional[Callable] = None):
        super().__init__()
        self._on_finished = on_finished

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.SplashScreen
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.NoFocus)

        # Centered 520x320 splash
        self._w, self._h = 520, 320
        self.resize(self._w, self._h)
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self._w) // 2,
            (screen.height() - self._h) // 2,
        )

        # Animation state
        self._opacity = 0.0
        self._phase = "in"        # in -> hold -> out -> done
        self._phase_t = 0.0
        self._elapsed = QElapsedTimer()
        self._elapsed.start()

        # 60 FPS repaint
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    # ---------- timing ----------
    FADE_IN_MS = 250.0
    HOLD_MS = 1200.0
    FADE_OUT_MS = 300.0

    def _tick(self):
        t = self._elapsed.elapsed()
        if self._phase == "in":
            self._opacity = min(1.0, t / self.FADE_IN_MS)
            if t >= self.FADE_IN_MS:
                self._phase = "hold"
                self._elapsed.restart()
        elif self._phase == "hold":
            self._opacity = 1.0
            if t >= self.HOLD_MS:
                self._phase = "out"
                self._elapsed.restart()
        elif self._phase == "out":
            self._opacity = max(0.0, 1.0 - t / self.FADE_OUT_MS)
            if t >= self.FADE_OUT_MS:
                self._phase = "done"
                self._timer.stop()
                self.hide()
                if self._on_finished:
                    self._on_finished()
                self.close()
                return
        self.update()

    # ---------- paint ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # Background: dark rounded panel with subtle gradient
        bg = QRadialGradient(QPointF(self._w / 2, self._h / 2), self._w * 0.7)
        bg.setColorAt(0.0, QColor(20, 20, 36, int(240 * self._opacity)))
        bg.setColorAt(1.0, QColor(8, 8, 16, int(240 * self._opacity)))
        p.setBrush(QBrush(bg))
        p.setPen(QPen(QColor(0, 240, 255, int(180 * self._opacity)), 2))
        p.drawRoundedRect(QRectF(2, 2, self._w - 4, self._h - 4), 18, 18)

        cx, cy = self._w / 2, self._h / 2 - 30

        # Animated rings (rotating cyan/magenta)
        t_ms = self._elapsed.elapsed()
        for i, (color, radius, speed, phase) in enumerate([
            (QColor(0, 240, 255, int(220 * self._opacity)), 60, 2.0, 0.0),
            (QColor(255, 45, 149, int(180 * self._opacity)), 80, -1.5, 1.0),
            (QColor(0, 240, 255, int(120 * self._opacity)), 100, 1.0, 2.0),
        ]):
            angle = (t_ms / 1000.0) * speed + phase
            pen = QPen(color, 2)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            # Draw arc from angle to angle+270deg
            start_angle = int(angle * 16)
            p.drawArc(QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                      start_angle, 270 * 16)

        # Center logo dot
        grad = QRadialGradient(QPointF(cx - 6, cy - 6), 22)
        grad.setColorAt(0, QColor(255, 255, 255, int(255 * self._opacity)))
        grad.setColorAt(0.4, QColor(0, 240, 255, int(255 * self._opacity)))
        grad.setColorAt(1, QColor(0, 100, 180, int(255 * self._opacity)))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 22, 22)

        # App name
        p.setPen(QColor(240, 240, 250, int(255 * self._opacity)))
        name_font = QFont("Segoe UI", 26, QFont.Bold)
        p.setFont(name_font)
        p.drawText(QRectF(0, cy + 70, self._w, 36),
                   Qt.AlignHCenter | Qt.AlignVCenter,
                   APP_NAME)

        # Version
        p.setPen(QColor(0, 240, 255, int(220 * self._opacity)))
        ver_font = QFont("Segoe UI", 11, QFont.Medium)
        p.setFont(ver_font)
        p.drawText(QRectF(0, cy + 110, self._w, 22),
                   Qt.AlignHCenter | Qt.AlignVCenter,
                   f"v{APP_VERSION}")

        # Tagline
        p.setPen(QColor(140, 140, 170, int(220 * self._opacity)))
        tag_font = QFont("Segoe UI", 9)
        p.setFont(tag_font)
        p.drawText(QRectF(0, cy + 138, self._w, 18),
                   Qt.AlignHCenter | Qt.AlignVCenter,
                   APP_TAGLINE)

        # GitHub repo link (small, below the loading bar)
        p.setPen(QColor(100, 100, 130, int(200 * self._opacity)))
        link_font = QFont("Segoe UI", 8)
        p.setFont(link_font)
        p.drawText(QRectF(0, self._h - 22, self._w, 16),
                   Qt.AlignHCenter | Qt.AlignVCenter,
                   GITHUB_REPO)

        # Bottom loading bar
        bar_w = 240
        bar_h = 3
        bar_x = (self._w - bar_w) // 2
        bar_y = self._h - 40
        # Trough
        p.setBrush(QColor(40, 40, 60, int(180 * self._opacity)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 1, 1)
        # Fill - progresses across all phases (in + hold + out)
        total_ms = self.FADE_IN_MS + self.HOLD_MS + self.FADE_OUT_MS
        if self._phase == "in":
            progress = self._elapsed.elapsed() / total_ms
        elif self._phase == "hold":
            progress = (self.FADE_IN_MS + self._elapsed.elapsed()) / total_ms
        elif self._phase == "out":
            progress = (self.FADE_IN_MS + self.HOLD_MS + self._elapsed.elapsed()) / total_ms
        else:
            progress = 1.0
        progress = max(0.0, min(1.0, progress))
        fill_w = int(bar_w * progress)
        if fill_w > 0:
            fill_grad = QRadialGradient(QPointF(bar_x + fill_w / 2, bar_y), fill_w)
            fill_grad.setColorAt(0, QColor(0, 240, 255, int(255 * self._opacity)))
            fill_grad.setColorAt(1, QColor(0, 160, 200, int(255 * self._opacity)))
            p.setBrush(QBrush(fill_grad))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 1, 1)
