"""Minimal OpenAI-compatible chat client (/chat/completions, streaming) for any provider or local server."""
from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

import httpx

SYSTEM_PROMPT = Path(__file__).parent / "prompts" / "system.md"
TIMEOUT = httpx.Timeout(120, connect=10)


class LLMError(Exception):
    pass


def _url(base_url: str, path: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise LLMError("Set an http(s) base URL in Settings, e.g. https://api.openai.com/v1")
    return base + path


def _headers(api_key: str) -> dict:
    h = {"Content-Type": "application/json"}
    if api_key:                      # local servers (Ollama, LM Studio) need none
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _error(r: httpx.Response) -> str:
    try:
        body = r.json()
        msg = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
    except ValueError:
        msg = r.text[:300]
    hint = {401: " (check the API key)", 404: " (check the base URL and model name)", 429: " (rate limit or no credit)"}
    return f"LLM endpoint returned {r.status_code}: {msg or r.reason_phrase}{hint.get(r.status_code, '')}"


def custom_prompt_path() -> Path:
    import app_config
    return app_config.DATA / "coach_prompt.md"


def default_prompt() -> str:
    return SYSTEM_PROMPT.read_text(encoding="utf-8")


def system_prompt() -> str:
    """The coach's instructions: the user's edited version (data/coach_prompt.md) if any, else the default."""
    try:
        text = custom_prompt_path().read_text(encoding="utf-8")
        if text.strip():
            return text
    except OSError:
        pass
    return default_prompt()


async def list_models(llm: dict) -> list[str]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(_url(llm["base_url"], "/models"), headers=_headers(llm.get("api_key", "")))
    if r.status_code != 200:
        raise LLMError(_error(r))
    return sorted(m.get("id", "") for m in r.json().get("data", []))


def _usage(u: dict) -> dict:
    """Provider usage -> {input, output, cost?} (cost only when the provider reports it, e.g. OpenRouter)."""
    out = {"input": u.get("prompt_tokens") or u.get("input_tokens") or 0,
           "output": u.get("completion_tokens") or u.get("output_tokens") or 0}
    if u.get("cost") is not None:
        out["cost"] = float(u["cost"])
    return out


async def stream_events(llm: dict, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[tuple]:
    """Chat completions stream as events: ("delta", text) | ("tool_call", {id, name, arguments}) | ("usage", {...}).

    Optional features are dropped one by one if the endpoint rejects them (temperature, tools, usage reporting),
    so local or minimal OpenAI-compatible servers still work."""
    if not llm.get("model"):
        raise LLMError("Set a model in Settings (e.g. gpt-4o-mini)")
    local = any(h in (llm.get("base_url") or "") for h in ("://localhost", "://127.0.0.1"))
    if not llm.get("api_key") and not local:   # don't send squad data to a remote endpoint that will just reject it
        raise LLMError("The AI coach isn't set up yet: add an API key, sign in with ChatGPT, or pick a local model in Settings › AI coach")
    body = {"model": llm["model"], "messages": messages, "stream": True, "stream_options": {"include_usage": True}}
    if "openrouter.ai" in (llm.get("base_url") or ""):
        body["usage"] = {"include": True}       # OpenRouter adds the cost to the usage block
    if llm.get("temperature") is not None:
        body["temperature"] = llm["temperature"]
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        for _attempt in range(4):
            async with c.stream("POST", _url(llm["base_url"], "/chat/completions"), headers=_headers(llm.get("api_key", "")),
                                json=body) as r:
                if r.status_code != 200:
                    await r.aread()
                    err = _error(r)
                    low = err.lower()
                    if r.status_code in (400, 422):
                        dropped = next((k for k in ("temperature", "tools", "stream_options", "usage")
                                        if k in body and (k.rstrip("s") in low or k in low)), None)
                        if dropped is None and "tool" in low and "tools" in body:
                            dropped = "tools"
                        if dropped:
                            body.pop(dropped, None)
                            continue
                    raise LLMError(err)
                calls: dict[int, dict] = {}
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if chunk.get("usage"):
                        yield ("usage", _usage(chunk["usage"]))
                    for ch in chunk.get("choices") or []:
                        delta = ch.get("delta") or {}
                        if delta.get("content"):
                            yield ("delta", delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                            slot["id"] = tc.get("id") or slot["id"]
                            fn = tc.get("function") or {}
                            slot["name"] += fn.get("name") or ""
                            slot["arguments"] += fn.get("arguments") or ""
                for k in sorted(calls):
                    if calls[k]["name"]:
                        yield ("tool_call", calls[k])
                return


async def stream_chat(llm: dict, messages: list[dict]) -> AsyncIterator[str]:
    """Text deltas only (no tools)."""
    async for kind, val in stream_events(llm, messages):
        if kind == "delta":
            yield val
