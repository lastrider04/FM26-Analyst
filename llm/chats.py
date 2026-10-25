"""Saved coach conversations, per game snapshot: data/chats/save-<n>/<id>.json"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid

import app_config

KEEP_MESSAGES = 200


def _dir(save_id: int):
    d = app_config.DATA / "chats" / f"save-{save_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(save_id: int, cid: str):
    if not re.fullmatch(r"[0-9a-f]{12}", cid or ""):
        raise KeyError(cid)
    return _dir(save_id) / f"{cid}.json"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def load(save_id: int, cid: str) -> dict:
    p = _path(save_id, cid)
    if not p.exists():
        raise KeyError(cid)
    return json.loads(p.read_text(encoding="utf-8"))


def save(save_id: int, cid: str, messages: list[dict]) -> dict:
    p = _path(save_id, cid)
    now = dt.datetime.now().isoformat(sep=" ", timespec="minutes")
    try:
        conv = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        conv = {"id": cid, "created": now}
    first = next((m["content"] for m in messages if m["role"] == "user"), "Conversation")
    conv.update(title=conv.get("title") or (first[:70] + ("…" if len(first) > 70 else "")), updated=now,
                messages=messages[-KEEP_MESSAGES:])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(conv, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return conv


def listing(save_id: int) -> list[dict]:
    out = []
    for p in _dir(save_id).glob("*.json"):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": c["id"], "title": c.get("title"), "updated": c.get("updated"),
                    "messages": len(c.get("messages", []))})
    return sorted(out, key=lambda c: c.get("updated") or "", reverse=True)


def delete(save_id: int, cid: str) -> None:
    _path(save_id, cid).unlink(missing_ok=True)
