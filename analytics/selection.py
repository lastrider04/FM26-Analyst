"""Recommended for next match: form, trend, goal threat, ability and fitness, with same-position swaps."""
from __future__ import annotations

import sqlite3

from .metrics import aggregate, match_lines
from .players import ACCOMPLISHED, NATURAL, all_players
from .squad import CONDITION_LOW, JADED, injury_text

# position groups a manager rotates within
GROUPS = {"GK": ["GK"], "D C": ["DC"], "D L / WB L": ["DL", "WBL"], "D R / WB R": ["DR", "WBR"],
          "DM / M C": ["DM", "MC"], "AM C": ["AMC"], "AM L / M L": ["AML", "ML"], "AM R / M R": ["AMR", "MR"],
          "ST": ["ST"]}
CAUTION_CONDITION = 90.0
CAUTION_JADED = 200
SHARPNESS_LOW = 70.0
FRESH_CONDITION, FRESH_JADED = 95.0, 100
NEUTRAL_FORM = 6.7          # stand-in rating for players without captured matches
RECENT = 5                  # matches used for form
STARTER_WINDOW = 3          # a "likely starter" started at least 2 of the club's last 3 captured matches
HEAVY_LOAD_MINUTES = 170    # minutes over the last two captured matches that count as a heavy load


def group_of(positions: dict[str, int]) -> str | None:
    best = max(((v, p) for p, v in positions.items() if p != "SW"), default=None)
    return next((g for g, ps in GROUPS.items() if best and best[1] in ps), None)


def plays_in(positions: dict[str, int], group: str) -> bool:
    return any(positions.get(p, 1) >= ACCOMPLISHED for p in GROUPS[group])


def _trend(ratings: list[float]) -> float:
    n = len(ratings)
    if n < 2:
        return 0.0
    xm, ym = (n - 1) / 2, sum(ratings) / n
    num = sum((i - xm) * (r - ym) for i, r in enumerate(ratings))
    den = sum((i - xm) ** 2 for i in range(n))
    return round(num / den, 3)


def recommend(con: sqlite3.Connection, club_id: int, n: int = 6) -> dict:
    """Score every senior player on what the captures hold, then pick starters and same-position swaps.

    score = recent form (avg rating, last RECENT captured matches; NEUTRAL_FORM if none)
            + 0.5 x trend (capped +/-0.4)
            + 0.15 x goal involvements per recent appearance
            + up to +0.3 for xG+xA per 90 over all stored minutes (attacking threat)
            + (ability - 160) / 400                         (small tie-breaker)
            + condition / sharpness bonuses, jadedness penalty
    Unfit (never recommended): injured, condition < 85% or jadedness > 300. Cautions: condition 85-90%, jadedness
    200-300, sharpness < 70%, heavy minutes over the last two matches, no captured matches.
    """
    data = all_players(con, club_id)
    squad = [p for p in data["players"] if p["status"] in ("first team", "loaned in")]
    if not squad:
        return {"recommended": [], "swaps": [], "rest": [], "basis": {}}

    lines = match_lines(con, club_id)
    aggs = aggregate(lines)
    fixtures = sorted({(l.date, l.fixture_id) for l in lines})
    recent = {f for _, f in fixtures[-RECENT:]}
    last = {f for _, f in fixtures[-STARTER_WINDOW:]}
    last2 = {f for _, f in fixtures[-2:]}
    ratings: dict[int, list[float]] = {}
    ga: dict[int, int] = {}
    starts: dict[int, int] = {}
    load: dict[int, int] = {}
    for l in sorted(lines, key=lambda l: l.date):
        if l.fixture_id in recent:
            ratings.setdefault(l.unique_id, []).append(l.rating)
            ga[l.unique_id] = ga.get(l.unique_id, 0) + l.goals + l.assists
        if l.fixture_id in last and l.started:
            starts[l.unique_id] = starts.get(l.unique_id, 0) + 1
        if l.fixture_id in last2:
            load[l.unique_id] = load.get(l.unique_id, 0) + l.minutes
    need = min(2, len(last))

    rows = []
    for p in squad:
        uid = p["unique_id"]
        cond, sharp, jad = p["condition"] or 0, p["sharpness"] or 0, p["jadedness"] or 0
        r = ratings.get(uid, [])
        form = round(sum(r) / len(r), 2) if r else None
        trend = _trend(r)
        gi = ga.get(uid, 0)
        agg = aggs.get(uid)
        threat = (agg.per90s().get("xg_plus_xa") or 0) if agg and agg.per90_reliable else 0
        score = ((form or NEUTRAL_FORM) + 0.5 * max(-0.4, min(0.4, trend)) + (0.15 * gi / len(r) if r else 0)
                 + min(0.3, 0.1 * threat) + ((p["ca"] or 160) - 160) / 400
                 + (cond - 92) / 25 + (sharp - 90) / 60 - max(0, jad - 150) / 600)
        issues = []
        if p.get("injury"):
            issues.append(injury_text(p["injury"]))
        if cond < CONDITION_LOW:
            issues.append(f"condition {cond:.0f}%")
        if jad > JADED:
            issues.append(f"jaded ({jad})")
        cautions = []
        if CONDITION_LOW <= cond < CAUTION_CONDITION:
            cautions.append(f"condition {cond:.0f}%")
        if CAUTION_JADED < jad <= JADED:
            cautions.append(f"tiring ({jad})")
        if sharp < SHARPNESS_LOW:
            cautions.append(f"sharpness {sharp:.0f}%")
        if load.get(uid, 0) >= HEAVY_LOAD_MINUTES and group_of(p["positions"]) != "GK":   # keepers always play 90
            cautions.append(f"{load[uid]}' in last 2")
        if not r:
            cautions.append("no captured matches")
        why = []
        if form is not None:
            why.append(f"form {form:.2f} in {len(r)}" + (" ↑" if trend >= 0.1 else " ↓" if trend <= -0.1 else ""))
        if gi:
            why.append(f"{gi} G+A")
        if threat:
            why.append(f"xG+xA/90 {threat:.2f}")
        why.append(f"cond {cond:.0f}%, sharp {sharp:.0f}%")
        why.append(f"CA {p['ca']}")
        rows.append(dict(unique_id=uid, name=p["name"], position=p["primary"], group=group_of(p["positions"]),
                         positions=p["positions"], condition=round(cond, 1), sharpness=round(sharp, 1), jadedness=jad,
                         form=form, trend=trend, goal_involvements=gi, threat=round(threat, 2), ca=p["ca"],
                         injury=p.get("injury"),
                         score=round(score, 2), starter=bool(last) and starts.get(uid, 0) >= need,
                         unfit=issues, caution=cautions, why=", ".join(why)))

    fit = sorted((r for r in rows if not r["unfit"]), key=lambda r: -r["score"])
    swaps, used = [], set()
    for s in sorted((r for r in rows if r["starter"] and r["group"]), key=lambda r: r["score"]):
        hard = bool(s["unfit"])
        if not hard and not s["caution"]:
            continue
        natural = lambda r: max(r["positions"].get(p, 1) for p in GROUPS[s["group"]]) >= NATURAL
        for alt in sorted(fit, key=lambda r: -(r["score"] + 0.3 * natural(r))):
            if alt["unique_id"] == s["unique_id"] or alt["starter"] or alt["unique_id"] in used:
                continue
            if not plays_in(alt["positions"], s["group"]):
                continue
            fresh = alt["condition"] >= FRESH_CONDITION and alt["jadedness"] < FRESH_JADED
            if hard or (fresh and alt["score"] >= s["score"] - 0.1):
                used.add(alt["unique_id"])
                swaps.append({"out": s, "in": alt, "group": s["group"], "must": hard,
                              "reason": ("rest: " if hard else "consider: ") + ", ".join(s["unfit"] or s["caution"])})
                break
    strip = lambda r: {k: v for k, v in r.items() if k != "positions"}
    return {"recommended": [strip(r) for r in fit[:n]],
            "swaps": [{**w, "out": strip(w["out"]), "in": strip(w["in"])} for w in swaps],
            "rest": [strip(r) for r in rows if r["unfit"]],
            "basis": {"condition_at": data["game_date"], "matches": len(recent)}}
