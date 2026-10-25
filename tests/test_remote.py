"""Phone companion: the remote gate, pairing, password and Google sign-in (no game, no real Google)."""
import json
import socket
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import app_config
from web import remote

H = {"X-FM-Remote": "1"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "DB_PATH", tmp_path / "w.db")
    monkeypatch.setattr(app_config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    monkeypatch.setattr(remote, "LIMIT", remote.Limiter())
    from store.db import connect
    connect(app_config.DB_PATH).close()
    from web import app as web
    monkeypatch.setattr(web.REMOTE, "apply", lambda cfg=None: {"running": False, "address": None, "error": None})
    desk, phone = TestClient(web.app), TestClient(web.GATE)
    desk.put("/api/remote", json={"enabled": True, "password_user": "me", "password": PW})
    return desk, phone


PW = "correct horse battery"


def new_code(desk):
    p = desk.post("/api/remote/pair").json()
    assert p["url"].endswith("#" + p["code"].replace("-", ""))
    return p["code"]


def sign_in(phone, name="Test phone"):
    r = phone.post("/auth/password", json={"user": "me", "password": PW, "name": name}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def pair(desk, phone, name="Test phone"):
    """Both steps: the password, then the code (typed, lower case and with the dash, as a person might)."""
    assert sign_in(phone, name) == {"ok": True, "done": False, "who": "me", "code": False, "need": "code"}
    code = new_code(desk)
    r = phone.post("/auth/pair", json={"code": code.lower(), "name": name}, headers=H)
    assert r.status_code == 200 and r.json()["done"], r.text
    return code


def test_signed_out_phone_sees_only_sign_in(env):
    desk, phone = env
    assert phone.get("/api/overview").status_code == 401
    r = phone.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert phone.get("/login").status_code == 200
    assert phone.get("/static/app.js").status_code == 200
    assert phone.get("/manifest.webmanifest").status_code == 200
    assert phone.get("/auth/options").json() == {"google": False, "password": True, "signed_in": False,
                                                  "pending": {"who": None, "code": False}}


def test_code_alone_or_sign_in_alone_is_not_enough(env):
    desk, phone = env
    r = phone.post("/auth/pair", json={"code": new_code(desk)}, headers=H).json()
    assert r == {"ok": True, "done": False, "who": None, "code": True, "need": "signin"}
    assert phone.get("/api/overview").status_code == 401
    assert phone.get("/auth/options").json()["pending"] == {"who": None, "code": True}
    other = TestClient(phone.app)
    sign_in(other)
    assert other.get("/api/overview").status_code == 401
    # code first, then sign-in also completes it
    assert sign_in(phone)["done"] is True
    assert phone.get("/api/overview").status_code == 200
    assert phone.get("/auth/me").json()["method"] == "password"
    assert phone.cookies.get(remote.PENDING_COOKIE) is None


def test_no_codes_until_a_sign_in_exists(env):
    desk, phone = env
    desk.put("/api/remote", json={"clear_password": True})
    r = desk.post("/api/remote/pair")
    assert r.status_code == 400 and "sign-in" in r.json()["detail"]


def test_pending_pairing_expires(env, monkeypatch):
    desk, phone = env
    sign_in(phone)
    for p in remote._pending.values():
        p["created"] -= remote.PENDING_TTL + 1
    r = phone.post("/auth/pair", json={"code": new_code(desk)}, headers=H).json()
    assert r["done"] is False and r["need"] == "signin"


def test_qr_pairing_and_allow_list(env, monkeypatch):
    desk, phone = env
    code = pair(desk, phone)
    assert phone.get("/api/status").json()["remote"] is True
    assert desk.get("/api/status").json()["remote"] is False
    assert phone.get("/api/overview").status_code == 200
    assert phone.get("/auth/me").json()["name"] == "Test phone"
    assert phone.get("/auth/options").json()["signed_in"] is True
    # desktop-only parts are never reachable from the phone, even signed in
    from web import app as web
    quit_called = []
    monkeypatch.setattr(web.threading, "Timer", lambda *a, **k: quit_called.append(a))
    for method, path in (("GET", "/api/settings"), ("PUT", "/api/settings"), ("POST", "/api/shutdown"),
                         ("GET", "/api/remote"), ("POST", "/api/remote/pair"), ("GET", "/api/snapshots"),
                         ("POST", "/api/snapshots"), ("POST", "/api/backup"), ("PUT", "/api/coach/prompt"),
                         ("POST", "/api/chatgpt/start"), ("GET", "/auth/callback")):
        r = phone.request(method, path, headers=H, json={})
        assert r.status_code in (403, 404), (method, path, r.status_code)
    assert not quit_called
    # a code works once
    assert phone.post("/auth/pair", json={"code": code}, headers=H).status_code == 400


def test_changes_need_the_app_header_and_same_origin(env):
    desk, phone = env
    pair(desk, phone)
    assert phone.put("/api/auto", json={"enabled": False}).status_code == 403
    assert phone.put("/api/auto", json={"enabled": False}, headers={**H, "Origin": "https://evil.example"}).status_code == 403
    assert phone.put("/api/auto", json={"enabled": False}, headers={**H, "Origin": "http://testserver"}).status_code == 200


def test_expired_pair_code(env):
    desk, phone = env
    code = new_code(desk)
    remote._pairs[remote._hash(remote.norm_code(code))] = time.time() - 1
    assert phone.post("/auth/pair", json={"code": code}, headers=H).status_code == 400


def test_revoked_device_is_signed_out(env):
    desk, phone = env
    pair(desk, phone)
    dev = desk.get("/api/remote").json()["devices"][0]
    assert "hash" not in dev
    assert desk.delete(f"/api/remote/devices/{dev['id']}").status_code == 200
    assert phone.get("/api/overview").status_code == 401


def test_device_file_stores_only_a_hash(env, tmp_path):
    desk, phone = env
    pair(desk, phone)
    token = phone.cookies.get(remote.COOKIE)
    stored = (tmp_path / "devices.json").read_text()
    assert token and token not in stored and remote._hash(token) in stored


def test_password_sign_in_and_lockout(env):
    desk, phone = env
    assert desk.put("/api/remote", json={"password_user": "me", "password": "short"}).status_code == 400
    r = desk.put("/api/remote", json={"password_user": "Me", "password": PW}).json()
    assert r["password_set"] and "hash" not in json.dumps(r)
    assert "correct horse" not in (app_config.CONFIG_PATH).read_text()
    assert phone.post("/auth/password", json={"user": "me", "password": PW}, headers=H).status_code == 200
    other = TestClient(phone.app)
    for _ in range(remote.MAX_FAILURES):
        assert other.post("/auth/password", json={"user": "me", "password": "wrong"}, headers=H).status_code == 401
    assert other.post("/auth/password", json={"user": "me", "password": PW}, headers=H).status_code == 429
    assert other.post("/auth/pair", json={"code": "AAAA-AAAA"}, headers=H).status_code == 429


def test_google_settings_are_validated_and_secret_encrypted(env):
    desk, phone = env
    assert desk.put("/api/remote", json={"public_url": "http://fm.example.com"}).status_code == 400
    assert desk.put("/api/remote", json={"allowed_emails": ["not-an-email"]}).status_code == 400
    r = desk.put("/api/remote", json={"public_url": "https://fm.example.com/", "google_client_id": "cid",
                                      "google_client_secret": "s3cret", "allowed_emails": ["Me@Gmail.com"]}).json()
    assert r["google_ready"] and r["redirect_uri"] == "https://fm.example.com/auth/google/callback"
    assert r["allowed_emails"] == ["me@gmail.com"] and "s3cret" not in json.dumps(r)
    assert "s3cret" not in app_config.CONFIG_PATH.read_text()
    assert app_config.load_config()["remote"]["google_client_secret"] == "s3cret"
    assert phone.get("/auth/options").json()["google"] is True


def claims(**kw):
    base = {"iss": "https://accounts.google.com", "aud": "cid", "exp": time.time() + 60, "nonce": "n",
            "email": "me@gmail.com", "email_verified": True}
    return {**base, **kw}


def test_google_claims_checks():
    cfg = {"google_client_id": "cid", "allowed_emails": ["me@gmail.com"]}
    assert remote.check_claims(claims(), cfg, "n") == "me@gmail.com"
    for bad in (claims(aud="other"), claims(iss="evil"), claims(exp=1), claims(nonce="x"),
                claims(email_verified=False), claims(email="someone@gmail.com")):
        with pytest.raises(ValueError):
            remote.check_claims(bad, cfg, "n")


def test_google_flow_with_fake_token_endpoint(env, monkeypatch):
    desk, phone = env
    desk.put("/api/remote", json={"public_url": "https://fm.example.com", "google_client_id": "cid",
                                  "google_client_secret": "sec", "allowed_emails": ["me@gmail.com"]})
    b = phone.post("/auth/google/begin", headers=H).json()
    q = dict(httpx.URL(b["url"]).params)
    assert q["redirect_uri"] == "https://fm.example.com/auth/google/callback" and q["code_challenge_method"] == "S256"
    assert phone.post("/auth/google/poll", json={"poll": b["poll"]}, headers=H).json() == {"status": "pending"}

    payload = remote._b64url(json.dumps(claims(nonce=q["nonce"])).encode())

    def token(request):
        form = dict(httpx.QueryParams(request.content.decode()))
        assert form["client_secret"] == "sec" and form["code"] == "abc" and form["code_verifier"]
        return httpx.Response(200, json={"id_token": f"h.{payload}.sig"})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(token)))
    # the callback may land in another browser: it has no cookie and doesn't need one
    r = TestClient(phone.app).get(f"/auth/google/callback?code=abc&state={q['state']}")
    assert "Signed in as me@gmail.com" in r.text
    r = phone.post("/auth/google/poll", json={"poll": b["poll"], "name": "Pixel"}, headers=H).json()
    assert r["status"] == "ok" and r["who"] == "me@gmail.com" and r["done"] is False
    assert phone.get("/api/overview").status_code == 401           # Google alone isn't enough either
    assert phone.post("/auth/pair", json={"code": new_code(desk)}, headers=H).json()["done"] is True
    assert phone.get("/auth/me").json()["method"] == "google"
    assert phone.post("/auth/google/poll", json={"poll": b["poll"]}, headers=H).json()["status"] == "error"


def test_proxy_ip_restriction(env):
    desk, phone = env
    desk.put("/api/remote", json={"proxy_ip": "10.0.0.5"})
    assert phone.get("/login").status_code == 403          # the test client isn't 10.0.0.5
    assert desk.put("/api/remote", json={"proxy_ip": "not-an-ip"}).status_code == 400


def test_listener_starts_and_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = remote.RemoteServer(remote.RemoteGate(lambda scope, receive, send: None))
    st = srv.apply({"enabled": True, "host": "127.0.0.1", "port": port})
    try:
        assert st["running"] and st["address"] == f"127.0.0.1:{port}"
        assert httpx.get(f"http://127.0.0.1:{port}/api/overview").status_code == 401
    finally:
        srv.apply({"enabled": False})
    assert not srv.state()["running"]
