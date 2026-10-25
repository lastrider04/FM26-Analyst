"""Automatic captures while the game runs, so nothing is missed.

Every POLL seconds the watcher reads the in-game clock (a 4-byte read; cheap) and captures when:
  * a stored upcoming fixture of the club has kicked off at least MATCH_DONE ago (game time),
    i.e. right after each match while its player stats are still in memory; or
  * WEEKLY game days have passed since the last capture (for development tracking).
A fixture that still shows as unplayed after a capture (postponed, or not finished yet) is
retried once per game day, so the watcher never loops.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Callable

import app_config
from store.db import connect

POLL = 15                               # real seconds between clock checks
MATCH_DONE = dt.timedelta(hours=2, minutes=30)
WEEKLY = 7


class AutoCapture:
    def __init__(self, run_capture: Callable[[], bool], is_busy: Callable[[], bool],
                 paused: Callable[[], str | None] = lambda: None):
        """paused(): a reason to hold off entirely (e.g. the reader self-check failed), checked before any game read."""
        self.run_capture, self.is_busy, self.paused = run_capture, is_busy, paused
        self.enabled = True
        self.status = "starting"
        self.last_reason: str | None = None
        self.last_at: str | None = None
        self.next_trigger: str | None = None
        self._tried: dict[tuple, dt.date] = {}   # fixture -> game date it was last tried on
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="auto-capture").start()

    def stop(self) -> None:
        self._stop.set()

    def state(self) -> dict:
        return {"enabled": self.enabled, "status": self.status, "next": self.next_trigger,
                "last_reason": self.last_reason, "last_at": self.last_at}

    # ------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.wait(POLL):
            try:
                self._tick()
            except Exception as e:  # never let the watcher die
                self.status = f"error: {e}"

    def _game_clock(self) -> dt.datetime | None:
        from reader.matches import game_datetime
        from reader.process import GameProcess, ProcessNotFound
        try:
            with GameProcess() as p:
                return game_datetime(p)
        except (ProcessNotFound, OSError):
            return None

    def _tick(self) -> None:
        if not self.enabled:
            self.status = "off"
            return
        reason = self.paused()
        if reason:
            self.status, self.next_trigger = reason, None
            return
        now = self._game_clock()
        if now is None:
            self.status, self.next_trigger = "waiting for the game", None
            return
        if self.is_busy():
            self.status = "capture running"
            return
        club = app_config.load_config()["club_id"]
        con = connect(app_config.DB_PATH)
        try:
            last = con.execute("SELECT max(game_date) FROM snapshots WHERE club_id = ?", (club,)).fetchone()[0]
            due = con.execute(
                """SELECT f.date, f.kickoff, f.home_id, f.away_id, h.name AS home, a.name AS away
                   FROM fixtures f LEFT JOIN clubs h ON h.club_id = f.home_id LEFT JOIN clubs a ON a.club_id = f.away_id
                   WHERE (f.home_id = ? OR f.away_id = ?) AND f.home_goals IS NULL AND f.date <= ?
                   ORDER BY f.date, f.kickoff""", (club, club, now.date().isoformat())).fetchall()
            upcoming = con.execute(
                """SELECT f.date, f.kickoff, h.name AS home, a.name AS away FROM fixtures f
                   LEFT JOIN clubs h ON h.club_id = f.home_id LEFT JOIN clubs a ON a.club_id = f.away_id
                   WHERE (f.home_id = ? OR f.away_id = ?) AND f.home_goals IS NULL AND f.date >= ?
                   ORDER BY f.date, f.kickoff LIMIT 1""", (club, club, now.date().isoformat())).fetchone()
        finally:
            con.close()

        reason = None
        for f in due:
            h, m = map(int, (f["kickoff"] or "15:00").split(":"))
            finished = dt.datetime.fromisoformat(f["date"]).replace(hour=h, minute=m) + MATCH_DONE
            key = (f["date"], f["home_id"], f["away_id"])
            if now >= finished and self._tried.get(key) != now.date():
                self._tried[key] = now.date()
                reason = f"after {f['home']} v {f['away']}"
                break
        if not reason and (last is None or (now.date() - dt.date.fromisoformat(last)).days >= WEEKLY):
            reason = f"weekly ({WEEKLY} game days since last capture)"

        if upcoming:
            h, m = map(int, (upcoming["kickoff"] or "15:00").split(":"))
            done = dt.datetime.fromisoformat(upcoming["date"]).replace(hour=h, minute=m) + MATCH_DONE
            self.next_trigger = f"after {upcoming['home']} v {upcoming['away']} ({done:%a %d %b %H:%M} game time)"
        if reason:
            self.status = f"capturing: {reason}"
            if self.run_capture():
                self.last_reason, self.last_at = reason, now.isoformat(sep=" ", timespec="minutes")
        else:
            self.status = f"watching · game time {now:%a %d %b %Y %H:%M}"
