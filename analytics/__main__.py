"""Text report from the stored data (no game needed).

    python -m analytics                 full report
    python -m analytics --days 30       development over the last 30 game days
"""
from __future__ import annotations

import argparse

from analytics.development import GROUPS, development, leaderboard, snapshot_pair
from analytics.form import player_form, team_form
from analytics.metrics import PER90_MIN_MINUTES, aggregate, last_match, match_lines
from analytics.squad import alerts, latest_snapshot
import app_config
from app_config import load_config
from store.careers import activate
from store.db import connect


def section(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 70 - len(title)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--club", type=int)
    ap.add_argument("--days", type=int, help="development window in game days (default: all snapshots)")
    args = ap.parse_args()
    club = args.club or load_config()["club_id"]
    activate()
    con = connect(app_config.DB_PATH)
    snap = latest_snapshot(con, club)
    if not snap:
        print("no snapshots yet - run: python -m capture")
        return
    print(f"latest snapshot #{snap['id']} at game date {snap['game_date']}")

    summary, lines = last_match(con, club)
    section("Last match")
    if summary:
        print(f"{summary['date']} {summary['venue']} vs {summary['opponent']} {summary['score']} ({summary['result']}) "
              f"- {summary['competition']} | team xG {summary['xg']} | avg rating {summary['avg_rating']}")
        print(f"  {'player':<24}{'min':>4}{'rat':>6}{'G':>3}{'A':>3}{'xG':>6}{'xA':>6}{'pass%':>7}{'km':>6}")
        for l in lines:
            pp = f"{l.pass_pct:.0f}" if l.pass_pct is not None else "-"
            print(f"  {l.name:<24}{l.minutes:>4}{l.rating:>6.2f}{l.goals:>3}{l.assists:>3}"
                  f"{l.xg:>6.2f}{l.xa:>6.2f}{pp:>7}{l.distance_km:>6.1f}")
    else:
        print("no match stats stored yet")

    section("Team form (last 10 competitive)")
    tf = team_form(con, club)
    print(f"{tf.string}  {tf.points} pts, goals {tf.goals_for}-{tf.goals_against}, unbeaten run {tf.unbeaten_run}")
    for r in tf.results[-5:]:
        print(f"  {r['date']} {r['venue']} {r['opponent']:<22} {r['gf']}-{r['ga']} {r['result']}  {r['competition']}")

    all_lines = match_lines(con, club)
    section(f"Player form (last 5 stored matches)")
    for f in player_form(all_lines)[:12]:
        rs = " ".join(f"{r:.1f}" for r in f.ratings)
        print(f"  {f.name:<24} avg {f.avg:.2f} ({f.vs_season:+.2f} vs season) trend {f.trend:+.2f}  [{rs}]  {f.label}")

    section(f"Per 90 (stored matches, min {PER90_MIN_MINUTES} minutes)")
    aggs = [a for a in aggregate(all_lines).values() if a.per90_reliable]
    print(f"  {'player':<24}{'apps':>5}{'min':>6}{'rat':>6}{'G+A/90':>8}{'xG+xA/90':>10}{'G-xG':>7}{'pass%':>7}{'km/90':>7}")
    for a in sorted(aggs, key=lambda a: -(a.per90s()["xg_plus_xa"] or 0))[:12]:
        p = a.per90s()
        print(f"  {a.name:<24}{a.apps:>5}{a.minutes:>6}{a.avg_rating:>6.2f}{p['goal_involvements']:>8.2f}"
              f"{p['xg_plus_xa']:>10.2f}{a.goals_minus_xg:>+7.2f}{a.pass_pct or 0:>7.1f}{p['distance_km']:>7.1f}")

    section("Development")
    pair = snapshot_pair(con, club, args.days)
    if not pair:
        print("needs at least two snapshots")
    else:
        devs = development(con, *pair)
        days = devs[0].days if devs else 0
        print(f"snapshot #{pair[0]} -> #{pair[1]} ({days} game days)")
        if days == 0:
            print("  both snapshots are from the same game date - capture again after some game time")
        up, down = leaderboard(devs, statuses=("first team", "loaned in", "youth team"))
        for title, rows in (("improving", up), ("declining", down)):
            print(f"  {title}:")
            for d in rows:
                moved = ", ".join(f"{c.attr} {c.shown_before}->{c.shown_after}" if c.shown_delta
                                  else f"{c.attr} {c.raw_delta:+d}raw" for c in d.moved[:5])
                groups = " ".join(f"{g[:4]} {d.group_delta(g):+d}" for g in GROUPS if d.group_delta(g))
                print(f"    {d.name:<24} CA {d.ca_before}->{d.ca_after} (PA {d.pa}, age {d.age})  {groups}  | {moved}")
            if not rows:
                print("    none")

    section("Alerts")
    for a in alerts(con, club):
        print(f"  {a.kind:<18} {a.name:<24} {a.detail}")


if __name__ == "__main__":
    main()
