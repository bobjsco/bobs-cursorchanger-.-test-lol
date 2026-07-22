# CursorForge

A custom cursor studio for Windows. Replace the system cursor with a
fully animated, glowing, gradient-filled shape or image. Includes
bouncing ball physics, glass distortion, trail effects, and more.

![version](https://img.shields.io/badge/version-1.1.0-00f0ff)
![platform](https://img.shields.io/badge/platform-Windows-0078D4)
![python](https://img.shields.io/badge/python-3.8%2B-3776AB)

---

## What is this?

CursorForge is a Windows-only app that replaces your system cursor with
a customizable animated shape. Features include:

- **14 cursor shapes** (circle, square, triangle, star, heart, arrow, etc.)
- **4 fill modes**: solid, gradient, image, glass (real-time screen refraction)
- **Effects**: glow, shadow, outline, highlight
- **Animations**: pulse, color cycle, spin, trail
- **Motion physics**: squish (stretch in direction of motion), inertia (spring)
- **Ball physics mode**: click to spawn bouncing balls, drag to throw them
- **System tray integration** — runs in background, right-click for menu

## Repo structure

```
cursorforge/
├── cursorforge/                  # App source code
│   ├── main.py                   # Entry point (splash + app identity + tray)
│   ├── menu_window.py            # Main menu UI (1084 lines)
│   ├── cursor_painter.py         # Cursor rendering (shapes, gradients, glass)
│   ├── overlay.py                # Click-through topmost cursor overlay
│   ├── ball_overlay.py           # Bouncing ball physics overlay
│   ├── shapes.py                 # Shape geometry definitions
│   ├── theme.py                  # Dark neon QSS theme
│   ├── splash.py                 # Animated splash screen
│   └── requirements.txt          # Runtime deps (PyQt5, numpy)
├── build/
│   └── build_standalone_bat.py   # Generator: builds CursorForge.bat
├── README.md
├── LICENSE
└── .gitignore
```

## How distribution works

You don't ship an `.exe`. You ship a single `.bat` file.

`build/build_standalone_bat.py` reads all the `.py` files in
`cursorforge/`, base64-encodes them, and embeds them inside a polyglot
`.bat` file that is BOTH a valid Windows batch script AND valid Python.

When a user double-clicks `CursorForge.bat`:

1. **BAT line 1** runs Python on the same file with `-x` (skips line 1)
2. **Python bootstrapper** takes over:
   - Shows a Tkinter loading screen with progress bar
   - Hash-diffs each embedded file vs `%LOCALAPPDATA%\cursorforgesource\`
   - Only copies files that changed (delta sync)
   - Creates a Python venv on first run
   - `pip install` requirements on first run (or when requirements.txt changes)
   - Creates Start Menu + Desktop shortcuts
   - Writes an Add/Remove Programs registry entry
   - Launches the app from the venv
3. **Subsequent runs**: only changed files are replaced, app launches fast

### Why this approach?

- No PyInstaller (10+ minute builds, 50MB+ exes, antivirus false positives)
- No NSIS / Inno Setup installer
- Single file users can download and double-click
- Differential updates — only changed files are copied
- Source is always recoverable from the install dir

## Building the distributable

### Requirements

- Python 3.8+ on PATH (with `py` launcher)
- The files in this repo

### Steps

1. Edit code in `cursorforge/`
2. Bump `APP_VERSION` at the top of `build/build_standalone_bat.py`
3. Run:
   ```bash
   python build/build_standalone_bat.py
   ```
4. Output: `CursorForge.bat` (~200 KB) — distribute this single file

Users who already have CursorForge installed just re-download the new
`.bat` and double-click. The hash-diff update will only replace the
files that actually changed.

## Command-line flags

```bash
CursorForge.bat                  # Install or update, then launch app
CursorForge.bat --uninstall      # Remove CursorForge completely
CursorForge.bat --force          # Force update even if version matches
CursorForge.bat --no-launch      # Update/patch, don't launch the app
CursorForge.bat --help           # Show help
```

## For users

### Requirements

- Windows 10 or later
- Python 3.8+ installed ([download](https://www.python.org/downloads/))
  - Tick **"Add Python to PATH"** during install

### Install

1. Download `CursorForge.bat`
2. Double-click it
3. Wait ~30 seconds for the first install (downloads PyQt5 + numpy)
4. The app launches automatically

### Update

Double-click the **CursorForge Bootstrapper** desktop shortcut. It
patches files without launching the app.

Or just re-download and double-click the latest `CursorForge.bat`.

### Uninstall

- Method 1: Settings → Apps → Add/Remove Programs → CursorForge → Uninstall
- Method 2: `CursorForge.bat --uninstall`

## Install location

```
%LOCALAPPDATA%\cursorforgesource\
├── main.py, overlay.py, ...        # App source
├── launch.bat                      # Runs the app (pythonw main.py)
├── CursorForge.bat                 # Copy of the bootstrapper (for updates)
├── CursorForge Bootstrapper.bat    # Shortcut target for updates
├── install_info.json               # Version metadata
├── venv\                           # Python venv with PyQt5, numpy
└── launch.log                      # Debug log from last launch
```

## Versioning

Bump `APP_VERSION` in `build/build_standalone_bat.py` every time you
change code. Even though the hash-diff catches file changes anyway,
bumping the version lets the loading screen show a nice
"Updating to vX.Y.Z" message instead of "Already up to date".

Current version: **1.1.0**

## Tech stack

- **Python 3.8+**
- **PyQt5** — GUI framework
- **numpy** — numeric computations for cursor rendering
- **Tkinter** — bootstrapper loading screen (no PyQt5 dependency at boot time)
- **Win32 API** — `SetSystemCursor`, `SetWindowLong`, `GetCursorPos`,
  `SetCurrentProcessExplicitAppUserModelID`, BitBlt for screen capture

## License

MIT — see [LICENSE](LICENSE).
