"""Recommended for next match: fitness exclusions and same-position swaps."""
from analytics.selection import recommend
from capture.snapshot import store_snapshot
from store.db import connect
from tests.test_analytics import CHE, OUR, PAL, fixture, line, player, snap

AML = {"AML": 20, "ML": 16}


def test_rest_tired_starter_and_swap_in_fresh_player(tmp_path):
    con = connect(tmp_path / "s.db")
    f1, f2 = fixture("2031-11-22", OUR, CHE, 6, 2), fixture("2031-11-29", PAL, OUR, 0, 2)
    m = lambda f, k: dict(fixture=dict(date=f["date"], home_id=f["home_id"], away_id=f["away_id"]), match_key=k,
                          link_confidence="high", players=[line(1, 0, 7.4), line(2, 1, 7.0)])
    store_snapshot(con, snap("2031-12-01", [
        player(1, "Alex Rivers", 158, {}, positions=AML, condition=80.0),                 # starter, tired
        player(2, "Jamie Cole", 170, {}, positions={"AMC": 20}, jadedness=250),             # starter, tiring
        player(3, "Sam Hollis", 120, {}, positions={"AML": 18}, condition=99.0),          # fresh back-up
        player(4, "Leo Marsh", 150, {}, positions={"AMC": 18, "AML": 15}, condition=99.0, jadedness=0,
               sharpness=100.0),
    ], [f1, f2], [m(f1, "m1"), m(f2, "m2")]))

    r = recommend(con, OUR)
    assert [p["name"] for p in r["rest"]] == ["Alex Rivers"]
    assert "Alex Rivers" not in [p["name"] for p in r["recommended"]]
    swaps = {w["out"]["name"]: (w["in"]["name"], w["must"]) for w in r["swaps"]}
    assert swaps["Alex Rivers"] == ("Sam Hollis", True)       # natural AML preferred over Marsh (accomplished)
    assert swaps["Jamie Cole"] == ("Leo Marsh", False)        # tiring starter, fresh same-position option
    con.close()


def test_injured_player_is_rested_alerted_and_counted_down(tmp_path):
    from analytics.players import all_players
    from analytics.squad import alerts
    con = connect(tmp_path / "i.db")
    f1, f2 = fixture("2031-11-22", OUR, CHE, 6, 2), fixture("2031-11-29", PAL, OUR, 0, 2)
    m = lambda f, k: dict(fixture=dict(date=f["date"], home_id=f["home_id"], away_id=f["away_id"]), match_key=k,
                          link_confidence="high", players=[line(1, 0, 7.4), line(2, 1, 7.0)])
    store_snapshot(con, snap("2031-12-15", [
        player(1, "Tom Hart", 170, {}, positions={"DL": 20},
               injuries=[{"start": "2031-12-06", "min_days": 7, "max_days": 12}]),
        player(2, "Dan Price", 180, {}, positions={"DC": 20}),
        player(3, "Ben Crane", 165, {}, positions={"DL": 18, "DC": 16}, condition=99.0),
    ], [f1, f2], [m(f1, "m1"), m(f2, "m2")]))
    hart = next(p for p in all_players(con, OUR)["players"] if p["unique_id"] == 1)
    assert hart["injury"] == {"since": "2031-12-06", "back_min": 0, "back_max": 3}     # 9 days in: 0-3 left
    assert [(a.kind, a.name) for a in alerts(con, OUR)] == [("injured", "Tom Hart")]
    r = recommend(con, OUR)
    assert "Tom Hart" not in [p["name"] for p in r["recommended"]]
    assert r["rest"][0]["unfit"] == ["injured, back in 0-3 days"]
    assert {(w["out"]["name"], w["in"]["name"]) for w in r["swaps"]} == {("Tom Hart", "Ben Crane")}
    con.close()


def test_no_squad(tmp_path):
    con = connect(tmp_path / "e.db")
    assert recommend(con, OUR) == {"recommended": [], "swaps": [], "rest": [], "basis": {}}
    con.close()
