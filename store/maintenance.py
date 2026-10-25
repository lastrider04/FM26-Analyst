"""One-off data fixes.

    python -m store.maintenance unlink 2031-11-01 [--club <id>]   remove a wrongly linked match (stats + link)
    python -m store.maintenance rebuild-matches                  re-derive all match stats from data/snapshots/*.json
"""
from __future__ import annotations

import argparse
import json

import app_config
from app_config import load_config
from store.careers import activate
from store.db import connect


def rebuild_matches(con) -> list[tuple[int, int]]:
    """Wipe stored matches and replay every saved snapshot in order with the current storage rules
    (sticky links, duplicate-copy keys, counter decoding). Returns (snapshot id, new matches)."""
    from capture.snapshot import store_matches
    con.execute("DELETE FROM player_match_stats")
    con.execute("DELETE FROM matches")
    out = []
    for path in sorted(app_config.SNAPSHOT_DIR.glob("*.json")):
        sid = int(path.name.split("_")[0])
        snap = json.loads(path.read_text(encoding="utf-8"))
        new = store_matches(con, snap, sid)
        con.execute("UPDATE snapshots SET n_new_matches = ? WHERE id = ?", (new, sid))
        out.append((sid, new))
    con.commit()
    return out


def unlink(con, club_id: int, date: str) -> int:
    ids = [r[0] for r in con.execute("""SELECT m.fixture_id FROM matches m JOIN fixtures f ON f.id = m.fixture_id
                                        WHERE m.club_id = ? AND f.date = ?""", (club_id, date))]
    for fid in ids:
        con.execute("DELETE FROM player_match_stats WHERE fixture_id = ?", (fid,))
        con.execute("DELETE FROM matches WHERE fixture_id = ?", (fid,))
    con.commit()
    return len(ids)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("unlink")
    u.add_argument("date")
    u.add_argument("--club", type=int)
    sub.add_parser("rebuild-matches")
    args = ap.parse_args()
    activate()
    con = connect(app_config.DB_PATH)
    if args.cmd == "unlink":
        n = unlink(con, args.club or load_config()["club_id"], args.date)
        print(f"unlinked {n} match(es) on {args.date}")
    elif args.cmd == "rebuild-matches":
        for sid, new in rebuild_matches(con):
            print(f"  snapshot #{sid}: {new} new match(es)")
        for r in con.execute("""SELECT f.date, f.competition, m.link_confidence, count(s.unique_id)
                                FROM matches m JOIN fixtures f ON f.id = m.fixture_id
                                LEFT JOIN player_match_stats s ON s.fixture_id = f.id
                                GROUP BY f.id ORDER BY f.date"""):
            print("   ", tuple(r))


if __name__ == "__main__":
    main()
