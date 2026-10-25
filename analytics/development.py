"""Player development between two snapshots: CA/PA and attribute changes.

Attributes are stored raw (1-100); FM shows round(raw / 5). Raw changes reveal progress
before the visible 1-20 number moves, so both are reported.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass, field

GROUPS = {
    "technical": ["corners", "crossing", "dribbling", "finishing", "first_touch", "free_kicks", "heading",
                  "long_shots", "long_throws", "marking", "passing", "penalty_taking", "tackling", "technique"],
    "mental": ["aggression", "anticipation", "bravery", "composure", "concentration", "decisions", "determination",
               "flair", "leadership", "off_the_ball", "positioning", "teamwork", "vision", "work_rate"],
    "physical": ["acceleration", "agility", "balance", "jumping_reach", "natural_fitness", "pace", "stamina",
                 "strength"],
    "goalkeeping": ["aerial_reach", "command_of_area", "communication", "eccentricity", "handling", "kicking",
                    "one_on_ones", "punching", "reflexes", "rushing_out", "throwing"],
    "hidden": ["consistency", "dirtiness", "important_matches", "injury_proneness", "versatility"],
}
GROUP_OF = {a: g for g, attrs in GROUPS.items() for a in attrs}
# for these a rise is bad news
NEGATIVE = {"dirtiness", "injury_proneness"}


@dataclass
class AttrChange:
    attr: str
    group: str
    before_raw: int
    after_raw: int

    @property
    def raw_delta(self) -> int:
        return self.after_raw - self.before_raw

    @property
    def shown_before(self) -> int:
        return round(self.before_raw / 5)

    @property
    def shown_after(self) -> int:
        return round(self.after_raw / 5)

    @property
    def shown_delta(self) -> int:
        return self.shown_after - self.shown_before


@dataclass
class Development:
    unique_id: int
    name: str
    age: int | None
    status: str
    ca_before: int
    ca_after: int
    pa: int | None
    days: int
    changes: list[AttrChange] = field(default_factory=list)

    @property
    def ca_delta(self) -> int:
        return self.ca_after - self.ca_before

    @property
    def ca_per_30_days(self) -> float | None:
        return round(self.ca_delta * 30 / self.days, 2) if self.days > 0 else None

    @property
    def headroom(self) -> int | None:
        """PA - CA now: how much growth is left."""
        return self.pa - self.ca_after if self.pa is not None else None

    def group_delta(self, group: str) -> int:
        """Sum of raw changes in a group (negative-trait rises count against)."""
        return sum(-c.raw_delta if c.attr in NEGATIVE else c.raw_delta for c in self.changes if c.group == group)

    @property
    def moved(self) -> list[AttrChange]:
        return [c for c in self.changes if c.raw_delta]


def snapshot_pair(con: sqlite3.Connection, club_id: int, days: int | None = None) -> tuple[int, int] | None:
    """(before, after) snapshot ids: latest vs earliest, or latest vs the last one at least `days` game-days older."""
    rows = con.execute("SELECT id, game_date FROM snapshots WHERE club_id = ? ORDER BY game_date, id",
                       (club_id,)).fetchall()
    if len(rows) < 2:
        return None
    after = rows[-1]
    if days is None:
        return rows[0]["id"], after["id"]
    cutoff = (dt.date.fromisoformat(after["game_date"]) - dt.timedelta(days=days)).isoformat()
    older = [r for r in rows if r["game_date"] <= cutoff]
    return (older[-1]["id"] if older else rows[0]["id"]), after["id"]


def development(con: sqlite3.Connection, before: int, after: int) -> list[Development]:
    dates = dict(con.execute("SELECT id, game_date FROM snapshots WHERE id IN (?, ?)", (before, after)).fetchall())
    d0, d1 = (dt.date.fromisoformat(dates[i]) for i in (before, after))
    states = con.execute("""
        SELECT a.unique_id, p.name, p.dob, b.status, a.ca AS ca0, b.ca AS ca1, b.pa
        FROM player_state a JOIN player_state b ON b.unique_id = a.unique_id AND b.snapshot_id = ?
        JOIN players p ON p.unique_id = a.unique_id
        WHERE a.snapshot_id = ?""", (after, before)).fetchall()
    attrs: dict[int, dict[str, list[int]]] = {}
    for r in con.execute("""SELECT snapshot_id, unique_id, attr, raw FROM player_attributes
                            WHERE snapshot_id IN (?, ?)""", (before, after)):
        attrs.setdefault(r["unique_id"], {}).setdefault(r["attr"], [None, None])[0 if r["snapshot_id"] == before else 1] = r["raw"]
    out = []
    for s in states:
        dob = dt.date.fromisoformat(s["dob"]) if s["dob"] else None
        age = (d1.year - dob.year - ((d1.month, d1.day) < (dob.month, dob.day))) if dob else None
        changes = [AttrChange(a, GROUP_OF.get(a, "other"), v[0], v[1])
                   for a, v in attrs.get(s["unique_id"], {}).items() if None not in v]
        out.append(Development(s["unique_id"], s["name"], age, s["status"], s["ca0"], s["ca1"], s["pa"],
                               (d1 - d0).days, sorted(changes, key=lambda c: -abs(c.raw_delta))))
    return out


def leaderboard(devs: list[Development], n: int = 10, statuses: tuple[str, ...] | None = None
                ) -> tuple[list[Development], list[Development]]:
    """(top improvers, top decliners) by CA change, then total raw attribute change."""
    pool = [d for d in devs if statuses is None or d.status in statuses]
    score = lambda d: (d.ca_delta, sum(d.group_delta(g) for g in GROUPS))
    ranked = sorted(pool, key=score, reverse=True)
    improvers = [d for d in ranked if score(d) > (0, 0)][:n]
    decliners = [d for d in reversed(ranked) if score(d) < (0, 0)][:n]
    return improvers, decliners
