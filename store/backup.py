"""Automatic database backups: one copy per real day per save, newest KEEP kept.

data/backups/save-<id>/fm_analyst-YYYY-MM-DD.db   (SQLite online backup, safe while the app is running)
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import app_config

KEEP = 14


def backup_dir(cid: int) -> Path:
    return app_config.DATA / "backups" / f"save-{cid}"


def backup(db_path: Path, cid: int, tag: str | None = None) -> Path | None:
    if not db_path.exists():
        return None
    d = backup_dir(cid)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"fm_analyst-{tag or dt.date.today().isoformat()}.db"
    src = sqlite3.connect(db_path)
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    prune(cid)
    return dest


def daily(db_path: Path, cid: int) -> Path | None:
    """Back up once per real-world day (no-op if today's copy exists)."""
    if (backup_dir(cid) / f"fm_analyst-{dt.date.today().isoformat()}.db").exists():
        return None
    return backup(db_path, cid)


def prune(cid: int, keep: int = KEEP) -> None:
    files = sorted(backup_dir(cid).glob("fm_analyst-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


def status(cid: int) -> dict:
    files = sorted(backup_dir(cid).glob("fm_analyst-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {"count": len(files), "keep": KEEP, "folder": str(backup_dir(cid)),
            "latest": dt.datetime.fromtimestamp(files[0].stat().st_mtime).isoformat(sep=" ", timespec="minutes") if files else None,
            "latest_file": files[0].name if files else None}
