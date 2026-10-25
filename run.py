"""Start the dashboard (http://127.0.0.1:8765) with the in-game capture hotkey.

    .venv\\Scripts\\python.exe run.py            dashboard + hotkey, opens the browser
    .venv\\Scripts\\python.exe run.py --no-hotkey --no-browser
"""
from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

import app_config
from web.app import CAPTURE, app

HOST, PORT = "127.0.0.1", 8765


def start_hotkey(combo: str) -> None:
    from capture.hotkey import BEEP_FAIL, BEEP_OK, BEEP_START, beep, listen

    def on_press():
        if not CAPTURE.run():
            return  # a capture is already running
        beep(BEEP_START)
        while CAPTURE.running:
            threading.Event().wait(0.5)
        beep(BEEP_OK if CAPTURE.last and CAPTURE.last.get("ok") else BEEP_FAIL)

    def loop():
        try:
            listen(combo, on_press)
        except OSError as e:
            print(f"hotkey disabled: {e}")

    threading.Thread(target=loop, daemon=True, name="hotkey").start()
    print(f"hotkey {combo.upper()} active: press it in game to capture")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-hotkey", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    if not args.no_hotkey:
        start_hotkey(app_config.load_config()["hotkey"])
    url = f"http://{HOST}:{args.port}"
    print(f"dashboard: {url}")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=HOST, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
