"""Offset profiles: one JSON per game build, selected by GameProcess.build_id()."""
from __future__ import annotations

import json
from pathlib import Path

PROFILE_DIR = Path(__file__).parent / "profiles"


class UnknownBuild(RuntimeError):
    pass


def _ints(node):
    """Convert "0x.." strings (and "-0x..") to ints, recursively."""
    if isinstance(node, dict):
        return {k: _ints(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_ints(v) for v in node]
    if isinstance(node, str):
        s = node.lstrip("-")
        if s.startswith("0x"):
            v = int(s, 16)
            return -v if node.startswith("-") else v
    return node


def load_profile(build_id: str) -> dict:
    path = PROFILE_DIR / f"fm26_{build_id}.json"
    if not path.exists():
        known = sorted(p.stem for p in PROFILE_DIR.glob("fm26_*.json"))
        raise UnknownBuild(
            f"No offset profile for game build {build_id}. The game was probably patched; "
            f"run recalibration. Known profiles: {known}")
    return _ints(json.loads(path.read_text(encoding="utf-8")))
