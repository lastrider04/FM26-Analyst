"""Game snapshots: one history (database + capture files) per FM save game or job, so they never mix.

Shown in the dashboard as "game snapshots". You can start a new one (new save, or a new job at another club),
switch between them, rename or delete them. A capture also detects a different save by itself: FM generates newgens
with fresh UniqueIDs in every save and a squad changes only gradually, so the overlap of the club's player IDs
identifies the save. A snapshot you've just started (no captures yet) always takes the next capture.

Registry: data/careers.json  {"active": 1, "careers": {"1": {...}, "2": {...}}}
Snapshot #1 keeps the original paths (data/fm_analyst.db, data/snapshots); later ones live in data/careers/<id>/.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
import threading

import app_config

MATCH_THRESHOLD = 0.35          # Jaccard overlap of club player IDs needed to call it the same save
_lock = threading.Lock()


class SnapshotError(Exception):
    pass


def registry_path():
    return app_config.DATA / "careers.json"


def _read() -> dict:
    try:
        return json.loads(registry_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(reg: dict) -> None:
    app_config.DATA.mkdir(parents=True, exist_ok=True)
    tmp = registry_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    tmp.replace(registry_path())


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _db_summary(db_path) -> dict:
    """Club, first/last game date and current player IDs of an existing database (for bootstrapping)."""
    if not db_path.exists():
        return {}
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT club_id, min(game_date), max(game_date) FROM snapshots").fetchone()
        if not row or row[0] is None:
            return {}
        last = con.execute("SELECT id FROM snapshots ORDER BY game_date DESC, id DESC LIMIT 1").fetchone()[0]
        uids = [r[0] for r in con.execute("SELECT unique_id FROM player_state WHERE snapshot_id = ?", (last,))]
        name = con.execute("SELECT name FROM clubs WHERE club_id = ?", (row[0],)).fetchone()
        return {"club_id": row[0], "club": name[0] if name else None, "first_game_date": row[1],
                "last_game_date": row[2], "fingerprint": sorted(uids)}
    except sqlite3.Error:
        return {}
    finally:
        con.close()


def registry() -> dict:
    """The registry, created on first use from the existing database (which becomes snapshot #1)."""
    with _lock:
        reg = _read()
        if not reg.get("careers"):
            first = {"db": "fm_analyst.db", "snapshots": "snapshots", "created": _now(),
                     **_db_summary(app_config.DATA / "fm_analyst.db")}
            if first.get("club"):
                first["name"] = f"{first['club']} {first['first_game_date'][:4]}" if first.get("first_game_date") else first["club"]
            reg = {"active": 1, "careers": {"1": first}}
            _write(reg)
        return reg


def label(cid: int | str, c: dict) -> str:
    name = c.get("name") or c.get("club") or f"Game {cid}"
    return f"{name} (#{cid})"


def activate(cid: int | str | None = None) -> int:
    """Point app_config.DB_PATH / SNAPSHOT_DIR at a snapshot (default: the active one) and make it active."""
    reg = registry()
    cid = str(cid if cid is not None else reg["active"])
    if cid not in reg["careers"]:
        raise SnapshotError(f"no game snapshot #{cid}")
    c = reg["careers"][cid]
    app_config.DB_PATH = app_config.DATA / c["db"]
    app_config.SNAPSHOT_DIR = app_config.DATA / c["snapshots"]
    if str(reg["active"]) != cid:
        with _lock:
            reg = _read()
            reg["active"] = int(cid)
            _write(reg)
    return int(cid)


def _sync_club(c: dict) -> None:
    """Captures read the club in settings: follow the snapshot's club."""
    if c.get("club_id"):
        cfg = app_config.load_config()
        if cfg.get("club_id") != c["club_id"]:
            cfg["club_id"] = c["club_id"]
            app_config.save_config(cfg)


def switch(cid: int) -> int:
    """User switched snapshot in Settings: activate it and point captures at its club."""
    cid = activate(cid)
    _sync_club(registry()["careers"][str(cid)])
    return cid


def _new_entry(reg: dict, name: str | None, club_id: int | None, club: str | None, game_date: str | None) -> str:
    cid = str(max(int(k) for k in reg["careers"]) + 1)
    reg["careers"][cid] = {"db": f"careers/{cid}/fm_analyst.db", "snapshots": f"careers/{cid}/snapshots",
                           "created": _now(), "name": name, "club_id": club_id, "club": club,
                           "first_game_date": game_date, "last_game_date": game_date, "fingerprint": []}
    (app_config.DATA / "careers" / cid).mkdir(parents=True, exist_ok=True)
    return cid


def start_new(name: str, club_id: int, club: str | None) -> int:
    """Start an empty snapshot for a new game or job; it becomes active and takes the next capture.
    The previous snapshot is kept unchanged and can be switched back to."""
    name = (name or "").strip()[:60] or (club or "New game")
    registry()                          # make sure the registry (and snapshot #1) exists first
    with _lock:
        reg = _read()
        cid = _new_entry(reg, name, club_id, club, None)
        _write(reg)
    return switch(int(cid))


def rename(cid: int, name: str) -> None:
    name = (name or "").strip()[:60]
    if not name:
        raise SnapshotError("name can't be empty")
    registry()
    with _lock:
        reg = _read()
        if str(cid) not in reg["careers"]:
            raise SnapshotError(f"no game snapshot #{cid}")
        reg["careers"][str(cid)]["name"] = name
        _write(reg)


def delete(cid: int) -> None:
    """Delete a snapshot that isn't active (its database and capture files; its backups are kept)."""
    reg = registry()
    if int(reg["active"]) == int(cid):
        raise SnapshotError("switch to another game snapshot before deleting this one")
    c = reg["careers"].get(str(cid))
    if not c:
        raise SnapshotError(f"no game snapshot #{cid}")
    for rel in (c["db"], c["db"] + "-wal", c["db"] + "-shm"):
        (app_config.DATA / rel).unlink(missing_ok=True)
    snaps = app_config.DATA / c["snapshots"]
    if snaps.exists():
        shutil.rmtree(snaps)
    folder = app_config.DATA / "careers" / str(cid)
    if folder.exists() and not any(folder.iterdir()):
        folder.rmdir()
    with _lock:
        reg = _read()
        reg["careers"].pop(str(cid), None)
        _write(reg)


def overlap(a: set[int], b: set[int]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def resolve(uids: set[int], club_id: int, club: str | None, game_date: str | None) -> tuple[int, bool]:
    """Which snapshot does a capture with these club player IDs belong to? Returns (id, created).

    A freshly started (still empty) active snapshot takes the capture. Otherwise the best-matching snapshot wins;
    if none matches, a new one is created automatically (a different save was loaded)."""
    reg = registry()
    active = reg["careers"][str(reg["active"])]
    if not active.get("fingerprint"):
        return int(reg["active"]), False
    best, score = None, 0.0
    for cid, c in reg["careers"].items():
        fp = set(c.get("fingerprint") or [])
        s = overlap(uids, fp) if fp else 0.0
        if s > score:
            best, score = cid, s
    if best is not None and score >= MATCH_THRESHOLD:
        return int(best), False
    with _lock:
        reg = _read()
        cid = _new_entry(reg, f"{club or 'New game'} ({game_date[:4] if game_date else 'auto'})", club_id, club, game_date)
        _write(reg)
    return int(cid), True


def record_capture(cid: int, uids: set[int], club_id: int, club: str | None, game_date: str | None) -> str | None:
    """Update a snapshot after a capture. Returns the previous last game date if the game went back in time
    (an older save file of the same career was loaded), else None."""
    with _lock:
        reg = _read()
        c = reg["careers"][str(cid)]
        rewound = c.get("last_game_date") if game_date and c.get("last_game_date") and game_date < c["last_game_date"] else None
        c.update(fingerprint=sorted(uids), club_id=club_id, club=club or c.get("club"),
                 last_game_date=game_date or c.get("last_game_date"),
                 first_game_date=c.get("first_game_date") or game_date)
        if not c.get("name"):
            c["name"] = f"{c.get('club') or 'Game'} {game_date[:4]}" if game_date else c.get("club")
        if rewound:
            c["rewound"] = {"from": rewound, "to": game_date}
        _write(reg)
    return rewound


def active_info() -> dict | None:
    lst = listing()
    return next((c for c in lst["careers"] if c["id"] == lst["active"]), None)


def _captures(c: dict) -> int:
    p = app_config.DATA / c["db"]
    if not p.exists():
        return 0
    con = sqlite3.connect(p)
    try:
        return con.execute("SELECT count(*) FROM snapshots").fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def listing() -> dict:
    reg = registry()
    return {"active": int(reg["active"]),
            "careers": [{"id": int(k), "label": label(k, c), "name": c.get("name"), "club": c.get("club"),
                         "club_id": c.get("club_id"), "first_game_date": c.get("first_game_date"),
                         "last_game_date": c.get("last_game_date"), "rewound": c.get("rewound"),
                         "captures": _captures(c), "db": c["db"]}
                        for k, c in sorted(reg["careers"].items(), key=lambda kv: int(kv[0]))]}
