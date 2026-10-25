"""FastAPI backend for the dashboard: JSON over the analytics layer, plus capture and settings."""
from __future__ import annotations

import dataclasses
import threading
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import app_config
from analytics.development import GROUPS, GROUP_OF, development, leaderboard, snapshot_pair
from analytics.form import in_form, player_form, team_form
from analytics.selection import recommend
from analytics.metrics import PER90_MIN_MINUTES, aggregate, last_match, match_detail, match_lines, neighbours
from analytics.players import all_players, compare, similar_players
from analytics.squad import alerts, latest_snapshot
from store.db import connect

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="FM26 Analyst")


@app.middleware("http")
async def no_stale_ui(request, call_next):
    """Always revalidate the UI files so an updated dashboard shows up without a hard refresh."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


from store import backup, careers  # noqa: E402


def db():
    return connect(app_config.DB_PATH)


def club() -> int | None:
    """The club you manage, or None until it's chosen on first run."""
    return app_config.load_config()["club_id"]


def plain(obj):
    """Dataclasses/rows -> JSON-able dicts, including @property values the UI needs."""
    if dataclasses.is_dataclass(obj):
        d = {f.name: plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        for name in dir(type(obj)):
            if isinstance(getattr(type(obj), name, None), property):
                d[name] = plain(getattr(obj, name))
        return d
    if isinstance(obj, (list, tuple)):
        return [plain(x) for x in obj]
    if isinstance(obj, dict):
        return {k: plain(v) for k, v in obj.items()}
    if hasattr(obj, "keys"):  # sqlite3.Row
        return {k: obj[k] for k in obj.keys()}
    return obj


# ---------------------------------------------------------------- capture
class CaptureState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.started: float | None = None
        self.last: dict | None = None

    def run(self) -> bool:
        if club() is None:
            self.last = {"ok": False, "error": "Choose the club you manage first (on the Overview page)."}
            return False
        if HEALTH.loading():
            self.last = {"ok": False, "error": "FM26 is still loading: captures start once your save has loaded."}
            return False
        if HEALTH.bad():            # the reader doesn't match this game build: don't store doubtful data
            self.last = {"ok": False, "error": "Captures are paused: the reader self-check failed for this game build "
                         "(see the banner). Your history is safe."}
            return False
        if not self.lock.acquire(blocking=False):
            return False
        self.running, self.started = True, time.time()

        def work():
            from capture.snapshot import capture  # imported lazily: needs the game process
            try:
                r = capture(club())
                self.last = {"ok": True, **dataclasses.asdict(r)}
            except Exception as e:
                self.last = {"ok": False, "error": str(e), "trace": traceback.format_exc(limit=3)}
            finally:
                self.running = False
                self.lock.release()

        threading.Thread(target=work, daemon=True).start()
        return True


class HealthState:
    """Reader self-check, run whenever FM starts (which is when a patch would show).

    FM can be found before a save has finished loading (main menu, loading screen), when there's no squad or game
    date to read yet. So a failed check is retried every RETRY_SECONDS, shown as "loading" (captures wait, no banner),
    and only reported as failed once it keeps failing: FAILS_TO_REPORT checks spanning at least REPORT_AFTER seconds.
    "Check again" (force) gives an immediate final verdict."""

    RETRY_SECONDS = 45
    FAILS_TO_REPORT = 3
    REPORT_AFTER = 120

    def __init__(self):
        self.lock = threading.Lock()
        self.pid: int | None = None
        self.running = False
        self.result: dict | None = None
        self.fails = 0
        self.first_fail: float | None = None
        self.next_check = 0.0

    def bad(self) -> bool:
        """The reader doesn't match this build: captures pause and the banner shows."""
        return bool(self.result and self.result["status"] in ("unknown_build", "failed"))

    def loading(self) -> bool:
        """Checks are failing so far, most likely because the save is still loading: captures wait, no banner."""
        return bool(self.result and self.result["status"] == "loading")

    def maybe_check(self, force: bool = False) -> None:
        from reader.process import ProcessNotFound, find_pid
        try:
            pid = find_pid()
        except (ProcessNotFound, OSError):
            return
        new_game = pid != self.pid
        due = self.loading() and time.time() >= self.next_check
        if not (new_game or due or force) or not self.lock.acquire(blocking=False):
            return
        if new_game:
            self.fails, self.first_fail, self.result = 0, None, None
        self.pid, self.running = pid, True
        threading.Thread(target=self._run, args=(force,), daemon=True, name="self-check").start()

    def _run(self, final: bool = False) -> None:
        """One check (the lock is held by the caller); decides between ok, loading (retry) and failed."""
        from reader.process import GameProcess
        from reader.selfcheck import self_check
        try:
            try:
                with GameProcess() as p:
                    r = self_check(p, club())
            except Exception as e:      # noqa: BLE001
                r = {"status": "failed", "checks": [{"name": "attach to game", "ok": False, "detail": str(e)}]}
            if r["status"] != "failed":
                self.fails, self.first_fail = 0, None
                self.result = r
            else:
                now = time.time()
                self.fails += 1
                self.first_fail = self.first_fail or now
                bad = [f"{c['name']}: {c.get('detail', '')}" for c in r.get("checks", []) if not c["ok"]]
                print(f"reader self-check failed ({self.fails}): " + "; ".join(bad), flush=True)
                if final or (self.fails >= self.FAILS_TO_REPORT and now - self.first_fail >= self.REPORT_AFTER):
                    self.result = r
                else:                   # probably still loading the save: check again shortly
                    self.result = {**r, "status": "loading"}
                    self.next_check = now + self.RETRY_SECONDS
        finally:
            self.running = False
            self.lock.release()
            print(f"reader self-check: {self.result['status']}", flush=True)

    def state(self) -> dict:
        return {"running": self.running, **(self.result or {"status": "pending"})}


HEALTH = HealthState()
CAPTURE = CaptureState()

from capture.auto import AutoCapture  # noqa: E402  (needs CAPTURE)


def _auto_paused() -> str | None:
    if club() is None:
        return "waiting for you to choose your club"
    HEALTH.maybe_check()            # cheap unless the game was (re)started
    if HEALTH.running:
        return "checking the reader against this game build"
    if HEALTH.loading():
        return "waiting for FM26 to finish loading your save"
    if HEALTH.bad():
        return "paused: reader self-check failed for this game build"
    return None


AUTO = AutoCapture(run_capture=CAPTURE.run, is_busy=lambda: CAPTURE.running, paused=_auto_paused)


@app.on_event("startup")
def start_auto_capture():
    careers.activate()          # point DB_PATH / SNAPSHOT_DIR at the active game snapshot
    AUTO.enabled = bool(app_config.load_config().get("auto_capture", True))
    AUTO.start()
    HEALTH.maybe_check()
    REMOTE.apply()              # the phone listener, if turned on in Settings › Phone
    try:
        backup.daily(app_config.DB_PATH, careers.listing()["active"])
    except Exception as e:      # a failed backup must never stop the app
        print("startup backup failed:", e, flush=True)


# ---------------------------------------------------------------- game snapshots & backups
class SnapshotRef(BaseModel):
    id: int


class NewSnapshot(BaseModel):
    name: str = ""
    club_id: int
    club: str | None = None
    confirm: bool = False


class SnapshotName(BaseModel):
    name: str


def _not_capturing():
    if CAPTURE.running:
        raise HTTPException(409, "a capture is running - try again in a moment")


@app.get("/api/snapshots")
def snapshots():
    lst = careers.listing()
    return {**lst, "backups": backup.status(lst["active"])}


@app.put("/api/snapshots/active")
def snapshot_switch(s: SnapshotRef):
    _not_capturing()
    try:
        careers.switch(s.id)
    except careers.SnapshotError as e:
        raise HTTPException(404, str(e))
    return snapshots()


@app.post("/api/snapshots")
def snapshot_new(s: NewSnapshot):
    """Start a new game snapshot (new save or new job). The current one is backed up and kept."""
    if not s.confirm:
        raise HTTPException(400, "confirmation required")
    _not_capturing()
    import datetime as dt
    old = careers.listing()["active"]
    try:
        backup.backup(app_config.DB_PATH, old, tag=dt.datetime.now().strftime("%Y-%m-%d_%H%M%S") + "_before-new-game")
    except Exception as e:      # never block starting a new game on a backup problem
        print("backup before new game failed:", e, flush=True)
    cid = careers.start_new(s.name, s.club_id, s.club)
    return {**snapshots(), "started": cid}


@app.put("/api/snapshots/{cid}/name")
def snapshot_rename(cid: int, s: SnapshotName):
    try:
        careers.rename(cid, s.name)
    except careers.SnapshotError as e:
        raise HTTPException(400, str(e))
    return snapshots()


@app.delete("/api/snapshots/{cid}")
def snapshot_delete(cid: int):
    _not_capturing()
    try:
        careers.delete(cid)
    except careers.SnapshotError as e:
        raise HTTPException(400, str(e))
    return snapshots()


_CLUB_CACHE: dict = {"at": 0.0, "names": {}}


@app.get("/api/clubs")
def clubs(q: str = ""):
    """Club search for starting a new game: from the running game (every club), else from the stored history."""
    names: dict[int, str] = {}
    try:
        if time.time() - _CLUB_CACHE["at"] > 60:
            from reader.fixtures import read_club_names
            from reader.process import GameProcess
            with GameProcess() as p:
                _CLUB_CACHE.update(names=read_club_names(p), at=time.time())
        names = _CLUB_CACHE["names"]
    except Exception:
        con = db()
        try:
            names = dict(con.execute("SELECT club_id, name FROM clubs").fetchall())
        finally:
            con.close()
    q = q.strip().lower()
    hits = sorted(((cid, n) for cid, n in names.items() if n and (not q or q in n.lower())),
                  key=lambda kv: (kv[1].lower() != q, not kv[1].lower().startswith(q), len(kv[1]), kv[1], kv[0]))[:30]
    return {"clubs": [{"club_id": cid, "name": n} for cid, n in hits]}


@app.post("/api/backup")
def backup_now():
    import datetime as dt
    cid = careers.listing()["active"]
    path = backup.backup(app_config.DB_PATH, cid, tag=dt.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    if not path:
        raise HTTPException(400, "nothing to back up yet")
    return {"file": path.name, **backup.status(cid)}


class AutoToggle(BaseModel):
    enabled: bool


@app.get("/api/auto")
def auto_state():
    return AUTO.state()


@app.put("/api/auto")
def auto_set(t: AutoToggle):
    cfg = app_config.load_config()
    cfg["auto_capture"] = AUTO.enabled = t.enabled
    app_config.save_config(cfg)
    return AUTO.state()


@app.post("/api/shutdown")
def shutdown():
    """Stop the background app (used by the app window's Quit button)."""
    import os
    threading.Timer(0.5, os._exit, args=(0,)).start()
    return {"stopping": True}


@app.get("/api/health")
def health():
    return HEALTH.state()


@app.post("/api/health/recheck")
def health_recheck():
    HEALTH.maybe_check(force=True)
    return HEALTH.state()


@app.post("/api/capture")
def start_capture():
    return {"started": CAPTURE.run(), "running": True}


@app.get("/api/capture")
def capture_status():
    return {"running": CAPTURE.running,
            "elapsed": round(time.time() - CAPTURE.started, 1) if CAPTURE.running and CAPTURE.started else None,
            "last": CAPTURE.last}


# ---------------------------------------------------------------- status
@app.get("/api/status")
def status(request: Request):
    from reader.process import ProcessNotFound, find_pid
    try:
        find_pid()
        game = True
    except ProcessNotFound:
        game = False
    if game:
        HEALTH.maybe_check()
    con = db()
    try:
        snap = latest_snapshot(con, club())
        n = con.execute("SELECT count(*) FROM snapshots WHERE club_id = ?", (club(),)).fetchone()[0]
        name = con.execute("SELECT name FROM clubs WHERE club_id = ?", (club(),)).fetchone()
        return {"game_running": game, "club_id": club(), "club": name[0] if name else None,
                "snapshots": n, "latest": plain(snap) if snap else None,
                "hotkey": app_config.load_config()["hotkey"], "auto": AUTO.state(),
                "save": careers.active_info(), "health": HEALTH.state(),
                "remote": getattr(request.state, "remote_device", None) is not None, "needs_club": club() is None}
    finally:
        con.close()


# ---------------------------------------------------------------- analytics
@app.get("/api/overview")
def overview():
    con = db()
    try:
        summary, lines = last_match(con, club())
        tf = team_form(con, club())
        snap = latest_snapshot(con, club())
        c = club()
        upcoming = [dict(r) | {"venue": "N" if r["neutral"] else "H" if r["home_id"] == c else "A",
                               "opponent": r["away"] if r["home_id"] == c else r["home"]}
                    for r in con.execute(
            """SELECT f.*, h.name AS home, a.name AS away FROM fixtures f
               LEFT JOIN clubs h ON h.club_id = f.home_id LEFT JOIN clubs a ON a.club_id = f.away_id
               WHERE (f.home_id = ? OR f.away_id = ?) AND f.home_goals IS NULL AND f.date >= ?
               ORDER BY f.date, f.kickoff LIMIT 6""", (c, c, snap["game_date"] if snap else "0000"))]
        return {"last_match": {"summary": summary, "players": plain(lines)}, "upcoming": upcoming,
                "in_form": in_form(match_lines(con, c)),
                "next_match": recommend(con, c),
                "team_form": plain(tf) | {"string": tf.string, "points": tf.points, "goals_for": tf.goals_for,
                                          "goals_against": tf.goals_against, "unbeaten_run": tf.unbeaten_run},
                "alerts": plain(alerts(con, club()))}
    finally:
        con.close()


@app.get("/api/match/{fixture_id}")
def match(fixture_id: int):
    con = db()
    try:
        summary, lines = match_detail(con, club(), fixture_id)
        if not summary:
            raise HTTPException(404, "fixture not found")
        return {"summary": summary, "players": plain(lines), **neighbours(con, club(), fixture_id)}
    finally:
        con.close()


@app.get("/api/squad")
def squad_table(include: str = "first team,loaned in"):
    statuses = tuple(s.strip() for s in include.split(","))
    con = db()
    try:
        snap = latest_snapshot(con, club())
        if not snap:
            return {"players": []}
        q = ",".join("?" * len(statuses))
        rows = [plain(r) for r in con.execute(
            f"""SELECT s.*, p.name, p.dob FROM player_state s JOIN players p USING (unique_id)
                WHERE s.snapshot_id = ? AND s.status IN ({q}) ORDER BY s.ca DESC""", (snap["id"], *statuses))]
        lines = match_lines(con, club())
        form = {f.unique_id: f for f in player_form(lines)}
        aggs = aggregate(lines)
        for r in rows:
            f, a = form.get(r["unique_id"]), aggs.get(r["unique_id"])
            r["form"] = f.ratings if f else []
            r["form_label"] = f.label if f else None
            r["avg_rating"] = a.avg_rating if a else None
            r["apps"] = a.apps if a else 0
            r["age"] = _age(r["dob"], snap["game_date"])
        return {"game_date": snap["game_date"], "players": rows}
    finally:
        con.close()


def _age(dob: str | None, on: str) -> int | None:
    if not dob:
        return None
    y, m, d = map(int, dob.split("-"))
    Y, M, D = map(int, on.split("-"))
    return Y - y - ((M, D) < (m, d))


@app.get("/api/players")
def players_all():
    con = db()
    try:
        data = all_players(con, club())
        lines = match_lines(con, club())
        form = {f.unique_id: f for f in player_form(lines)}
        aggs = aggregate(lines)
        for p in data["players"]:
            f, a = form.get(p["unique_id"]), aggs.get(p["unique_id"])
            p.update(form=f.ratings if f else [], form_label=f.label if f else None,
                     avg_rating=a.avg_rating if a else None, apps=a.apps if a else 0)
        return data
    finally:
        con.close()


@app.get("/api/similar/{unique_id}")
def similar(unique_id: int, n: int = 6, include: str | None = None):
    con = db()
    try:
        kw = {"statuses": tuple(s.strip() for s in include.split(","))} if include else {}
        return {"similar": similar_players(con, club(), unique_id, n, **kw)}
    finally:
        con.close()


@app.get("/api/compare")
def compare_players(a: int, b: int):
    con = db()
    try:
        return compare(con, club(), a, b)
    except KeyError as e:
        raise HTTPException(404, f"player {e} not in the latest snapshot")
    finally:
        con.close()


@app.get("/api/per90")
def per90():
    con = db()
    try:
        from analytics.roles import squad_metrics
        sm = squad_metrics(con, club())
        aggs = [a for a in aggregate(match_lines(con, club())).values()]
        return {"min_minutes": PER90_MIN_MINUTES, "role_labels": sm["labels"],
                "goalkeepers": sorted(sm["goalkeepers"].values(), key=lambda g: -g["minutes"]),
                "players": [plain(a) | {"per90s": a.per90s(), "roles": sm["roles"].get(a.unique_id)}
                            for a in sorted(aggs, key=lambda a: -a.minutes) if a.unique_id not in sm["goalkeepers"]]}
    finally:
        con.close()


@app.get("/api/form")
def form():
    con = db()
    try:
        return {"players": plain(player_form(match_lines(con, club())))}
    finally:
        con.close()


@app.get("/api/development")
def dev(days: int | None = None, include: str = "first team,loaned in,youth team"):
    con = db()
    try:
        pair = snapshot_pair(con, club(), days)
        if not pair:
            return {"pair": None, "players": [], "improvers": [], "decliners": []}
        devs = development(con, *pair)
        statuses = tuple(s.strip() for s in include.split(","))
        up, down = leaderboard(devs, n=15, statuses=statuses)
        enrich = lambda d: plain(d) | {"groups": {g: d.group_delta(g) for g in GROUPS}}
        snaps = {r["id"]: r["game_date"] for r in con.execute("SELECT id, game_date FROM snapshots WHERE id IN (?,?)", pair)}
        return {"pair": {"before": pair[0], "after": pair[1], "before_date": snaps[pair[0]],
                         "after_date": snaps[pair[1]], "days": devs[0].days if devs else 0},
                "improvers": [enrich(d) for d in up], "decliners": [enrich(d) for d in down]}
    finally:
        con.close()


@app.get("/api/player/{unique_id}")
def player(unique_id: int):
    con = db()
    try:
        p = con.execute("SELECT * FROM players WHERE unique_id = ?", (unique_id,)).fetchone()
        if not p:
            raise HTTPException(404, "player not found")
        history = [plain(r) for r in con.execute(
            """SELECT s.game_date, s.id AS snapshot_id, ps.* FROM player_state ps
               JOIN snapshots s ON s.id = ps.snapshot_id WHERE ps.unique_id = ? ORDER BY s.game_date, s.id""",
            (unique_id,))]
        attr_rows = con.execute(
            """SELECT s.game_date, a.attr, a.raw FROM player_attributes a JOIN snapshots s ON s.id = a.snapshot_id
               WHERE a.unique_id = ? ORDER BY s.game_date, s.id""", (unique_id,)).fetchall()
        attrs: dict[str, list] = {}
        for r in attr_rows:
            attrs.setdefault(r["attr"], []).append({"date": r["game_date"], "raw": r["raw"]})
        latest = {a: v[-1]["raw"] for a, v in attrs.items()}
        lines = match_lines(con, club(), unique_id=unique_id)
        agg = aggregate(lines).get(unique_id)
        from analytics.roles import squad_metrics
        sm = squad_metrics(con, club())
        return {"player": plain(p), "history": history,
                "goalkeeping": sm["goalkeepers"].get(unique_id), "roles": sm["roles"].get(unique_id),
                "role_labels": sm["labels"],
                "attributes": {g: {a: latest[a] for a in attrs_ if a in latest} for g, attrs_ in GROUPS.items()}
                | {"other": {a: v for a, v in latest.items() if a not in GROUP_OF}},
                "attribute_history": attrs, "matches": plain(lines),
                "totals": (plain(agg) | {"per90s": agg.per90s()}) if agg else None}
    finally:
        con.close()


@app.get("/api/fixtures")
def fixtures(since: str | None = None):
    con = db()
    try:
        c = club()
        rows = con.execute(
            """SELECT f.*, h.name AS home, a.name AS away,
                      EXISTS (SELECT 1 FROM matches m WHERE m.fixture_id = f.id) AS has_stats
               FROM fixtures f LEFT JOIN clubs h ON h.club_id = f.home_id LEFT JOIN clubs a ON a.club_id = f.away_id
               WHERE (f.home_id = ? OR f.away_id = ?) AND (? IS NULL OR f.date >= ?) ORDER BY f.date DESC""",
            (c, c, since, since)).fetchall()
        out = []
        for r in rows:
            d = plain(r)
            home = r["home_id"] == c
            gf, ga = (r["home_goals"], r["away_goals"]) if home else (r["away_goals"], r["home_goals"])
            d.update(venue="N" if r["neutral"] else "H" if home else "A", opponent=r["away"] if home else r["home"],
                     result=None if gf is None else "W" if gf > ga else "L" if gf < ga else "D")
            out.append(d)
        return {"fixtures": out}
    finally:
        con.close()


# ---------------------------------------------------------------- settings
class Settings(BaseModel):
    club_id: int | None = None
    hotkey: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_temperature: float | None = None
    llm_clear_key: bool = False
    llm_provider: str | None = None          # "api" (OpenAI-compatible endpoint + key) or "chatgpt" (ChatGPT plan)
    llm_chatgpt_model: str | None = None
    llm_chatgpt_effort: str | None = None    # "" = model default, else low / medium / high


@app.get("/api/settings")
def get_settings():
    cfg = app_config.load_config()
    key = cfg["llm"].get("api_key") or ""
    return {"club_id": cfg["club_id"], "hotkey": cfg["hotkey"], "llm_base_url": cfg["llm"].get("base_url", ""),
            "llm_model": cfg["llm"].get("model", ""), "llm_temperature": cfg["llm"].get("temperature"),
            "llm_provider": cfg["llm"].get("provider", "api"), "llm_chatgpt_model": cfg["llm"].get("chatgpt_model", ""),
            "llm_chatgpt_effort": cfg["llm"].get("chatgpt_effort", ""),
            "llm_api_key_set": bool(key), "llm_api_key_hint": f"…{key[-4:]}" if len(key) >= 8 else ""}


@app.put("/api/settings")
def put_settings(s: Settings):
    cfg = app_config.load_config()
    if s.club_id is not None:
        changed = cfg["club_id"] != s.club_id
        cfg["club_id"] = s.club_id
        if changed:
            app_config.save_config(cfg)
            HEALTH.maybe_check(force=True)      # re-run the squad check for the new club
    if s.hotkey:
        from capture.hotkey import parse
        try:
            parse(s.hotkey)
        except ValueError as e:
            raise HTTPException(400, str(e))
        cfg["hotkey"] = s.hotkey
    if s.llm_base_url is not None:
        url = s.llm_base_url.strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(400, "base URL must start with http:// or https://")
        cfg["llm"]["base_url"] = url
    if s.llm_model is not None:
        cfg["llm"]["model"] = s.llm_model.strip()
    if s.llm_temperature is not None:
        cfg["llm"]["temperature"] = max(0.0, min(2.0, s.llm_temperature))
    if s.llm_provider is not None:
        if s.llm_provider not in ("api", "chatgpt"):
            raise HTTPException(400, "provider must be 'api' or 'chatgpt'")
        cfg["llm"]["provider"] = s.llm_provider
    if s.llm_chatgpt_model is not None:
        cfg["llm"]["chatgpt_model"] = s.llm_chatgpt_model.strip()
    if s.llm_chatgpt_effort is not None:
        if s.llm_chatgpt_effort not in ("", "low", "medium", "high"):
            raise HTTPException(400, "thinking depth must be default, low, medium or high")
        cfg["llm"]["chatgpt_effort"] = s.llm_chatgpt_effort
    if s.llm_clear_key:
        cfg["llm"]["api_key"] = ""
    elif s.llm_api_key:  # empty = keep the stored key
        cfg["llm"]["api_key"] = s.llm_api_key.strip()
    app_config.save_config(cfg)
    return get_settings()


# ---------------------------------------------------------------- AI coach
class ChatMessage(BaseModel):
    role: str
    content: str
    usage: dict | None = None        # kept so saved conversations show each answer's usage
    tools: list[str] | None = None   # look-ups the coach made for that answer


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    page: str = "overview"
    conversation_id: str | None = None


MAX_TURNS = 12        # earlier turns aren't sent to the model (they stay in the saved conversation)
MAX_TOOL_ROUNDS = 3   # look-up rounds per answer before the model must reply


def _events(messages: list[dict], tools: list[dict] | None):
    """The configured provider's event stream: ("delta"|"tool_call"|"usage", value)."""
    from llm import chatgpt
    from llm.client import stream_events
    llm = app_config.load_config()["llm"]
    if llm.get("provider") == "chatgpt":
        return chatgpt.stream_events(llm.get("chatgpt_model", ""), messages, llm.get("chatgpt_effort") or None, tools)
    return stream_events(llm, messages, tools)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Stream the coach's answer as server-sent events:
    {"conversation": id} first, then {"delta"} text, {"tool": label} while looking something up,
    {"usage": {input, output, cost?, plan?}}, then {"done": true} or {"error": ...}. The conversation is saved."""
    import json
    from fastapi.responses import StreamingResponse
    from llm import chats, tools as coach_tools
    from llm.client import LLMError, system_prompt
    from llm.context import build_context

    con = db()
    try:
        context = build_context(con, club(), req.page)
    finally:
        con.close()
    all_turns = [m for m in req.messages if m.role in ("user", "assistant") and m.content.strip()]
    turns = all_turns[-MAX_TURNS:]
    if not turns or turns[-1].role != "user":
        raise HTTPException(400, "last message must be from the user")
    messages = [{"role": "system", "content": system_prompt()},
                {"role": "system", "content": "DATA (read from the user's game by the app):\n\n" + context
                 + "\n\nIf you need more detail than this, use the look-up tools (get_player, get_match, list_matches)."}]
    messages += [{"role": m.role, "content": m.content} for m in turns]
    save_id = careers.listing()["active"]
    cid = req.conversation_id or chats.new_id()
    try:
        chats._path(save_id, cid)
    except KeyError:
        cid = chats.new_id()

    async def events():
        from llm import chatgpt
        yield f"data: {json.dumps({'conversation': cid})}\n\n"
        text, used, usage = "", [], {"input": 0, "output": 0}
        msgs = list(messages)
        try:
            for rnd in range(MAX_TOOL_ROUNDS + 1):
                calls, said = [], ""
                async for kind, val in _events(msgs, coach_tools.TOOLS if rnd < MAX_TOOL_ROUNDS else None):
                    if kind == "delta":
                        said += val
                        yield f"data: {json.dumps({'delta': val})}\n\n"
                    elif kind == "tool_call":
                        calls.append(val)
                    elif kind == "usage":
                        usage["input"] += val.get("input", 0)
                        usage["output"] += val.get("output", 0)
                        if "cost" in val:
                            usage["cost"] = round(usage.get("cost", 0) + val["cost"], 6)
                        if val.get("plan"):
                            usage["plan"] = True
                text += said
                if not calls:
                    break
                msgs.append({"role": "assistant", "content": said or None,
                             "tool_calls": [{"id": c["id"], "type": "function",
                                             "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]})
                con = db()
                try:
                    for c in calls:
                        try:
                            args = json.loads(c["arguments"] or "{}")
                        except ValueError:
                            args = {}
                        label = coach_tools.describe(c["name"], args)
                        used.append(label)
                        yield f"data: {json.dumps({'tool': label})}\n\n"
                        out = coach_tools.run(con, club(), c["name"], c["arguments"])
                        msgs.append({"role": "tool", "tool_call_id": c["id"], "content": out[:20000]})
                finally:
                    con.close()
            yield f"data: {json.dumps({'usage': usage})}\n\n"
            if text.strip():
                saved = [m.model_dump(exclude_none=True) for m in all_turns]
                saved.append({"role": "assistant", "content": text, "usage": usage, **({"tools": used} if used else {})})
                chats.save(save_id, cid, saved)
            yield 'data: {"done": true}\n\n'
        except (LLMError, chatgpt.ChatGPTError) as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        except Exception as e:  # network errors etc.
            yield f"data: {json.dumps({'error': f'Could not reach the LLM endpoint: {e}'})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # stream through nginx


@app.get("/api/chats")
def chat_list():
    from llm import chats
    return {"conversations": chats.listing(careers.listing()["active"])}


@app.get("/api/chats/{cid}")
def chat_get(cid: str):
    from llm import chats
    try:
        return chats.load(careers.listing()["active"], cid)
    except KeyError:
        raise HTTPException(404, "conversation not found")


@app.delete("/api/chats/{cid}")
def chat_delete(cid: str):
    from llm import chats
    try:
        chats.delete(careers.listing()["active"], cid)
    except KeyError:
        raise HTTPException(404, "conversation not found")
    return {"deleted": cid}


class CoachPrompt(BaseModel):
    text: str


@app.get("/api/coach/prompt")
def coach_prompt():
    from llm.client import custom_prompt_path, default_prompt, system_prompt
    return {"text": system_prompt(), "custom": custom_prompt_path().exists(), "default": default_prompt()}


@app.put("/api/coach/prompt")
def coach_prompt_save(p: CoachPrompt):
    from llm.client import custom_prompt_path, default_prompt
    if len(p.text) > 20000:
        raise HTTPException(400, "instructions are too long (20,000 characters max)")
    path = custom_prompt_path()
    if not p.text.strip() or p.text.strip() == default_prompt().strip():
        path.unlink(missing_ok=True)                       # back to the built-in default
    else:
        app_config.DATA.mkdir(exist_ok=True)
        path.write_text(p.text, encoding="utf-8")
    return coach_prompt()


@app.get("/api/chat/context")
def chat_context(page: str = "overview"):
    """What the coach sees for a page (shown in the chat panel's 'data sent' view)."""
    from llm.context import build_context
    con = db()
    try:
        return {"page": page, "context": build_context(con, club(), page)}
    finally:
        con.close()


async def _stream(messages: list[dict]):
    """Text-only stream from the configured provider (used by Test connection)."""
    async for kind, val in _events(messages, None):
        if kind == "delta":
            yield val


@app.get("/api/llm/status")
def llm_status():
    from llm import chatgpt
    llm = app_config.load_config()["llm"]
    if llm.get("provider") == "chatgpt":
        st = chatgpt.status()
        ready = st["signed_in"] and st["plan_usage"] and bool(st["model"])
        return {"provider": "chatgpt", "ready": ready, "label": "Using ChatGPT plan" if ready else "ChatGPT: not set up",
                "detail": f"{st['email'] or ''} · {st['model']}" if ready else "Settings › AI coach", **st}
    local = any(h in (llm.get("base_url") or "") for h in ("://localhost", "://127.0.0.1"))
    ready = bool(llm.get("base_url") and llm.get("model") and (llm.get("api_key") or local))
    return {"provider": "api", "ready": ready, "label": (llm.get("model") or "not set up") if ready else "not set up",
            "detail": llm.get("base_url") or "Settings › AI coach"}


@app.post("/api/llm/test")
async def llm_test():
    from llm import chatgpt
    from llm.client import LLMError, list_models
    llm = app_config.load_config()["llm"]
    try:
        reply = ""
        async for d in _stream([{"role": "user", "content": "Reply with the single word: ready"}]):
            reply += d
        try:
            if llm.get("provider") == "chatgpt":
                models = [m["id"] for m in await chatgpt.list_models()]
            else:
                models = await list_models(llm)
        except (LLMError, chatgpt.ChatGPTError):
            models = []           # some providers don't list models; the chat call is what matters
        model = llm.get("chatgpt_model") if llm.get("provider") == "chatgpt" else llm["model"]
        return {"ok": True, "reply": reply.strip()[:80], "model": model, "models": models[:200]}
    except (LLMError, chatgpt.ChatGPTError) as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Could not reach the LLM endpoint: {e}"}


# ChatGPT plan (Sign in with ChatGPT, OpenAI's flow for locally hosted apps)
@app.post("/api/chatgpt/start")
def chatgpt_start(request: Request):
    import webbrowser
    from llm import chatgpt
    port = request.url.port or 8765
    try:
        url = chatgpt.start(f"http://127.0.0.1:{port}{chatgpt.CALLBACK_PATH}")
    except chatgpt.ChatGPTError as e:
        raise HTTPException(400, str(e))
    webbrowser.open(url)          # the system browser, as OpenAI requires; the URL isn't logged
    return {"opened": True}


@app.get("/auth/callback")
async def chatgpt_callback(request: Request):
    from fastapi.responses import HTMLResponse
    from llm import chatgpt
    from urllib.parse import unquote
    # parse the raw query ourselves: query_params decodes '+' as a space, which would corrupt a code containing '+'
    params = {}
    for part in request.url.query.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[unquote(k)] = unquote(v)
    code = params.get("code", "")
    print(f"ChatGPT callback: params={sorted(params)} code_len={len(code)} "
          f"code_has_plus={'+' in code} code_has_space={' ' in code} code_has_pct={'%' in request.url.query}", flush=True)
    try:
        st = await chatgpt.finish(params)
        if not st["plan_usage"]:
            msg = ("Signed in, but ChatGPT plan usage wasn't granted. Sign in again and allow plan usage, "
                   "or use an API key instead.")
        else:
            msg = f"You're using your ChatGPT plan{' as ' + st['email'] if st['email'] else ''}. You can close this tab and go back to FM26 Analyst."
        ok = True
    except chatgpt.ChatGPTError as e:
        msg, ok = str(e), False
        print("ChatGPT sign-in failed:", msg, flush=True)        # data/app.log; never contains tokens
    except Exception as e:
        msg, ok = "Sign-in failed unexpectedly - try again from Settings.", False
        print("ChatGPT sign-in error:", type(e).__name__, e, flush=True)
    import html
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><title>FM26 Analyst</title>
      <body style="background:#0d1117;color:#e6edf3;font:16px system-ui;display:grid;place-items:center;height:90vh">
      <div style="max-width:520px;text-align:center"><h2>{'✓' if ok else '✗'} {'Connected' if ok else 'Not connected'}</h2>
      <p>{html.escape(msg)}</p></div></body>""")


@app.post("/api/chatgpt/signout")
async def chatgpt_signout():
    from llm import chatgpt
    return await chatgpt.sign_out()


@app.get("/api/chatgpt/models")
async def chatgpt_models():
    from llm import chatgpt
    try:
        models = await chatgpt.list_models()
    except chatgpt.ChatGPTError as e:
        raise HTTPException(400, str(e))
    cfg = app_config.load_config()
    ids = [m["id"] for m in models]
    if models and cfg["llm"].get("chatgpt_model") not in ids:   # none chosen (or no longer offered): use the top one
        cfg["llm"]["chatgpt_model"] = ids[0]
        app_config.save_config(cfg)
    return {"models": models, "selected": cfg["llm"].get("chatgpt_model", "")}


@app.post("/api/chatgpt/ack")
def chatgpt_ack():
    from llm import chatgpt
    chatgpt.ack_first_use()
    return {"ok": True}


# ---------------------------------------------------------------- phone companion (Settings › Phone)
# These endpoints are desktop-only: the remote gate never lets a phone reach them (see web/remote.py ALLOW).
from web import remote  # noqa: E402

GATE = remote.RemoteGate(app)
REMOTE = remote.RemoteServer(GATE)


class RemoteSettings(BaseModel):
    enabled: bool | None = None
    port: int | None = None
    public_url: str | None = None
    proxy_ip: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    allowed_emails: list[str] | None = None
    clear_google: bool = False
    password_user: str | None = None
    password: str | None = None
    clear_password: bool = False


def _lan_ips() -> list[str]:
    import socket
    try:
        ips = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        ips = set()
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))


def _remote_base(r: dict) -> str:
    if r.get("public_url"):
        return r["public_url"].rstrip("/")
    ips = _lan_ips()
    return f"http://{ips[0] if ips else '127.0.0.1'}:{r['port']}"


@app.get("/api/remote")
def remote_get():
    r = app_config.load_config()["remote"]
    return {"enabled": r["enabled"], "port": r["port"], "public_url": r["public_url"], "proxy_ip": r["proxy_ip"],
            "google_client_id": r["google_client_id"], "google_secret_set": bool(r["google_client_secret"]),
            "allowed_emails": r["allowed_emails"], "google_ready": remote.google_ready(r),
            "redirect_uri": remote.redirect_uri(r) if r["public_url"] else "",
            "password_user": r["password_user"], "password_set": bool(r["password_hash"]),
            "server": REMOTE.state(), "devices": remote.DEVICES.listing(), "lan_ips": _lan_ips(),
            "base_url": _remote_base(r)}


@app.put("/api/remote")
def remote_put(s: RemoteSettings):
    cfg = app_config.load_config()
    r = cfg["remote"]
    if s.port is not None:
        if not 1024 <= s.port <= 65535 or s.port == 8765:
            raise HTTPException(400, "port must be 1024-65535 and not the dashboard's own 8765")
        r["port"] = s.port
    if s.public_url is not None:
        url = s.public_url.strip().rstrip("/")
        if url and not url.startswith("https://"):
            raise HTTPException(400, "the public address must start with https:// (your proxy's Let's Encrypt address)")
        r["public_url"] = url
    if s.proxy_ip is not None:
        import ipaddress
        ips = [x.strip() for x in s.proxy_ip.split(",") if x.strip()]
        try:
            [ipaddress.ip_address(x) for x in ips]
        except ValueError:
            raise HTTPException(400, "proxy address must be an IP like 192.168.1.20 (or several, comma-separated)")
        r["proxy_ip"] = ", ".join(ips)
    if s.google_client_id is not None:
        r["google_client_id"] = s.google_client_id.strip()
    if s.google_client_secret:              # empty = keep the stored secret
        r["google_client_secret"] = s.google_client_secret.strip()
    if s.allowed_emails is not None:
        emails = [e.strip().lower() for e in s.allowed_emails if e.strip()]
        if any("@" not in e for e in emails):
            raise HTTPException(400, "allowed accounts must be email addresses")
        r["allowed_emails"] = emails
    if s.clear_google:
        r["google_client_id"] = r["google_client_secret"] = ""
    if s.password_user is not None:
        r["password_user"] = s.password_user.strip()
    if s.password:
        if len(s.password) < 10:
            raise HTTPException(400, "use a password of at least 10 characters")
        if not r["password_user"]:
            raise HTTPException(400, "set a username for the password")
        r["password_hash"] = remote.hash_password(s.password)
    if s.clear_password:
        r["password_hash"] = ""
    if s.enabled is not None:
        r["enabled"] = s.enabled
    app_config.save_config(cfg)
    REMOTE.apply(r)
    return remote_get()


@app.post("/api/remote/pair")
def remote_pair():
    r = app_config.load_config()["remote"]
    if not r["enabled"]:
        raise HTTPException(400, "turn on phone access first")
    if not (r["password_hash"] or remote.google_ready(r)):
        raise HTTPException(400, "set up the password or Google sign-in first: pairing needs a sign-in as well as the code")
    code = remote.new_pair_code()
    return {"url": f"{_remote_base(r)}/pair#{code}", "code": f"{code[:4]}-{code[4:]}", "expires_in": remote.PAIR_TTL}


@app.delete("/api/remote/devices/{dev_id}")
def remote_revoke(dev_id: str):
    if not remote.DEVICES.revoke(dev_id):
        raise HTTPException(404, "no such device")
    return {"devices": remote.DEVICES.listing()}


# ---------------------------------------------------------------- static UI
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    # served from the root so it can look after the whole app
    return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
