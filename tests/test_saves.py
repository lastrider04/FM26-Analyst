"""Save games kept apart (one database each, matched by club player IDs) and daily backups."""
import os
import time

import pytest

import app_config
from capture.snapshot import store_snapshot
from store import backup, careers
from store.db import connect
from tests.test_analytics import OUR, fixture, player, snap


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    monkeypatch.setattr(app_config, "DB_PATH", tmp_path / "fm_analyst.db")
    monkeypatch.setattr(app_config, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(app_config, "CONFIG_PATH", tmp_path / "config.json")
    con = connect(tmp_path / "fm_analyst.db")                      # an existing install: becomes save #1
    store_snapshot(con, snap("2031-12-01", [player(u, f"Old {u}", 150, {}) for u in range(1, 21)],
                             [fixture("2031-11-22", OUR, 1000, 1, 0)], []))
    con.close()
    return tmp_path


def test_existing_database_becomes_save_1(data):
    lst = careers.listing()
    assert lst["active"] == 1 and len(lst["careers"]) == 1
    s1 = lst["careers"][0]
    assert s1["db"] == "fm_analyst.db" and s1["first_game_date"] == "2031-12-01" and s1["club"] == "Northbridge"
    assert s1["name"] == "Northbridge 2031" and s1["captures"] == 1


def test_same_squad_matches_new_squad_starts_separate_save(data):
    same = set(range(3, 23))                                       # a couple of transfers in and out
    assert careers.resolve(same, OUR, "Northbridge", "2031-12-08") == (1, False)
    other = set(range(5000, 5025))                                 # a brand-new save: different newgens
    cid, created = careers.resolve(other, OUR, "Northbridge", "2025-07-01")
    assert (cid, created) == (2, True)
    careers.activate(cid)
    assert app_config.DB_PATH == data / "careers" / "2" / "fm_analyst.db"
    # store the new save's capture and check save #1 is untouched
    con = connect(app_config.DB_PATH)
    store_snapshot(con, snap("2025-07-01", [player(u, f"New {u}", 120, {}) for u in other], [], []))
    con.close()
    careers.record_capture(cid, other, OUR, "Northbridge", "2025-07-01")
    old = connect(data / "fm_analyst.db")
    assert old.execute("SELECT count(*) FROM snapshots").fetchone()[0] == 1
    assert old.execute("SELECT count(*) FROM players WHERE name LIKE 'New %'").fetchone()[0] == 0
    old.close()
    # the next capture of the new save matches save #2, not #1
    assert careers.resolve(other, OUR, "Northbridge", "2025-07-08") == (2, False)
    careers.activate(1)
    assert app_config.DB_PATH == data / "fm_analyst.db" and careers.listing()["active"] == 1


def test_older_save_file_of_same_career_is_flagged_not_split(data):
    uids = set(range(1, 21))
    assert careers.resolve(uids, OUR, "Northbridge", "2031-11-28") == (1, False)
    assert careers.record_capture(1, uids, OUR, "Northbridge", "2031-11-28") == "2031-12-01"
    info = careers.active_info()
    assert info["rewound"] == {"from": "2031-12-01", "to": "2031-11-28"} and info["last_game_date"] == "2031-11-28"
    assert careers.record_capture(1, uids, OUR, "Northbridge", "2031-11-29") is None     # moving forward again


def test_daily_backup_once_per_day_and_pruned(data):
    db = data / "fm_analyst.db"
    first = backup.daily(db, 1)
    assert first and first.exists() and backup.daily(db, 1) is None                  # once a day
    for i in range(backup.KEEP + 3):
        p = backup.backup(db, 1, tag=f"2031-01-{i:02d}")
        t = time.time() - 1000 + i
        os.utime(p, (t, t))
    st = backup.status(1)
    assert st["count"] == backup.KEEP
    # the restored copy is a working database
    con = connect(backup.backup_dir(1) / st["latest_file"])
    assert con.execute("SELECT count(*) FROM snapshots").fetchone()[0] == 1
    con.close()


def test_start_new_game_takes_next_capture_and_switch_follows_club(data):
    cid = careers.start_new("Real Madrid job", 1001, "Real Madrid")
    assert cid == 2 and careers.listing()["active"] == 2
    assert app_config.load_config()["club_id"] == 1001                    # captures now read the new club
    assert app_config.DB_PATH == data / "careers" / "2" / "fm_analyst.db"
    # even a squad that overlaps snapshot #1 goes into the freshly started one
    assert careers.resolve(set(range(1, 21)), 1001, "Real Madrid", "2031-12-20") == (2, False)
    careers.record_capture(2, set(range(900, 930)), 1001, "Real Madrid", "2031-12-20")
    careers.switch(1)
    assert app_config.load_config()["club_id"] == OUR and app_config.DB_PATH == data / "fm_analyst.db"
    careers.rename(2, "Madrid")
    assert {c["id"]: c["name"] for c in careers.listing()["careers"]} == {1: "Northbridge 2031", 2: "Madrid"}


def test_delete_only_inactive_snapshot(data):
    cid = careers.start_new("Throwaway", OUR, "Northbridge")
    con = connect(app_config.DB_PATH)
    store_snapshot(con, snap("2025-07-01", [player(9001, "Temp", 100, {})], [], []))
    con.close()
    with pytest.raises(careers.SnapshotError):
        careers.delete(cid)                                               # in use
    careers.switch(1)
    careers.delete(cid)
    assert [c["id"] for c in careers.listing()["careers"]] == [1]
    assert not (data / "careers" / str(cid) / "fm_analyst.db").exists()
    assert (data / "fm_analyst.db").exists()


def test_new_game_api_needs_confirmation(data):
    from fastapi.testclient import TestClient
    from web.app import app
    c = TestClient(app)
    assert c.post("/api/snapshots", json={"name": "X", "club_id": OUR}).status_code == 400
    r = c.post("/api/snapshots", json={"name": "New save", "club_id": OUR, "club": "Northbridge", "confirm": True}).json()
    assert r["started"] == 2 and r["active"] == 2
    assert any(f.name.endswith("_before-new-game.db") for f in backup.backup_dir(1).iterdir())   # old one backed up first
    assert c.delete("/api/snapshots/2").status_code == 400                                       # in use
    assert c.put("/api/snapshots/active", json={"id": 1}).json()["active"] == 1