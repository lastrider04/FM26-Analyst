"""Auto-capture trigger logic with a fake game clock (no game needed)."""
import datetime as dt

import pytest

import app_config
from capture.auto import AutoCapture
from capture.snapshot import store_snapshot
from store.db import connect
from tests.test_analytics import CHE, OUR, fixture, player, snap


@pytest.fixture
def auto(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "DB_PATH", tmp_path / "a.db")
    monkeypatch.setattr(app_config, "CONFIG_PATH", tmp_path / "config.json")
    con = connect(app_config.DB_PATH)
    upcoming = fixture("2031-12-02", OUR, CHE, None, None) | {"kickoff": "20:00"}
    store_snapshot(con, snap("2031-12-02", [player(1, "Alex Rivers", 150, {})], [upcoming], []))
    con.close()
    calls = []
    a = AutoCapture(run_capture=lambda: calls.append(1) or True, is_busy=lambda: False)
    a.calls = calls
    return a


def at(a, monkeypatch, when):
    monkeypatch.setattr(a, "_game_clock", lambda: dt.datetime.fromisoformat(when))
    a._tick()


def test_captures_once_after_match(auto, monkeypatch):
    at(auto, monkeypatch, "2031-12-02 09:00")
    assert auto.calls == [] and "22:30" in auto.next_trigger
    at(auto, monkeypatch, "2031-12-02 21:50")          # match still being played / post-match screens
    assert auto.calls == []
    at(auto, monkeypatch, "2031-12-03 09:00")          # pressed Continue: next day
    assert auto.calls == [1] and auto.last_reason.startswith("after Northbridge v Chelsea")
    at(auto, monkeypatch, "2031-12-03 12:00")          # fixture still unplayed in this fake DB: no loop
    assert auto.calls == [1]


def test_weekly_and_off(auto, monkeypatch):
    auto.enabled = False
    at(auto, monkeypatch, "2031-12-20 09:00")
    assert auto.calls == [] and auto.status == "off"
    auto.enabled = True
    at(auto, monkeypatch, "2031-12-20 09:00")
    assert auto.calls == [1]                            # the overdue match (or weekly) triggers


def test_waits_for_game(auto, monkeypatch):
    monkeypatch.setattr(auto, "_game_clock", lambda: None)
    auto._tick()
    assert auto.status == "waiting for the game" and auto.calls == []
