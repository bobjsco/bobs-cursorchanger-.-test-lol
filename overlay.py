"""
overlay.py
==========
The click-through topmost overlay that replaces the system cursor.

Architecture:
  1. Hide the real system cursor by SetSystemCursor-ing a fully
     transparent 1x1 .cur in its place. (Restored on exit.)
  2. Create a borderless, frameless, topmost, translucent QWidget.
  3. After it's shown, mark it WS_EX_TRANSPARENT | WS_EX_LAYERED so
     mouse events pass through to whatever is underneath.
  4. A QTimer at ~60 FPS polls GetCursorPos(), moves the window so the
     cursor sits at the window's center, and triggers a repaint.
  5. paintEvent() delegates to CursorPainter which draws the cursor
     (with glow, gradient, shadow, glass, animations, trail, motion).
  6. For glass mode, captures the screen region behind the cursor each
     frame and passes it to the painter for barrel distortion.

Motion:
  - Mouse velocity is computed each frame (smoothed via EMA).
  - Velocity is passed to the painter for the squish deformation.
  - The painter maintains spring-physics state for the drawing offset
    (inertia + overshoot when the mouse stops).
  - The overlay window itself moves instantly with the cursor (so
    clicks land accurately); only the drawn cursor shape has the offset.

On crash / unexpected exit:
  * `atexit` calls SystemParametersInfoA(SPI_SETCURSORS, ...) which
    reloads all default system cursors from the registry.
  * Closing the window via the menu also restores.
  * Worst case: reboot Windows (always restores defaults).
"""
from __future__ import annotations

import atexit
import ctypes
import math
import sys
import time
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QPainter, QColor, QImage
from PyQt5.QtWidgets import QWidget, QApplication

from cursor_painter import CursorPainter


IS_WINDOWS = sys.platform.startswith("win")


# ---------------------------------------------------------------------------
# Win32 plumbing
# ---------------------------------------------------------------------------
if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32

    OCR_NORMAL = 32512
    SPI_SETCURSORS = 0x0057
    SPIF_UPDATEINIFILE = 0x0001

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

    class ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    gdi32.CreateBitmap.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
    ]
    gdi32.CreateBitmap.restype = wintypes.HBITMAP
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
    user32.CreateIconIndirect.restype = wintypes.HCURSOR
    user32.SetSystemCursor.argtypes = [wintypes.HCURSOR, ctypes.c_uint]
    user32.SetSystemCursor.restype = wintypes.BOOL
    user32.SystemParametersInfoA.argtypes = [
        ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
    ]
    user32.SystemParametersInfoA.restype = wintypes.BOOL
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

    # ---- Screen capture plumbing (BitBlt without CAPTUREBLT) ----
    # We deliberately omit the CAPTUREBLT (0x40000000) flag so that
    # layered windows — including OUR overlay — are NOT included in
    # the capture. This is what lets the glass cursor see the actual
    # desktop behind it instead of its own previous frame.
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_uint32,
    ]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32),
            ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                    ("bmiColors", ctypes.c_uint32 * 3)]

    SRCCOPY = 0x00CC0020
    BI_RGB = 0
    DIB_RGB_COLORS = 0

    def _capture_screen_region_excluding_overlay(x: int, y: int,
                                                  w: int, h: int):
        """Capture a screen region as a QImage, EXCLUDING our overlay
        window (and any other layered windows).

        Uses BitBlt without the CAPTUREBLT flag, so layered windows
        are not composited into the capture. This is the key trick
        that makes the glass cursor show the desktop behind it
        instead of its own previous frame.
        """
        try:
            # Clamp to screen bounds so we don't grab garbage
            sw = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            sh = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            x0 = max(0, x)
            y0 = max(0, y)
            x1 = min(sw, x + w)
            y1 = min(sh, y + h)
            cw = x1 - x0
            ch = y1 - y0
            if cw <= 0 or ch <= 0:
                return None

            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, cw, ch)
            old = gdi32.SelectObject(hdc_mem, hbmp)

            # BitBlt WITHOUT CAPTUREBLT -> excludes layered windows
            ok = gdi32.BitBlt(hdc_mem, 0, 0, cw, ch,
                              hdc_screen, x0, y0, SRCCOPY)
            if not ok:
                gdi32.SelectObject(hdc_mem, old)
                gdi32.DeleteObject(hbmp)
                gdi32.DeleteDC(hdc_mem)
                user32.ReleaseDC(0, hdc_screen)
                return None

            # Extract bits as BGRA (top-down via negative biHeight)
            bi = BITMAPINFO()
            bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bi.bmiHeader.biWidth = cw
            bi.bmiHeader.biHeight = -ch   # negative = top-down
            bi.bmiHeader.biPlanes = 1
            bi.bmiHeader.biBitCount = 32
            bi.bmiHeader.biCompression = BI_RGB

            buf = ctypes.create_string_buffer(cw * ch * 4)
            got = gdi32.GetDIBits(hdc_mem, hbmp, 0, ch, buf,
                                  ctypes.byref(bi), DIB_RGB_COLORS)

            gdi32.SelectObject(hdc_mem, old)
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)

            if not got:
                return None

            # On little-endian x86, BGRA bytes map directly to
            # QImage.Format_ARGB32 (which is BGRA in memory).
            qimg = QImage(buf, cw, ch, cw * 4, QImage.Format_ARGB32)
            # Copy so the buffer can be freed
            return qimg.copy()
        except Exception:
            return None

    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int

    def _restore_system_cursor():
        try:
            user32.SystemParametersInfoA(SPI_SETCURSORS, 0, None, SPIF_UPDATEINIFILE)
        except Exception:
            pass

    def _hide_system_cursor() -> bool:
        CS = 32
        xor_bytes = bytes(CS * CS * 3)
        and_bytes = bytes([0xFF] * (CS * 4))
        hbm_color = gdi32.CreateBitmap(CS, CS, 1, 24, xor_bytes)
        hbm_mask = gdi32.CreateBitmap(CS, CS, 1, 1, and_bytes)
        if not hbm_color or not hbm_mask:
            if hbm_color:
                gdi32.DeleteObject(hbm_color)
            if hbm_mask:
                gdi32.DeleteObject(hbm_mask)
            return False
        ii = ICONINFO()
        ii.fIcon = 0
        ii.xHotspot = 0
        ii.yHotspot = 0
        ii.hbmMask = hbm_mask
        ii.hbmColor = hbm_color
        cursor = user32.CreateIconIndirect(ctypes.byref(ii))
        gdi32.DeleteObject(hbm_color)
        gdi32.DeleteObject(hbm_mask)
        if not cursor:
            return False
        ok = user32.SetSystemCursor(cursor, OCR_NORMAL)
        return bool(ok)

else:
    _restore_system_cursor = lambda: None
    _hide_system_cursor = lambda: False
    _capture_screen_region_excluding_overlay = lambda x, y, w, h: None


atexit.register(_restore_system_cursor)


# ---------------------------------------------------------------------------
# Overlay widget
# ---------------------------------------------------------------------------
class CursorOverlay(QWidget):
    """Click-through topmost overlay that paints the custom cursor."""

    WINDOW_SIZE = 400   # 400x400, cursor at center (200, 200)

    def __init__(self, painter: CursorPainter, parent=None):
        super().__init__(parent)
        self.painter = painter
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.NoFocus)

        self.resize(self.WINDOW_SIZE, self.WINDOW_SIZE)

        self._cursor_hidden = False
        self._click_through_set = False

        # Motion state
        self._vx = 0.0
        self._vy = 0.0
        self._draw_offset = (0.0, 0.0)
        self._screen_capture: Optional[QImage] = None
        self._last_capture_pos: Optional[tuple] = None
        # Lag optimization: track last cursor position + last paint time so
        # we can skip repaints when nothing is changing.
        self._last_cursor_pos: Optional[tuple] = None
        self._idle_frames = 0
        self._has_active_animations = False

        # Initial position
        pos = self._get_cursor_pos()
        if pos:
            self.move(pos[0] - self.WINDOW_SIZE // 2,
                      pos[1] - self.WINDOW_SIZE // 2)
            self._last_cursor_pos = pos

        # Update loop - adaptive interval for lag reduction.
        # When cursor is moving OR animations are active: 8ms (~125 FPS max).
        # When idle (no movement, no animations): 33ms (~30 FPS) to save CPU.
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(8)

    # ---------- lifecycle ----------
    def showEvent(self, event):
        super().showEvent(event)
        if IS_WINDOWS:
            self._make_click_through()
            if _hide_system_cursor():
                self._cursor_hidden = True

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._cursor_hidden:
            _restore_system_cursor()
            self._cursor_hidden = False

    def closeEvent(self, event):
        if self._cursor_hidden:
            _restore_system_cursor()
            self._cursor_hidden = False
        super().closeEvent(event)

    # ---------- Win32 setup ----------
    def _make_click_through(self):
        if self._click_through_set or not IS_WINDOWS:
            return
        try:
            hwnd = int(self.winId())
            ex = user32.GetWindowLongA(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongA(
                hwnd, GWL_EXSTYLE,
                ex | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            )
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            self._click_through_set = True
        except Exception:
            pass

    # ---------- cursor polling ----------
    def _get_cursor_pos(self) -> Optional[tuple]:
        if IS_WINDOWS:
            try:
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                return (pt.x, pt.y)
            except Exception:
                return None
        else:
            from PyQt5.QtGui import QCursor
            pos = QCursor.pos()
            return (pos.x(), pos.y())

    def _capture_screen_region(self, x: int, y: int, w: int, h: int) -> Optional[QImage]:
        """Capture a screen region as a QImage, EXCLUDING our overlay.

        Uses direct Win32 BitBlt WITHOUT the CAPTUREBLT flag so that
        layered windows (including our overlay) are not included in
        the capture. This is the key trick that makes the glass cursor
        show the actual desktop behind it instead of its own previous
        frame.

        Falls back to Qt's grabWindow (which DOES include layered
        windows) only if the Win32 path fails.
        """
        if not IS_WINDOWS:
            return None
        # Primary path: direct Win32, excludes overlay
        img = _capture_screen_region_excluding_overlay(x, y, w, h)
        if img is not None:
            return img
        # Fallback: Qt grabWindow (includes overlay — not ideal but
        # better than nothing if BitBlt path fails)
        try:
            screen = QApplication.primaryScreen()
            if screen is None:
                return None
            pm = screen.grabWindow(0, x, y, w, h)
            return pm.toImage()
        except Exception:
            return None

    def _tick(self):
        pos = self._get_cursor_pos()
        if not pos:
            return

        # Update motion physics (mouse velocity + spring offset)
        vx, vy = self.painter.update_motion(pos[0], pos[1])
        self._vx = vx
        self._vy = vy
        self._draw_offset = self.painter.get_drawing_offset()

        # ---- Lag optimization: detect whether anything is changing ----
        # We need to repaint if ANY of:
        #   - cursor moved
        #   - velocity is non-trivial (spring physics still settling)
        #   - animations are active (pulse, color cycle, spin, trail)
        #   - glass mode (screen capture changes each frame)
        # Otherwise we can skip the repaint and slow the timer down.
        cfg = self.painter.config
        cursor_moved = (
            self._last_cursor_pos is None
            or abs(pos[0] - self._last_cursor_pos[0]) > 0
            or abs(pos[1] - self._last_cursor_pos[1]) > 0
        )
        speed = math.sqrt(vx * vx + vy * vy)
        spring_active = speed > 5.0 or (
            abs(self._draw_offset[0]) > 0.5
            or abs(self._draw_offset[1]) > 0.5
        )
        anim_active = bool(
            getattr(cfg, "anim_pulse", False)
            or getattr(cfg, "anim_color_cycle", False)
            or getattr(cfg, "anim_spin", False)
            or (getattr(cfg, "anim_trail", False) and
                len(getattr(self.painter, "_trail", [])) > 0)
        )
        glass_active = (cfg.fill_mode == "glass")
        trail_draining = (
            getattr(cfg, "anim_trail", False) is False
            and len(getattr(self.painter, "_trail", [])) > 0
        )

        anything_changing = (
            cursor_moved or spring_active or anim_active
            or glass_active or trail_draining
        )

        if anything_changing:
            self._idle_frames = 0
            # Speed the timer back up
            if self.timer.interval() != 8:
                self.timer.setInterval(8)
        else:
            self._idle_frames += 1
            # After ~10 idle frames, slow down to 33ms (~30 FPS) to save CPU
            if self._idle_frames > 10 and self.timer.interval() != 33:
                self.timer.setInterval(33)
            # Skip the rest of the tick - no need to move window, capture
            # screen, or repaint if nothing is changing.
            self._last_cursor_pos = pos
            return

        self._last_cursor_pos = pos

        # ---- Capture screen region for glass effect BEFORE moving the
        # overlay window. The overlay is still at its previous position
        # right now, so the desktop at the new cursor position is clean
        # (no previous cursor frame to refract). Combined with BitBlt
        # without CAPTUREBLT (in _capture_screen_region), this ensures
        # the glass sees the actual desktop behind it. ----
        if glass_active:
            # Capture a region ~6x the cursor size, centered on cursor.
            cap_size = int(max(cfg.size, 10) * 6)
            cap_x = pos[0] - cap_size // 2
            cap_y = pos[1] - cap_size // 2
            self._screen_capture = self._capture_screen_region(
                cap_x, cap_y, cap_size, cap_size
            )
        else:
            self._screen_capture = None

        # Move window so cursor is at center
        self.move(pos[0] - self.WINDOW_SIZE // 2,
                  pos[1] - self.WINDOW_SIZE // 2)

        # Trail
        self.painter.add_trail_point(*pos)

        self.update()

    # ---------- paint ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        cx = self.WINDOW_SIZE // 2
        cy = self.WINDOW_SIZE // 2

        # Apply spring-physics drawing offset
        dx, dy = self._draw_offset
        draw_cx = cx + dx
        draw_cy = cy + dy

        # Trail (uses screen coords -> window-local)
        self.painter.paint_trail(p, self.x(), self.y(), cx, cy)

        # Main cursor at offset position
        self.painter.paint(
            p, draw_cx, draw_cy,
            vx=self._vx, vy=self._vy,
            screen_capture=self._screen_capture,
        )
