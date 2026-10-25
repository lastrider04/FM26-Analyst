"""API tests against a synthetic database (no game needed)."""
import pytest
from fastapi.testclient import TestClient

import app_config
from capture.snapshot import store_snapshot
from store.db import connect
from tests.test_analytics import CHE, OUR, PAL, fixture, line, player, snap


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "DB_PATH", tmp_path / "w.db")
    monkeypatch.setattr(app_config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    con = connect(app_config.DB_PATH)
    f1, f2 = fixture("2031-11-22", OUR, CHE, 6, 2), fixture("2031-11-29", PAL, OUR, 0, 2)
    m = lambda f, k, pls: dict(fixture=dict(date=f["date"], home_id=f["home_id"], away_id=f["away_id"]),
                               match_key=k, link_confidence="goals", players=pls)
    store_snapshot(con, snap("2031-11-01", [player(1, "Alex Rivers", 150, {"dribbling": 80})], [f1],
                             [m(f1, "a", [line(1, 0, 7.0, goals=1)])]))
    store_snapshot(con, snap("2031-12-01", [player(1, "Alex Rivers", 158, {"dribbling": 85})], [f1, f2],
                             [m(f1, "a", [line(1, 0, 7.0, goals=1)]), m(f2, "b", [line(1, 0, 8.0)])]))
    con.close()
    from web.app import app
    return TestClient(app)




def test_overview(client):
    o = client.get("/api/overview").json()
    assert o["last_match"]["summary"]["opponent"] == "Crystal Palace"
    assert o["team_form"]["string"] == "WW"


def test_squad_and_player(client):
    s = client.get("/api/squad").json()
    assert s["players"][0]["name"] == "Alex Rivers" and s["players"][0]["form"] == [7.0, 8.0]
    p = client.get("/api/player/1").json()
    assert [h["ca"] for h in p["history"]] == [150, 158]
    assert p["attributes"]["technical"]["dribbling"] == 85
    assert client.get("/api/player/999").status_code == 404


def test_development_and_fixtures(client):
    d = client.get("/api/development").json()
    assert d["pair"]["days"] == 30 and d["improvers"][0]["ca_delta"] == 8
    f = client.get("/api/fixtures").json()["fixtures"]
    assert [x["result"] for x in f] == ["W", "W"] and f[0]["venue"] == "A"


def test_settings_hide_api_key(client):
    r = client.put("/api/settings", json={"llm_api_key": "sk-test-1234567890", "llm_model": "gpt-x"}).json()
    assert r["llm_api_key_set"] and "sk-test" not in str(r) and r["llm_model"] == "gpt-x"
    assert client.put("/api/settings", json={"hotkey": "hyper+q"}).status_code == 400


def test_match_view(client):
    fx = client.get("/api/fixtures").json()["fixtures"]
    latest = client.get(f"/api/match/{fx[0]['id']}").json()
    assert latest["summary"]["opponent"] == "Crystal Palace" and latest["summary"]["has_stats"]
    assert latest["previous"] == fx[1]["id"] and latest["next"] is None
    assert client.get("/api/match/9999").status_code == 404


def test_players_similar_compare(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "DB_PATH", tmp_path / "s.db")
    monkeypatch.setattr(app_config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    con = connect(app_config.DB_PATH)
    pos = lambda **kw: {p: kw.get(p, 1) for p in ["GK", "SW", "DL", "DC", "DR", "DM", "ML", "MC", "MR",
                                                   "AML", "AMC", "AMR", "ST", "WBL", "WBR"]}
    players = [
        player(1, "Alex Rivers", 158, {"dribbling": 84, "pace": 80}, positions=pos(AML=20, AMR=18)),
        player(2, "Kai Moran", 173, {"dribbling": 88, "pace": 75}, positions=pos(AMR=20, AML=16)),
        player(3, "Dan Price", 190, {"dribbling": 60, "pace": 85}, positions=pos(DC=20)),
        player(4, "Kid Keeper", 60, {"dribbling": 20, "pace": 40}, positions=pos(GK=20), status="youth team",
               at_club_id=2000778723, contract_club_id=OUR),
        player(5, "Loan Guy", 120, {"dribbling": 70, "pace": 70}, positions=pos(ST=20), status="loaned out",
               at_club_id=CHE),
    ]
    store_snapshot(con, snap("2031-12-01", players, [], []))
    con.close()
    from web.app import app
    c = TestClient(app)
    allp = {p["name"]: p for p in c.get("/api/players").json()["players"]}
    assert len(allp) == 5
    # a one-player own team is too small to rank as an age group
    assert allp["Kid Keeper"]["where"] == "Northbridge (other squad)" and allp["Loan Guy"]["where"] == "Chelsea"
    assert allp["Alex Rivers"]["position"] == "AM L, AM R"
    sim = c.get("/api/similar/1").json()["similar"]
    assert sim[0]["name"] == "Kai Moran" and sim[0]["position_match"] > 90
    cmp = c.get("/api/compare?a=1&b=2").json()
    assert [p["name"] for p in cmp["players"]] == ["Alex Rivers", "Kai Moran"]
    assert c.get("/api/compare?a=1&b=999").status_code == 404


def test_index_served(client):
    assert "FM26 Analyst" in client.get("/").text


def test_first_run_asks_for_a_club(client, monkeypatch):
    monkeypatch.setitem(app_config.DEFAULTS, "club_id", None)
    from web import app as web
    assert client.get("/api/status").json()["needs_club"] is True
    assert web.CAPTURE.run() is False and "Choose the club" in web.CAPTURE.last["error"]
    assert web._auto_paused() == "waiting for you to choose your club"
    monkeypatch.setattr(web.HEALTH, "maybe_check", lambda force=False: None)
    client.put("/api/settings", json={"club_id": 1001})
    assert client.get("/api/status").json()["needs_club"] is False
