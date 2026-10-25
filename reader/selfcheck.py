"""Reader self-check: is the offset profile still right for the running game build?

Run when the game starts. A patch usually changes game_plugin.dll, so the build has no profile (UnknownBuild); if a
patch keeps the build id but moves data, the value checks fail instead. Either way captures are paused until fixed.
"""
from __future__ import annotations

import datetime as dt
import time

from .process import GameProcess
from .profile import UnknownBuild, load_profile

MIN_PLAYERS = 11


def self_check(proc: GameProcess, club_id: int | None) -> dict:
    """{status: ok | unknown_build | failed, build_id, checks: [{name, ok, detail}], seconds}"""
    t0 = time.time()
    checks: list[dict] = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return ok

    build = proc.build_id()
    try:
        profile = load_profile(build)
    except UnknownBuild as e:
        add("game build recognised", False, str(e))
        return {"status": "unknown_build", "build_id": build, "checks": checks, "seconds": round(time.time() - t0, 1)}
    add("game build recognised", True, profile.get("game_version", build))

    from .matches import game_date
    try:
        d = game_date(proc, profile)
    except Exception as e:      # noqa: BLE001 - any read error is a failed check
        d, err = None, str(e)
    else:
        err = ""
    add("game date readable", d is not None and 1990 <= d.year <= 2100, d.isoformat() if d else err or "unreadable")

    from .fixtures import read_club_names
    try:
        names = read_club_names(proc, profile)
    except Exception as e:      # noqa: BLE001
        names, err = {}, str(e)
    add("club names readable", len(names) > 500 and (club_id is None or club_id in names),
        (f"{len(names)} clubs" + (f"; your club: {names.get(club_id, 'not found')}" if club_id is not None else ""))
        if names else err)
    if club_id is None:         # no club chosen yet: the squad check waits until one is
        status = "ok" if all(c["ok"] for c in checks) else "failed"
        return {"status": status, "build_id": build, "game_date": d.isoformat() if d else None, "checks": checks,
                "seconds": round(time.time() - t0, 1), "checked_at": dt.datetime.now().isoformat(sep=" ", timespec="seconds")}

    from .people import read_club_players
    try:
        players = read_club_players(proc, club_id, profile)
    except Exception as e:      # noqa: BLE001
        players, err = [], str(e)
    else:
        err = ""
    named = sum(1 for p in players if p.name)
    sane = sum(1 for p in players if p.fitness is not None and 0 <= p.fitness <= 100 and 1 <= p.ca <= 200)
    ok = len(players) >= MIN_PLAYERS and named >= 0.9 * len(players) and sane >= 0.9 * len(players)
    add("squad readable", ok, f"{len(players)} players, {named} named, {sane} with sane CA/condition" if players else err or "no players")

    status = "ok" if all(c["ok"] for c in checks) else "failed"
    return {"status": status, "build_id": build, "game_date": d.isoformat() if d else None, "checks": checks,
            "seconds": round(time.time() - t0, 1), "checked_at": dt.datetime.now().isoformat(sep=" ", timespec="seconds")}
