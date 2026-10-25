"""Open FM26 Analyst like an app: start the background server if needed, then open its own window.

    .venv\\Scripts\\pythonw.exe launch.py      (what the desktop shortcut runs; no console window)

The server (dashboard + hotkey + auto-capture) keeps running after the window is closed, so
captures still happen while you play. Quit it from Settings > App.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765"
LOG = ROOT / "data" / "app.log"
BROWSERS = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
]


def server_up() -> bool:
    try:
        with urllib.request.urlopen(URL + "/api/status", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def start_server() -> None:
    LOG.parent.mkdir(exist_ok=True)
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    log = open(LOG, "a", encoding="utf-8")
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: outlives this launcher
    subprocess.Popen([str(exe), str(ROOT / "run.py"), "--no-browser"], cwd=ROOT, stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)


def open_window() -> None:
    for b in BROWSERS:
        path = os.path.expandvars(b)
        if os.path.exists(path):
            # --app gives a standalone window (own taskbar entry, no tabs or address bar)
            subprocess.Popen([path, f"--app={URL}", "--window-size=1440,920",
                              f"--user-data-dir={ROOT / 'data' / 'app-window'}"])
            return
    webbrowser.open(URL)  # no Edge/Chrome found: fall back to the default browser


def main() -> None:
    if not server_up():
        start_server()
        for _ in range(60):
            if server_up():
                break
            time.sleep(0.5)
    open_window()


if __name__ == "__main__":
    main()
