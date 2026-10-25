"""AI coach: key encryption, context, chat streaming, ChatGPT sign-in + Responses parsing (network mocked)."""
import asyncio
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import app_config
import keystore
from llm import chatgpt, client
from tests.test_web import client as web_client  # noqa: F401 - fixture


def test_keystore_roundtrip():
    tok = keystore.protect("sk-secret-123")
    assert "sk-secret" not in tok and keystore.unprotect(tok) == "sk-secret-123"


def test_api_key_encrypted_on_disk_and_migrated(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"llm": {"api_key": "sk-old-plaintext"}}))
    assert app_config.load_config()["llm"]["api_key"] == "sk-old-plaintext"     # old plaintext still works...
    disk = (tmp_path / "config.json").read_text()
    assert "sk-old-plaintext" not in disk and "api_key_enc" in disk             # ...and is encrypted on first load
    assert app_config.load_config()["llm"]["api_key"] == "sk-old-plaintext"


def _mock_async_client(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler), **k))


def test_openai_compatible_stream(monkeypatch):
    sse = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in ("Rest ", "Doué")) + "data: [DONE]\n\n"
    seen = {}

    def handler(req):
        seen["auth"], seen["body"] = req.headers.get("authorization"), json.loads(req.content)
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    _mock_async_client(monkeypatch, handler)

    async def run():
        return "".join([d async for d in client.stream_chat(
            {"base_url": "https://x.test/v1", "api_key": "sk-1", "model": "m", "temperature": 0.4}, [{"role": "user", "content": "hi"}])])
    assert asyncio.run(run()) == "Rest Doué"
    assert seen["auth"] == "Bearer sk-1" and seen["body"]["stream"] is True


def test_chat_endpoint_streams_with_context(web_client, monkeypatch):  # noqa: F811
    captured = {}

    async def fake(llm, messages, tools=None):
        captured["messages"] = messages
        yield ("delta", "Start ")
        yield ("delta", "Rio.")
    monkeypatch.setattr(client, "stream_events", fake)
    r = web_client.post("/api/chat", json={"page": "player/1", "messages": [{"role": "user", "content": "Should he start?"}]})
    events = [json.loads(l[5:]) for l in r.text.splitlines() if l.startswith("data:")]
    assert "".join(e.get("delta", "") for e in events) == "Start Rio." and events[-1] == {"done": True}
    assert "conversation" in events[0]
    sysmsgs = [m["content"] for m in captured["messages"] if m["role"] == "system"]
    assert "assistant manager" in sysmsgs[0] and "PAGE IN VIEW: player page of Alex Rivers" in sysmsgs[1]
    assert web_client.post("/api/chat", json={"messages": []}).status_code == 400


def test_settings_reject_bad_url(web_client):  # noqa: F811
    assert web_client.put("/api/settings", json={"llm_base_url": "ftp://x"}).status_code == 400
    assert web_client.put("/api/settings", json={"llm_provider": "nope"}).status_code == 400


# ---------------------------------------------------------------- ChatGPT plan
@pytest.fixture
def gpt(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "DATA", tmp_path)
    monkeypatch.setattr(app_config, "CONFIG_PATH", tmp_path / "config.json")
    chatgpt._pending.clear()
    return tmp_path


def test_chatgpt_start_url(gpt):
    url = chatgpt.start("http://127.0.0.1:8765/auth/callback")
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith(chatgpt.AUTHORIZE)
    assert q["client_id"] == "dynamic_agent_client" and q["agent_name_hint"] == "FM26 Analyst"
    assert q["ext_agent_host_id"].startswith("urn:uuid:") and q["code_challenge_method"] == "S256"
    assert set(q["scope"].split()) >= {"openid", "offline_access", "chatgpt.tokens.use.direct"}
    assert q["resource"] == "https://api.openai.com/v1"
    host = q["ext_agent_host_id"]
    q2 = {k: v[0] for k, v in parse_qs(urlparse(chatgpt.start("http://127.0.0.1:8765/auth/callback")).query).items()}
    assert q2["ext_agent_host_id"] == host                                     # persisted per host
    with pytest.raises(chatgpt.ChatGPTError):
        chatgpt.start("http://localhost:8765/auth/callback")             # localhost is not allowed


def test_chatgpt_callback_rejects_unknown_state(gpt):
    with pytest.raises(chatgpt.ChatGPTError, match="expired"):
        asyncio.run(chatgpt.finish({"state": "forged", "code": "x", "client_id": "oaiapp_1"}))


def test_chatgpt_tokens_encrypted_and_responses_stream(gpt, monkeypatch):
    chatgpt.store({"host_id": "urn:uuid:1", "clients": {"u1": "oaiapp_1"},
                   "account": {"sub": "u1", "email": "a@b.c", "access_token": "at-secret", "refresh_token": "rt-secret",
                               "scope": "openid chatgpt.tokens.use.direct", "expires_at": time.time() + 3600}})
    disk = (gpt / "chatgpt.json").read_text()
    assert "at-secret" not in disk and "rt-secret" not in disk
    assert chatgpt.status()["plan_usage"] is True

    seen = {}
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in (
        {"type": "response.output_text.delta", "delta": "Rest "}, {"type": "response.output_text.delta", "delta": "Hart"},
        {"type": "response.completed"}))

    def handler(req):
        seen["body"], seen["auth"] = json.loads(req.content), req.headers["authorization"]
        return httpx.Response(200, text=sse)
    _mock_async_client(monkeypatch, handler)

    async def run():
        return "".join([d async for d in chatgpt.stream_chat("gpt-x", [
            {"role": "system", "content": "SYS"}, {"role": "system", "content": "DATA"}, {"role": "user", "content": "q"}])])
    assert asyncio.run(run()) == "Rest Hart"
    b = seen["body"]
    assert seen["auth"] == "Bearer at-secret" and b["store"] is False and b["stream"] is True
    assert b["instructions"] == "SYS" and "temperature" not in b and "reasoning" not in b
    assert b["input"][0] == {"role": "developer", "content": "DATA"} and all(i["role"] != "system" for i in b["input"])


def test_chatgpt_usage_limit_message(gpt, monkeypatch):
    chatgpt.store({"client_id": "oaiapp_1", "account": {"access_token": "t", "refresh_token": "r", "expires_at": time.time() + 3600}})
    _mock_async_client(monkeypatch, lambda req: httpx.Response(429, json={"error": {"code": "subscription_sharing_usage_limit_exceeded"}}))

    async def run():
        return [d async for d in chatgpt.stream_chat("gpt-x", [{"role": "user", "content": "q"}])]
    with pytest.raises(chatgpt.ChatGPTError, match="usage limit"):
        asyncio.run(run())


def test_chatgpt_refresh_rotates_tokens(gpt, monkeypatch):
    chatgpt.store({"clients": {"u1": "oaiapp_1"}, "account": {"sub": "u1", "access_token": "old", "refresh_token": "r1", "expires_at": time.time() + 10}})
    seen = {}

    def handler(req):
        seen["form"] = parse_qs(req.content.decode())
        return httpx.Response(200, json={"access_token": "new", "refresh_token": "r2", "expires_in": 3600, "scope": "chatgpt.tokens.use.direct"})
    _mock_async_client(monkeypatch, handler)
    assert asyncio.run(chatgpt.access_token()) == "new"
    assert seen["form"]["grant_type"] == ["refresh_token"] and seen["form"]["client_id"] == ["oaiapp_1"]
    assert chatgpt.load()["account"]["refresh_token"] == "r2"


def test_chatgpt_client_ids_are_per_account(gpt):
    cb = "http://127.0.0.1:8765/auth/callback"
    qs = lambda url: {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    # an id saved by an older version (registered under some other account's workspace) is never reused
    (gpt / "chatgpt.json").write_text(json.dumps({"host_id": "urn:uuid:1", "client_id": "oaiapp_other_workspace"}))
    assert qs(chatgpt.start(cb))["client_id"] == "dynamic_agent_client"
    # re-authorising the signed-in account reuses that account's own registration, with id_token_hint
    chatgpt.store({"host_id": "urn:uuid:1", "clients": {"u1": "oaiapp_mine"},
                   "account": {"sub": "u1", "id_token": "idt", "email": "me@x.y", "access_token": "a"}})
    q = qs(chatgpt.start(cb))
    assert q["client_id"] == "oaiapp_mine" and q["id_token_hint"] == "idt" and "agent_name_hint" not in q
    # after sign-out a new sign-in (maybe another account) registers fresh
    s = chatgpt.load(); s.pop("account"); chatgpt.store(s)
    assert qs(chatgpt.start(cb))["client_id"] == "dynamic_agent_client"

def test_chatgpt_model_list_plan_format(gpt, monkeypatch):
    chatgpt.store({"clients": {"u1": "oaiapp_1"}, "account": {"sub": "u1", "access_token": "t", "refresh_token": "r",
                                                               "expires_at": time.time() + 3600}})
    plan = {"models": [{"slug": "gpt-6.1-sol", "display_name": "GPT-6.1-Sol", "visibility": "list"},
                       {"slug": "gpt-reserve", "display_name": "GPT-Reserve", "visibility": "hide"},
                       {"slug": "gpt-6-luna", "display_name": "GPT-6-Luna", "visibility": "list"}]}
    _mock_async_client(monkeypatch, lambda req: httpx.Response(200, json=plan))
    ms = asyncio.run(chatgpt.list_models())
    assert [(m["id"], m["name"], m["usage"]) for m in ms] == [("gpt-6.1-sol", "GPT-6.1-Sol", 3), ("gpt-6-luna", "GPT-6-Luna", 1)]
    assert chatgpt.usage_tier("gpt-6-astra") == 4 and chatgpt.usage_tier("gpt-5.6-terra") == 2

def test_coach_prompt_edit_and_reset(web_client):  # noqa: F811
    from llm.client import default_prompt
    p = web_client.get("/api/coach/prompt").json()
    assert p["custom"] is False and p["text"] == default_prompt()
    p = web_client.put("/api/coach/prompt", json={"text": "Be brief. Only talk about defenders."}).json()
    assert p["custom"] is True and p["text"].startswith("Be brief")
    captured = {}

    async def fake(llm, messages, tools=None):
        captured["sys"] = messages[0]["content"]
        yield ("delta", "ok")
    import llm.client as lc
    orig = lc.stream_events
    lc.stream_events = fake
    try:
        web_client.post("/api/chat", json={"messages": [{"role": "user", "content": "q"}]})
    finally:
        lc.stream_events = orig
    assert captured["sys"] == "Be brief. Only talk about defenders."
    p = web_client.put("/api/coach/prompt", json={"text": ""}).json()          # reset
    assert p["custom"] is False and p["text"] == default_prompt()


def test_thinking_depth_setting(web_client):  # noqa: F811
    assert web_client.put("/api/settings", json={"llm_chatgpt_effort": "low"}).json()["llm_chatgpt_effort"] == "low"
    assert web_client.put("/api/settings", json={"llm_chatgpt_effort": "extreme"}).status_code == 400

def test_chatgpt_retries_503(gpt, monkeypatch):
    chatgpt.store({"clients": {"u1": "oaiapp_1"}, "account": {"sub": "u1", "access_token": "t", "refresh_token": "r",
                                                               "expires_at": time.time() + 3600}})
    calls = []
    ok = "".join(f"data: {json.dumps(e)}\n\n" for e in ({"type": "response.output_text.delta", "delta": "hi"},
                                                         {"type": "response.completed"}))

    def handler(req):
        calls.append(1)
        return httpx.Response(503, text="busy") if len(calls) == 1 else httpx.Response(200, text=ok)
    _mock_async_client(monkeypatch, handler)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(chatgpt.asyncio, "sleep", lambda s: real_sleep(0))

    async def run():
        return "".join([d async for d in chatgpt.stream_chat("m", [{"role": "user", "content": "q"}])])
    assert asyncio.run(run()) == "hi" and len(calls) == 2


def _events_of(r):
    return [json.loads(l[5:]) for l in r.text.splitlines() if l.startswith("data:")]


def test_coach_looks_up_a_player_then_answers_and_saves(web_client, monkeypatch):  # noqa: F811
    seen = []

    async def fake(llm, messages, tools=None):
        seen.append(messages)
        if len(seen) == 1:
            assert {t["name"] for t in tools} == {"get_player", "get_match", "list_matches"}
            yield ("tool_call", {"id": "call_1", "name": "get_player", "arguments": '{"name": "Rivers"}'})
            yield ("usage", {"input": 1000, "output": 20})
        else:
            tool_msg = messages[-1]
            assert tool_msg["role"] == "tool" and "PLAYER: Alex Rivers" in tool_msg["content"]
            assert messages[-2]["tool_calls"][0]["function"]["name"] == "get_player"
            yield ("delta", "Start Rio: form 7.5.")
            yield ("usage", {"input": 1500, "output": 30, "cost": 0.0012})
    monkeypatch.setattr(client, "stream_events", fake)
    ev = _events_of(web_client.post("/api/chat", json={"messages": [{"role": "user", "content": "How is Rivers doing?"}]}))
    assert any(e.get("tool") == "Looking up Rivers" for e in ev)
    usage = next(e["usage"] for e in ev if "usage" in e)
    assert usage == {"input": 2500, "output": 50, "cost": 0.0012}
    cid = ev[0]["conversation"]
    lst = web_client.get("/api/chats").json()["conversations"]
    assert lst[0]["id"] == cid and lst[0]["title"] == "How is Rivers doing?" and lst[0]["messages"] == 2
    conv = web_client.get(f"/api/chats/{cid}").json()
    assert conv["messages"][-1]["tools"] == ["Looking up Rivers"] and conv["messages"][-1]["usage"]["input"] == 2500
    # continuing the same conversation appends to it
    async def fake2(llm, messages, tools=None):
        yield ("delta", "Yes.")
    monkeypatch.setattr(client, "stream_events", fake2)
    follow = conv["messages"] + [{"role": "user", "content": "And next match?"}]
    ev = _events_of(web_client.post("/api/chat", json={"messages": follow, "conversation_id": cid}))
    assert ev[0]["conversation"] == cid
    assert len(web_client.get(f"/api/chats/{cid}").json()["messages"]) == 4
    assert web_client.delete(f"/api/chats/{cid}").status_code == 200
    assert web_client.get(f"/api/chats/{cid}").status_code == 404
    assert web_client.get("/api/chats/../../config").status_code == 404


def test_coach_tools_run_against_the_database(web_client):  # noqa: F811
    from llm import tools
    from store.db import connect
    con = connect(app_config.DB_PATH)
    assert "Several players" in tools.run(con, 1001, "get_player", '{"name": "zzz"}') or "No player" in tools.run(con, 1001, "get_player", '{"name": "zzz"}')
    assert "CAPTURED MATCHES" in tools.run(con, 1001, "list_matches", "{}")
    assert tools.run(con, 1001, "get_match", '{"opponent": "palace"}').startswith("MATCH")
    assert "Unknown tool" in tools.run(con, 1001, "drop_tables", "{}")
    con.close()


def test_openai_tool_call_and_usage_stream(monkeypatch):
    chunks = [
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "get_", "arguments": '{"na'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "player", "arguments": 'me": "Rio"}'}}]}}]},
        {"choices": [], "usage": {"prompt_tokens": 900, "completion_tokens": 12, "cost": 0.0005}},
    ]
    sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    _mock_async_client(monkeypatch, lambda req: httpx.Response(200, text=sse))

    async def run():
        return [e async for e in client.stream_events({"base_url": "https://x.test/v1", "api_key": "k", "model": "m"},
                                                      [{"role": "user", "content": "q"}], [{"name": "get_player"}])]
    ev = asyncio.run(run())
    assert ("usage", {"input": 900, "output": 12, "cost": 0.0005}) in ev
    assert ("tool_call", {"id": "c1", "name": "get_player", "arguments": '{"name": "Rio"}'}) in ev


def test_chatgpt_function_call_items_and_usage(gpt, monkeypatch):
    chatgpt.store({"clients": {"u1": "oaiapp_1"}, "account": {"sub": "u1", "access_token": "t", "refresh_token": "r",
                                                               "expires_at": time.time() + 3600}})
    seen = {}
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in (
        {"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "fc1", "name": "get_match",
                                                        "arguments": '{"opponent": "Arsenal"}'}},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 700, "output_tokens": 15}}}))

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, text=sse)
    _mock_async_client(monkeypatch, handler)
    msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "q"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "fc0", "type": "function",
                                                                  "function": {"name": "list_matches", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "fc0", "content": "CAPTURED MATCHES ..."}]

    async def run():
        return [e async for e in chatgpt.stream_events("gpt-x", msgs, None, [{"name": "get_match", "parameters": {}}])]
    ev = asyncio.run(run())
    assert ("tool_call", {"id": "fc1", "name": "get_match", "arguments": '{"opponent": "Arsenal"}'}) in ev
    assert ("usage", {"input": 700, "output": 15, "plan": True}) in ev
    items = seen["body"]["input"]
    assert {"type": "function_call", "call_id": "fc0", "name": "list_matches", "arguments": "{}"} in items
    assert {"type": "function_call_output", "call_id": "fc0", "output": "CAPTURED MATCHES ..."} in items
    assert seen["body"]["tools"][0] == {"type": "function", "name": "get_match", "parameters": {}}
