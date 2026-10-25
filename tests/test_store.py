"""Storage tests with synthetic snapshots (no game needed)."""
import base64
import copy

import pytest

from capture.hotkey import parse
from capture.snapshot import store_snapshot
from store.db import connect

RAW = base64.b64encode(bytes(0x110)).decode()


def snapshot(game_date="2031-11-29", ca=158, with_match=True):
    snap = dict(
        format=1, taken_at="2026-10-24T12:00:00+00:00", game_date=game_date, club_id=1001, build_id="test",
        clubs={"1001": "Northbridge", "642": "Crystal Palace"},
        players=[dict(unique_id=2000000001, name="Alex Rivers", first_name="Alex", last_name="Rivers",
                      dob="2008-08-29", status="first team", at_club_id=1001, contract_club_id=1001,
                      ca=ca, pa=166, condition=94.24, sharpness=59.59, jadedness=-354, value=69668000,
                      wage_per_week=100000, contract_start="2028-07-01", contract_expires="2033-06-30",
                      rep_home=8000, rep_current=8086, rep_world=7000, caps=0, intl_goals=0,
                      attributes={"crossing": 75, "dribbling": 84})],
        fixtures=[dict(date="2031-11-29", home_id=642, away_id=1001, home="Crystal Palace", away="Northbridge",
                       home_goals=0, away_goals=2, home_pens=None, away_pens=None, neutral=0,
                       competition_index=232, competition="Premier League")],
        matches=[],
    )
    if with_match:
        snap["matches"] = [dict(
            fixture=dict(date="2031-11-29", home_id=642, away_id=1001), match_key="abc", link_confidence="high",
            players=[dict(unique_id=2000000001, lineup_index=10, rating=7.31, minutes_on=0, minutes_off=0,
                          goals=1, assists=0, xg=0.11, xa=0.14, passes_attempted=53, passes_completed=45,
                          distance_m=13557.8, shirt_number=10, raw=RAW)])]
    return snap


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


def test_store_and_read_back(con):
    sid, new = store_snapshot(con, snapshot())
    assert (sid, new) == (1, 1)
    row = con.execute("SELECT ca, condition, status FROM player_state WHERE snapshot_id = 1").fetchone()
    assert tuple(row) == (158, 94.24, "first team")
    assert con.execute("SELECT raw FROM player_attributes WHERE attr = 'dribbling'").fetchone()[0] == 84
    pms = con.execute("SELECT rating, goals, length(raw) FROM player_match_stats").fetchone()
    assert tuple(pms) == (7.31, 1, 0x110)


def test_matches_and_fixtures_are_not_duplicated(con):
    store_snapshot(con, snapshot())
    sid2, new2 = store_snapshot(con, snapshot(game_date="2031-12-01"))
    assert new2 == 0
    assert con.execute("SELECT count(*) FROM fixtures").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM player_match_stats").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM snapshots").fetchone()[0] == 2


def test_development_between_snapshots(con):
    store_snapshot(con, snapshot(ca=158))
    store_snapshot(con, snapshot(game_date="2032-01-15", ca=161, with_match=False))
    rows = con.execute("SELECT ca FROM player_state WHERE unique_id = 2000000001 ORDER BY snapshot_id").fetchall()
    assert [r[0] for r in rows] == [158, 161]


def test_fixture_score_update(con):
    s = snapshot(with_match=False)
    s["fixtures"][0].update(home_goals=None, away_goals=None)
    store_snapshot(con, s)
    store_snapshot(con, snapshot(with_match=False))
    assert tuple(con.execute("SELECT home_goals, away_goals FROM fixtures").fetchone()) == (0, 2)


def test_duplicate_lineup_never_overwrites_another_fixture(con):
    """A second copy of a stored line-up, linked to a different fixture, must be ignored."""
    store_snapshot(con, snapshot())
    s = snapshot(game_date="2031-12-02")
    s["fixtures"].append(dict(date="2031-11-25", home_id=915, away_id=1001, home="Bayern", away="Northbridge",
                              home_goals=2, away_goals=2, home_pens=None, away_pens=None, neutral=0,
                              competition_index=3072, competition="UCL"))
    dup = copy.deepcopy(s["matches"][0])
    dup["fixture"] = dict(date="2031-11-25", home_id=915, away_id=1001)  # same players + ratings, wrong fixture
    dup["link_confidence"] = "goals"
    s["matches"].append(dup)
    _, new = store_snapshot(con, s)
    assert new == 0
    rows = con.execute("SELECT f.date FROM player_match_stats p JOIN fixtures f ON f.id = p.fixture_id").fetchall()
    assert [r[0] for r in rows] == ["2031-11-29"]


def test_counters_decoded_from_raw(con):
    s = snapshot()
    raw = bytearray(0x110)
    raw[0xBC], raw[0xC7], raw[0x90], raw[0x91] = 4, 3, 2, 2   # key passes, interceptions, shots, on target
    s["matches"][0]["players"][0]["raw"] = base64.b64encode(bytes(raw)).decode()
    s["build_id"] = "ec2a94dbd9c4"  # the profile that carries the counter offsets
    store_snapshot(con, s)
    row = con.execute("SELECT key_passes, interceptions, shots, shots_on_target FROM player_match_stats").fetchone()
    assert tuple(row) == (4, 3, 2, 2)


def test_hotkey_parse():
    mods, vk = parse("ctrl+alt+s")
    assert vk == ord("S") and mods & 0x3 == 0x3
    assert parse("ctrl+shift+f9")[1] == 0x78
    with pytest.raises(ValueError):
        parse("hyper+s")
