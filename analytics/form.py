"""Form: player rating trends over recent matches, and team results form from fixtures."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .metrics import PlayerMatchLine

FORM_MATCHES = 5


@dataclass
class PlayerForm:
    unique_id: int
    name: str
    ratings: list[float]          # oldest -> newest, last FORM_MATCHES appearances
    season_avg: float

    @property
    def avg(self) -> float:
        return round(sum(self.ratings) / len(self.ratings), 2)

    @property
    def vs_season(self) -> float:
        """Recent average minus season average: positive = in form."""
        return round(self.avg - self.season_avg, 2)

    @property
    def trend(self) -> float:
        """Least-squares slope of rating per match over the window."""
        n = len(self.ratings)
        if n < 2:
            return 0.0
        xm, ym = (n - 1) / 2, self.avg
        num = sum((i - xm) * (r - ym) for i, r in enumerate(self.ratings))
        den = sum((i - xm) ** 2 for i in range(n))
        return round(num / den, 3)

    @property
    def label(self) -> str:
        if len(self.ratings) < 3:
            return "too few games"
        if self.avg >= 7.3 and self.trend >= 0:
            return "excellent"
        if self.vs_season >= 0.2 or self.trend >= 0.1:
            return "improving"
        if self.vs_season <= -0.2 or self.trend <= -0.1:
            return "dipping"
        return "steady"


def player_form(lines: list[PlayerMatchLine], window: int = FORM_MATCHES) -> list[PlayerForm]:
    by: dict[int, list[PlayerMatchLine]] = {}
    for ln in lines:
        by.setdefault(ln.unique_id, []).append(ln)
    out = []
    for uid, ls in by.items():
        ls.sort(key=lambda l: l.date)
        all_r = [l.rating for l in ls]
        out.append(PlayerForm(uid, ls[-1].name, all_r[-window:], round(sum(all_r) / len(all_r), 2)))
    return sorted(out, key=lambda f: -f.avg)


def in_form(lines: list[PlayerMatchLine], n: int = 5, recent_matches: int = 5) -> list[dict]:
    """Top players on recent form: rating (last 3 games), trend, and goal involvements.

    score = avg rating of the last 3 appearances + 0.5 x trend (capped at +/-0.4, so two games
    can't fake a trend) + 0.15 x (goals + assists per game), over the club's last `recent_matches`
    stored matches; at least 2 appearances in that window.
    """
    fixtures = sorted({(l.date, l.fixture_id) for l in lines})[-recent_matches:]
    window = {fid for _, fid in fixtures}
    by: dict[int, list[PlayerMatchLine]] = {}
    for ln in lines:
        if ln.fixture_id in window:
            by.setdefault(ln.unique_id, []).append(ln)
    out = []
    for uid, ls in by.items():
        if len(ls) < 2:
            continue
        ls.sort(key=lambda l: l.date)
        last3 = [l.rating for l in ls[-3:]]
        f = PlayerForm(uid, ls[-1].name, [l.rating for l in ls], 0)
        ga = sum(l.goals + l.assists for l in ls)
        score = sum(last3) / len(last3) + 0.5 * max(-0.4, min(0.4, f.trend)) + 0.15 * ga / len(ls)
        reasons = [f"avg {sum(last3) / len(last3):.2f} last {len(last3)}"]
        if ga:
            reasons.append(f"{ga} G+A in {len(ls)}")
        if f.trend >= 0.1:
            reasons.append("rising")
        out.append(dict(unique_id=uid, name=ls[-1].name, ratings=[l.rating for l in ls], score=round(score, 2),
                        apps=len(ls), goal_involvements=ga, trend=f.trend, why=", ".join(reasons)))
    return sorted(out, key=lambda x: -x["score"])[:n]


@dataclass
class TeamForm:
    results: list[dict]           # oldest -> newest
    window: int

    @property
    def string(self) -> str:
        return "".join(r["result"] for r in self.results)

    @property
    def points(self) -> int:
        return sum({"W": 3, "D": 1, "L": 0}[r["result"]] for r in self.results)

    @property
    def goals_for(self) -> int:
        return sum(r["gf"] for r in self.results)

    @property
    def goals_against(self) -> int:
        return sum(r["ga"] for r in self.results)

    @property
    def unbeaten_run(self) -> int:
        n = 0
        for r in reversed(self.results):
            if r["result"] == "L":
                break
            n += 1
        return n


def team_form(con: sqlite3.Connection, club_id: int, window: int = 10, competitive_only: bool = True,
              until: str | None = None) -> TeamForm:
    """Last `window` played fixtures (friendlies excluded by default)."""
    rows = con.execute("""
        SELECT f.id, f.date, f.home_id, f.home_goals, f.away_goals, f.neutral, f.competition,
               h.name AS home, a.name AS away,
               EXISTS (SELECT 1 FROM matches m WHERE m.fixture_id = f.id) AS has_stats
        FROM fixtures f LEFT JOIN clubs h ON h.club_id = f.home_id LEFT JOIN clubs a ON a.club_id = f.away_id
        WHERE (f.home_id = ? OR f.away_id = ?) AND f.home_goals IS NOT NULL AND (? IS NULL OR f.date <= ?)
        ORDER BY f.date DESC""", (club_id, club_id, until, until)).fetchall()
    out = []
    for r in rows:
        if competitive_only and (r["competition"] or "").startswith("Friendly"):
            continue
        home = r["home_id"] == club_id
        gf, ga = (r["home_goals"], r["away_goals"]) if home else (r["away_goals"], r["home_goals"])
        out.append(dict(fixture_id=r["id"], has_stats=bool(r["has_stats"]), date=r["date"],
                        opponent=r["away"] if home else r["home"],
                        venue="N" if r["neutral"] else "H" if home else "A", gf=gf, ga=ga,
                        result="W" if gf > ga else "L" if gf < ga else "D", competition=r["competition"]))
        if len(out) == window:
            break
    return TeamForm(list(reversed(out)), window)
