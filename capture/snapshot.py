"""Capture a snapshot from the running game and store it.

    read_snapshot(proc, club_id) -> dict   (JSON-serialisable; the raw record of one capture)
    store_snapshot(con, snap) -> int        (writes it to SQLite, returns snapshot id)
    capture(club_id) -> CaptureResult       (both, plus the raw JSON file in data/snapshots/)
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import sqlite3
import time
from dataclasses import dataclass

import app_config
from reader.fixtures import read_club_names, read_fixtures, read_upcoming
from reader.matches import game_date, link_fixtures, read_matches
from reader.people import Player, read_club_players, read_person_names
from reader.process import GameProcess
from reader.profile import load_profile
from store.db import COUNTERS, connect, lineup_key, stored_links, upsert_fixture

SNAPSHOT_FORMAT = 1


def _status(pl: Player, club_id: int) -> str:
    if pl.loaned_out(club_id):
        return "loaned out"
    if pl.loaned_in(club_id):
        return "loaned in"
    if pl.uncontracted:
        return "no contract"
    if pl.youth_team(club_id):
        return "youth team"
    return "first team"


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def _key_of(m) -> str:
    return lineup_key((pm.unique_id, pm.rating) for pm in m.team.lineup if pm.played and pm.unique_id is not None)


def read_snapshot(proc: GameProcess, club_id: int,
                  known_links: dict[str, tuple[str, int, int]] | None = None) -> dict:
    """Read everything for one capture into a plain dict.

    known_links (line-up key -> stored fixture) keeps earlier links sticky: a line-up seen before
    stays on its fixture, and fixtures that already have stats aren't offered to new line-ups.
    """
    profile = load_profile(proc.build_id())
    today = game_date(proc, profile)
    clubs = read_club_names(proc, profile)
    players = read_club_players(proc, club_id, profile)
    fixtures = read_fixtures(proc, club_id, profile, names=clubs)
    matches = read_matches(proc, club_id, profile)
    current = {p.unique_id for p in players if not p.loaned_out(club_id)}

    known_links = known_links or {}
    by_fixture = {(f.date.isoformat(), f.home_id, f.away_id): f for f in fixtures}
    taken = set(known_links.values())
    seen_keys, new = set(), []
    for m in matches:
        k = _key_of(m)
        if k in seen_keys:
            m.fixture = None  # duplicate copy of a line-up already in this capture
            continue
        seen_keys.add(k)
        if k in known_links and known_links[k] in by_fixture:
            m.fixture, m.link_confidence = by_fixture[known_links[k]], "stored"
        else:
            new.append(m)
    free = [f for f in fixtures if (f.date.isoformat(), f.home_id, f.away_id) not in taken]
    link_fixtures(new, free, club_id, today, current_uids=current)

    fixture_dict = lambda f: dict(
        date=_iso(f.date), home_id=f.home_id, away_id=f.away_id, home=f.home, away=f.away,
        home_goals=f.home_goals, away_goals=f.away_goals, home_pens=f.home_pens, away_pens=f.away_pens,
        neutral=int(f.neutral), competition_index=f.competition_index, competition=f.competition,
        kickoff=f.kickoff)
    fixture_dicts = [fixture_dict(f) for f in fixtures]
    played_keys = {(f["date"], f["home_id"], f["away_id"]) for f in fixture_dicts}
    upcoming_dicts = [fixture_dict(f) for f in read_upcoming(proc, club_id, today, profile, names=clubs)
                      if (_iso(f.date), f.home_id, f.away_id) not in played_keys]

    match_dicts = []
    for m in matches:
        if not m.fixture:
            continue  # unlinked line-ups are skipped rather than guessed
        f = m.fixture
        match_dicts.append(dict(
            fixture=dict(date=_iso(f.date), home_id=f.home_id, away_id=f.away_id),
            match_key=_key_of(m), link_confidence=m.link_confidence,
            players=[dict(
                unique_id=pm.unique_id, lineup_index=i,
                rating=pm.rating, minutes_on=pm.stats["sub_on_minute"], minutes_off=pm.stats["sub_off_minute"],
                goals=pm.stats["goals"], assists=pm.stats["assists"], xg=pm.stats["xg"], xa=pm.stats["xa"],
                passes_attempted=pm.stats["passes_attempted"], passes_completed=pm.stats["passes_completed"],
                distance_m=pm.stats["distance_m"], shirt_number=pm.stats["shirt_number"],
                raw=base64.b64encode(pm.raw).decode(),
            ) for i, pm in enumerate(m.team.lineup) if pm.played and pm.unique_id is not None],
        ))

    # people in stored line-ups who aren't at the club any more still need a name
    club_uids = {p.unique_id for p in players}
    others = {pl["unique_id"] for m in match_dicts for pl in m["players"]} - club_uids
    other_people = [dict(unique_id=uid, name=n, first_name=f, last_name=l)
                    for uid, (n, f, l) in read_person_names(proc, others, profile).items()]

    return dict(
        format=SNAPSHOT_FORMAT,
        other_people=other_people,
        taken_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        game_date=_iso(today), club_id=club_id, build_id=proc.build_id(),
        clubs={str(k): v for k, v in clubs.items()
               if k in {f[s] for f in fixture_dicts + upcoming_dicts for s in ("home_id", "away_id")}
               | {p.at_club_id for p in players} | {club_id}},
        players=[dict(
            unique_id=p.unique_id, name=p.name, first_name=p.first_name, last_name=p.last_name,
            dob=_iso(p.dob), status=_status(p, club_id), at_club_id=p.at_club_id, contract_club_id=p.club_id,
            ca=p.ca, pa=p.pa, condition=p.fitness, sharpness=p.match_exercise, jadedness=p.jadedness,
            value=p.value, wage_per_week=p.contract.get("wage_per_week"),
            contract_start=_iso(p.contract.get("start")), contract_expires=_iso(p.contract.get("expires")),
            rep_home=p.reputation.get("home"), rep_current=p.reputation.get("current"),
            rep_world=p.reputation.get("world"), caps=p.caps, intl_goals=p.intl_goals,
            attributes=p.attributes, positions=p.positions,
            injuries=[dict(start=_iso(i["start"]), min_days=i.get("min_days"), max_days=i["max_days"]) for i in p.injuries],
        ) for p in players],
        fixtures=fixture_dicts,
        upcoming=upcoming_dicts,
        matches=match_dicts,
    )


def store_snapshot(con: sqlite3.Connection, snap: dict) -> tuple[int, int]:
    """Write a snapshot dict; returns (snapshot id, number of matches new to the database)."""
    cur = con.execute(
        "INSERT INTO snapshots (taken_at, game_date, club_id, build_id, n_players, n_fixtures) VALUES (?,?,?,?,?,?)",
        (snap["taken_at"], snap["game_date"], snap["club_id"], snap["build_id"],
         len(snap["players"]), len(snap["fixtures"])))
    sid = cur.lastrowid

    con.executemany("INSERT INTO clubs VALUES (?, ?) ON CONFLICT (club_id) DO UPDATE SET name = excluded.name",
                    [(int(k), v) for k, v in snap["clubs"].items()])
    for p in snap["players"]:
        con.execute("""INSERT INTO players VALUES (:unique_id, :name, :first_name, :last_name, :dob)
                       ON CONFLICT (unique_id) DO UPDATE SET name = excluded.name, first_name = excluded.first_name,
                       last_name = excluded.last_name, dob = excluded.dob""", p)
        con.execute("""INSERT INTO player_state (snapshot_id, unique_id, status, at_club_id, contract_club_id,
                       ca, pa, condition, sharpness, jadedness, value, wage_per_week, contract_start,
                       contract_expires, rep_home, rep_current, rep_world, caps, intl_goals, positions, injuries)
                       VALUES (:sid, :unique_id, :status, :at_club_id, :contract_club_id,
                       :ca, :pa, :condition, :sharpness, :jadedness, :value, :wage_per_week, :contract_start,
                       :contract_expires, :rep_home, :rep_current, :rep_world, :caps, :intl_goals, :positions, :injuries)""",
                    {**p, "sid": sid, "positions": json.dumps(p["positions"]) if p.get("positions") else None,
                     "injuries": json.dumps(p["injuries"]) if p.get("injuries") else None})
        con.executemany("INSERT INTO player_attributes VALUES (?, ?, ?, ?)",
                        [(sid, p["unique_id"], k, v) for k, v in p["attributes"].items()])

    for p in snap.get("other_people", []):
        con.execute("""INSERT INTO players (unique_id, name, first_name, last_name) VALUES
                       (:unique_id, :name, :first_name, :last_name) ON CONFLICT (unique_id) DO UPDATE SET
                       name = COALESCE(players.name, excluded.name)""", p)

    for f in snap["fixtures"]:
        upsert_fixture(con, f, sid)
    if "upcoming" in snap:
        # the schedule changes (rescheduled games): replace this club's stored unplayed fixtures
        con.execute("""DELETE FROM fixtures WHERE home_goals IS NULL AND date >= ? AND (home_id = ? OR away_id = ?)
                       AND id NOT IN (SELECT fixture_id FROM matches)""",
                    (snap["game_date"], snap["club_id"], snap["club_id"]))
        for f in snap["upcoming"]:
            upsert_fixture(con, f, sid)
    new = store_matches(con, snap, sid)
    con.execute("UPDATE snapshots SET n_new_matches = ? WHERE id = ?", (new, sid))
    con.commit()
    return sid, new


PMS_COLUMNS = ["fixture_id", "unique_id", "lineup_index", "rating", "minutes_on", "minutes_off", "goals", "assists",
               "xg", "xa", "passes_attempted", "passes_completed", "distance_m", "shirt_number", "raw", *COUNTERS]


def decode_counters(raw: bytes, offsets: dict) -> dict[str, int]:
    return {k: raw[o] for k, o in offsets.items() if not k.startswith("_") and o < len(raw)}


def store_matches(con: sqlite3.Connection, snap: dict, sid: int) -> int:
    """Store the snapshot's line-ups; returns how many matches are new to the database.

    Links are sticky: a line-up key already stored keeps its fixture, and a fixture that already
    has a (different) line-up is never overwritten. Line-ups are re-keyed by players + ratings so
    duplicate copies in memory count as the same match.
    """
    try:
        offsets = load_profile(snap["build_id"])["match_stats"].get("counters", {})
    except Exception:
        offsets = {}
    links = stored_links(con, snap["club_id"])
    taken = {v: k for k, v in links.items()}
    at_club = {p["unique_id"] for p in snap["players"] if p.get("status") != "loaned out"}
    new = 0
    for m in snap["matches"]:
        key = lineup_key((p["unique_id"], p["rating"]) for p in m["players"])
        ids = [p["unique_id"] for p in m["players"]]
        share = sum(u in at_club for u in ids) / len(ids) if ids else 0
        if key not in links and m["link_confidence"] == "goals" and share < 0.8:
            continue  # goals-only link for a line-up mostly not at the club: likely an old match
        target = links.get(key) or (m["fixture"]["date"], m["fixture"]["home_id"], m["fixture"]["away_id"])
        if taken.get(target, key) != key:
            continue  # that fixture already holds a different line-up: keep the earlier one
        row = con.execute("SELECT id FROM fixtures WHERE date = ? AND home_id = ? AND away_id = ?", target).fetchone()
        if not row:
            continue
        fid = row[0]
        if key not in links:
            new += 1
            con.execute("INSERT OR IGNORE INTO matches VALUES (?, ?, ?, ?, ?)",
                        (fid, snap["club_id"], key, m["link_confidence"], sid))
            links[key], taken[target] = target, key
        for pl in m["players"]:
            raw = base64.b64decode(pl["raw"])
            vals = {**pl, "fixture_id": fid, "raw": raw, **decode_counters(raw, offsets)}
            con.execute(f"INSERT OR REPLACE INTO player_match_stats ({', '.join(PMS_COLUMNS)}) "
                        f"VALUES ({', '.join(':' + c for c in PMS_COLUMNS)})",
                        {c: vals.get(c) for c in PMS_COLUMNS})
    return new


@dataclass
class CaptureResult:
    snapshot_id: int
    game_date: str | None
    players: int
    fixtures: int
    matches_in_memory: int
    new_matches: int
    seconds: float
    json_path: str
    save_id: int = 1
    new_save: bool = False            # this capture didn't match any known save: a separate history was started
    rewound_from: str | None = None   # game date went back (an older save file of this career was loaded)
    backup: str | None = None         # today's automatic backup, if this capture made it


def capture(club_id: int) -> CaptureResult:
    """Read the game, work out which save it is, and store into that save's database (+ daily backup)."""
    from store import backup, careers
    t0 = time.time()
    careers.activate()
    con = connect(app_config.DB_PATH)
    try:
        known = stored_links(con, club_id)
    finally:
        con.close()
    with GameProcess() as proc:
        snap = read_snapshot(proc, club_id, known)
    uids = {p["unique_id"] for p in snap["players"]}
    club = snap["clubs"].get(str(club_id))
    save_id, created = careers.resolve(uids, club_id, club, snap["game_date"])
    careers.activate(save_id)
    con = connect(app_config.DB_PATH)
    try:
        sid, new = store_snapshot(con, snap)
    finally:
        con.close()
    rewound = careers.record_capture(save_id, uids, club_id, club, snap["game_date"])
    app_config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = app_config.SNAPSHOT_DIR / f"{sid:05d}_{snap['game_date']}.json"
    path.write_text(json.dumps(snap), encoding="utf-8")
    b = backup.daily(app_config.DB_PATH, save_id)
    return CaptureResult(sid, snap["game_date"], len(snap["players"]), len(snap["fixtures"]),
                         len(snap["matches"]), new, round(time.time() - t0, 1), str(path),
                         save_id=save_id, new_save=created, rewound_from=rewound, backup=b.name if b else None)
