"""Look-up tools the coach can call when a question needs more than the summary DATA block."""
from __future__ import annotations

import json
import sqlite3
import unicodedata

from analytics.metrics import match_detail
from analytics.players import all_players

TOOLS = [
    {"name": "get_player",
     "description": "Full detail on one player at the club (any team, loans included): attributes 1-20, CA history, "
                    "every captured match, injury, and keeper stats or role scores. Use for questions about a "
                    "specific player who isn't the page in view.",
     "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "Player name or surname"}},
                    "required": ["name"]}},
    {"name": "get_match",
     "description": "Every player's stats in one captured match, found by opponent and/or date (latest match if both "
                    "are empty). Use for questions about a particular game.",
     "parameters": {"type": "object", "properties": {
         "opponent": {"type": "string", "description": "Opponent club name, or part of it"},
         "date": {"type": "string", "description": "Match date YYYY-MM-DD (optional)"}}}},
    {"name": "list_matches",
     "description": "The club's captured matches with player stats: date, opponent, venue, score, competition.",
     "parameters": {"type": "object", "properties": {}}},
]
LABELS = {"get_player": "Looking up {name}", "get_match": "Looking up the match {opponent}{date}",
          "list_matches": "Checking the match list"}


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


def describe(name: str, args: dict) -> str:
    return LABELS.get(name, name).format(name=args.get("name", ""), opponent=args.get("opponent", "") or "",
                                         date=(" " + args["date"]) if args.get("date") else "").strip()


def _stored_matches(con: sqlite3.Connection, club_id: int) -> list[sqlite3.Row]:
    return con.execute("""SELECT f.id, f.date, f.home_id, f.home_goals, f.away_goals, f.competition,
                                 h.name AS home, a.name AS away
                          FROM matches m JOIN fixtures f ON f.id = m.fixture_id
                          LEFT JOIN clubs h ON h.club_id = f.home_id LEFT JOIN clubs a ON a.club_id = f.away_id
                          WHERE m.club_id = ? ORDER BY f.date DESC""", (club_id,)).fetchall()


def run(con: sqlite3.Connection, club_id: int, name: str, arguments: str | dict) -> str:
    """Execute a tool call; always returns text for the model (errors included, never raises)."""
    from llm.context import _focus, _match_block
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
    except ValueError:
        args = {}
    try:
        if name == "get_player":
            want = _fold(args.get("name", "")).strip()
            if not want:
                return "Give a player name."
            data = all_players(con, club_id)
            hits = [p for p in data["players"] if want in _fold(p["name"])]
            exact = [p for p in hits if _fold(p["name"]) == want or _fold(p["name"]).split()[-1] == want]
            hits = exact or hits
            if not hits:
                return f"No player matching '{args.get('name')}' at the club."
            if len(hits) > 1 and not exact:
                return "Several players match: " + ", ".join(f"{p['name']} ({p['position']}, {p['where']})" for p in hits[:10])
            return _focus(con, club_id, f"player/{hits[0]['unique_id']}", data).replace("PAGE IN VIEW: player page of", "PLAYER:")
        if name == "get_match":
            opp, date = _fold(args.get("opponent", "")), (args.get("date") or "").strip()
            for r in _stored_matches(con, club_id):
                other = r["away"] if r["home_id"] == club_id else r["home"]
                if (not opp or opp in _fold(other or "")) and (not date or r["date"] == date):
                    s, lines = match_detail(con, club_id, r["id"])
                    return _match_block("MATCH", s, lines)
            return f"No captured match found for opponent '{args.get('opponent', '')}' date '{date}'."
        if name == "list_matches":
            rows = _stored_matches(con, club_id)
            out = []
            for r in rows[:40]:
                home = r["home_id"] == club_id
                gf, ga = (r["home_goals"], r["away_goals"]) if home else (r["away_goals"], r["home_goals"])
                out.append(f"- {r['date']} {'vs' if home else 'at'} {r['away'] if home else r['home']} {gf}-{ga} ({r['competition']})")
            return "CAPTURED MATCHES (newest first)\n" + ("\n".join(out) or "none")
        return f"Unknown tool {name}."
    except Exception as e:      # noqa: BLE001 - report to the model instead of failing the answer
        return f"Look-up failed: {e}"
