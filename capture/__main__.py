"""Capture snapshots from the running game.

    python -m capture            one capture now
    python -m capture --watch    stay running; press the hotkey (default Ctrl+Alt+S) in game to capture
    python -m capture --import data/snapshots/00001_2031-12-01.json   re-store a saved snapshot
"""
from __future__ import annotations

import argparse
import json
import traceback

import app_config
from app_config import load_config
from capture.hotkey import BEEP_FAIL, BEEP_OK, BEEP_START, beep, listen
from capture.snapshot import capture, store_snapshot
from store.db import connect


def run_once(club_id: int) -> bool:
    try:
        r = capture(club_id)
    except Exception as e:  # keep the watcher alive; report and carry on
        print(f"capture FAILED: {e}")
        traceback.print_exc()
        return False
    print(f"save #{r.save_id}{' (NEW save detected: separate history started)' if r.new_save else ''}: "
          f"snapshot #{r.snapshot_id} at game date {r.game_date}: {r.players} players, "
          f"{r.fixtures} fixtures, {r.matches_in_memory} match line-ups in memory, "
          f"{r.new_matches} new -> {r.seconds}s")
    if r.rewound_from:
        print(f"  note: game date went back from {r.rewound_from} - an older save file of this career was loaded")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--club", type=int)
    ap.add_argument("--import", dest="import_path")
    args = ap.parse_args()
    cfg = load_config()
    club = args.club or cfg["club_id"]

    if args.import_path:
        from store.careers import activate
        activate()                      # imports go into the active save
        con = connect(app_config.DB_PATH)
        sid, new = store_snapshot(con, json.load(open(args.import_path, encoding="utf-8")))
        print(f"imported as snapshot #{sid} ({new} new matches)")
        return
    if not args.watch:
        run_once(club)
        return

    def on_press():
        beep(BEEP_START)
        print("capturing...")
        beep(BEEP_OK if run_once(club) else BEEP_FAIL)

    print(f"watching: press {cfg['hotkey'].upper()} in game to capture (Ctrl+C here to stop)")
    try:
        listen(cfg["hotkey"], on_press)
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
