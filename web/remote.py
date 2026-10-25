"""Phone companion: a second, locked-down listener meant to sit behind a reverse proxy (e.g. NGINX Proxy Manager).

The desktop dashboard on 127.0.0.1 is unchanged. This listener (default 0.0.0.0:8766) only serves:
  - the sign-in page and its /auth/* endpoints (QR pairing, Google sign-in, password),
  - the UI shell (/static, the PWA manifest and service worker),
  - and, for a paired device, the allow-listed parts of the dashboard API (ALLOW): reading every page, the coach,
    Capture and the Auto switch. Settings, game snapshots, sign-ins, backups and Quit are never reachable here.

Pairing a device takes two steps, in either order, within PENDING_TTL: sign in (Google or the password) AND enter
the one-time pairing code shown in Settings › Phone on the PC (scanned as a QR code, or typed). Neither alone is
enough. Progress is held server-side against a short-lived fm_pending cookie.
A paired device holds a random token in an HttpOnly cookie; only its SHA-256 is stored (data/devices.json).
Requests that change anything must carry the X-FM-Remote header (a cross-site page can't send it without a CORS
preflight, which this listener never answers), and an Origin header, when present, must match the Host.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

import app_config

STATIC = Path(__file__).parent / "static"
COOKIE = "fm_device"
PENDING_COOKIE = "fm_pending"  # a pairing in progress: signed in, or code entered, but not both yet
PENDING_TTL = 15 * 60
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I: easy to read off the PC screen and type
CODE_LEN = 8                   # ~40 bits; single use, 10 minutes, attempt-limited, and useless without a sign-in
DEVICE_DAYS = 180              # a device not seen for this long has to sign in again
PAIR_TTL = 600                 # a pairing code is valid for 10 minutes, once
GOOGLE_TTL = 600               # a Google sign-in must finish within 10 minutes
CSRF_HEADER = "x-fm-remote"
MAX_FAILURES, FAIL_WINDOW = 5, 15 * 60   # wrong passwords / pairing codes before sign-in pauses
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
CALLBACK_PATH = "/auth/google/callback"

# what a paired phone may do: (methods, path pattern)
ALLOW = [
    ({"GET", "HEAD"}, re.compile(r"/|/api/(status|overview|squad|players|compare|per90|form|development|fixtures"
                                 r"|capture|auto|health|chats|llm/status|chat/context)")),
    ({"GET", "HEAD"}, re.compile(r"/api/(match|similar|player|chats)/[^/]+")),
    ({"POST"}, re.compile(r"/api/(capture|chat)")),
    ({"PUT"}, re.compile(r"/api/auto")),
    ({"DELETE"}, re.compile(r"/api/chats/[^/]+")),
]
SHELL = {"/manifest.webmanifest", "/sw.js", "/favicon.ico"}   # served without sign-in (no data in them)


def settings() -> dict:
    return app_config.load_config()["remote"]


def allowed(method: str, path: str) -> bool:
    return any(method in ms and rx.fullmatch(path) for ms, rx in ALLOW)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- paired devices
class Devices:
    """data/devices.json: [{id, name, method, created, last_seen, hash}]. Shared by every game snapshot."""

    def __init__(self):
        self.lock = threading.Lock()

    @property
    def path(self) -> Path:
        return app_config.DATA / "devices.json"

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save(self, devs: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(devs, indent=2), encoding="utf-8")

    def listing(self) -> list[dict]:
        with self.lock:
            return [{k: v for k, v in d.items() if k != "hash"} for d in self._live(self._load())]

    @staticmethod
    def _live(devs: list[dict]) -> list[dict]:
        cutoff = time.time() - DEVICE_DAYS * 86400
        return [d for d in devs if d.get("last_seen", 0) >= cutoff]

    def add(self, name: str, method: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock:
            devs = self._live(self._load())
            devs.append({"id": secrets.token_hex(6), "name": name, "method": method, "created": now,
                         "last_seen": now, "hash": _hash(token)})
            self._save(devs)
        return token

    def find(self, token: str | None) -> dict | None:
        if not token or len(token) > 100:
            return None
        h = _hash(token)
        with self.lock:
            devs = self._load()
            for d in self._live(devs):
                if hmac.compare_digest(d["hash"], h):
                    if time.time() - d.get("last_seen", 0) > 300:     # sliding expiry, written at most every 5 min
                        d["last_seen"] = time.time()
                        self._save(devs)
                    return {k: v for k, v in d.items() if k != "hash"}
        return None

    def revoke(self, dev_id: str) -> bool:
        with self.lock:
            devs = self._load()
            keep = [d for d in devs if d["id"] != dev_id]
            self._save(keep)
            return len(keep) < len(devs)


DEVICES = Devices()


# ---------------------------------------------------------------- password (scrypt) and attempt limit
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 15, 8, 1
    h = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(stored: str, password: str) -> bool:
    try:
        _, n, r, p, salt, want = stored.split("$")
        h = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                           maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(h, base64.b64decode(want))


class Limiter:
    """Pauses password and pairing-code sign-in after MAX_FAILURES wrong tries in FAIL_WINDOW (for everyone:
    behind a proxy every request has the proxy's address). Google sign-in isn't affected."""

    def __init__(self):
        self.fails: deque[float] = deque()
        self.lock = threading.Lock()

    def _trim(self):
        while self.fails and self.fails[0] < time.time() - FAIL_WINDOW:
            self.fails.popleft()

    def check(self):
        with self.lock:
            self._trim()
            if len(self.fails) >= MAX_FAILURES:
                wait = int(self.fails[0] + FAIL_WINDOW - time.time()) // 60 + 1
                raise HTTPException(429, f"Too many wrong attempts - try again in {wait} min, or use Google sign-in.")

    def fail(self):
        with self.lock:
            self.fails.append(time.time())


LIMIT = Limiter()


# ---------------------------------------------------------------- one-time pairing codes (QR or typed)
_pairs: dict[str, float] = {}
_pairs_lock = threading.Lock()


def norm_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def new_pair_code() -> str:
    """Returns e.g. "K7QF2M9P" (shown as K7QF-2M9P)."""
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
    with _pairs_lock:
        now = time.time()
        for k in [k for k, exp in _pairs.items() if exp < now]:
            del _pairs[k]
        _pairs[_hash(code)] = now + PAIR_TTL
    return code


def use_pair_code(code: str) -> bool:
    with _pairs_lock:
        exp = _pairs.pop(_hash(norm_code(code)), None)
    return bool(exp and exp >= time.time())


# ---------------------------------------------------------------- Google sign-in
# The phone asks for a sign-in URL plus a secret poll id, opens Google in a new window, and polls until the
# callback (which may land in another browser, e.g. Safari instead of the installed app) has approved it.
# The cookie is then set by the poll response, so it lands in the app that asked, wherever Google finished.
_google: dict[str, dict] = {}
_google_lock = threading.Lock()


def google_ready(cfg: dict) -> bool:
    return bool(cfg.get("google_client_id") and cfg.get("google_client_secret") and cfg.get("allowed_emails")
                and str(cfg.get("public_url", "")).startswith("https://"))


def redirect_uri(cfg: dict) -> str:
    return str(cfg.get("public_url", "")).rstrip("/") + CALLBACK_PATH


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def google_begin(cfg: dict) -> dict:
    state, poll, nonce, verifier = (secrets.token_urlsafe(24), secrets.token_urlsafe(32), secrets.token_urlsafe(16),
                                    secrets.token_urlsafe(48))
    with _google_lock:
        now = time.time()
        for k in [k for k, v in _google.items() if v["created"] < now - GOOGLE_TTL]:
            del _google[k]
        _google[state] = {"poll": _hash(poll), "nonce": nonce, "verifier": verifier, "created": now,
                          "email": None, "error": None}
    q = {"client_id": cfg["google_client_id"], "redirect_uri": redirect_uri(cfg), "response_type": "code",
         "scope": "openid email", "state": state, "nonce": nonce, "prompt": "select_account",
         "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
    return {"url": f"{GOOGLE_AUTH}?{urlencode(q)}", "poll": poll}


def _id_claims(id_token: str) -> dict:
    # The token came straight from Google's token endpoint over TLS in exchange for our code + secret, so OpenID
    # Connect allows trusting it without checking the signature (Core 1.0 §3.1.3.7); the claims are still checked.
    part = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def check_claims(claims: dict, cfg: dict, nonce: str) -> str:
    """The signed-in email if it's allowed, else raise ValueError with a message for the user."""
    if claims.get("iss") not in GOOGLE_ISSUERS or claims.get("aud") != cfg["google_client_id"]:
        raise ValueError("That sign-in wasn't issued for this app.")
    if float(claims.get("exp", 0)) < time.time() or claims.get("nonce") != nonce:
        raise ValueError("That sign-in has expired - try again.")
    email = str(claims.get("email", "")).lower()
    if not email or not claims.get("email_verified"):
        raise ValueError("Google didn't confirm an email address for that account.")
    if email not in {e.strip().lower() for e in cfg.get("allowed_emails", []) if e.strip()}:
        raise ValueError(f"{email} isn't allowed to use this dashboard. Add it in Settings › Phone on your PC.")
    return email


async def google_finish(params: dict) -> str:
    import httpx
    cfg = settings()
    with _google_lock:
        p = _google.get(params.get("state", ""))
    if not p:
        raise ValueError("This sign-in link has expired - start again from the app.")
    try:
        if params.get("error"):
            raise ValueError("Google sign-in was cancelled." if params["error"] == "access_denied"
                             else f"Google sign-in failed ({params['error']}).")
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(GOOGLE_TOKEN, data={
                "code": params.get("code", ""), "client_id": cfg["google_client_id"],
                "client_secret": cfg["google_client_secret"], "redirect_uri": redirect_uri(cfg),
                "grant_type": "authorization_code", "code_verifier": p["verifier"]})
        if r.status_code != 200:
            raise ValueError(f"Google didn't accept the sign-in ({r.status_code}) - check the client ID and secret.")
        email = check_claims(_id_claims(r.json()["id_token"]), cfg, p["nonce"])
        p["email"] = email
        return email
    except ValueError as e:
        p["error"] = str(e)
        raise
    except Exception as e:
        p["error"] = "Google sign-in failed - try again."
        raise ValueError(p["error"]) from e


def google_poll(poll: str) -> dict:
    """{"status": "pending"} | {"status": "ok", "email"} (consumed) | {"status": "error", "error"}."""
    h = _hash(poll or "")
    with _google_lock:
        for state, p in list(_google.items()):
            if hmac.compare_digest(p["poll"], h):
                if p["error"]:
                    del _google[state]
                    return {"status": "error", "error": p["error"]}
                if p["email"]:
                    del _google[state]
                    return {"status": "ok", "email": p["email"]}
                return {"status": "pending"}
    return {"status": "error", "error": "This sign-in has expired - try again."}


# ---------------------------------------------------------------- sign-in endpoints (only on the remote listener)
auth_app = FastAPI(title="FM26 Analyst sign-in", docs_url=None, redoc_url=None, openapi_url=None)


class PairBody(BaseModel):
    code: str
    name: str = ""


class PasswordBody(BaseModel):
    user: str
    password: str
    name: str = ""


class PollBody(BaseModel):
    poll: str
    name: str = ""


def device_name(name: str, request: Request) -> str:
    name = re.sub(r"[\x00-\x1f<>]", "", name or "").strip()[:40]
    if name:
        return name
    ua = request.headers.get("user-agent", "")
    for key, label in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android phone"), ("Windows", "Windows PC"),
                       ("Macintosh", "Mac")):
        if key in ua:
            return label
    return "Phone"


def _https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


_pending: dict[str, dict] = {}         # hash(fm_pending cookie) -> {who, method, code, created}
_pending_lock = threading.Lock()


def _pending_of(request: Request) -> dict | None:
    token = request.cookies.get(PENDING_COOKIE)
    with _pending_lock:
        now = time.time()
        for k in [k for k, v in _pending.items() if v["created"] < now - PENDING_TTL]:
            del _pending[k]
        return _pending.get(_hash(token)) if token else None


def pending_state(request: Request) -> dict:
    p = _pending_of(request)
    return {"who": p["who"] if p else None, "code": bool(p and p["code"])}


def _progress(request: Request, name: str, extra: dict | None = None, **step) -> JSONResponse:
    """Record one pairing step (who=... after a sign-in, or code=True); pair the device once both are done."""
    token = request.cookies.get(PENDING_COOKIE)
    with _pending_lock:
        p = _pending.get(_hash(token)) if token else None
        if p is None or p["created"] < time.time() - PENDING_TTL:
            token = secrets.token_urlsafe(32)
            p = _pending[_hash(token)] = {"who": None, "method": None, "code": False, "created": time.time()}
        p.update(step)
        done = bool(p["who"] and p["code"])
        if done:
            del _pending[_hash(token)]
    if not done:
        resp = JSONResponse({"ok": True, "done": False, "who": p["who"], "code": p["code"],
                             "need": "code" if p["who"] else "signin", **(extra or {})})
        resp.set_cookie(PENDING_COOKIE, token, max_age=PENDING_TTL, httponly=True, secure=_https(request),
                        samesite="lax", path="/")
        return resp
    dev = DEVICES.add(device_name(name, request), p["method"])
    resp = JSONResponse({"ok": True, "done": True, "who": p["who"], **(extra or {})})
    resp.set_cookie(COOKIE, dev, max_age=DEVICE_DAYS * 86400, httponly=True, secure=_https(request), samesite="lax", path="/")
    resp.delete_cookie(PENDING_COOKIE, path="/")
    return resp


@auth_app.get("/login")
@auth_app.get("/pair")
def login_page():
    return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-cache"})


@auth_app.get("/auth/options")
def options(request: Request):
    cfg = settings()
    return {"google": google_ready(cfg), "password": bool(cfg.get("password_hash")),
            "signed_in": request.state.remote_device is not None, "pending": pending_state(request)}


@auth_app.post("/auth/pair")
def pair(b: PairBody, request: Request):
    LIMIT.check()
    if not use_pair_code(b.code):
        LIMIT.fail()
        raise HTTPException(400, "That pairing code is wrong, expired or already used - make a new one in Settings › Phone.")
    return _progress(request, b.name, code=True)


@auth_app.post("/auth/password")
def password_login(b: PasswordBody, request: Request):
    LIMIT.check()
    cfg = settings()
    ok = bool(cfg.get("password_hash")) and verify_password(cfg["password_hash"], b.password)
    if not ok or b.user.strip().lower() != str(cfg.get("password_user", "")).strip().lower():
        LIMIT.fail()
        raise HTTPException(401, "Wrong username or password.")
    return _progress(request, b.name, who=str(cfg["password_user"]), method="password")


@auth_app.post("/auth/google/begin")
def google_start():
    cfg = settings()
    if not google_ready(cfg):
        raise HTTPException(400, "Google sign-in isn't set up - see Settings › Phone on your PC.")
    return google_begin(cfg)


@auth_app.get(CALLBACK_PATH)
async def google_callback(request: Request):
    import html
    try:
        email = await google_finish(dict(request.query_params))
        ok, msg = True, f"Signed in as {email}. Go back to FM26 Analyst - it'll finish signing in by itself."
    except ValueError as e:
        ok, msg = False, str(e)
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
      <title>FM26 Analyst</title><body style="background:#0d1117;color:#e6edf3;font:16px system-ui;display:grid;place-items:center;height:90vh;margin:0 16px">
      <div style="max-width:420px;text-align:center"><h2>{'✓ Signed in' if ok else '✗ Not signed in'}</h2><p>{html.escape(msg)}</p>
      <p style="color:#8b98a8">You can close this window.</p></div><script>setTimeout(() => window.close(), 1500)</script></body>""")


@auth_app.post("/auth/google/poll")
def google_check(b: PollBody, request: Request):
    r = google_poll(b.poll)
    if r["status"] == "ok":
        return _progress(request, b.name, {"status": "ok"}, who=r["email"], method="google")
    return r


@auth_app.get("/auth/me")
def me(request: Request):
    d = request.state.remote_device
    if d is None:
        raise HTTPException(401, "Not signed in")
    return d


@auth_app.post("/auth/logout")
def logout(request: Request):
    d = request.state.remote_device
    if d:
        DEVICES.revoke(d["id"])
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    resp.delete_cookie(PENDING_COOKIE, path="/")
    return resp


# ---------------------------------------------------------------- the gate in front of the dashboard app
async def _send_json(send, status: int, body: dict, headers: list | None = None):
    data = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode()),
                            (b"cache-control", b"no-store")] + (headers or [])})
    await send({"type": "http.response.body", "body": data})


def _same_origin(headers: dict) -> bool:
    if headers.get(CSRF_HEADER) != "1":
        return False
    origin = headers.get("origin")
    return not origin or urlparse(origin).netloc == headers.get("host", "")


class RemoteGate:
    """ASGI app for the remote listener: sign-in pages, then the allow-listed dashboard for paired devices."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            return
        cfg = settings()
        client = (scope.get("client") or ("", 0))[0]
        proxies = {ip.strip() for ip in str(cfg.get("proxy_ip", "")).split(",") if ip.strip()}
        if proxies and client not in proxies:
            return await _send_json(send, 403, {"detail": "Not allowed from this address."})
        path, method = scope["path"], scope["method"]
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        device = DEVICES.find(Request(scope).cookies.get(COOKIE))
        scope.setdefault("state", {})["remote_device"] = device
        if method not in ("GET", "HEAD") and not _same_origin(headers):
            return await _send_json(send, 403, {"detail": "Blocked: request didn't come from the FM26 Analyst app."})
        if path in ("/login", "/pair") or path.startswith("/auth/"):
            return await auth_app(scope, receive, send)
        if method in ("GET", "HEAD") and (path.startswith("/static/") or path in SHELL):
            return await self.app(scope, receive, send)
        if device is None:
            if path.startswith("/api/"):
                return await _send_json(send, 401, {"detail": "Not signed in", "login": "/login"})
            return await RedirectResponse("/login", status_code=303)(scope, receive, send)
        if not allowed(method, path):
            return await _send_json(send, 403, {"detail": "Not available on the phone - use the dashboard on your PC."})
        return await self.app(scope, receive, send)


# ---------------------------------------------------------------- the listener itself
class RemoteServer:
    """Runs the gate on its own uvicorn server in a thread; started, stopped and restarted from Settings."""

    def __init__(self, gate):
        self.gate = gate
        self.server = None
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.bound: tuple[str, int] | None = None
        self.lock = threading.Lock()

    def apply(self, cfg: dict | None = None) -> dict:
        cfg = cfg or settings()
        with self.lock:
            want = (cfg.get("host") or "0.0.0.0", int(cfg.get("port") or 8766)) if cfg.get("enabled") else None
            if want == self.bound and self.running:
                return self.state()
            self._stop()
            if want:
                self._start(*want)
        return self.state()

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive() and self.server and self.server.started)

    def _start(self, host: str, port: int):
        import uvicorn
        self.error = None
        config = uvicorn.Config(self.gate, host=host, port=port, lifespan="off", log_level="warning",
                                proxy_headers=False, server_header=False, timeout_graceful_shutdown=2)
        server = uvicorn.Server(config)

        def run():
            try:
                server.run()
            except BaseException as e:          # uvicorn exits (SystemExit) when the port can't be bound
                self.error = f"couldn't listen on {host}:{port} - is the port in use?" if isinstance(e, SystemExit) else str(e)
            if not server.started and not self.error:
                self.error = f"couldn't listen on {host}:{port} - is the port in use?"

        self.server, self.bound = server, (host, port)
        self.thread = threading.Thread(target=run, daemon=True, name="remote-listener")
        self.thread.start()
        for _ in range(60):                       # up to 3 s for it to bind (or fail)
            if server.started or not self.thread.is_alive():
                break
            time.sleep(0.05)
        if not server.started:
            self.bound = None

    def _stop(self):
        if self.server and self.thread and self.thread.is_alive():
            self.server.should_exit = True
            self.thread.join(5)
        self.server, self.thread, self.bound = None, None, None

    def stop(self):
        with self.lock:
            self._stop()

    def state(self) -> dict:
        return {"running": self.running, "address": f"{self.bound[0]}:{self.bound[1]}" if self.bound else None,
                "error": self.error}
