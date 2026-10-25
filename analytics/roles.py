"""Goalkeeper metrics and outfield role scores from stored match stats.

Goalkeepers: "shots faced" is shots on target faced (saves + on-target goals). Save % = saves / shots on target faced.
Goals conceded use the real score when the keeper played the whole match (own goals aren't shots on target), else
shots on target faced - saves for his minutes. FM doesn't give us the opponents' shot xG, so xG prevented isn't available.

Role scores (outfield): each is the average percentile rank, within the club's outfield players with enough minutes,
of a few per-90 stats. 100 = best in the squad on that role, 0 = lowest. They compare your own players, not leagues.
"""
from __future__ import annotations

from collections import defaultdict

from .metrics import PER90_MIN_MINUTES, PlayerAggregate, PlayerMatchLine

CLEAN_SHEET_MINUTES = 60

ROLES = {
    "chance_creation": ("Chance creation", ["key_passes", "xa", "progressive_passes", "crosses_completed"]),
    "goal_threat": ("Goal threat", ["xg", "shots", "goals"]),
    "finishing": ("Finishing", ["goals_minus_xg", "shot_accuracy"]),
    "defensive_work": ("Defensive work", ["tackles_won", "interceptions", "clearances", "headers_won", "key_tackles"]),
    "ball_security": ("Ball security", ["pass_pct", "passes_completed"]),
}


def _saves(c: dict) -> int:
    return (c.get("saves_held") or 0) + (c.get("saves_parried") or 0) + (c.get("saves_tipped") or 0)


def goalkeeping(lines: list[PlayerMatchLine], keepers: set[int]) -> dict[int, dict]:
    """Per keeper: apps, minutes, saves, shots on target faced, conceded, save %, clean sheets, per-90s."""
    acc: dict[int, dict] = defaultdict(lambda: dict(apps=0, minutes=0, saves=0, faced=0, conceded=0, clean_sheets=0,
                                                    ratings=[], name=""))
    for l in lines:
        saves, faced = _saves(l.counters), l.counters.get("shots_faced") or 0
        if l.unique_id not in keepers and not faced and not saves:
            continue
        a = acc[l.unique_id]
        # full match: the real score (counts own goals and other goals that weren't shots on target);
        # part of a match: shots on target faced minus saves
        ga = int(l.score.split("-")[1]) if l.score and "-" in l.score else None
        conceded = ga if (ga is not None and l.minutes >= 90) else max(0, faced - saves)
        a["name"] = l.name
        a["apps"] += 1
        a["minutes"] += l.minutes
        a["saves"] += saves
        a["faced"] += faced
        a["conceded"] += conceded
        a["clean_sheets"] += int(conceded == 0 and l.minutes >= CLEAN_SHEET_MINUTES)
        a["ratings"].append(l.rating)
    out = {}
    for uid, a in acc.items():
        m = a["minutes"]
        out[uid] = {"unique_id": uid, "name": a["name"], "apps": a["apps"], "minutes": m, "saves": a["saves"],
                    "shots_on_target_faced": a["faced"], "goals_conceded": a["conceded"],
                    "clean_sheets": a["clean_sheets"],
                    "save_pct": round(100 * a["saves"] / a["faced"], 1) if a["faced"] else None,
                    "saves_per90": round(90 * a["saves"] / m, 2) if m else None,
                    "conceded_per90": round(90 * a["conceded"] / m, 2) if m else None,
                    "faced_per90": round(90 * a["faced"] / m, 2) if m else None,
                    "avg_rating": round(sum(a["ratings"]) / len(a["ratings"]), 2) if a["ratings"] else None,
                    "reliable": m >= PER90_MIN_MINUTES}
    return out


def _metrics(a: PlayerAggregate) -> dict[str, float | None]:
    p = a.per90s()
    c = a.counters
    shots = c.get("shots") or 0
    return {"key_passes": p.get("key_passes"), "xa": p.get("xa"), "progressive_passes": p.get("progressive_passes"),
            "crosses_completed": a.per90(c.get("crosses_completed") or 0), "xg": p.get("xg"), "shots": p.get("shots"),
            "goals": p.get("goals"), "goals_minus_xg": a.per90(a.goals - a.xg),
            "shot_accuracy": round(100 * (c.get("shots_on_target") or 0) / shots, 1) if shots >= 5 else None,
            "tackles_won": p.get("tackles_won"), "interceptions": p.get("interceptions"),
            "clearances": p.get("clearances"), "headers_won": p.get("headers_won"),
            "key_tackles": a.per90(c.get("key_tackles") or 0), "pass_pct": a.pass_pct,
            "passes_completed": p.get("passes_completed")}


def _percentiles(values: dict[int, float]) -> dict[int, float]:
    """uid -> 0..100 rank (ties share the average rank)."""
    if not values:
        return {}
    if len(values) == 1:
        return {uid: 50.0 for uid in values}
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    ranks: dict[int, float] = {}
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        r = (i + j) / 2
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = 100 * r / (len(ordered) - 1)
        i = j + 1
    return ranks


def role_scores(aggs: dict[int, PlayerAggregate], outfield: set[int]) -> dict[int, dict]:
    """uid -> {role: 0..100} for outfield players with >= PER90_MIN_MINUTES stored minutes."""
    pool = {uid: _metrics(a) for uid, a in aggs.items() if uid in outfield and a.per90_reliable}
    if not pool:
        return {}
    pct = {}
    for metric in {m for _, ms in ROLES.values() for m in ms}:
        vals = {uid: m[metric] for uid, m in pool.items() if m.get(metric) is not None}
        pct[metric] = _percentiles(vals)
    out = {}
    for uid in pool:
        scores = {}
        for role, (_, ms) in ROLES.items():
            got = [pct[m][uid] for m in ms if uid in pct[m]]
            scores[role] = round(sum(got) / len(got)) if got else None
        out[uid] = scores
    return out


def role_labels() -> dict[str, str]:
    return {k: v[0] for k, v in ROLES.items()}


def squad_metrics(con, club_id: int) -> dict:
    """{goalkeepers: {uid: ...}, roles: {uid: {role: score}}, labels} for the club (keepers by best position)."""
    from .metrics import aggregate, match_lines
    from .players import all_players
    players = all_players(con, club_id)["players"]
    keepers = {p["unique_id"] for p in players if p.get("primary") == "GK"}
    lines = match_lines(con, club_id)
    aggs = aggregate(lines)
    return {"goalkeepers": goalkeeping(lines, keepers),
            "roles": role_scores(aggs, {uid for uid in aggs if uid not in keepers}),
            "labels": role_labels()}
