"""SQLite storage for snapshots, players, fixtures and per-player match stats.

Design:
- a snapshot is one capture: player state + attributes as they were at that game date;
- fixtures and player match stats are facts that don't change, so they're upserted
  (each match is stored once, however many snapshots saw it);
- attributes are stored long-format (one row per attribute) so changes are easy to query.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 5

COUNTERS = ["shots", "shots_on_target", "shots_woodwork", "saves_held", "saves_parried", "dribbles", "fouls_made",
            "fouls_against", "crosses_attempted", "crosses_completed", "key_passes", "tackles_attempted",
            "tackles_won", "headers_attempted", "headers_won", "interceptions", "throw_ins", "corners",
            "defending_free_kicks", "attacking_free_kicks", "clearances", "shots_faced", "progressive_passes",
            "clear_cut_chances", "key_tackles", "saves_tipped"]

# columns added after v1: (table, column, type). Applied to existing databases on connect.
ADDED_COLUMNS = [
    ("player_state", "positions", "TEXT"),   # JSON {"GK": 1, ..., "ST": 20}
    ("fixtures", "kickoff", "TEXT"),         # "HH:MM"
    ("player_state", "injuries", "TEXT"),    # JSON [{"start": "YYYY-MM-DD", "min_days": n, "max_days": n}]
    *[("player_match_stats", c, "INTEGER") for c in COUNTERS],
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at TEXT NOT NULL,          -- real-world UTC time
    game_date TEXT,                  -- in-game date
    club_id INTEGER NOT NULL,
    build_id TEXT NOT NULL,
    n_players INTEGER, n_fixtures INTEGER, n_new_matches INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS players (
    unique_id INTEGER PRIMARY KEY,
    name TEXT, first_name TEXT, last_name TEXT, dob TEXT
);

CREATE TABLE IF NOT EXISTS player_state (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    unique_id INTEGER NOT NULL REFERENCES players(unique_id),
    status TEXT,                     -- first team / youth team / loaned in / loaned out / no contract
    at_club_id INTEGER, contract_club_id INTEGER,
    ca INTEGER, pa INTEGER,
    condition REAL,                  -- FM condition %, 0-100
    sharpness REAL,                  -- FM match sharpness %, 0-100
    jadedness INTEGER, value INTEGER, wage_per_week INTEGER,
    contract_start TEXT, contract_expires TEXT,
    rep_home INTEGER, rep_current INTEGER, rep_world INTEGER,
    caps INTEGER, intl_goals INTEGER,
    PRIMARY KEY (snapshot_id, unique_id)
);

CREATE TABLE IF NOT EXISTS player_attributes (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    unique_id INTEGER NOT NULL,
    attr TEXT NOT NULL,
    raw INTEGER NOT NULL,            -- 1-100; display value = round(raw / 5)
    PRIMARY KEY (snapshot_id, unique_id, attr)
);

CREATE TABLE IF NOT EXISTS clubs (club_id INTEGER PRIMARY KEY, name TEXT);

CREATE TABLE IF NOT EXISTS fixtures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    home_id INTEGER NOT NULL, away_id INTEGER NOT NULL,
    home_goals INTEGER, away_goals INTEGER, home_pens INTEGER, away_pens INTEGER,
    neutral INTEGER NOT NULL DEFAULT 0,
    competition_index INTEGER, competition TEXT,
    first_seen_snapshot INTEGER REFERENCES snapshots(id),
    UNIQUE (date, home_id, away_id)
);

CREATE TABLE IF NOT EXISTS matches (
    fixture_id INTEGER PRIMARY KEY REFERENCES fixtures(id),
    club_id INTEGER NOT NULL,        -- the club whose line-up we have
    match_key TEXT NOT NULL,         -- content hash from the reader
    link_confidence TEXT,
    first_seen_snapshot INTEGER REFERENCES snapshots(id)
);

CREATE TABLE IF NOT EXISTS player_match_stats (
    fixture_id INTEGER NOT NULL REFERENCES fixtures(id),
    unique_id INTEGER NOT NULL,
    lineup_index INTEGER,            -- 0 = first starter; 11+ = substitutes
    rating REAL, minutes_on INTEGER, minutes_off INTEGER,
    goals INTEGER, assists INTEGER, xg REAL, xa REAL,
    passes_attempted INTEGER, passes_completed INTEGER,
    distance_m REAL, shirt_number INTEGER,
    raw BLOB,                        -- full 0x110-byte record for later decoding
    PRIMARY KEY (fixture_id, unique_id)
);

CREATE INDEX IF NOT EXISTS idx_state_player ON player_state(unique_id);
CREATE INDEX IF NOT EXISTS idx_attr_player ON player_attributes(unique_id, attr);
CREATE INDEX IF NOT EXISTS idx_pms_player ON player_match_stats(unique_id);
CREATE INDEX IF NOT EXISTS idx_fixtures_date ON fixtures(date);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    for table, column, ctype in ADDED_COLUMNS:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ctype}")
    con.execute("INSERT INTO meta VALUES ('schema_version', ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),))
    con.commit()
    return con


def lineup_key(players) -> str:
    """Stable identity of a match line-up: who played and their ratings.

    FM can hold several slightly different copies of one line-up; they agree on these, so they
    collapse to one key (the reader's content hash also covers other bytes and can differ).
    """
    import hashlib
    sig = sorted((int(uid), round(float(r), 2)) for uid, r in players)
    return hashlib.sha1(repr(sig).encode()).hexdigest()[:16]


def stored_links(con: sqlite3.Connection, club_id: int) -> dict[str, tuple[str, int, int]]:
    """match_key -> (date, home_id, away_id) for every stored match."""
    return {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        """SELECT m.match_key, f.date, f.home_id, f.away_id FROM matches m JOIN fixtures f ON f.id = m.fixture_id
           WHERE m.club_id = ?""", (club_id,))}


def upsert_fixture(con: sqlite3.Connection, f: dict, snapshot_id: int) -> int:
    """Insert or update a fixture (scores can change from blank to final); returns its id."""
    con.execute(
        """INSERT INTO fixtures (date, home_id, away_id, home_goals, away_goals, home_pens, away_pens,
                                 neutral, competition_index, competition, first_seen_snapshot, kickoff)
           VALUES (:date, :home_id, :away_id, :home_goals, :away_goals, :home_pens, :away_pens,
                   :neutral, :competition_index, :competition, :snapshot_id, :kickoff)
           ON CONFLICT (date, home_id, away_id) DO UPDATE SET
               home_goals = COALESCE(excluded.home_goals, fixtures.home_goals),
               away_goals = COALESCE(excluded.away_goals, fixtures.away_goals),
               home_pens = excluded.home_pens, away_pens = excluded.away_pens,
               neutral = excluded.neutral, competition_index = excluded.competition_index,
               competition = excluded.competition, kickoff = COALESCE(excluded.kickoff, fixtures.kickoff)""",
        {"kickoff": None, **f, "snapshot_id": snapshot_id})
    return con.execute("SELECT id FROM fixtures WHERE date = ? AND home_id = ? AND away_id = ?",
                       (f["date"], f["home_id"], f["away_id"])).fetchone()[0]
