"""Sign in with ChatGPT: use the user's ChatGPT plan for the coach (OpenAI's flow for locally hosted apps).

Follows developers.openai.com/siwc/token-sharing-open-source:
  * OAuth 2 authorization code + PKCE (S256) in the system browser, loopback redirect on 127.0.0.1;
  * dynamic client registration (client_id=dynamic_agent_client first, then the issued oaiapp_... id);
  * a persisted per-host ext_agent_host_id (urn:uuid);
  * ID token verified against OpenAI's JWKS (issuer, audience, nonce, expiry); plan scope checked;
  * Responses API with store=false, stream=true, no temperature, instructions instead of system messages;
  * rotating refresh tokens, refreshes serialised; sign-out revokes the refresh token.
Tokens live only in data/chatgpt.json, encrypted with DPAPI, and are never logged or sent to the browser.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
import uuid
from typing import AsyncIterator
from urllib.parse import urlencode

import httpx

import app_config
from keystore import protect, unprotect

AUTH = "https://auth.openai.com"
AUTHORIZE = AUTH + "/api/accounts/authorize"
TOKEN = AUTH + "/api/accounts/oauth/token"
DISCOVERY = AUTH + "/.well-known/openid-configuration"
API = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
APP_NAME = "FM26 Analyst"
CALLBACK_PATH = "/auth/callback"          # OpenAI's loopback contract: only the port may vary, path is fixed
MANAGE_USAGE = "https://chatgpt.com/#settings"
TIMEOUT = httpx.Timeout(120, connect=10)

_pending: dict[str, dict] = {}      # state -> {verifier, nonce, redirect_uri, created}
_refresh_lock = asyncio.Lock()


class ChatGPTError(Exception):
    pass


# ------------------------------------------------------------------ storage
def _path():
    return app_config.DATA / "chatgpt.json"


def load() -> dict:
    """{host_id, client_id, account: {...tokens}} with tokens decrypted (in memory only)."""
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if raw.get("secret"):
        try:
            raw["account"] = json.loads(unprotect(raw.pop("secret")))
        except (OSError, ValueError):
            raw.pop("secret", None)
    raw.pop("client_id", None)   # pre-per-account format: an id of unknown account/workspace is never reused
    return raw


def store(state: dict) -> None:
    out = {k: v for k, v in state.items() if k != "account"}
    if state.get("account"):
        out["secret"] = protect(json.dumps(state["account"]))
    app_config.DATA.mkdir(exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    tmp.replace(_path())                       # atomic


def account_client(state: dict) -> str | None:
    """The issued client id registered for the signed-in account."""
    return state.get("clients", {}).get((state.get("account") or {}).get("sub", ""))


def host_id(state: dict) -> str:
    if not state.get("host_id"):
        state["host_id"] = f"urn:uuid:{uuid.uuid4()}"
        store(state)
    return state["host_id"]


def status() -> dict:
    s = load()
    a = s.get("account") or {}
    signed = bool(a.get("refresh_token") or a.get("access_token"))
    return {"signed_in": signed, "email": a.get("email"), "plan_usage": signed and PLAN_SCOPE in (a.get("scope") or "").split(),
            "model": app_config.load_config()["llm"].get("chatgpt_model") or "", "manage_usage_url": MANAGE_USAGE,
            "first_use_ack": bool(s.get("first_use_ack"))}


# ------------------------------------------------------------------ sign-in
def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def start(redirect_uri: str) -> str:
    """Authorization URL for the system browser. redirect_uri must be http://127.0.0.1:<port>/auth/callback."""
    if not redirect_uri.startswith("http://127.0.0.1:"):
        raise ChatGPTError("The callback must be on 127.0.0.1 (open the dashboard at http://127.0.0.1:8765)")
    s = load()
    verifier, state, nonce = _b64url(secrets.token_bytes(48)), _b64url(secrets.token_bytes(24)), _b64url(secrets.token_bytes(24))
    for k in [k for k, v in _pending.items() if time.time() - v["created"] > 900]:
        _pending.pop(k)
    # Client ids are registered per account/workspace: reuse one only when re-authorising that same signed-in
    # account; otherwise (new or different account) start a fresh registration with dynamic_agent_client.
    acct = s.get("account") or {}
    client_id = s.get("clients", {}).get(acct.get("sub", "")) if acct.get("id_token") else None
    _pending[state] = {"verifier": verifier, "nonce": nonce, "redirect_uri": redirect_uri, "created": time.time(),
                       "client_id": client_id}
    params = {"client_id": client_id or "dynamic_agent_client", "ext_agent_host_id": host_id(s),
              "response_type": "code", "redirect_uri": redirect_uri, "scope": SCOPES, "resource": API,
              "state": state, "nonce": nonce, "code_challenge_method": "S256",
              "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest())}
    if client_id:
        params["id_token_hint"] = acct["id_token"]
        if acct.get("email"):
            params["login_hint"] = acct["email"]
    else:
        params["agent_name_hint"] = APP_NAME
    return AUTHORIZE + "?" + urlencode(params)


def _oauth_error(r: httpx.Response) -> str:
    """OAuth error code + description from a failed token response (these never contain tokens)."""
    try:
        b = r.json()
    except ValueError:
        return r.text[:200] or r.reason_phrase
    err = b.get("error")
    if isinstance(err, dict):
        return " ".join(str(err.get(k)) for k in ("code", "message") if err.get(k)) or str(err)[:200]
    return " - ".join(str(x) for x in (err, b.get("error_description")) if x) or str(b)[:200]


async def _verify_id_token(id_token: str, client_id: str, nonce: str) -> dict:
    import jwt
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        jwks_uri = (await c.get(DISCOVERY)).json()["jwks_uri"]
        jwks = (await c.get(jwks_uri)).json()
    kid = jwt.get_unverified_header(id_token).get("kid")
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not key:
        raise ChatGPTError("ID token signing key not found")
    claims = jwt.decode(id_token, jwt.PyJWK(key).key, algorithms=[key.get("alg", "RS256")], audience=client_id,
                        issuer=AUTH, options={"require": ["exp", "iat", "sub"]})
    if claims.get("nonce") != nonce:
        raise ChatGPTError("ID token nonce mismatch")
    return claims


async def finish(params: dict) -> dict:
    """Handle the loopback callback. Returns status()."""
    pend = _pending.pop(params.get("state") or "", None)
    if not pend:
        raise ChatGPTError("Sign-in expired or was started elsewhere - try again")
    if params.get("error"):
        raise ChatGPTError("Sign-in cancelled" if params["error"] == "access_denied" else f"Sign-in failed: {params['error']}")
    s = load()
    issued = params.get("client_id")
    if pend["client_id"] and issued and issued != pend["client_id"]:
        raise ChatGPTError("Unexpected client id in the callback - sign-in rejected")
    client_id = pend["client_id"] or issued
    if not client_id or not client_id.startswith("oaiapp_"):
        raise ChatGPTError("Registration incomplete (no client id returned) - try again")
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(TOKEN, data={"grant_type": "authorization_code", "client_id": client_id, "code": params.get("code", ""),
                                      "code_verifier": pend["verifier"], "redirect_uri": pend["redirect_uri"], "resource": API})
    if r.status_code != 200:
        print(f"ChatGPT token exchange: {r.status_code} {_oauth_error(r)} client={client_id[:10]}… "
              f"redirect={pend['redirect_uri']} verifier_len={len(pend['verifier'])} "
              f"age={time.time() - pend['created']:.0f}s", flush=True)
        raise ChatGPTError(f"Token exchange failed ({r.status_code}: {_oauth_error(r)}) - try signing in again")
    tok = r.json()
    claims = await _verify_id_token(tok["id_token"], client_id, pend["nonce"])
    prev = s.get("account") or {}
    if prev.get("sub") and prev["sub"] != claims["sub"]:
        prev = {}                                  # a different ChatGPT account: replace
    s.setdefault("clients", {})[claims["sub"]] = client_id      # this account's registration, for later re-auth
    s["account"] = {"sub": claims["sub"], "email": claims.get("email"), "access_token": tok["access_token"],
                    "refresh_token": tok.get("refresh_token") or prev.get("refresh_token"), "id_token": tok["id_token"],
                    "scope": tok.get("scope", ""), "expires_at": time.time() + int(tok.get("expires_in", 3600))}
    store(s)
    return status()


async def sign_out() -> dict:
    s = load()
    a = s.get("account") or {}
    confirmed = True
    cid = account_client(s)
    if a.get("refresh_token") and cid:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                rev = (await c.get(DISCOVERY)).json().get("revocation_endpoint")
                if rev:
                    r = await c.post(rev, data={"token": a["refresh_token"], "token_type_hint": "refresh_token",
                                                "client_id": cid})
                    confirmed = r.status_code == 200
        except httpx.HTTPError:
            confirmed = False
    s.pop("account", None)                         # keep client_id + host_id for the next sign-in
    store(s)
    return {"signed_out": True, "revocation_confirmed": confirmed}


def ack_first_use() -> None:
    s = load()
    s["first_use_ack"] = True
    store(s)


async def access_token() -> str:
    """A valid access token, refreshing (serialised) when within 5 minutes of expiry."""
    async with _refresh_lock:
        s = load()
        a = s.get("account") or {}
        if not a.get("access_token"):
            raise ChatGPTError("Not signed in with ChatGPT - Settings › AI coach › Continue with ChatGPT")
        if a.get("expires_at", 0) - time.time() > 300:
            return a["access_token"]
        if not a.get("refresh_token"):
            raise ChatGPTError("ChatGPT session expired - sign in again")
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(TOKEN, data={"grant_type": "refresh_token", "client_id": account_client(s),
                                          "refresh_token": a["refresh_token"], "resource": API})
        if r.status_code != 200:
            code = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("error", "")
            if code in ("invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
                        "refresh_token_invalidated", "refresh_token_reused"):
                s.pop("account", None)
                store(s)
                raise ChatGPTError("ChatGPT session ended - sign in again in Settings")
            raise ChatGPTError(f"Couldn't refresh the ChatGPT session ({r.status_code}) - try again shortly")
        tok = r.json()
        a.update(access_token=tok["access_token"], refresh_token=tok.get("refresh_token", a["refresh_token"]),
                 scope=tok.get("scope", a.get("scope")), expires_at=time.time() + int(tok.get("expires_in", 3600)))
        if tok.get("id_token"):
            a["id_token"] = tok["id_token"]
        store(s)
        return a["access_token"]


# ------------------------------------------------------------------ inference
# OpenAI publishes no per-model usage rates for plan usage; its descriptions rank the families:
# Astra "frontier ... most demanding", Sol "workhorse" (6.1-Sol: "near-Astra performance at a lower cost"),
# Terra "balanced ... straightforward", Luna "fast and affordable". 1 = lightest on your plan, 4 = heaviest.
USAGE_BY_FAMILY = {"astra": 4, "sol": 3, "terra": 2, "luna": 1}
USAGE_LABEL = {1: "lowest usage", 2: "low usage", 3: "moderate usage", 4: "highest usage"}


def usage_tier(slug: str) -> int | None:
    return next((v for k, v in USAGE_BY_FAMILY.items() if k in slug.lower()), None)


async def list_models() -> list[dict]:
    """Models this plan lists, in OpenAI's order (best first), with an estimated relative usage tier.

    Plan accounts get {"models": [{slug, display_name, description, availability_nux, ...}]}."""
    tok = await access_token()
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(API + "/models", headers={"Authorization": f"Bearer {tok}"})
    if r.status_code != 200:
        raise ChatGPTError(f"Couldn't list models ({r.status_code})")
    body = r.json()
    out = []
    for m in body.get("models") or body.get("data") or []:
        mid = m.get("slug") or m.get("id")
        if mid and m.get("visibility", "list") == "list":
            tier = usage_tier(mid)
            out.append({"id": mid, "name": m.get("display_name") or mid, "description": m.get("description") or "",
                        "usage": tier, "usage_label": USAGE_LABEL.get(tier, "usage unknown"),
                        "note": (m.get("availability_nux") or {}).get("message") or "",
                        "default_reasoning": m.get("default_reasoning_level") or "",
                        "reasoning_levels": [r.get("effort") for r in m.get("supported_reasoning_levels") or []]})
    return out


ERRORS = {
    "subscription_sharing_usage_limit_exceeded": "You've reached this app's ChatGPT plan usage limit. Review it in ChatGPT settings › Usage (Manage usage).",
    "subscription_sharing_usage_unavailable": "ChatGPT plan usage is temporarily unavailable - try again in a minute.",
    "subscription_sharing_user_unavailable": "ChatGPT plan usage is temporarily unavailable - try again in a minute.",
    "subscription_sharing_user_not_eligible": "This ChatGPT account isn't eligible to use its plan in other apps.",
    "subscription_sharing_unsupported_capability": "The chosen model or option isn't supported with ChatGPT plan usage - pick another model in Settings.",
    "subscription_sharing_invalid_user": "ChatGPT didn't accept this session - sign out and sign in again in Settings.",
}


def _err(body: dict, status: int) -> str:
    e = body.get("error") or (body.get("response") or {}).get("error") or (body if "code" in body else {})
    code = e.get("code") if isinstance(e, dict) else None
    return ERRORS.get(code) or f"ChatGPT returned {status}: {(e.get('message') if isinstance(e, dict) else e) or 'error'}"


def _input_items(messages: list[dict]) -> list[dict]:
    """Chat-completions messages (incl. assistant tool_calls and tool results) -> Responses API input items."""
    sysmsgs = [m["content"] for m in messages if m["role"] == "system"]
    items: list[dict] = [{"role": "developer", "content": c} for c in sysmsgs[1:]]
    for m in messages:
        if m["role"] in ("user", "assistant") and m.get("content"):
            items.append({"role": m["role"], "content": m["content"]})
        for tc in m.get("tool_calls") or []:
            items.append({"type": "function_call", "call_id": tc["id"], "name": tc["function"]["name"],
                          "arguments": tc["function"]["arguments"]})
        if m["role"] == "tool":
            items.append({"type": "function_call_output", "call_id": m["tool_call_id"], "output": m["content"]})
    return items


async def stream_chat(model: str, messages: list[dict], effort: str | None = None) -> AsyncIterator[str]:
    """Text deltas only (no tools)."""
    async for kind, val in stream_events(model, messages, effort):
        if kind == "delta":
            yield val


async def stream_events(model: str, messages: list[dict], effort: str | None = None,
                        tools: list[dict] | None = None) -> AsyncIterator[tuple]:
    """Chat-completions style messages -> Responses API stream, as events:
    ("delta", text) | ("tool_call", {id, name, arguments}) | ("usage", {input, output}).
    System messages become instructions / developer input; effort = reasoning effort (None = model default)."""
    if not model:
        raise ChatGPTError("Pick a ChatGPT model in Settings › AI coach")
    sysmsgs = [m["content"] for m in messages if m["role"] == "system"]
    body = {"model": model, "store": False, "stream": True, "input": _input_items(messages)}
    if sysmsgs:
        body["instructions"] = sysmsgs[0]
    if effort:
        body["reasoning"] = {"effort": effort}
    if tools:
        body["tools"] = [{"type": "function", **t} for t in tools]
    tok = await access_token()
    completed = False
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for attempt, wait in enumerate((1, 3, None)):     # 503 = temporarily unavailable: bounded backoff, per OpenAI
            r = await c.send(c.build_request("POST", API + "/responses", json=body,
                                             headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}),
                             stream=True)
            if r.status_code == 200:
                break
            raw = await r.aread()
            await r.aclose()
            if r.status_code == 503 and wait:
                await asyncio.sleep(wait)
                continue
            try:
                msg = _err(json.loads(raw), r.status_code)
            except ValueError:
                msg = ("ChatGPT is temporarily unavailable - try again in a minute" if r.status_code == 503
                       else f"ChatGPT returned {r.status_code}")
            raise ChatGPTError(msg)
        try:
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except ValueError:
                    continue
                t = ev.get("type", "")
                if t == "response.output_text.delta":
                    yield ("delta", ev.get("delta", ""))
                elif t == "response.output_item.done" and (ev.get("item") or {}).get("type") == "function_call":
                    it = ev["item"]
                    yield ("tool_call", {"id": it.get("call_id") or it.get("id"), "name": it.get("name", ""),
                                         "arguments": it.get("arguments") or "{}"})
                elif t == "response.completed":
                    u = (ev.get("response") or {}).get("usage") or {}
                    if u:
                        yield ("usage", {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                                         "plan": True})
                    completed = True
                    return
                elif t in ("response.failed", "response.incomplete", "error"):
                    raise ChatGPTError(_err(ev, 200) if t != "response.incomplete" else "The answer was cut short - try again")
        finally:
            await r.aclose()
    if not completed:
        raise ChatGPTError("The connection to ChatGPT dropped before the answer finished - try again")
