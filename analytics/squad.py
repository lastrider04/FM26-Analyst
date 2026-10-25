"""Squad status and alerts from the latest snapshot: condition, sharpness, jadedness, contracts."""
from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

CONDITION_LOW = 85.0       # % : risky to start
SHARPNESS_LOW = 70.0       # % : needs minutes
JADED = 300                # jadedness above this ~ FM's "needs a rest"
CONTRACT_MONTHS = 12


@dataclass
class Alert:
    kind: str
    unique_id: int
    name: str
    detail: str


def injury_status(raw: str | None, game_date: str | None) -> dict | None:
    """Current injury from player_state.injuries JSON: {since, back_min, back_max} in days from game_date
    (the longest of several injuries counts)."""
    if not raw or not game_date:
        return None
    import json
    today = dt.date.fromisoformat(game_date)
    best = None
    for i in json.loads(raw):
        start = dt.date.fromisoformat(i["start"])
        gone = (today - start).days
        lo, hi = max(0, (i.get("min_days") or i["max_days"]) - gone), max(0, i["max_days"] - gone)
        if best is None or hi > best["back_max"]:
            best = {"since": i["start"], "back_min": lo, "back_max": hi}
    return best


def injury_text(inj: dict) -> str:
    lo, hi = inj["back_min"], inj["back_max"]
    when = "any day now" if hi == 0 else f"back in {hi} day{'s' * (hi != 1)}" if lo == hi else f"back in {lo}-{hi} days"
    return f"injured, {when}"


def latest_snapshot(con: sqlite3.Connection, club_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM snapshots WHERE club_id = ? ORDER BY game_date DESC, id DESC LIMIT 1",
                       (club_id,)).fetchone()


def squad(con: sqlite3.Connection, snapshot_id: int, statuses: tuple[str, ...] = ("first team", "loaned in")
          ) -> list[sqlite3.Row]:
    q = ",".join("?" * len(statuses))
    return con.execute(f"""SELECT s.*, p.name, p.dob FROM player_state s JOIN players p USING (unique_id)
                           WHERE s.snapshot_id = ? AND s.status IN ({q}) ORDER BY s.ca DESC""",
                       (snapshot_id, *statuses)).fetchall()


def alerts(con: sqlite3.Connection, club_id: int) -> list[Alert]:
    snap = latest_snapshot(con, club_id)
    if not snap:
        return []
    today = dt.date.fromisoformat(snap["game_date"])
    out = []
    for r in squad(con, snap["id"]):
        inj = injury_status(r["injuries"] if "injuries" in r.keys() else None, snap["game_date"])
        if inj:
            out.append(Alert("injured", r["unique_id"], r["name"], f"{injury_text(inj)[9:]}, since {inj['since']}"))
            continue        # condition/sharpness alerts are noise while he's injured
        if r["condition"] is not None and r["condition"] < CONDITION_LOW:
            out.append(Alert("low condition", r["unique_id"], r["name"], f"{r['condition']:.0f}%"))
        if r["sharpness"] is not None and r["sharpness"] < SHARPNESS_LOW:
            out.append(Alert("low sharpness", r["unique_id"], r["name"], f"{r['sharpness']:.0f}%"))
        if r["jadedness"] is not None and r["jadedness"] > JADED:
            out.append(Alert("jaded", r["unique_id"], r["name"], f"jadedness {r['jadedness']}"))
        if r["status"] == "first team" and r["contract_expires"]:
            exp = dt.date.fromisoformat(r["contract_expires"])
            months = (exp.year - today.year) * 12 + exp.month - today.month
            if 0 <= months <= CONTRACT_MONTHS:
                # loaned-in players are skipped: their stored contract is the parent club's, not the loan
                out.append(Alert("contract expiring", r["unique_id"], r["name"], f"{exp} ({months} months)"))
    return out
