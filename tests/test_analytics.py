"""Analytics tests on a synthetic database (no game needed)."""
import base64
import copy

import pytest

from analytics.development import development, leaderboard, snapshot_pair
from analytics.form import player_form, team_form
from analytics.metrics import aggregate, last_match, match_lines, minutes_played
from analytics.squad import alerts
from capture.snapshot import store_snapshot
from store.db import connect

RAW = base64.b64encode(bytes(0x110)).decode()
OUR, PAL, CHE = 1001, 642, 1000


def player(uid, name, ca, attrs, **kw):
    p = dict(unique_id=uid, name=name, first_name=name.split()[0], last_name=name.split()[-1], dob="2008-08-29",
             status="first team", at_club_id=OUR, contract_club_id=OUR, ca=ca, pa=180, condition=95.0,
             sharpness=90.0, jadedness=0, value=1, wage_per_week=1, contract_start="2030-07-01",
             contract_expires="2035-06-30", rep_home=1, rep_current=1, rep_world=1, caps=0, intl_goals=0,
             attributes=attrs)
    p.update(kw)
    return p


def line(uid, idx, rating, goals=0, xg=0.0, on=0, off=0):
    return dict(unique_id=uid, lineup_index=idx, rating=rating, minutes_on=on, minutes_off=off, goals=goals,
                assists=0, xg=xg, xa=0.0, passes_attempted=40, passes_completed=36, distance_m=10000.0,
                shirt_number=idx + 1, raw=RAW)


def snap(game_date, players, fixtures, matches):
    return dict(format=1, taken_at="2026-10-24T12:00:00+00:00", game_date=game_date, club_id=OUR, build_id="t",
                clubs={str(OUR): "Northbridge", str(PAL): "Crystal Palace", str(CHE): "Chelsea"},
                players=players, fixtures=fixtures, matches=matches)


def fixture(date, home, away, hg, ag, comp="Premier League"):
    return dict(date=date, home_id=home, away_id=away, home=str(home), away=str(away), home_goals=hg,
                away_goals=ag, home_pens=None, away_pens=None, neutral=0, competition_index=232, competition=comp)


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "a.db")
    f1 = fixture("2031-11-22", OUR, CHE, 6, 2)
    f2 = fixture("2031-11-29", PAL, OUR, 0, 2)
    m1 = dict(fixture=dict(date=f1["date"], home_id=OUR, away_id=CHE), match_key="m1", link_confidence="goals",
              players=[line(1, 0, 7.0, goals=2, xg=1.0), line(2, 11, 6.5, on=60)])
    m2 = dict(fixture=dict(date=f2["date"], home_id=PAL, away_id=OUR), match_key="m2", link_confidence="high",
              players=[line(1, 0, 8.0, xg=0.5, off=70), line(2, 1, 7.2)])
    store_snapshot(c, snap("2031-11-01", [player(1, "Alex Rivers", 150, {"dribbling": 80, "pace": 70}),
                                          player(2, "Jamie Cole", 180, {"dribbling": 60, "pace": 90},
                                                 condition=70.0)],
                           [f1], [m1]))
    store_snapshot(c, snap("2031-12-01", [player(1, "Alex Rivers", 158, {"dribbling": 84, "pace": 72}),
                                          player(2, "Jamie Cole", 178, {"dribbling": 59, "pace": 90},
                                                 condition=70.0, contract_expires="2032-06-30")],
                           [f1, f2], [m1, m2]))
    yield c
    c.close()


def test_minutes():
    assert minutes_played(0, 0, 0) == 90
    assert minutes_played(0, 0, 70) == 70
    assert minutes_played(11, 60, 0) == 30


def test_aggregates_and_per90(con):
    aggs = aggregate(match_lines(con, OUR))
    rio = aggs[1]
    assert (rio.apps, rio.minutes, rio.goals, rio.avg_rating) == (2, 160, 2, 7.5)
    assert rio.per90s()["goals"] == round(2 * 90 / 160, 2)
    assert rio.goals_minus_xg == 0.5


def test_last_match(con):
    summary, lines = last_match(con, OUR)
    assert summary["opponent"] == "Crystal Palace" and summary["venue"] == "A" and summary["score"] == "2-0"
    assert lines[0].name == "Alex Rivers"


def test_development(con):
    pair = snapshot_pair(con, OUR)
    devs = {d.unique_id: d for d in development(con, *pair)}
    rio, aj = devs[1], devs[2]
    assert (rio.ca_delta, rio.days, rio.headroom) == (8, 30, 22)
    assert {c.attr: c.raw_delta for c in rio.moved} == {"dribbling": 4, "pace": 2}
    assert rio.group_delta("technical") == 4
    up, down = leaderboard(list(devs.values()))
    assert [d.unique_id for d in up] == [1] and [d.unique_id for d in down] == [2]


def test_form(con):
    tf = team_form(con, OUR)
    assert tf.string == "WW" and tf.points == 6 and tf.goals_for == 8
    pf = {f.unique_id: f for f in player_form(match_lines(con, OUR))}
    assert pf[1].ratings == [7.0, 8.0] and pf[1].trend == 1.0


def test_alerts(con):
    kinds = {(a.kind, a.unique_id) for a in alerts(con, OUR)}
    assert ("low condition", 2) in kinds and ("contract expiring", 2) in kinds
    assert not any(uid == 1 for _, uid in kinds)
