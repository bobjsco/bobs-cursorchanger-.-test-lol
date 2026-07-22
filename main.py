"""
main.py
=======
CursorForge entry point.

A custom cursor studio for Windows: replace the system cursor with a
fully animated, glowing, gradient-filled shape or image.
"""
from __future__ import annotations

import sys


def _check_windows():
    if not sys.platform.startswith("win"):
        print("=" * 60, file=sys.stderr)
        print("CursorForge is a Windows-only application.", file=sys.stderr)
        print("It uses Win32 APIs (SetSystemCursor, CreateIconIndirect,", file=sys.stderr)
        print("SetWindowLong, GetCursorPos) which only exist on Windows.", file=sys.stderr)
        print("Detected platform:", sys.platform, file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        sys.exit(1)


def _set_app_identity():
    """Set the AppUserModelID so Windows groups this process under its own
    taskbar icon (instead of python.exe's icon). Also sets the process
    display name. Must be called BEFORE the QApplication is created."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        # Set AppUserModelID - this is what Windows uses for taskbar grouping.
        # Once set, the taskbar shows our app's icon (set via setWindowIcon)
        # instead of python.exe's icon.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "CursorForge.CursorForge.App"
        )
    except Exception:
        pass


def _make_app_icon_pixmap():
    """Generate the app icon as a QPixmap (64x64).

    Design: dark background, cyan ring with magenta center dot.
    Used for both the window icon and the taskbar icon (once
    AppUserModelID is set).
    """
    from PyQt5.QtGui import QPixmap, QPainter, QColor, QPen, QBrush, QRadialGradient, QPointF
    from PyQt5.QtCore import Qt, QRectF
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    # Outer cyan ring
    p.setPen(QPen(QColor("#00f0ff"), 3))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(8, 8, 48, 48)

    # Inner magenta dot with radial gradient
    grad = QRadialGradient(QPointF(28, 28), 14)
    grad.setColorAt(0.0, QColor(255, 255, 255, 255))
    grad.setColorAt(0.4, QColor(255, 45, 149, 255))
    grad.setColorAt(1.0, QColor(180, 20, 100, 255))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    p.drawEllipse(22, 22, 20, 20)
    p.end()
    return pm


def main():
    _check_windows()
    _set_app_identity()

    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QFont, QIcon
    from menu_window import MenuWindow

    app = QApplication(sys.argv)
    app.setApplicationName("CursorForge")
    app.setOrganizationName("CursorForge")
    app.setQuitOnLastWindowClosed(False)  # keep running in tray

    font = QFont("Segoe UI", 9)
    app.setFont(font)

    # Set the app icon from generated pixmap. Combined with the
    # AppUserModelID set above, this makes the taskbar show OUR icon
    # instead of python's.
    icon_pm = _make_app_icon_pixmap()
    app_icon = QIcon(icon_pm)
    app.setWindowIcon(app_icon)

    # Build the menu window (but don't show yet - splash shows first).
    win = MenuWindow()
    win.setWindowIcon(app_icon)

    # Show splash, then show menu when splash finishes.
    try:
        from splash import SplashWindow
        def on_splash_done():
            win.show()
            win.raise_()
            win.activateWindow()

        splash = SplashWindow(on_finished=on_splash_done)
        splash.show()
    except Exception as e:
        # Splash failed (e.g. on a headless test) - just show the window.
        print(f"[CursorForge] Splash skipped: {e}", file=sys.stderr)
        win.show()
        win.raise_()
        win.activateWindow()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
