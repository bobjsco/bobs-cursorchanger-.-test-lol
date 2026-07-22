"""
cursor_painter.py
=================
The rendering engine for CursorForge. Given a CursorConfig + current
animation time, paints the cursor with:
  - 14+ shape options
  - Solid / linear-gradient / radial-gradient / conic-gradient / image / GLASS fill
  - Multi-pass outer glow (color-shiftable)
  - Drop shadow (8-pass offset blur simulation)
  - Outline (separate color + width)
  - Inner highlight (glossy top-left spot)
  - Animations: pulse (size), spin (rotation), color cycle (hue rotate),
                trail (last N positions fading out)
  - MOTION: velocity-based squish (stretch in direction of motion),
            spring-physics inertia (overshoot + ease back when stopping)
  - GLASS: captures the screen behind the cursor and applies numpy-based
           barrel distortion (bulge/magnification), plus tint + edge highlight
"""
from __future__ import annotations

import colorsys
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QBrush,
    QRadialGradient, QLinearGradient, QConicalGradient,
    QPixmap, QPainterPathStroker, QImage,
)

import shapes

# numpy is required for the glass barrel distortion. If unavailable,
# glass falls back to a simpler scale-up magnification (no refraction).
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


RGB = Tuple[int, int, int]
GradientStop = Tuple[float, RGB]


@dataclass
class CursorConfig:
    # ---- Shape ----
    shape: str = "Circle"
    size: int = 32                # px radius (cursor "size")
    rotation: int = 0             # static rotation in degrees

    # ---- Fill ----
    fill_mode: str = "solid"      # "solid" | "gradient" | "image" | "glass"

    # Solid color
    color: RGB = (0, 240, 255)    # neon cyan

    # Gradient
    gradient_type: str = "linear"  # "linear" | "radial" | "conic"
    gradient_angle: int = 45
    gradient_stops: List[GradientStop] = field(default_factory=lambda: [
        (0.0, (255, 45, 149)),
        (0.5, (0, 240, 255)),
        (1.0, (160, 90, 255)),
    ])

    # Image
    image_path: str = ""
    image_mode: str = "replace"   # "replace" | "attached"
    image_scale: float = 1.0

    # Glass (new)
    glass_tint: RGB = (180, 220, 255)
    glass_tint_amount: int = 10        # 0-100, how strongly tinted (low = clearer refraction)
    glass_refraction: int = 45         # 0-100, barrel distortion strength
    glass_magnification: int = 30      # 0-100, center zoom
    glass_edge: int = 70               # 0-100, edge highlight brightness
    glass_edge_width: int = 2          # px
    glass_specular: bool = True        # bright specular dot top-left

    # ---- Effects ----
    glow_intensity: int = 60
    glow_radius: int = 24
    shadow_intensity: int = 35
    shadow_offset_x: int = 3
    shadow_offset_y: int = 3
    outline_width: int = 0
    outline_color: RGB = (255, 255, 255)
    highlight: bool = True

    # ---- Animations ----
    pulse: bool = False
    pulse_speed: int = 50
    pulse_amount: int = 25
    color_cycle: bool = False
    color_cycle_speed: int = 30
    spin: bool = False
    spin_speed: int = 50
    trail: bool = False
    trail_length: int = 12
    trail_fade: int = 60

    # ---- Motion (new) ----
    motion_squish: bool = True
    motion_squish_amount: int = 50     # 0-100, max stretch factor
    motion_squish_threshold: int = 200  # px/sec below which no squish
    motion_inertia: bool = True
    motion_inertia_amount: int = 50    # 0-100, higher = more lag + overshoot

    def clone(self) -> "CursorConfig":
        c = CursorConfig()
        for k, v in self.__dict__.items():
            if isinstance(v, list):
                setattr(c, k, list(v))
            else:
                setattr(c, k, v)
        return c


# ---------------------------------------------------------------------------
# CursorPainter
# ---------------------------------------------------------------------------
class CursorPainter:
    """Renders the cursor based on a CursorConfig + animation time.

    Stateful: holds the trail deque, spring-physics state for inertia,
    and the start_time used by all animation loops.
    """

    def __init__(self, config: Optional[CursorConfig] = None):
        self.config = config or CursorConfig()
        self.start_time = time.monotonic()
        self.trail_points: deque = deque(maxlen=60)

        # ---- Spring physics for inertia ----
        # drawing_offset is added to the cursor position to get the
        # actual draw position. When the mouse moves fast, the offset
        # lags slightly behind (cursor trails). When the mouse stops,
        # the offset overshoots then springs back to 0.
        self._spring_pos = [0.0, 0.0]   # current drawing offset (px)
        self._spring_vel = [0.0, 0.0]   # offset velocity (px/sec)
        self._mouse_vel = [0.0, 0.0]    # smoothed mouse velocity (px/sec)
        self._last_mouse_pos: Optional[List[float]] = None
        self._last_time = time.monotonic()

    def reset_animations(self):
        self.start_time = time.monotonic()
        self.trail_points.clear()
        self._spring_pos = [0.0, 0.0]
        self._spring_vel = [0.0, 0.0]
        self._mouse_vel = [0.0, 0.0]
        self._last_mouse_pos = None
        self._last_time = time.monotonic()

    # ---------- trail ----------
    def add_trail_point(self, x: float, y: float):
        if self.config.trail:
            self.trail_points.append((x, y, time.monotonic()))

    def clear_trail(self):
        self.trail_points.clear()

    # ---------- motion physics ----------
    def update_motion(self, mouse_x: float, mouse_y: float) -> Tuple[float, float]:
        """Call this every frame with the current mouse position.
        Updates mouse velocity (smoothed) and integrates the spring
        physics for the drawing offset. Returns (vx, vy) smoothed
        mouse velocity in px/sec."""
        now = time.monotonic()
        dt = min(now - self._last_time, 0.05)   # cap dt at 50ms
        self._last_time = now

        if self._last_mouse_pos is None:
            self._last_mouse_pos = [mouse_x, mouse_y]
            return 0.0, 0.0

        # Raw mouse velocity
        raw_vx = (mouse_x - self._last_mouse_pos[0]) / max(dt, 0.001)
        raw_vy = (mouse_y - self._last_mouse_pos[1]) / max(dt, 0.001)
        self._last_mouse_pos = [mouse_x, mouse_y]

        # Smooth mouse velocity (EMA)
        alpha = 0.35
        self._mouse_vel[0] = self._mouse_vel[0] * (1 - alpha) + raw_vx * alpha
        self._mouse_vel[1] = self._mouse_vel[1] * (1 - alpha) + raw_vy * alpha

        # Spring physics for drawing offset
        if self.config.motion_inertia:
            amt = self.config.motion_inertia_amount / 100.0
            # stiffness: high amount = softer spring = more lag/overshoot
            #   amt=0 -> k=400 (very stiff, barely lags)
            #   amt=1 -> k=80 (soft, lots of lag + bounce)
            stiffness = 400 - amt * 320
            # damping: higher amount = less damping = more oscillation
            #   amt=0 -> c=40 (critically damped, no overshoot)
            #   amt=1 -> c=8 (very underdamped, bouncy)
            damping = 40 - amt * 32

            # Target offset: we want the cursor to lead the mouse slightly
            # when moving (look-ahead), which creates the overshoot when
            # the mouse stops.
            look_ahead = amt * 0.04    # 0..40ms look-ahead
            target_offset_x = self._mouse_vel[0] * look_ahead
            target_offset_y = self._mouse_vel[1] * look_ahead

            # Spring force towards target offset
            fx = (target_offset_x - self._spring_pos[0]) * stiffness
            fy = (target_offset_y - self._spring_pos[1]) * stiffness

            self._spring_vel[0] += fx * dt
            self._spring_vel[1] += fy * dt

            # Damping (exponential decay, frame-rate independent)
            decay = math.exp(-damping * dt)
            self._spring_vel[0] *= decay
            self._spring_vel[1] *= decay

            self._spring_pos[0] += self._spring_vel[0] * dt
            self._spring_pos[1] += self._spring_vel[1] * dt
        else:
            self._spring_pos = [0.0, 0.0]
            self._spring_vel = [0.0, 0.0]

        return self._mouse_vel[0], self._mouse_vel[1]

    def get_drawing_offset(self) -> Tuple[float, float]:
        """Returns (dx, dy) to add to mouse position for drawing.
        This is the spring-physics offset that creates the inertia effect."""
        return self._spring_pos[0], self._spring_pos[1]

    # ---------- animation helpers ----------
    def _t(self) -> float:
        return time.monotonic() - self.start_time

    def animated_size(self) -> float:
        cfg = self.config
        size = float(cfg.size)
        if cfg.pulse:
            freq = 0.4 + cfg.pulse_speed / 40.0
            amount = cfg.pulse_amount / 100.0
            size = size * (1.0 + amount * math.sin(self._t() * freq * 2 * math.pi))
        return max(2.0, size)

    def animated_rotation(self) -> float:
        cfg = self.config
        rot = float(cfg.rotation)
        if cfg.spin:
            speed = cfg.spin_speed * 3.6
            rot = (rot + self._t() * speed) % 360
        return rot

    def cycled_color(self, base: RGB) -> RGB:
        cfg = self.config
        if not cfg.color_cycle:
            return base
        freq = 0.05 + cfg.color_cycle_speed / 120.0
        offset = (self._t() * freq) % 1.0
        h, s, v = colorsys.rgb_to_hsv(base[0] / 255, base[1] / 255, base[2] / 255)
        h = (h + offset) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, max(0.5, s), v)
        return (int(r * 255), int(g * 255), int(b * 255))

    def cycled_stops(self) -> List[GradientStop]:
        cfg = self.config
        if not cfg.color_cycle:
            return list(cfg.gradient_stops)
        freq = 0.05 + cfg.color_cycle_speed / 120.0
        offset = (self._t() * freq) % 1.0
        out = []
        for pos, (r, g, b) in cfg.gradient_stops:
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            h = (h + offset) % 1.0
            r2, g2, b2 = colorsys.hsv_to_rgb(h, max(0.5, s), v)
            out.append((pos, (int(r2 * 255), int(g2 * 255), int(b2 * 255))))
        return out

    # ---------- brush ----------
    def make_brush(self, bounding_rect: QRectF) -> QBrush:
        cfg = self.config
        if cfg.fill_mode == "solid":
            c = self.cycled_color(cfg.color)
            return QBrush(QColor(*c, 255))
        if cfg.fill_mode == "gradient":
            stops = self.cycled_stops()
            cx = bounding_rect.center().x()
            cy = bounding_rect.center().y()
            r = max(1.0, bounding_rect.width() / 2)
            if cfg.gradient_type == "linear":
                ang = math.radians(cfg.gradient_angle)
                dx = math.cos(ang) * r
                dy = math.sin(ang) * r
                g = QLinearGradient(QPointF(cx - dx, cy - dy),
                                    QPointF(cx + dx, cy + dy))
                for pos, c in stops:
                    g.setColorAt(max(0.0, min(1.0, pos)), QColor(*c, 255))
                return QBrush(g)
            if cfg.gradient_type == "radial":
                g = QRadialGradient(QPointF(cx, cy), r)
                for pos, c in stops:
                    g.setColorAt(max(0.0, min(1.0, pos)), QColor(*c, 255))
                return QBrush(g)
            if cfg.gradient_type == "conic":
                g = QConicalGradient(QPointF(cx, cy), float(cfg.gradient_angle))
                for pos, c in stops:
                    g.setColorAt(max(0.0, min(1.0, pos)), QColor(*c, 255))
                return QBrush(g)
        return QBrush(QColor(255, 0, 255, 255))

    # ---------- main paint ----------
    def paint(self, painter: QPainter, cx: float, cy: float,
              alpha: float = 1.0,
              vx: float = 0.0, vy: float = 0.0,
              screen_capture: Optional[QImage] = None):
        """Paint the cursor at (cx, cy) in painter coords.

        vx, vy: mouse velocity in px/sec (for squish deformation).
        screen_capture: QImage of the screen behind the cursor (for glass).
        """
        cfg = self.config
        size = self.animated_size()
        rotation = self.animated_rotation()

        painter.save()
        if alpha < 1.0:
            painter.setOpacity(alpha)
        painter.translate(cx, cy)
        painter.rotate(rotation)

        # ---- Velocity squish (stretch in direction of motion) ----
        if cfg.motion_squish:
            speed = math.sqrt(vx * vx + vy * vy)
            threshold = float(cfg.motion_squish_threshold)
            if speed > threshold:
                amt = cfg.motion_squish_amount / 100.0
                max_stretch = 0.6 * amt           # up to +60% stretch
                # normalized speed factor (0 at threshold, 1 at threshold+2000)
                norm = min((speed - threshold) / 2000.0, 1.0)
                stretch = 1.0 + max_stretch * norm
                squish = 1.0 / stretch             # area-preserving
                angle = math.degrees(math.atan2(vy, vx))
                # Rotate to motion direction, scale, rotate back
                painter.rotate(angle)
                painter.scale(stretch, squish)
                painter.rotate(-angle)

        path = shapes.shape_path(cfg.shape, size)
        bbox = path.boundingRect()

        # ---- 1. Drop shadow ----
        if cfg.shadow_intensity > 0:
            self._paint_shadow(painter, path)

        # ---- 2. Outer glow ----
        if cfg.glow_intensity > 0 and cfg.fill_mode != "glass":
            self._paint_glow(painter, path, size)

        # ---- 3. Fill ----
        if cfg.fill_mode == "glass":
            self._paint_glass(painter, path, size, screen_capture)
        elif cfg.fill_mode == "image" and cfg.image_path and cfg.image_mode == "replace":
            self._paint_image(painter, size * 2 * cfg.image_scale)
        else:
            # Solid / gradient fill
            brush = self.make_brush(bbox)
            painter.setPen(Qt.NoPen)
            painter.setBrush(brush)
            painter.drawPath(path)
            # Image attached (clipped to shape)
            if cfg.fill_mode == "image" and cfg.image_path and cfg.image_mode == "attached":
                painter.save()
                painter.setClipPath(path)
                self._paint_image(painter, size * 1.6 * cfg.image_scale)
                painter.restore()

        # ---- 4. Outline ----
        if cfg.outline_width > 0:
            oc = self.cycled_color(cfg.outline_color)
            pen = QPen(QColor(*oc, 255), cfg.outline_width)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        # ---- 5. Inner highlight ----
        if cfg.highlight and cfg.fill_mode not in ("image", "glass"):
            self._paint_highlight(painter, path, size)

        painter.restore()

    # ---------- sub-painters ----------
    def _paint_shadow(self, painter: QPainter, path: QPainterPath):
        cfg = self.config
        base_alpha = int(cfg.shadow_intensity * 2.55)
        painter.save()
        painter.setPen(Qt.NoPen)
        passes = 8
        for i in range(passes):
            t = i / (passes - 1)
            extra = t * 5.0
            alpha = int(base_alpha * (1.0 - t * 0.7))
            if alpha < 2:
                continue
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.save()
            painter.translate(
                cfg.shadow_offset_x + extra * (1 if cfg.shadow_offset_x >= 0 else -1),
                cfg.shadow_offset_y + extra * (1 if cfg.shadow_offset_y >= 0 else -1),
            )
            scale = 1.0 + t * 0.05
            painter.scale(scale, scale)
            painter.drawPath(path)
            painter.restore()
        painter.restore()

    def _paint_glow(self, painter: QPainter, path: QPainterPath, size: float):
        cfg = self.config
        if cfg.fill_mode == "solid":
            glow_rgb = self.cycled_color(cfg.color)
        elif cfg.fill_mode == "gradient" and cfg.gradient_stops:
            glow_rgb = self.cycled_stops()[0][1]
        else:
            glow_rgb = cfg.color
        r, g, b = glow_rgb
        base_alpha = int(cfg.glow_intensity * 2.55)

        painter.save()
        painter.setPen(Qt.NoPen)
        max_extra = max(4.0, cfg.glow_radius)
        passes = 10
        for i in range(passes):
            t = i / passes
            extra = max_extra * (1.0 - t * 0.5)
            alpha = int(base_alpha * (1.0 - t) * 0.35)
            if alpha < 2:
                continue
            stroker = QPainterPathStroker()
            stroker.setWidth(extra)
            halo = stroker.createStroke(path)
            painter.setBrush(QColor(r, g, b, alpha))
            painter.drawPath(halo)
        painter.restore()

    def _paint_highlight(self, painter: QPainter, path: QPainterPath,
                         size: float):
        painter.save()
        painter.setPen(Qt.NoPen)
        hl_grad = QRadialGradient(
            QPointF(-size * 0.35, -size * 0.35), size * 0.9
        )
        hl_grad.setColorAt(0.0, QColor(255, 255, 255, 110))
        hl_grad.setColorAt(0.5, QColor(255, 255, 255, 30))
        hl_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(hl_grad))
        painter.drawPath(path)
        painter.restore()

    def _paint_image(self, painter: QPainter, target_size: float):
        cfg = self.config
        if not cfg.image_path:
            return
        try:
            pm = QPixmap(cfg.image_path)
            if pm.isNull():
                return
            target = int(target_size)
            if target < 4:
                target = 4
            scaled = pm.scaledToWidth(target, Qt.SmoothTransformation)
            painter.drawPixmap(QPointF(-scaled.width() / 2, -scaled.height() / 2), scaled)
        except Exception:
            pass

    # ---------- glass ----------
    def _paint_glass(self, painter: QPainter, path: QPainterPath,
                     size: float, screen_capture: Optional[QImage]):
        """Glass fill: refract the screen behind the cursor (barrel
        distortion via numpy), clip to shape, add tint + edge highlight."""
        cfg = self.config

        # ---- A. Draw refracted (or fallback) screen capture clipped to shape ----
        painter.save()
        painter.setClipPath(path)

        if screen_capture is not None and not screen_capture.isNull():
            if HAS_NUMPY:
                distorted = self._barrel_distort(
                    screen_capture, size,
                    cfg.glass_refraction / 100.0,
                    cfg.glass_magnification / 100.0,
                )
                if distorted is not None and not distorted.isNull():
                    # Draw the QImage directly (drawImage works in
                    # offscreen mode; QPixmap.fromImage can crash on
                    # some headless setups and is unnecessary here).
                    painter.drawImage(
                        QRectF(-distorted.width() / 2,
                               -distorted.height() / 2,
                               distorted.width(),
                               distorted.height()),
                        distorted,
                        QRectF(0, 0, distorted.width(), distorted.height())
                    )
                else:
                    self._paint_glass_fallback(painter, screen_capture, size)
            else:
                self._paint_glass_fallback(painter, screen_capture, size)
        else:
            # No screen capture available (e.g. menu preview without fake bg)
            # Draw a translucent tinted fill so the shape is still visible.
            tint_alpha = int(cfg.glass_tint_amount * 2.55)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(*cfg.glass_tint, tint_alpha)))
            painter.drawPath(path)

        # ---- B. Tint overlay (colored glass) ----
        tint_alpha = int(cfg.glass_tint_amount * 2.55)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(*cfg.glass_tint, tint_alpha)))
        painter.drawPath(path)

        # ---- C. Specular highlight (glossy spot, top-left) ----
        if cfg.glass_specular:
            spec = QRadialGradient(
                QPointF(-size * 0.4, -size * 0.4), size * 0.7
            )
            spec.setColorAt(0.0, QColor(255, 255, 255, 180))
            spec.setColorAt(0.3, QColor(255, 255, 255, 60))
            spec.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(QBrush(spec))
            painter.setPen(Qt.NoPen)
            painter.drawPath(path)

        painter.restore()

        # ---- D. Edge highlight (bright rim, drawn after clip is cleared) ----
        if cfg.glass_edge > 0:
            edge_alpha = int(cfg.glass_edge * 2.55)
            # Outer bright edge
            pen = QPen(QColor(255, 255, 255, edge_alpha), cfg.glass_edge_width)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            # Subtle inner dark edge for depth (1px inside)
            inner_pen = QPen(QColor(0, 0, 0, int(edge_alpha * 0.3)), 1)
            painter.setPen(inner_pen)
            painter.drawPath(path)

    def _paint_glass_fallback(self, painter: QPainter,
                              screen_capture: QImage, size: float):
        """Fallback when numpy isn't available: scale up the captured
        image to simulate magnification (no real barrel distortion)."""
        cfg = self.config
        w = screen_capture.width()
        h = screen_capture.height()
        scale = 1.0 + cfg.glass_magnification / 200.0
        new_w = int(w * scale)
        new_h = int(h * scale)
        pm = QPixmap.fromImage(screen_capture).scaled(
            new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        painter.drawPixmap(QPointF(-new_w / 2, -new_h / 2), pm)

    def _barrel_distort(self, img: QImage, radius: float,
                        refraction: float, magnification: float) -> Optional[QImage]:
        """Apply barrel distortion to img using numpy.

        radius: cursor radius in px (defines the distortion region)
        refraction: 0..1, how strong the barrel distortion is
        magnification: 0..1, how much the center is zoomed

        Returns a new QImage the same size as img, with pixels remapped.

        The mapping is designed so that the visible region inside the
        cursor (r < radius in capture coords) samples from a wider area
        of the captured image, producing a clear magnifying-glass
        effect that shows what's behind/around the cursor.
        """
        if img.isNull() or radius < 1:
            return None
        try:
            # Convert to RGBA8888 for predictable byte order
            src = img.convertToFormat(QImage.Format_RGBA8888)
            w, h = src.width(), src.height()

            ptr = src.bits()
            ptr.setsize(w * h * 4)
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4)).copy()

            cx, cy = w / 2.0, h / 2.0
            # Build coordinate grids
            y_coords, x_coords = np.mgrid[0:h, 0:w].astype(np.float32)
            dx = x_coords - cx
            dy = y_coords - cy
            r_px = np.sqrt(dx * dx + dy * dy)
            # Normalize: r=1.0 at the cursor radius
            r = r_px / max(1.0, radius)

            # ---- Magnification + barrel bulge ----
            # For pixels INSIDE the cursor (r < 1): we want them to
            # sample from a SMALLER area of the capture (closer to
            # center), creating a magnifying-glass effect. The cursor
            # center samples from the center of the capture (which is
            # the desktop directly behind the cursor); the cursor edge
            # samples from a fraction of the way out.
            #
            # For pixels OUTSIDE the cursor (r >= 1): no distortion,
            # they sample from their own location (but these are
            # clipped out by setClipPath(path) anyway).
            inside = r < 1.0

            # Magnification factor: higher = stronger zoom.
            #   At r=0 (center): combined = 1 + magnification*1.5 (e.g. 1.45)
            #     -> src = center + dx / 1.45 (samples closer to center)
            #   At r=1 (edge): combined = 1
            #     -> src = center + dx (samples from cursor edge)
            # This produces a smooth magnifying-glass warp.
            mag_factor = 1.0 + magnification * (1.0 - r * r) * 1.5

            # Refraction: add a slight barrel/pincushion warp at the
            # edges so the magnification has a "lens" curvature rather
            # than being a flat scale.
            ref_factor = 1.0 + refraction * 0.4 * r * (1.0 - r)

            # Combined source radius divisor (higher = more zoom in)
            combined = mag_factor * ref_factor

            # Source coords: divide dx,dy by combined (samples closer
            # to center -> magnifies the desktop behind the cursor).
            # Outside the cursor, pass through unchanged.
            src_x = np.where(inside, cx + dx / combined, x_coords)
            src_y = np.where(inside, cy + dy / combined, y_coords)

            src_x = np.clip(src_x.astype(np.int32), 0, w - 1)
            src_y = np.clip(src_y.astype(np.int32), 0, h - 1)

            # Sample (nearest neighbor; bilinear would be smoother but
            # slower. numpy fancy indexing makes this fast.)
            distorted = arr[src_y, src_x]

            # ---- CRITICAL ALPHA FIX ----
            # BitBlt screen captures return BGRA with alpha=0 (GDI
            # doesn't write alpha for RGB content). If we just multiply
            # the source alpha by edge_fade, the entire image ends up
            # transparent and only the tint overlay shows through ->
            # the cursor looks like a flat colored shape with NO
            # refraction visible.
            #
            # Fix: FORCE alpha=255 everywhere inside the cursor (the
            # desktop content is fully opaque), then apply a soft fade
            # ONLY at the very rim so the glass blends smoothly into
            # the surrounding desktop. Outside the cursor, alpha=0
            # (clipped away by setClipPath anyway).
            # --------------------------------
            # Start with all-transparent
            new_alpha = np.zeros_like(distorted[..., 3], dtype=np.float32)
            # Inside the cursor: ramp from 255 at center to 0 at the
            # very edge (r=1). The 1.05 factor means alpha stays at
            # 255 until r > ~0.95, then fades to 0 at r=1. This keeps
            # the entire cursor body fully opaque (showing the
            # refraction) while smoothing only the outermost rim.
            inner_fade = np.clip((1.0 - r) * 20.0, 0.0, 1.0)
            new_alpha = np.where(inside, inner_fade * 255.0, 0.0)
            distorted[..., 3] = new_alpha.astype(np.uint8)

            distorted = np.ascontiguousarray(distorted)
            # ---- CRITICAL: copy bytes out of numpy into a Python
            # bytes object so the QImage's backing storage is owned by
            # Qt after .copy(). PyQt5's QImage(data, ...) does NOT take
            # ownership of the numpy buffer — if numpy GC's the array
            # before QPixmap.fromImage reads it, we segfault. ----
            byte_view = bytes(distorted)
            result = QImage(byte_view, w, h, w * 4, QImage.Format_RGBA8888)
            out = result.copy()   # deep copy detaches from byte_view
            # Keep refs alive until copy completes (defensive)
            del byte_view, distorted, result
            return out
        except Exception:
            return None

    # ---------- trail ----------
    def paint_trail(self, painter: QPainter, window_x: int, window_y: int,
                    center_x: float, center_y: float):
        cfg = self.config
        if not cfg.trail or len(self.trail_points) < 2:
            return
        now = time.monotonic()
        max_age = (cfg.trail_length / 12.0) * 0.4
        fade_factor = cfg.trail_fade / 100.0
        for i, (tx, ty, tt) in enumerate(self.trail_points):
            age = now - tt
            if age > max_age or age < 0.005:
                continue
            recency = 1.0 - (age / max_age)
            alpha = recency * fade_factor * 0.85
            if alpha < 0.02:
                continue
            lx = tx - window_x
            ly = ty - window_y
            if abs(lx - center_x) < 2 and abs(ly - center_y) < 2:
                continue
            self.paint(painter, lx, ly, alpha=alpha)
