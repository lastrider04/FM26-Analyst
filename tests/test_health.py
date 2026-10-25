"""Reader self-check: unknown builds and failed checks pause captures."""
import reader.selfcheck as sc
from capture.auto import AutoCapture
from reader.profile import UnknownBuild


class FakeProc:
    def build_id(self):
        return "deadbeef0000"


def test_unknown_build_is_reported(monkeypatch):
    def boom(build):
        raise UnknownBuild(f"no offset profile for build {build}")
    monkeypatch.setattr(sc, "load_profile", boom)
    r = sc.self_check(FakeProc(), 1001)
    assert r["status"] == "unknown_build" and r["build_id"] == "deadbeef0000"
    assert r["checks"][0] == {"name": "game build recognised", "ok": False, "detail": "no offset profile for build deadbeef0000"}


def test_auto_capture_holds_off_before_reading_the_game(monkeypatch):
    calls = []
    a = AutoCapture(run_capture=lambda: calls.append(1) or True, is_busy=lambda: False,
                    paused=lambda: "paused: reader self-check failed for this game build")
    monkeypatch.setattr(a, "_game_clock", lambda: (_ for _ in ()).throw(AssertionError("game read while paused")))
    a._tick()
    assert a.status.startswith("paused") and calls == []


def test_failed_health_blocks_manual_capture(monkeypatch):
    from web import app as web
    monkeypatch.setattr(web.HEALTH, "maybe_check", lambda force=False: None)     # never touch a live game in tests
    monkeypatch.setattr(web.HEALTH, "result", {"status": "unknown_build", "checks": []})
    assert web.CAPTURE.run() is False
    assert "paused" in web.CAPTURE.last["error"]
    assert web._auto_paused().startswith("paused")
    monkeypatch.setattr(web.HEALTH, "result", {"status": "ok", "checks": []})
    assert not web.HEALTH.bad() and web._auto_paused() is None
