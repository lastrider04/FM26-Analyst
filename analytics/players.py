"""All players (every status), positions, where they are, comparisons and similar-player search."""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3

from .development import GROUP_OF, GROUPS
from .squad import injury_status, latest_snapshot

POSITIONS = ["GK", "SW", "DL", "DC", "DR", "DM", "ML", "MC", "MR", "AML", "AMC", "AMR", "ST", "WBL", "WBR"]
LABEL = {"GK": "GK", "SW": "SW", "DL": "D L", "DC": "D C", "DR": "D R", "DM": "DM", "ML": "M L", "MC": "M C",
         "MR": "M R", "AML": "AM L", "AMC": "AM C", "AMR": "AM R", "ST": "ST", "WBL": "WB L", "WBR": "WB R"}
NATURAL, ACCOMPLISHED = 18, 15
STATUS_ORDER = ["first team", "loaned in", "youth team", "loaned out", "no contract"]
YOUTH_LABELS = ["U21", "U18", "Academy"]  # assigned to the club's own teams from oldest to youngest squad
MIN_TEAM_SIZE = 5  # smaller own "teams" (trialists, odd registrations) aren't ranked as age groups


def positions_of(row) -> dict[str, int]:
    raw = row["positions"] if "positions" in row.keys() else None
    return json.loads(raw) if raw else {}


def position_string(pos: dict[str, int], threshold: int = ACCOMPLISHED) -> str:
    """'AM L, AM R, ST' style list, best first."""
    good = sorted(((v, p) for p, v in pos.items() if v >= threshold and p != "SW"), reverse=True)
    return ", ".join(LABEL[p] for _, p in good)


def primary_position(pos: dict[str, int]) -> str | None:
    best = max(((v, -POSITIONS.index(p), p) for p, v in pos.items() if p != "SW"), default=None)
    return LABEL[best[2]] if best else None


def _age(dob: str | None, on: str) -> int | None:
    if not dob:
        return None
    b, d = dt.date.fromisoformat(dob), dt.date.fromisoformat(on)
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def all_players(con: sqlite3.Connection, club_id: int) -> dict:
    """Every player in the latest snapshot with status, team/club they're at, positions and age."""
    snap = latest_snapshot(con, club_id)
    if not snap:
        return {"game_date": None, "players": [], "teams": {}}
    rows = con.execute("""SELECT s.*, p.name, p.dob, c.name AS at_club FROM player_state s
                          JOIN players p USING (unique_id) LEFT JOIN clubs c ON c.club_id = s.at_club_id
                          WHERE s.snapshot_id = ?""", (snap["id"],)).fetchall()
    club_name = (con.execute("SELECT name FROM clubs WHERE club_id = ?", (club_id,)).fetchone() or [None])[0] or "Club"
    players = []
    for r in rows:
        d = dict(r)
        d["age"] = _age(r["dob"], snap["game_date"])
        pos = positions_of(r)
        d["positions"] = pos
        d["position"] = position_string(pos) or primary_position(pos)
        d["primary"] = primary_position(pos)
        d["injury"] = injury_status(d.pop("injuries", None), snap["game_date"])
        players.append(d)

    # own youth/academy teams have no entry in the club name table: label them by squad age
    own_teams = {}
    for p in players:
        if p["at_club_id"] != club_id and p["status"] in ("youth team", "no contract") and not p["at_club"]:
            own_teams.setdefault(p["at_club_id"], []).append(p["age"] or 0)
    median = lambda ages: sorted(ages)[len(ages) // 2]
    ranked = sorted((t for t in own_teams if len(own_teams[t]) >= MIN_TEAM_SIZE), key=lambda t: -median(own_teams[t]))
    team_names = {t: f"{club_name} {YOUTH_LABELS[min(i, len(YOUTH_LABELS) - 1)]}" for i, t in enumerate(ranked)}
    for t in own_teams:
        team_names.setdefault(t, f"{club_name} (other squad)")
    team_names[club_id] = club_name
    for p in players:
        p["where"] = p["at_club"] or team_names.get(p["at_club_id"]) or f"club {p['at_club_id']}"
    players.sort(key=lambda p: (STATUS_ORDER.index(p["status"]) if p["status"] in STATUS_ORDER else 9, -p["ca"]))
    return {"game_date": snap["game_date"], "players": players,
            "teams": {str(k): v for k, v in team_names.items()}}


# ------------------------------------------------------------------ similarity
def _relevant_attrs(is_gk: bool) -> list[str]:
    groups = ["goalkeeping", "mental", "physical"] if is_gk else ["technical", "mental", "physical"]
    return [a for g in groups for a in GROUPS[g]]


def position_similarity(a: dict[str, int], b: dict[str, int]) -> float:
    """Cosine of familiarity vectors (1 = unfamiliar is treated as 0)."""
    va = [max(0, a.get(p, 1) - 1) for p in POSITIONS]
    vb = [max(0, b.get(p, 1) - 1) for p in POSITIONS]
    na, nb = math.sqrt(sum(x * x for x in va)), math.sqrt(sum(x * x for x in vb))
    return sum(x * y for x, y in zip(va, vb)) / (na * nb) if na and nb else 0.0


def attribute_similarity(a: dict[str, int], b: dict[str, int], attrs: list[str]) -> float:
    """1 - mean absolute difference on the 1-20 scale, over the given attributes."""
    keys = [k for k in attrs if k in a and k in b]
    if not keys:
        return 0.0
    diff = sum(abs(round(a[k] / 5) - round(b[k] / 5)) for k in keys) / len(keys)
    return max(0.0, 1 - diff / 19)


def _attributes(con, snapshot_id: int) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    for r in con.execute("SELECT unique_id, attr, raw FROM player_attributes WHERE snapshot_id = ?", (snapshot_id,)):
        out.setdefault(r["unique_id"], {})[r["attr"]] = r["raw"]
    return out


def similar_players(con: sqlite3.Connection, club_id: int, unique_id: int, n: int = 6,
                    statuses: tuple[str, ...] = tuple(STATUS_ORDER)) -> list[dict]:
    """Club players most like `unique_id`: 60% position overlap, 40% attribute closeness."""
    data = all_players(con, club_id)
    snap = latest_snapshot(con, club_id)
    attrs = _attributes(con, snap["id"]) if snap else {}
    me = next((p for p in data["players"] if p["unique_id"] == unique_id), None)
    if not me:
        return []
    is_gk = me["positions"].get("GK", 1) >= ACCOMPLISHED
    rel = _relevant_attrs(is_gk)
    out = []
    for p in data["players"]:
        if p["unique_id"] == unique_id or p["status"] not in statuses:
            continue
        ps = position_similarity(me["positions"], p["positions"])
        at = attribute_similarity(attrs.get(unique_id, {}), attrs.get(p["unique_id"], {}), rel)
        score = 0.6 * ps + 0.4 * at
        out.append({**{k: p[k] for k in ("unique_id", "name", "age", "status", "where", "position", "ca", "pa")},
                    "score": round(score * 100), "position_match": round(ps * 100), "attribute_match": round(at * 100)})
    return sorted(out, key=lambda x: -x["score"])[:n]


def compare(con: sqlite3.Connection, club_id: int, a: int, b: int) -> dict:
    """Side-by-side data for two players from the latest snapshot plus stored match totals."""
    from .metrics import aggregate, match_lines
    data = {p["unique_id"]: p for p in all_players(con, club_id)["players"]}
    snap = latest_snapshot(con, club_id)
    attrs = _attributes(con, snap["id"]) if snap else {}
    aggs = aggregate(match_lines(con, club_id))
    out = []
    for uid in (a, b):
        p = data.get(uid)
        if not p:
            raise KeyError(uid)
        agg = aggs.get(uid)
        out.append({**p, "attributes": attrs.get(uid, {}),
                    "totals": None if not agg else {
                        "apps": agg.apps, "minutes": agg.minutes, "avg_rating": agg.avg_rating, "goals": agg.goals,
                        "assists": agg.assists, "xg": agg.xg, "xa": agg.xa, "pass_pct": agg.pass_pct,
                        "goals_minus_xg": agg.goals_minus_xg, "per90": agg.per90s()},
                    "ca_history": [dict(r) for r in con.execute(
                        """SELECT s.game_date, ps.ca FROM player_state ps JOIN snapshots s ON s.id = ps.snapshot_id
                           WHERE ps.unique_id = ? ORDER BY s.game_date, s.id""", (uid,))]})
    groups = {g: [x for x in attrs_ if x in out[0]["attributes"] or x in out[1]["attributes"]]
              for g, attrs_ in GROUPS.items()}
    groups["other"] = sorted({k for p in out for k in p["attributes"] if k not in GROUP_OF})
    return {"players": out, "groups": groups,
            "position_match": round(100 * position_similarity(out[0]["positions"], out[1]["positions"])),
            "attribute_match": round(100 * attribute_similarity(
                out[0]["attributes"], out[1]["attributes"],
                _relevant_attrs(out[0]["positions"].get("GK", 1) >= ACCOMPLISHED)))}
