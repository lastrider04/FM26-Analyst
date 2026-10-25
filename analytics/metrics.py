"""Per-match metrics and per-player aggregates (totals, per-90s) from stored match stats."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from store.db import COUNTERS

MATCH_MINUTES = 90  # FM doesn't store match length here; extra time isn't counted
PER90_MIN_MINUTES = 180  # below this, per-90 numbers are too noisy to rank on


@dataclass
class PlayerMatchLine:
    fixture_id: int
    date: str
    opponent: str
    venue: str              # H / A / N
    result: str             # W / D / L
    score: str              # our goals - their goals
    competition: str
    unique_id: int
    name: str
    started: bool
    minutes: int
    rating: float
    goals: int
    assists: int
    xg: float
    xa: float
    passes_attempted: int
    passes_completed: int
    distance_km: float
    counters: dict = field(default_factory=dict)  # shots, key passes, tackles, ... (see store.db.COUNTERS)

    @property
    def pass_pct(self) -> float | None:
        return round(100 * self.passes_completed / self.passes_attempted, 1) if self.passes_attempted else None

    @property
    def rates(self) -> dict[str, float | None]:
        """Completion percentages for the attempted/completed counters."""
        c = self.counters
        pct = lambda done, att: round(100 * (c.get(done) or 0) / c[att]) if c.get(att) else None
        return {"crosses": pct("crosses_completed", "crosses_attempted"),
                "shots_on_target": pct("shots_on_target", "shots"),
                "tackles": pct("tackles_won", "tackles_attempted"),
                "headers": pct("headers_won", "headers_attempted")}


def minutes_played(lineup_index: int, minutes_on: int, minutes_off: int) -> int:
    started = lineup_index < 11
    start = 0 if started else minutes_on
    end = minutes_off if minutes_off else MATCH_MINUTES
    return max(0, end - start)


def _venue(club_id: int, home_id: int, neutral: int) -> str:
    return "N" if neutral else "H" if club_id == home_id else "A"


def match_lines(con: sqlite3.Connection, club_id: int, since: str | None = None,
                unique_id: int | None = None, fixture_id: int | None = None) -> list[PlayerMatchLine]:
    """One line per player per stored match, oldest first."""
    sql = """
        SELECT f.id, f.date, f.home_id, f.away_id, f.home_goals, f.away_goals, f.neutral, f.competition,
               h.name AS home, a.name AS away, s.*, p.name AS pname
        FROM player_match_stats s
        JOIN matches m ON m.fixture_id = s.fixture_id AND m.club_id = ?
        JOIN fixtures f ON f.id = s.fixture_id
        LEFT JOIN clubs h ON h.club_id = f.home_id
        LEFT JOIN clubs a ON a.club_id = f.away_id
        LEFT JOIN players p ON p.unique_id = s.unique_id
        WHERE (? IS NULL OR f.date >= ?) AND (? IS NULL OR s.unique_id = ?) AND (? IS NULL OR f.id = ?)
        ORDER BY f.date, s.lineup_index"""
    out = []
    for r in con.execute(sql, (club_id, since, since, unique_id, unique_id, fixture_id, fixture_id)):
        home = r["home_id"] == club_id
        gf, ga = (r["home_goals"], r["away_goals"]) if home else (r["away_goals"], r["home_goals"])
        out.append(PlayerMatchLine(
            fixture_id=r["id"], date=r["date"], opponent=(r["away"] if home else r["home"]) or "?",
            venue=_venue(club_id, r["home_id"], r["neutral"]),
            result="W" if gf > ga else "L" if gf < ga else "D", score=f"{gf}-{ga}",
            competition=r["competition"] or "", unique_id=r["unique_id"], name=r["pname"] or str(r["unique_id"]),
            started=r["lineup_index"] < 11,
            minutes=minutes_played(r["lineup_index"], r["minutes_on"], r["minutes_off"]),
            rating=r["rating"], goals=r["goals"], assists=r["assists"], xg=r["xg"], xa=r["xa"],
            passes_attempted=r["passes_attempted"], passes_completed=r["passes_completed"],
            distance_km=round(r["distance_m"] / 1000, 2),
            counters={c: r[c] for c in COUNTERS if c in r.keys() and r[c] is not None},
        ))
    return out


PER90_COUNTERS = ["key_passes", "progressive_passes", "dribbles", "shots", "tackles_won", "interceptions",
                  "clearances", "headers_won"]


@dataclass
class PlayerAggregate:
    unique_id: int
    name: str
    apps: int = 0
    starts: int = 0
    minutes: int = 0
    goals: int = 0
    assists: int = 0
    xg: float = 0.0
    xa: float = 0.0
    passes_attempted: int = 0
    passes_completed: int = 0
    distance_km: float = 0.0
    ratings: list[float] = field(default_factory=list)
    counters: dict = field(default_factory=dict)

    @property
    def avg_rating(self) -> float | None:
        return round(sum(self.ratings) / len(self.ratings), 2) if self.ratings else None

    @property
    def pass_pct(self) -> float | None:
        return round(100 * self.passes_completed / self.passes_attempted, 1) if self.passes_attempted else None

    @property
    def goals_minus_xg(self) -> float:
        """Finishing over/under-performance; positive = scoring more than chances suggest."""
        return round(self.goals - self.xg, 2)

    def per90(self, value: float) -> float | None:
        return round(value * 90 / self.minutes, 2) if self.minutes else None

    def per90s(self) -> dict[str, float | None]:
        return {
            "goals": self.per90(self.goals), "assists": self.per90(self.assists),
            "xg": self.per90(self.xg), "xa": self.per90(self.xa),
            "goal_involvements": self.per90(self.goals + self.assists),
            "xg_plus_xa": self.per90(self.xg + self.xa),
            "passes_completed": self.per90(self.passes_completed),
            "distance_km": self.per90(self.distance_km),
            **{c: self.per90(self.counters.get(c, 0)) for c in PER90_COUNTERS},
        }

    @property
    def per90_reliable(self) -> bool:
        return self.minutes >= PER90_MIN_MINUTES


def aggregate(lines: list[PlayerMatchLine]) -> dict[int, PlayerAggregate]:
    out: dict[int, PlayerAggregate] = {}
    for ln in lines:
        a = out.setdefault(ln.unique_id, PlayerAggregate(ln.unique_id, ln.name))
        a.apps += 1
        a.starts += ln.started
        a.minutes += ln.minutes
        a.goals += ln.goals
        a.assists += ln.assists
        a.xg += ln.xg
        a.xa += ln.xa
        a.passes_attempted += ln.passes_attempted
        a.passes_completed += ln.passes_completed
        a.distance_km += ln.distance_km
        a.ratings.append(ln.rating)
        for k, v in ln.counters.items():
            a.counters[k] = a.counters.get(k, 0) + v
    for a in out.values():
        a.xg, a.xa, a.distance_km = round(a.xg, 2), round(a.xa, 2), round(a.distance_km, 1)
    return out


def match_detail(con: sqlite3.Connection, club_id: int, fixture_id: int) -> tuple[dict | None, list[PlayerMatchLine]]:
    """One fixture: summary (always, if the fixture exists) + player lines when stats were captured."""
    f = con.execute("""SELECT f.*, h.name AS home, a.name AS away FROM fixtures f
                       LEFT JOIN clubs h ON h.club_id = f.home_id LEFT JOIN clubs a ON a.club_id = f.away_id
                       WHERE f.id = ?""", (fixture_id,)).fetchone()
    if not f:
        return None, []
    home = f["home_id"] == club_id
    gf, ga = (f["home_goals"], f["away_goals"]) if home else (f["away_goals"], f["home_goals"])
    lines = sorted(match_lines(con, club_id, fixture_id=fixture_id), key=lambda l: -l.rating)
    summary = dict(fixture_id=fixture_id, date=f["date"], opponent=(f["away"] if home else f["home"]) or "?",
                   venue=_venue(club_id, f["home_id"], f["neutral"]),
                   result=None if gf is None else "W" if gf > ga else "L" if gf < ga else "D",
                   score=f"{gf}-{ga}", competition=f["competition"] or "",
                   pens=f"{f['home_pens']}-{f['away_pens']}" if f["home_pens"] is not None else None,
                   has_stats=bool(lines),
                   goals=sum(l.goals for l in lines), xg=round(sum(l.xg for l in lines), 2),
                   avg_rating=round(sum(l.rating for l in lines) / len(lines), 2) if lines else None)
    return summary, lines


def last_match(con: sqlite3.Connection, club_id: int) -> tuple[dict | None, list[PlayerMatchLine]]:
    """The most recent match with stored player stats."""
    row = con.execute("""SELECT f.id FROM matches m JOIN fixtures f ON f.id = m.fixture_id
                         WHERE m.club_id = ? ORDER BY f.date DESC LIMIT 1""", (club_id,)).fetchone()
    return match_detail(con, club_id, row[0]) if row else (None, [])


def neighbours(con: sqlite3.Connection, club_id: int, fixture_id: int) -> dict:
    """Previous / next played fixture ids (by date) for stepping through matches."""
    date = con.execute("SELECT date FROM fixtures WHERE id = ?", (fixture_id,)).fetchone()
    if not date:
        return {}
    q = """SELECT id FROM fixtures WHERE (home_id = ? OR away_id = ?) AND home_goals IS NOT NULL
           AND date {op} ? ORDER BY date {order} LIMIT 1"""
    prev = con.execute(q.format(op="<", order="DESC"), (club_id, club_id, date[0])).fetchone()
    nxt = con.execute(q.format(op=">", order="ASC"), (club_id, club_id, date[0])).fetchone()
    return {"previous": prev[0] if prev else None, "next": nxt[0] if nxt else None}
