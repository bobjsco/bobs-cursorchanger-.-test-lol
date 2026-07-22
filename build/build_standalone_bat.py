#!/usr/bin/env python3
"""
Generate a single standalone CursorForge.bat file (polyglot BAT + Python).

Format:
  Line 1: @python -x "%~f0" %* & goto :eof      (BAT command, skipped by Python)
  Line 2+: Python code                           (never reached by BAT)

When the user double-clicks the .bat:
  1. Windows runs it as a batch file
  2. Line 1 calls python with -x flag on the same file, then exits the BAT
  3. The -x flag tells Python to skip line 1
  4. Python runs lines 2+ as a normal script

Usage:
  python build/build_standalone_bat.py

Output is written to dist/CursorForge.bat (relative to repo root).
"""
import base64
from pathlib import Path

# Resolve paths relative to THIS script so it works after cloning the repo.
# Script lives at <repo>/build/build_standalone_bat.py
# Source lives at <repo>/cursorforge/
# Output goes to <repo>/dist/CursorForge.bat
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SRC = REPO_ROOT / "cursorforge"
OUT = REPO_ROOT / "dist" / "CursorForge.bat"

APP_FILES = [
    "main.py",
    "cursor_painter.py",
    "overlay.py",
    "menu_window.py",
    "ball_overlay.py",
    "shapes.py",
    "theme.py",
    "splash.py",
    "requirements.txt",
]

APP_VERSION = "1.1.1"

# Read and base64-encode each app file
embedded = {}
for fname in APP_FILES:
    p = SRC / fname
    if not p.exists():
        raise FileNotFoundError(f"Missing: {p}")
    data = p.read_bytes()
    embedded[fname] = base64.b64encode(data).decode("ascii")

# Build the embedded files dict as Python source
embedded_repr = "{\n"
for fname, b64 in embedded.items():
    embedded_repr += f"    {fname!r}: {b64!r},\n"
embedded_repr += "}"

# The Python bootstrapper code
BOOTSTRAPPER_PY = '''# CursorForge bootstrapper (Python part of the polyglot .bat)
# Lines below are pure Python - the BAT line above already exited.
import os
import sys
# Print IMMEDIATELY so we know Python actually started. If the user sees
# this, Python ran. If they don't, Python isn't running at all (BAT issue).
sys.stdout.write("[CursorForge] Python bootstrapper started.\\n")
sys.stdout.flush()
import json
import shutil
import base64
import hashlib
import subprocess
import threading
import queue
import time
from pathlib import Path
from datetime import datetime, date

APP_NAME = "CursorForge"
APP_VERSION = "''' + APP_VERSION + '''"
SOURCE_DIR_NAME = "cursorforgesource"

LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
SOURCE_DIR = LOCALAPPDATA / SOURCE_DIR_NAME
VENV_DIR = SOURCE_DIR / "venv"
INSTALL_INFO_FILE = SOURCE_DIR / "install_info.json"

APPDATA = Path(os.environ.get("APPDATA", os.path.expanduser("~")))
START_MENU_DIR = APPDATA / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
DESKTOP_DIR = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"

try:
    import winreg
except ImportError:
    winreg = None

UNINSTALL_REG_PATH = rf"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP_NAME}"

EMBEDDED_FILES = ''' + embedded_repr + '''

LAUNCHER_BAT = SOURCE_DIR / "launch.bat"


def log(msg):
    print(f"[{APP_NAME}] {msg}", flush=True)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                buf = f.read(65536)
                if not buf:
                    break
                h.update(buf)
        return h.hexdigest()
    except Exception:
        return None


def find_system_python():
    try:
        r = subprocess.run(["py", "-3", "--version"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return "py"
    except Exception:
        pass
    for c in ["python", "python3"]:
        try:
            r = subprocess.run([c, "--version"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and "Python 3" in (r.stdout + r.stderr):
                return c
        except Exception:
            continue
    for ver in ["3.12", "3.11", "3.10", "3.9"]:
        for prefix in [
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("ProgramFiles", ""),
            "C:/Python",
        ]:
            if not prefix:
                continue
            cand = Path(prefix) / f"Python{ver.replace('.', '')}" / "python.exe"
            if cand.exists():
                return str(cand)
    return None


def venv_python():
    return VENV_DIR / "Scripts" / "python.exe"


def venv_pythonw():
    return VENV_DIR / "Scripts" / "pythonw.exe"


def venv_pip():
    return VENV_DIR / "Scripts" / "pip.exe"


def venv_exists():
    return venv_python().exists() and venv_pip().exists()


def create_venv(python_cmd):
    log(f"Creating venv at {VENV_DIR} ...")
    VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    try:
        if VENV_DIR.exists():
            shutil.rmtree(VENV_DIR, ignore_errors=True)
        r = subprocess.run(
            [python_cmd, "-m", "venv", str(VENV_DIR)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            log(f"venv creation failed: {r.stderr}")
            return False
        return venv_exists()
    except Exception as e:
        log(f"venv exception: {e}")
        return False


def pip_install_requirements(upgrade=False):
    req_file = SOURCE_DIR / "requirements.txt"
    if not req_file.exists():
        return False
    label = "upgrade" if upgrade else "first run"
    log(f"pip install ({label}) ...")
    cmd = [str(venv_pip()), "install"]
    if upgrade:
        cmd.append("--upgrade")
    cmd += ["-r", str(req_file)]
    try:
        r = subprocess.run(cmd, timeout=600)
        return r.returncode == 0
    except Exception as e:
        log(f"pip exception: {e}")
        return False


def create_shortcut(shortcut_path, target, description="",
                    working_dir=None, icon_path=None):
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut_path.parent.mkdir(parents=True, exist_ok=True)
        lnk = shell.CreateShortCut(str(shortcut_path))
        lnk.Targetpath = str(target)
        if working_dir:
            lnk.WorkingDirectory = str(working_dir)
        if icon_path and Path(icon_path).exists():
            lnk.IconLocation = str(icon_path)
        if description:
            lnk.Description = description
        lnk.Save()
        return True
    except ImportError:
        pass
    try:
        ps = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$lnk = $ws.CreateShortcut('{shortcut_path}'); "
            f"$lnk.TargetPath = '{target}'; "
        )
        if working_dir:
            ps += f"$lnk.WorkingDirectory = '{working_dir}'; "
        if icon_path and Path(icon_path).exists():
            ps += f"$lnk.IconLocation = '{icon_path}'; "
        if description:
            ps += f"$lnk.Description = '{description}'; "
        ps += "$lnk.Save()"
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       check=True, capture_output=True, timeout=15)
        return True
    except Exception as e:
        log(f"shortcut failed: {e}")
        return False


def write_uninstall_registry():
    if winreg is None:
        return
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_PATH) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(key, "InstallDate", 0, winreg.REG_SZ,
                              date.today().isoformat())
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(SOURCE_DIR))
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ,
                              f'"{LAUNCHER_BAT}" --uninstall')
            winreg.SetValueEx(key, "NoModify", 0, winreg.DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.DWORD, 1)
    except Exception as e:
        log(f"registry write failed: {e}")


def update_registry_version():
    if winreg is None:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_PATH,
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
    except FileNotFoundError:
        write_uninstall_registry()
    except Exception:
        pass


def remove_registry_entry():
    if winreg is None:
        return
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_PATH)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def read_install_info():
    if not INSTALL_INFO_FILE.exists():
        return {}
    try:
        with open(INSTALL_INFO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_install_info(info):
    with open(INSTALL_INFO_FILE, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)


def write_launcher_bat():
    """Write the launch.bat that starts the actual CursorForge app.

    Uses pythonw.exe (no console window) so the user only sees the GUI.
    Falls back to python.exe only if pythonw is missing.
    """
    pyw = venv_pythonw()
    py = venv_python()
    py_to_use = pyw if pyw.exists() else py
    LAUNCHER_BAT.write_text(
        f'@echo off\\r\\n'
        f'cd /d "{SOURCE_DIR}"\\r\\n'
        f'start "" "{py_to_use}" "{SOURCE_DIR / "main.py"}"\\r\\n',
        encoding="utf-8",
    )


# Path to a SECOND launcher that re-runs the bootstrapper for updates/patches.
# This is what the user can double-click later to update CursorForge without
# having to re-download the .bat file.
BOOTSTRAPPER_LAUNCHER = SOURCE_DIR / "CursorForge Bootstrapper.bat"


def write_bootstrapper_launcher():
    """Write a small .bat at SOURCE_DIR that re-runs THIS bootstrapper.

    The bootstrapper (this very file, the polyglot .bat) is copied to
    SOURCE_DIR so the user can re-run it for updates/patches later. A
    desktop shortcut pointing to this copy is created.
    """
    # Copy the running .bat file (sys.argv[0]) to the source dir so the
    # user can re-run it without needing the original download.
    # If we can't find the original (e.g. running from a different
    # location), we write a stub that just prints a helpful message.
    try:
        import shutil as _shutil
        original = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
        # The original .bat is the file Python is currently executing.
        # When Python runs via `py -x "%~f0"`, sys.argv[0] is the .bat path.
        # We copy it to a stable name in SOURCE_DIR.
        target_bat = SOURCE_DIR / "CursorForge.bat"
        if original and original.exists() and original.suffix.lower() == ".bat":
            _shutil.copy2(original, target_bat)
        # Write the launcher that just calls the copied .bat
        # --no-launch: when the user runs the Bootstrapper to update/patch,
        # we don't auto-start the app - they can start it from the
        # CursorForge shortcut when ready.
        BOOTSTRAPPER_LAUNCHER.write_text(
            f'@echo off\\r\\n'
            f'cd /d "{SOURCE_DIR}"\\r\\n'
            f'echo [CursorForge Bootstrapper] Checking for updates and patching files...\\r\\n'
            f'call "{target_bat}" --no-launch %*\\r\\n',
            encoding="utf-8",
        )
    except Exception as e:
        log(f"write_bootstrapper_launcher failed: {e}")


def version_tuple(v):
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


class LoadingScreen:
    def __init__(self):
        self.msg_queue = queue.Queue()
        self.done = False
        self.error = None
        self._tk = None
        self._status_var = None
        self._progress = None
        self._use_tk = False
        try:
            import tkinter as tk
            from tkinter import ttk
            self._tk = tk.Tk()
            self._tk.title(APP_NAME)
            self._tk.geometry("500x240")
            self._tk.resizable(False, False)
            self._tk.configure(bg="#0a0a12")
            self._tk.update_idletasks()
            w = self._tk.winfo_width()
            h = self._tk.winfo_height()
            sw = self._tk.winfo_screenwidth()
            sh = self._tk.winfo_screenheight()
            self._tk.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

            tk.Label(self._tk, text=APP_NAME, bg="#0a0a12", fg="#00f0ff",
                     font=("Segoe UI", 22, "bold")).pack(pady=(30, 4))
            tk.Label(self._tk, text=f"v{APP_VERSION}", bg="#0a0a12", fg="#7a7a8a",
                     font=("Segoe UI", 9)).pack(pady=(0, 14))

            self._status_var = tk.StringVar(value="Starting...")
            tk.Label(self._tk, textvariable=self._status_var, bg="#0a0a12",
                     fg="#e0e0e0", font=("Segoe UI", 10),
                     wraplength=460).pack(pady=(0, 12), padx=20)

            style = ttk.Style()
            style.theme_use("default")
            style.configure("cyan.Horizontal.TProgressbar",
                            troughcolor="#1a1a26",
                            background="#00f0ff",
                            bordercolor="#1a1a26",
                            lightcolor="#00f0ff",
                            darkcolor="#00a0c0")
            self._progress = ttk.Progressbar(self._tk, orient="horizontal",
                                             length=440, mode="determinate",
                                             style="cyan.Horizontal.TProgressbar")
            self._progress.pack(pady=(0, 20))
            self._progress["value"] = 0
            self._progress["maximum"] = 100
            self._use_tk = True
        except Exception as e:
            print(f"[{APP_NAME}] (no GUI: {e})")
            self._use_tk = False

    def set_status(self, msg, progress=None):
        self.msg_queue.put(("status", msg, progress))

    def set_done(self, error=None):
        self.msg_queue.put(("done", None, error))

    def pump(self):
        if self._use_tk and self._tk is not None:
            while True:
                try:
                    item = self.msg_queue.get_nowait()
                except queue.Empty:
                    break
                kind, msg, extra = item
                if kind == "status":
                    if self._status_var is not None:
                        self._status_var.set(msg)
                    if self._progress is not None and extra is not None:
                        self._progress["value"] = float(extra)
                elif kind == "done":
                    self.error = extra
                    self.done = True
                    return False
            self._tk.update_idletasks()
            self._tk.update()
        else:
            while True:
                try:
                    item = self.msg_queue.get_nowait()
                except queue.Empty:
                    break
                kind, msg, extra = item
                if kind == "status":
                    pct = f" ({extra:.0f}%)" if extra is not None else ""
                    print(f"[{APP_NAME}] {msg}{pct}")
                elif kind == "done":
                    self.error = extra
                    self.done = True
                    return False
        return True

    def close(self):
        if self._use_tk and self._tk is not None:
            try:
                self._tk.destroy()
            except Exception:
                pass
            self._tk = None


def worker_install_or_update(screen, force=False):
    try:
        screen.set_status("Creating source folder...", 5)
        log("Creating source folder...")
        SOURCE_DIR.mkdir(parents=True, exist_ok=True)

        screen.set_status("Checking local files...", 15)
        log("Checking local files...")
        changes = []
        unchanged = 0
        for fname, b64 in EMBEDDED_FILES.items():
            new_bytes = base64.b64decode(b64)
            new_hash = sha256_bytes(new_bytes)
            old_hash = sha256_file(SOURCE_DIR / fname)
            if new_hash == old_hash and old_hash is not None:
                unchanged += 1
            else:
                changes.append((fname, new_bytes))

        info = read_install_info()
        installed_version = info.get("version", "0.0.0")
        log(f"Installed: v{installed_version}  |  Update: v{APP_VERSION}  |  {len(changes)} changed, {unchanged} unchanged")
        screen.set_status(
            f"Installed: v{installed_version}  |  Update: v{APP_VERSION}  |  {len(changes)} changed",
            30)

        if not changes and not force and version_tuple(APP_VERSION) <= version_tuple(installed_version):
            log("Already up to date - skipping install.")
            screen.set_status("Already up to date!", 100)
            return None

        total = max(len(changes), 1)
        for i, (fname, data) in enumerate(changes):
            log(f"Updating: {fname}")
            screen.set_status(f"Updating: {fname}",
                              30 + int(40 * (i + 1) / total))
            with open(SOURCE_DIR / fname, "wb") as f:
                f.write(data)

        if not venv_exists():
            log("Venv not found - creating fresh.")
            screen.set_status("Locating Python...", 70)
            py = find_system_python()
            if not py:
                return ("Could not find Python 3.8+. Install from "
                        "https://www.python.org/downloads/ (tick 'Add Python to PATH').")
            log(f"Found Python: {py}")
            screen.set_status(f"Creating venv (using {py})...", 75)
            if not create_venv(py):
                return "venv creation failed"
            screen.set_status("Installing dependencies (~30s)...", 80)
            if not pip_install_requirements(upgrade=False):
                return "pip install failed"
            log("Venv created and dependencies installed.")
        else:
            log(f"Venv exists at {VENV_DIR}")
            req_changed = any(c[0] == "requirements.txt" for c in changes)
            if req_changed or force:
                log("requirements.txt changed - refreshing deps.")
                screen.set_status("Refreshing dependencies...", 80)
                pip_install_requirements(upgrade=True)
            else:
                log("Skipping pip install (no requirement changes).")

        # Verify venv is actually functional by trying to import the deps
        log("Verifying venv: can we import PyQt5?")
        try:
            r = subprocess.run(
                [str(venv_python()), "-c", "import PyQt5; print('OK')"],
                capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                log(f"PyQt5 import FAILED: {r.stderr.strip()}")
                log("Reinstalling deps...")
                screen.set_status("Reinstalling broken dependencies...", 80)
                if not pip_install_requirements(upgrade=True):
                    return "pip install failed (PyQt5 missing)"
            else:
                log("PyQt5 import OK.")
        except Exception as e:
            log(f"Venv verification exception: {e}")

        screen.set_status("Writing launcher...", 90)
        write_launcher_bat()
        log(f"Launcher written: {LAUNCHER_BAT}")

        # Always (re)write the bootstrapper launcher so the user has a way
        # to update/patch later without re-downloading.
        write_bootstrapper_launcher()
        log(f"Bootstrapper launcher written: {BOOTSTRAPPER_LAUNCHER}")

        if not info:
            screen.set_status("Creating shortcuts...", 95)
            log("Creating shortcuts...")
            # CursorForge app shortcut -> runs launch.bat -> starts the app
            create_shortcut(START_MENU_DIR / f"{APP_NAME}.lnk",
                            LAUNCHER_BAT,
                            description=f"{APP_NAME} v{APP_VERSION} - run the app",
                            working_dir=SOURCE_DIR)
            create_shortcut(DESKTOP_DIR / f"{APP_NAME}.lnk",
                            LAUNCHER_BAT,
                            description=f"{APP_NAME} v{APP_VERSION} - run the app",
                            working_dir=SOURCE_DIR)
            # CursorForge Bootstrapper shortcut -> re-runs bootstrapper for
            # updates/patches (does NOT launch the app directly).
            create_shortcut(START_MENU_DIR / f"{APP_NAME} Bootstrapper.lnk",
                            BOOTSTRAPPER_LAUNCHER,
                            description=f"Update or patch {APP_NAME}",
                            working_dir=SOURCE_DIR)
            create_shortcut(DESKTOP_DIR / f"{APP_NAME} Bootstrapper.lnk",
                            BOOTSTRAPPER_LAUNCHER,
                            description=f"Update or patch {APP_NAME}",
                            working_dir=SOURCE_DIR)
            write_uninstall_registry()
            log("Shortcuts and registry entry created.")

        info["app_name"] = APP_NAME
        info["version"] = APP_VERSION
        info["source_dir"] = str(SOURCE_DIR)
        info["venv_dir"] = str(VENV_DIR)
        info["launcher_bat"] = str(LAUNCHER_BAT)
        info["last_updated"] = datetime.now().isoformat()
        if "installed_at" not in info:
            info["installed_at"] = datetime.now().isoformat()
        write_install_info(info)
        update_registry_version()

        screen.set_status("Done!", 100)
        log("Worker complete.")
        return None
    except Exception as e:
        log(f"Worker exception: {e}")
        import traceback
        traceback.print_exc()
        return f"Exception: {e}"


def launch_app():
    """Launch the actual CursorForge app (pythonw, no console).

    The app's GUI (QApplication + MenuWindow) is the user-visible surface.
    Using pythonw.exe means no console window appears. If pythonw is missing
    (rare), fall back to python.exe.
    """
    pyw = venv_pythonw()
    py = venv_python()
    main_py = SOURCE_DIR / "main.py"

    print(f"[{APP_NAME}] Launch check:")
    print(f"  LAUNCHER_BAT exists: {LAUNCHER_BAT.exists()}")
    print(f"  venv pythonw exists: {pyw.exists()}  ({pyw})")
    print(f"  venv python exists:  {py.exists()}  ({py})")
    print(f"  main.py exists: {main_py.exists()}  ({main_py})")
    sys.stdout.flush()

    if not main_py.exists():
        log(f"main.py missing: {main_py}")
        return

    py_to_use = pyw if pyw.exists() else py
    if not py_to_use.exists():
        log(f"Neither pythonw nor python in venv. Venv is broken.")
        log("Run this bootstrapper with --force to rebuild, or --uninstall then re-run.")
        return

    try:
        # Detached, no console. The app's GUI window will appear.
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            [str(py_to_use), str(main_py)],
            cwd=str(SOURCE_DIR),
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        print(f"[{APP_NAME}] App launched (no console). The GUI should appear shortly.")
        sys.stdout.flush()
    except Exception as e:
        log(f"Failed to launch: {e}")
        import traceback
        traceback.print_exc()


def do_uninstall(silent=False):
    print()
    print(f"  {'=' * 58}")
    print(f"    Uninstalling {APP_NAME}")
    print(f"  {'=' * 58}")
    print()
    print(f"  Source location: {SOURCE_DIR}")
    if not silent:
        try:
            resp = input(f"  Remove {APP_NAME} completely? [y/N]: ").strip().lower()
        except EOFError:
            resp = "y"
        if resp not in ("y", "yes"):
            print("  Cancelled.")
            return 0

    print("  Removing shortcuts...")
    if START_MENU_DIR.exists():
        shutil.rmtree(START_MENU_DIR, ignore_errors=True)
    desk = DESKTOP_DIR / f"{APP_NAME}.lnk"
    if desk.exists():
        try:
            desk.unlink()
        except Exception:
            pass

    print("  Removing registry entry...")
    remove_registry_entry()

    print(f"  Deleting source folder: {SOURCE_DIR}")
    try:
        shutil.rmtree(SOURCE_DIR, ignore_errors=True)
    except Exception as e:
        print(f"  (warning) {e}")

    print()
    print(f"  {APP_NAME} has been uninstalled.")
    if not silent:
        try:
            input("  Press ENTER to exit...")
        except EOFError:
            pass
    return 0


def main():
    args = sys.argv[1:]
    # ALWAYS print a startup banner so the user can see Python actually ran.
    # Without this, if anything fails silently, the user sees an empty window
    # that closes instantly.
    print()
    print("=" * 60)
    print(f"  {APP_NAME} v{APP_VERSION} bootstrapper")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Source dir: {SOURCE_DIR}")
    print("=" * 60)
    print()
    sys.stdout.flush()

    if "--uninstall" in args:
        return do_uninstall(silent="--silent" in args)
    if "--help" in args or "-h" in args:
        print(f"{APP_NAME} v{APP_VERSION}")
        print()
        print("  Just run this file to install or update CursorForge.")
        print("  Add --uninstall to remove it completely.")
        return 0

    print(f"[{APP_NAME}] Starting install/update worker...")
    sys.stdout.flush()
    screen = LoadingScreen()
    result = {"error": None}

    def run():
        err = worker_install_or_update(screen, force="--force" in args)
        result["error"] = err
        screen.set_done(error=err)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    while screen.pump():
        time.sleep(0.02)
    screen.close()
    t.join(timeout=2)

    if result["error"]:
        print()
        print(f"[{APP_NAME}] ERROR: {result['error']}")
        sys.stdout.flush()
        try:
            input("Press ENTER to exit...")
        except EOFError:
            pass
        return 1

    # --no-launch: just update/patch, don't start the app.
    # --launch:    force launch even if running as update
    # Default: launch the app after install (so first-run user sees the app).
    no_launch = "--no-launch" in args
    force_launch = "--launch" in args

    if no_launch and not force_launch:
        print(f"[{APP_NAME}] Update/patch complete (--no-launch). "
              "Use the CursorForge shortcut to start the app.")
        sys.stdout.flush()
        return 0

    print(f"[{APP_NAME}] Install/update complete. Launching app...")
    sys.stdout.flush()
    launch_app()
    print(f"[{APP_NAME}] App launched. You can close this window.")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        print()
        print("=" * 60)
        print("  CursorForge bootstrapper crashed with an unhandled error.")
        print("  Please report this. Full traceback:")
        print("=" * 60)
        traceback.print_exc()
        print("=" * 60)
        try:
            input("\\nPress ENTER to close this window...")
        except (EOFError, KeyboardInterrupt):
            pass
        sys.exit(1)
'''

# Assemble the BAT file using a robust polyglot pattern.
#
# Layout:
#   Line 1:  @python -x "%~f0" %*  ||  py -x "%~f0" %*  ||  goto :nopython
#            (BAT: try `python`, fall back to `py`, fall back to label.
#             -x tells Python to skip line 1.)
#
#   Line 2:  exit /b %errorlevel%
#            (BAT: exits after Python finishes. Python sees this line
#             but it's the LAST BAT line before the Python code starts.
#             Wait - this would crash Python. So we need to make line 2
#             valid Python too.)
#
# Actually, the cleanest approach: ONE BAT line that calls Python. If
# Python fails to start, that line itself shows the error. After Python
# runs, the BAT just exits. The trick is the `||` chains and that the
# BAT command line is INSIDE a Python comment-ish context.
#
# The simplest reliable polyglot:
#   Line 1: BAT command (Python skips via -x)
#   Line 2+: Python code, with the FIRST line being a Python comment
#            that contains the BAT error fallback.
#
# But that means the BAT fallback can't be multi-line. So let's do this:
#   Line 1: @python -x "%~f0" %* 2>nul || py -x "%~f0" %* 2>nul || python-not-found-handler
#   Line 2: # (Python comment) - but BAT will try to execute `#`...
#
# OK the truly simplest approach: just one BAT line, no fallback. If
# Python isn't found, the user sees "python is not recognized" from
# cmd.exe and the window stays open because we add `pause` if there's
# an error.

# Line 1: Run Python on this file (-x skips line 1 for Python).
# After Python finishes, pause if there was an error, then EXIT the BAT
# so it never reaches line 2 (which is Python code, not BAT code).
# CRITICAL DEBUGGING VERSION:
# - Always pause at the end so user can see Python output
# - No 2>nul so stderr is visible
# - exit /b at end so BAT never reaches Python code
#
# We always pause so the user can read what happened. If the install
# succeeded, they can just press any key. If it failed, the error is
# visible instead of vanishing instantly.
bat_line1 = (
    '@py -x "%~f0" %* || python -x "%~f0" %* || '
    '(echo [CursorForge] Python not found. '
    'Install Python 3 from https://www.python.org/downloads/ & pause) '
    '& echo. & echo [CursorForge] Done. Press any key to close... & pause >nul & exit /b\n'
)

bat_content = bat_line1 + BOOTSTRAPPER_PY

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(bat_content, encoding="utf-8")

print(f"Wrote: {OUT}")
print(f"Size: {OUT.stat().st_size:,} bytes ({OUT.stat().st_size/1024:.1f} KB)")
