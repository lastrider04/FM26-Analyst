"""Local settings and paths. Everything personal lives in data/ (git-ignored)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DB_PATH = DATA / "fm_analyst.db"
SNAPSHOT_DIR = DATA / "snapshots"
CONFIG_PATH = DATA / "config.json"

DEFAULTS = {
    "club_id": None,            # the club you manage: chosen on first run (Overview), or in Settings › Capture
    "hotkey": "ctrl+alt+s",     # global capture hotkey
    "auto_capture": True,       # capture by itself after each match and weekly
    "llm": {"base_url": "https://api.openai.com/v1", "api_key": "", "model": "gpt-4o-mini", "temperature": 0.4},
    # phone companion: a second, locked-down listener for a reverse proxy (see web/remote.py)
    "remote": {"enabled": False, "host": "0.0.0.0", "port": 8766, "public_url": "", "proxy_ip": "",
               "google_client_id": "", "google_client_secret": "", "allowed_emails": [],
               "password_user": "", "password_hash": ""},
}
SECRETS = [("llm", "api_key"), ("remote", "google_client_secret")]   # DPAPI-encrypted on disk as <name>_enc


def load_config() -> dict:
    """Config with secrets decrypted in memory only (on disk they're DPAPI-encrypted, see SECRETS)."""
    cfg = json.loads(json.dumps(DEFAULTS))
    stored = {}
    if CONFIG_PATH.exists():
        stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        for k, v in stored.items():
            cfg[k] = {**cfg[k], **v} if isinstance(cfg.get(k), dict) and isinstance(v, dict) else v
    migrate = False
    for section, name in SECRETS:
        sec = cfg[section]
        enc = sec.pop(name + "_enc", None)
        if enc:
            from keystore import unprotect
            try:
                sec[name] = unprotect(enc)
            except OSError:      # encrypted by another Windows user / machine: treat as not set
                sec[name] = ""
        elif sec.get(name):      # plaintext from an older version: encrypt it now
            migrate = True
    if migrate:
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    DATA.mkdir(exist_ok=True)
    out = json.loads(json.dumps(cfg))
    for section, name in SECRETS:
        sec = out.setdefault(section, {})
        secret = sec.pop(name, "")
        sec.pop(name + "_enc", None)
        if secret:
            from keystore import protect
            sec[name + "_enc"] = protect(secret)
    CONFIG_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
