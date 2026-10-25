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


class _Game:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _health_with(monkeypatch, results):
    """A HealthState whose checks return the given statuses in turn (no live game)."""
    import reader.process
    from web import app as web
    seq = iter(results)
    monkeypatch.setattr(reader.process, "GameProcess", _Game)
    monkeypatch.setattr(sc, "self_check", lambda p, club: {"status": next(seq), "checks": [
        {"name": "squad readable", "ok": False, "detail": "0 players"}]})
    h = web.HealthState()

    def run(final=False):
        h.lock.acquire()
        h._run(final)
    return h, run


def test_failed_check_while_loading_retries_quietly(monkeypatch):
    h, run = _health_with(monkeypatch, ["failed", "failed", "ok"])
    run()
    assert h.loading() and not h.bad()                   # no banner yet: probably still loading the save
    run()
    assert h.loading()
    run()
    assert h.result["status"] == "ok" and h.fails == 0


def test_check_that_keeps_failing_is_reported(monkeypatch):
    h, run = _health_with(monkeypatch, ["failed"] * 4)
    for _ in range(3):
        run()
    assert h.loading()                                   # 3 failures but within REPORT_AFTER seconds
    h.first_fail -= h.REPORT_AFTER
    run()
    assert h.bad()


def test_check_again_gives_a_final_verdict(monkeypatch):
    h, run = _health_with(monkeypatch, ["failed"])
    run(final=True)
    assert h.bad()


def test_loading_holds_captures(monkeypatch):
    from web import app as web
    monkeypatch.setattr(web.HEALTH, "maybe_check", lambda force=False: None)
    monkeypatch.setattr(web.HEALTH, "result", {"status": "loading", "checks": []})
    assert web.CAPTURE.run() is False and "still loading" in web.CAPTURE.last["error"]
    assert web._auto_paused() == "waiting for FM26 to finish loading your save"
