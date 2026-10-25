"""Global capture hotkey using the Win32 RegisterHotKey API (no keyboard hook, no admin needed)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)

MODS = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
HOTKEY_ID = 1
BEEP_START, BEEP_OK, BEEP_FAIL = 0x00000040, 0x00000000, 0x00000010  # MB_ICONINFORMATION / MB_OK / MB_ICONHAND


def parse(combo: str) -> tuple[int, int]:
    """'ctrl+alt+s' -> (modifiers, virtual-key code)."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    mods = 0
    for p in parts[:-1]:
        if p not in MODS:
            raise ValueError(f"unknown modifier {p!r} in hotkey {combo!r}")
        mods |= MODS[p]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])  # VK_F1 = 0x70
    else:
        raise ValueError(f"unsupported key {key!r} in hotkey {combo!r}")
    return mods | MOD_NOREPEAT, vk


def beep(kind: int) -> None:
    user32.MessageBeep(kind)


def listen(combo: str, on_press: Callable[[], None]) -> None:
    """Block, calling on_press (on a worker thread) each time the hotkey is pressed.

    Presses while a previous capture is still running are ignored. Stop with Ctrl+C.
    """
    mods, vk = parse(combo)
    if not user32.RegisterHotKey(None, HOTKEY_ID, mods, vk):
        raise OSError(f"could not register hotkey {combo!r} (already used by another app?)")
    busy = threading.Lock()

    def run():
        if not busy.acquire(blocking=False):
            return
        try:
            on_press()
        finally:
            busy.release()

    try:
        msg = wt.MSG()
        while True:
            # PeekMessage + short sleep keeps Ctrl+C responsive (GetMessage would block it)
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    threading.Thread(target=run, daemon=True).start()
            else:
                threading.Event().wait(0.05)
    finally:
        user32.UnregisterHotKey(None, HOTKEY_ID)
