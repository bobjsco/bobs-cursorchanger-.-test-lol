"""
ball_overlay.py
===============
Realistic bouncing ball physics overlay for CursorForge.

FEATURES:
  - Click anywhere to spawn a ball that falls with gravity
  - Balls bounce off screen edges + taskbar with restitution
  - Ball-to-ball elastic collisions (momentum + energy conservation)
  - Drag a ball with the mouse, then release to "yeet" it
    (release velocity is tracked from recent mouse motion)
  - Balls despawn after 5 seconds of no interaction
    (spawn, drag, or collision resets the timer)
  - Each ball has a 3D radial-gradient look + soft shadow

ARCHITECTURE:
  - Separate topmost translucent QWidget (NOT the cursor overlay)
  - NOT click-through by default so it can receive mouse events
  - Dynamic click-through: when the cursor is NOT over a ball, the
    window becomes WS_EX_TRANSPARENT so clicks pass through to the
    desktop. When the cursor IS over a ball, it becomes interactive
    so you can grab and drag it.
  - This means: clicking empty space spawns a ball (captured by us),
    but if ball mode is OFF, the window is fully click-through and
    invisible so the desktop works normally.

PHYSICS:
  - Gravity: ~1200 px/s^2 (tunable)
  - Restitution: 0.65 (bounciness; 0 = no bounce, 1 = perfect)
  - Air friction: 0.5% velocity decay per frame
  - Ground friction: 2% velocity decay when sliding on floor
  - Ball-ball: elastic collision with mass = radius^2
  - Substepping: 2x substeps per frame for stability at high speeds
"""
from __future__ import annotations

import math
import sys
import time
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QRectF
from PyQt5.QtGui import (
    QPainter, QColor, QRadialGradient, QBrush, QPen, QPixmap
)
from PyQt5.QtWidgets import QWidget, QApplication


IS_WINDOWS = sys.platform.startswith("win")


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_LAYERED = 0x00080000
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000

    HWND_TOPMOST = -1
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040

    user32.GetWindowLongA.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongA.restype = ctypes.c_long
    user32.SetWindowLongA.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongA.restype = ctypes.c_long
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.c_void_p]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int


# ---------------------------------------------------------------------------
# Ball dataclass
# ---------------------------------------------------------------------------
@dataclass
class Ball:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    radius: float = 24.0
    color: Tuple[int, int, int] = (255, 80, 120)
    spawn_time: float = field(default_factory=time.monotonic)
    last_active: float = field(default_factory=time.monotonic)
    being_dragged: bool = False
    # Drag velocity tracking (EMA of recent position deltas)
    drag_vx: float = 0.0
    drag_vy: float = 0.0
    _last_drag_x: float = 0.0
    _last_drag_y: float = 0.0
    _last_drag_t: float = 0.0

    def touch(self):
        self.last_active = time.monotonic()

    def age_since_active(self) -> float:
        return time.monotonic() - self.last_active


# ---------------------------------------------------------------------------
# Ball overlay widget
# ---------------------------------------------------------------------------
class BallOverlay(QWidget):
    """Topmost overlay that renders + simulates bouncing balls.

    Set `enabled = True` to activate ball mode. When disabled, the
    overlay is hidden and fully click-through.
    """

    DESPAWN_SECONDS = 5.0
    GRAVITY = 1200.0           # px/s^2
    RESTITUTION = 0.65         # bounciness
    AIR_FRICTION = 0.995       # per-frame velocity multiplier
    GROUND_FRICTION = 0.98     # when sliding on floor
    SUBSTEPS = 2               # physics substeps per frame

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.NoFocus)

        # Cover the whole screen
        self._screen_geo = self._get_screen_geometry()
        self.resize(self._screen_geo.width(), self._screen_geo.height())
        self.move(self._screen_geo.x(), self._screen_geo.y())

        self.balls: List[Ball] = []
        self.enabled = False
        self._dragging: Optional[Ball] = None
        self._click_through = True   # start click-through
        self._click_through_set = False

        # Ball appearance config
        self.ball_size: int = 28
        self.ball_bounciness: int = 65   # 0-100
        self.ball_gravity: int = 50       # 0-100 (50 = default 1200 px/s^2)
        self.ball_color: Tuple[int, int, int] = (255, 80, 120)
        self.random_colors: bool = True

        # Physics loop
        self._last_t = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)   # ~60 FPS

        # Mouse polling for drag velocity tracking
        self.setMouseTracking(True)

    # ---------- screen geometry ----------
    def _get_screen_geometry(self):
        # Use the virtual geometry (covers all monitors)
        screen = QApplication.primaryScreen().virtualGeometry()
        return screen

    # ---------- Win32 click-through toggle ----------
    def _make_click_through(self, click_through: bool):
        """Toggle WS_EX_TRANSPARENT so the window either captures mouse
        events (for ball interaction) or passes them through to the
        desktop."""
        if not IS_WINDOWS:
            return
        try:
            hwnd = int(self.winId())
            ex = user32.GetWindowLongA(hwnd, GWL_EXSTYLE)
            if click_through:
                ex |= WS_EX_TRANSPARENT
            else:
                ex &= ~WS_EX_TRANSPARENT
            ex |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            user32.SetWindowLongA(hwnd, GWL_EXSTYLE, ex)
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            self._click_through = click_through
        except Exception:
            pass

    def _ensure_window_flags(self):
        if self._click_through_set or not IS_WINDOWS:
            return
        # When ball mode is OFF (default), the overlay is hidden so
        # click-through doesn't matter. When ball mode is ON, set_enabled
        # explicitly toggles it to interactive. So here we just mark the
        # flags as set without forcing click-through.
        self._click_through_set = True

    # ---------- show/hide ----------
    def showEvent(self, event):
        super().showEvent(event)
        # Defer the click-through setup until the window has an HWND
        QTimer.singleShot(50, self._ensure_window_flags)

    # ---------- enable/disable ----------
    def set_enabled(self, on: bool):
        self.enabled = on
        if on:
            self.show()
            self.raise_()
            # CRITICAL: when ball mode is ON, the overlay must NOT be
            # click-through - otherwise clicks on empty space pass through
            # to the desktop and no balls get spawned. Force interactive
            # mode (no WS_EX_TRANSPARENT) so mousePressEvent fires for
            # every click.
            QTimer.singleShot(60, lambda: self._make_click_through(False))
        else:
            # Clear all balls when disabling
            self.balls.clear()
            self._dragging = None
            self.hide()

    # ---------- config ----------
    def set_ball_size(self, size: int):
        self.ball_size = size

    def set_ball_bounciness(self, b: int):
        self.ball_bounciness = b

    def set_ball_gravity(self, g: int):
        self.ball_gravity = g

    def set_ball_color(self, rgb: Tuple[int, int, int]):
        self.ball_color = rgb

    def set_random_colors(self, on: bool):
        self.random_colors = on

    # ---------- spawn ----------
    def spawn_ball(self, x: float, y: float):
        """Spawn a new ball at (x, y) in screen coords."""
        radius = float(self.ball_size)
        if self.random_colors:
            # Pick a vibrant random color
            hue = random.random()
            import colorsys
            r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
            color = (int(r * 255), int(g * 255), int(b * 255))
        else:
            color = self.ball_color
        ball = Ball(
            x=x, y=y, vx=0.0, vy=0.0,
            radius=radius, color=color,
        )
        # Small initial downward velocity so it starts falling naturally
        ball.vy = 50.0
        self.balls.append(ball)
        # Cap the number of balls to avoid runaway memory
        if len(self.balls) > 60:
            # Remove the oldest ball
            self.balls.pop(0)

    # ---------- mouse handling ----------
    def _ball_at(self, x: float, y: float) -> Optional[Ball]:
        """Find the topmost ball containing (x, y)."""
        # Iterate in reverse so newer balls (drawn on top) are grabbed first
        for ball in reversed(self.balls):
            dx = x - ball.x
            dy = y - ball.y
            if dx * dx + dy * dy <= ball.radius * ball.radius:
                return ball
        return None

    def mousePressEvent(self, event):
        if not self.enabled:
            return
        if event.button() != Qt.LeftButton:
            return
        x = event.globalX()
        y = event.globalY()
        ball = self._ball_at(x, y)
        if ball is not None:
            # Start dragging
            self._dragging = ball
            ball.being_dragged = True
            ball.vx = 0.0
            ball.vy = 0.0
            ball._last_drag_x = x
            ball._last_drag_y = y
            ball._last_drag_t = time.monotonic()
            ball.touch()
        else:
            # Spawn a new ball at click location
            self.spawn_ball(x, y)

    def mouseMoveEvent(self, event):
        if self._dragging is None:
            return
        x = event.globalX()
        y = event.globalY()
        ball = self._dragging
        now = time.monotonic()
        dt = max(now - ball._last_drag_t, 0.001)
        # Track velocity (EMA for stability)
        raw_vx = (x - ball._last_drag_x) / dt
        raw_vy = (y - ball._last_drag_y) / dt
        alpha = 0.5
        ball.drag_vx = ball.drag_vx * (1 - alpha) + raw_vx * alpha
        ball.drag_vy = ball.drag_vy * (1 - alpha) + raw_vy * alpha
        ball.x = x
        ball.y = y
        ball._last_drag_x = x
        ball._last_drag_y = y
        ball._last_drag_t = now
        ball.touch()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self._dragging is not None:
            ball = self._dragging
            ball.being_dragged = False
            # Yeet: transfer drag velocity to physics velocity
            ball.vx = ball.drag_vx
            ball.vy = ball.drag_vy
            ball.drag_vx = 0.0
            ball.drag_vy = 0.0
            ball.touch()
            self._dragging = None

    # ---------- physics ----------
    def _tick(self):
        if not self.enabled:
            return

        now = time.monotonic()
        dt = min(now - self._last_t, 0.05)   # cap at 50ms
        self._last_t = now

        # Run physics substeps for stability
        sub_dt = dt / self.SUBSTEPS
        for _ in range(self.SUBSTEPS):
            self._physics_step(sub_dt)

        # Despawn old balls
        self.balls = [b for b in self.balls
                      if b.age_since_active() < self.DESPAWN_SECONDS]

        # Update click-through based on whether cursor is over a ball
        self._update_click_through()

        # Trigger repaint
        self.update()

    def _physics_step(self, dt: float):
        screen = self._screen_geo
        floor_y = screen.bottom()     # bottom of screen (taskbar is here)
        left_x = screen.left()
        right_x = screen.right()
        top_y = screen.top()

        gravity = self.GRAVITY * (self.ball_gravity / 50.0)
        restitution = self.ball_bounciness / 100.0

        for ball in self.balls:
            if ball.being_dragged:
                # Dragged balls don't undergo physics
                continue

            # Apply gravity
            ball.vy += gravity * dt

            # Air friction
            ball.vx *= self.AIR_FRICTION
            ball.vy *= self.AIR_FRICTION

            # Update position
            ball.x += ball.vx * dt
            ball.y += ball.vy * dt

            r = ball.radius

            # Floor collision
            if ball.y + r > floor_y:
                ball.y = floor_y - r
                if ball.vy > 0:
                    ball.vy = -ball.vy * restitution
                    ball.touch()
                # Ground friction
                ball.vx *= self.GROUND_FRICTION
                # Stop tiny bounces
                if abs(ball.vy) < 30:
                    ball.vy = 0.0

            # Ceiling collision
            if ball.y - r < top_y:
                ball.y = top_y + r
                if ball.vy < 0:
                    ball.vy = -ball.vy * restitution
                    ball.touch()

            # Left wall
            if ball.x - r < left_x:
                ball.x = left_x + r
                if ball.vx < 0:
                    ball.vx = -ball.vx * restitution
                    ball.touch()

            # Right wall
            if ball.x + r > right_x:
                ball.x = right_x - r
                if ball.vx > 0:
                    ball.vx = -ball.vx * restitution
                    ball.touch()

        # Ball-to-ball collisions
        n = len(self.balls)
        for i in range(n):
            for j in range(i + 1, n):
                self._collide_balls(self.balls[i], self.balls[j])

    def _collide_balls(self, a: Ball, b: Ball):
        """Elastic collision between two balls."""
        dx = b.x - a.x
        dy = b.y - a.y
        dist_sq = dx * dx + dy * dy
        r_sum = a.radius + b.radius
        if dist_sq >= r_sum * r_sum:
            return   # no collision
        dist = math.sqrt(max(dist_sq, 0.0001))
        if dist == 0:
            # Balls exactly overlap — nudge apart
            a.x -= 0.5
            b.x += 0.5
            return

        # Normal vector
        nx = dx / dist
        ny = dy / dist

        # Relative velocity along normal
        rvx = b.vx - a.vx
        rvy = b.vy - a.vy
        vel_along_normal = rvx * nx + rvy * ny
        if vel_along_normal > 0:
            # Balls are separating — no impulse needed
            pass
        else:
            # Mass proportional to radius squared
            ma = a.radius * a.radius
            mb = b.radius * b.radius
            restitution = self.ball_bounciness / 100.0
            # Impulse magnitude
            j = -(1 + restitution) * vel_along_normal / (1 / ma + 1 / mb)
            impulse_x = j * nx
            impulse_y = j * ny
            if not a.being_dragged:
                a.vx -= impulse_x / ma
                a.vy -= impulse_y / ma
            if not b.being_dragged:
                b.vx += impulse_x / mb
                b.vy += impulse_y / mb
            a.touch()
            b.touch()

        # Positional correction (separate overlapping balls)
        overlap = r_sum - dist
        if overlap > 0:
            correction = overlap * 0.5
            if a.being_dragged and not b.being_dragged:
                b.x += nx * overlap
                b.y += ny * overlap
            elif b.being_dragged and not a.being_dragged:
                a.x -= nx * overlap
                a.y -= ny * overlap
            elif not a.being_dragged and not b.being_dragged:
                a.x -= nx * correction
                a.y -= ny * correction
                b.x += nx * correction
                b.y += ny * correction

    # ---------- click-through management ----------
    def _update_click_through(self):
        """When ball mode is ON, the overlay must STAY interactive so the
        user can click anywhere to spawn balls. We do NOT toggle
        click-through based on whether the cursor is over a ball - that
        was the old behaviour and it caused clicks on empty space to pass
        through to the desktop instead of spawning balls.

        Now: when ball mode is on, always interactive. When off, the
        overlay is hidden so this method is never reached.
        """
        if not self.enabled:
            return
        # Ensure we're in interactive (non-click-through) mode.
        if self._click_through:
            self._make_click_through(False)

    # ---------- paint ----------
    def paintEvent(self, event):
        if not self.enabled:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        for ball in self.balls:
            self._draw_ball(p, ball)

    def _draw_ball(self, p: QPainter, ball: Ball):
        r = ball.radius
        cx, cy = ball.x - self.x(), ball.y - self.y()   # screen->local

        # ---- Shadow on the "floor" ----
        floor_y = self._screen_geo.bottom() - self.y()
        shadow_dist = max(0, floor_y - cy)
        # Shadow gets more faint + larger the further from floor
        shadow_alpha = max(20, int(120 * (1 - shadow_dist / 600)))
        # Shadow radius: scales with ball radius + a bit more spread
        # when the ball is higher (further from floor)
        shadow_r = r * (0.9 + min(shadow_dist / 400, 0.6))
        # Shadow position: directly below the ball, on the floor
        shadow_y = floor_y - 2
        shadow_x = cx
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, shadow_alpha))
        p.drawEllipse(QPointF(shadow_x, shadow_y), shadow_r, shadow_r * 0.3)

        # ---- Ball body with radial gradient (3D look) ----
        # Highlight at top-left, full color at center, darker at bottom-right
        grad = QRadialGradient(
            QPointF(cx - r * 0.35, cy - r * 0.35), r * 1.4
        )
        r0, g0, b0 = ball.color
        # Lighter highlight
        hr = min(255, r0 + 120)
        hg = min(255, g0 + 120)
        hb = min(255, b0 + 120)
        # Darker edge
        dr = max(0, r0 - 80)
        dg = max(0, g0 - 80)
        db = max(0, b0 - 80)
        grad.setColorAt(0.0, QColor(hr, hg, hb, 255))
        grad.setColorAt(0.4, QColor(r0, g0, b0, 255))
        grad.setColorAt(1.0, QColor(dr, dg, db, 255))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # ---- Glossy specular spot (top-left) ----
        spec = QRadialGradient(
            QPointF(cx - r * 0.4, cy - r * 0.4), r * 0.5
        )
        spec.setColorAt(0.0, QColor(255, 255, 255, 180))
        spec.setColorAt(0.5, QColor(255, 255, 255, 50))
        spec.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(spec))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # ---- Subtle outline ----
        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)
