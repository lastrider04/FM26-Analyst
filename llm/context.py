"""Compact, factual data context for the coach: the squad picture plus detail on the dashboard page in view."""
from __future__ import annotations

import sqlite3

from analytics.development import development, leaderboard, snapshot_pair
from analytics.form import in_form, team_form
from analytics.metrics import aggregate, last_match, match_detail, match_lines
from analytics.players import _attributes, all_players, compare, similar_players
from analytics.selection import recommend
from analytics.squad import alerts, injury_text

SENIOR = ("first team", "loaned in")
DEV_AGE = 21


def _f(v, d=0):
    return "-" if v is None else f"{v:.{d}f}" if isinstance(v, float) else str(v)


def _table(head: list[str], rows: list[list]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
                     + ["| " + " | ".join(_f(c) if not isinstance(c, str) else c for c in r) + " |" for r in rows])


def build_context(con: sqlite3.Connection, club_id: int, page: str = "overview") -> str:
    data = all_players(con, club_id)
    if not data["players"]:
        return "NO DATA: nothing has been captured yet. Ask the user to press Capture in the dashboard while FM26 runs."
    club = (con.execute("SELECT name FROM clubs WHERE club_id = ?", (club_id,)).fetchone() or ["Club"])[0]
    lines = match_lines(con, club_id)
    aggs = aggregate(lines)
    fixtures = sorted({(l.date, l.fixture_id) for l in lines})
    recent_ids = {f for _, f in fixtures[-5:]}
    recent: dict[int, list] = {}
    for l in sorted(lines, key=lambda l: l.date):
        if l.fixture_id in recent_ids:
            recent.setdefault(l.unique_id, []).append(l)
    rec = recommend(con, club_id)
    out = [f"CLUB: {club}. GAME DATE (latest capture): {data['game_date']}. "
           f"Player stats are from {len(fixtures)} captured matches (FM keeps only recent ones in memory)."]

    sq = [p for p in data["players"] if p["status"] in SENIOR]
    rows = []
    for p in sq:
        a, r = aggs.get(p["unique_id"]), recent.get(p["unique_id"], [])
        rows.append([p["name"], p["position"] or "-", p["age"], f"{p['ca']}/{p['pa']}", f"{p['condition']:.0f}%",
                     f"{p['sharpness']:.0f}%", p["jadedness"],
                     injury_text(p["injury"]).replace("injured, ", "INJURED ") if p.get("injury") else "fit", p["status"],
                     len(r), sum(1 for l in r if l.started), " ".join(f"{l.rating:.1f}" for l in r) or "-",
                     a.apps if a else 0, a.minutes if a else 0, _f(a.avg_rating, 2) if a else "-",
                     a.goals if a else 0, a.assists if a else 0])
    out.append("SENIOR SQUAD (condition/sharpness %, jadedness: >300 needs rest, >200 tiring; injury from the medical "
               "record; recent = last 5 captured matches, ratings oldest->newest)\n" + _table(
        ["player", "positions", "age", "CA/PA", "cond", "sharp", "jaded", "injury", "status", "recent apps", "recent starts",
         "recent ratings", "apps", "mins", "avg rating", "G", "A"], rows))

    from analytics.roles import squad_metrics
    sm = squad_metrics(con, club_id)
    senior_ids = {p["unique_id"] for p in sq}
    gks = [g for g in sm["goalkeepers"].values() if g["unique_id"] in senior_ids]
    if gks:
        out.append("GOALKEEPERS (captured matches; save % = saves / shots on target faced; xG prevented not available)\n"
                   + _table(["keeper", "apps", "mins", "avg rating", "save %", "saves", "on target faced", "conceded",
                             "clean sheets", "conceded/90"],
                            [[g["name"], g["apps"], g["minutes"], _f(g["avg_rating"], 2), _f(g["save_pct"], 1), g["saves"],
                              g["shots_on_target_faced"], g["goals_conceded"], g["clean_sheets"], _f(g["conceded_per90"], 2)]
                             for g in sorted(gks, key=lambda g: -g["minutes"])]))
    names = {p["unique_id"]: p["name"] for p in sq}
    roles = [(names[u], s) for u, s in sm["roles"].items() if u in names]
    if roles:
        keys = list(sm["labels"])
        out.append("ROLE SCORES (outfield, 0-100 vs your own players with 180+ captured minutes; " + "; ".join(
            f"{sm['labels'][k]}" for k in keys) + ")\n" + _table(
            ["player"] + [sm["labels"][k] for k in keys],
            [[n] + [s[k] if s[k] is not None else "-" for k in keys] for n, s in sorted(roles)]))

    dev = [p for p in data["players"] if (p["age"] or 99) <= DEV_AGE and (p["pa"] or 0) - (p["ca"] or 0) >= 10]
    dev.sort(key=lambda p: -((p["pa"] or 0) - (p["ca"] or 0)))
    out.append(f"DEVELOPMENT CANDIDATES (age <= {DEV_AGE}, PA-CA >= 10, any team)\n" + _table(
        ["player", "positions", "age", "CA/PA", "headroom", "where", "status", "captured apps", "mins", "sharp"],
        [[p["name"], p["position"] or "-", p["age"], f"{p['ca']}/{p['pa']}", (p["pa"] or 0) - p["ca"], p["where"],
          p["status"], aggs[p["unique_id"]].apps if p["unique_id"] in aggs else 0,
          aggs[p["unique_id"]].minutes if p["unique_id"] in aggs else 0, f"{p['sharpness']:.0f}%"] for p in dev[:20]]))

    up = con.execute("""SELECT f.date, f.kickoff, f.home_id, h.name AS home, a.name AS away, f.competition FROM fixtures f
                        LEFT JOIN clubs h ON h.club_id = f.home_id LEFT JOIN clubs a ON a.club_id = f.away_id
                        WHERE (f.home_id = ? OR f.away_id = ?) AND f.home_goals IS NULL AND f.date >= ?
                        ORDER BY f.date, f.kickoff LIMIT 5""", (club_id, club_id, data["game_date"])).fetchall()
    out.append("NEXT FIXTURES\n" + "\n".join(
        f"- {r['date']} {r['kickoff'] or ''} {'vs' if r['home_id'] == club_id else 'at'} "
        f"{r['away'] if r['home_id'] == club_id else r['home']} ({r['competition']})" for r in up) or "NEXT FIXTURES: none stored")

    tf = team_form(con, club_id)
    out.append(f"TEAM FORM (last {len(tf.results)} competitive, oldest->newest): {tf.string}, {tf.points} pts, "
               f"goals {tf.goals_for}-{tf.goals_against}")
    out.append("IN FORM (app's score: last-3 average + trend + goal involvements)\n" + "\n".join(
        f"- {p['name']}: {p['why']} (score {p['score']})" for p in in_form(lines)))
    out.append("APP'S NEXT-MATCH RECOMMENDATION (rule-based: form, trend, goal threat, ability, condition, sharpness, jadedness, recent minutes)\n"
               + "\n".join(f"- swap: {w['out']['name']} -> {w['in']['name']} [{w['group']}] ({w['reason']})" for w in rec["swaps"])
               + "\n" + "\n".join(f"- best placed: {p['name']} ({p['position']}): {p['why']}" for p in rec["recommended"]))
    al = alerts(con, club_id)
    out.append("ALERTS\n" + ("\n".join(f"- {a.kind}: {a.name} ({a.detail})" for a in al) or "none"))

    summary, ml = last_match(con, club_id)
    if summary:
        out.append(_match_block("LAST MATCH", summary, ml))
    out.append(_focus(con, club_id, page, data))
    return "\n\n".join(x for x in out if x)


def _match_block(title: str, s: dict, lines) -> str:
    head = (f"{title}: {s['date']} {'vs' if s['venue'] != 'A' else 'at'} {s['opponent']} {s['score']} ({s['result'] or 'not played'}), "
            f"{s['competition']}, team xG {s['xg']}, avg rating {s['avg_rating']}")
    if not lines:
        return head + " - no player stats captured"
    return head + "\n" + _table(
        ["player", "start", "mins", "rating", "G", "A", "xG", "xA", "pass %", "shots", "key passes", "tackles won",
         "interceptions", "km"],
        [[l.name, "Y" if l.started else "sub", l.minutes, f"{l.rating:.2f}", l.goals, l.assists, f"{l.xg:.2f}",
          f"{l.xa:.2f}", _f(l.pass_pct), l.counters.get("shots", 0), l.counters.get("key_passes", 0),
          l.counters.get("tackles_won", 0), l.counters.get("interceptions", 0), f"{l.distance_km:.1f}"] for l in lines])


def _focus(con, club_id: int, page: str, data: dict) -> str:
    """Extra detail for the dashboard page the user is looking at."""
    name, *args = (page or "overview").split("?")[0].split("/")
    try:
        if name == "player" and args:
            uid = int(args[0])
            p = next((x for x in data["players"] if x["unique_id"] == uid), None)
            if not p:
                return ""
            snap = con.execute("SELECT id FROM snapshots WHERE club_id = ? ORDER BY game_date DESC, id DESC LIMIT 1",
                               (club_id,)).fetchone()
            attrs = _attributes(con, snap[0]).get(uid, {}) if snap else {}
            ml = sorted(match_lines(con, club_id, unique_id=uid), key=lambda l: l.date)
            ca = []
            for r in con.execute("""SELECT s.game_date, ps.ca FROM player_state ps JOIN snapshots s ON s.id = ps.snapshot_id
                                    WHERE ps.unique_id = ? ORDER BY s.game_date, s.id""", (uid,)):
                if not ca or ca[-1]["ca"] != r["ca"]:   # only changes
                    ca.append(r)
            sim = similar_players(con, club_id, uid)
            return (f"PAGE IN VIEW: player page of {p['name']} - treat 'he', 'him', 'this player' as {p['name']}.\n"
                    f"{p['name']}: {p['position']}, age {p['age']}, CA {p['ca']} / PA {p['pa']}, {p['status']} at {p['where']}, "
                    f"condition {p['condition']:.0f}%, sharpness {p['sharpness']:.0f}%, jadedness {p['jadedness']}, "
                    f"contract to {p['contract_expires']}\n"
                    "Attributes (1-20): " + ", ".join(f"{k} {round(v / 5)}" for k, v in sorted(attrs.items())) + "\n"
                    "CA history: " + ", ".join(f"{r['game_date']} {r['ca']}" for r in ca) + "\n"
                    "Match log (date opponent minutes rating G A xG xA shots/on target key passes tackles won interceptions): "
                    + ("; ".join(f"{l.date} {l.opponent} {l.minutes}' {l.rating:.2f} G{l.goals} A{l.assists} xG{l.xg:.2f} "
                                 f"xA{l.xa:.2f} sh{l.counters.get('shots', 0)}/{l.counters.get('shots_on_target', 0)} "
                                 f"kp{l.counters.get('key_passes', 0)} tk{l.counters.get('tackles_won', 0)} "
                                 f"int{l.counters.get('interceptions', 0)}" for l in ml) or "none captured") + "\n"
                    "Most similar club players (position + attributes): "
                    + ", ".join(f"{s['name']} ({s['position']}, CA {s['ca']}, {s['score']}%)" for s in sim))
        if name == "match" and args:
            s, lines = match_detail(con, club_id, int(args[0]))
            return _match_block("PAGE IN VIEW: match", s, lines) if s else ""
        if name == "compare" and len(args) >= 2:
            c = compare(con, club_id, int(args[0]), int(args[1]))
            a, b = c["players"]
            keys = sorted(set(a["attributes"]) | set(b["attributes"]))
            return (f"PAGE IN VIEW: comparing {a['name']} and {b['name']} (position match {c['position_match']}%, "
                    f"attribute match {c['attribute_match']}%)\n" + _table(
                        ["attribute", a["name"], b["name"]],
                        [[k, round(a["attributes"].get(k, 0) / 5), round(b["attributes"].get(k, 0) / 5)] for k in keys]))
        if name == "development":
            pair = snapshot_pair(con, club_id)
            if not pair:
                return "PAGE IN VIEW: development (only one snapshot so far)"
            up, down = leaderboard(development(con, *pair), n=10)
            fmt = lambda d: f"- {d.name} ({d.age}): CA {d.ca_before}->{d.ca_after} over {d.days} days; " + ", ".join(
                f"{c.attr} {c.shown_before}->{c.shown_after}" for c in d.changes if c.shown_delta)
            return "PAGE IN VIEW: development\nImprovers:\n" + "\n".join(map(fmt, up)) + "\nDecliners:\n" + "\n".join(map(fmt, down))
    except (ValueError, KeyError, IndexError):
        return ""
    return f"PAGE IN VIEW: {name}"
