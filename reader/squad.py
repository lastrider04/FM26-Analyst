"""Read squad players from memory using the build's offset profile."""
from __future__ import annotations

import datetime as dt
import struct
from dataclasses import dataclass, field

from .memory import Memory
from .process import GameProcess
from .profile import load_profile

UNPACK = {"i16": "<h", "i32": "<i", "u8": "<B", "ptr": "<Q"}


@dataclass
class SquadPlayer:
    address: int
    group: int
    unique_id: int
    full_name: str
    short_name: str | None
    ca: int
    pa: int | None
    attributes: dict[str, int]  # raw 1-100
    positions_raw: list[int]
    person: dict[str, int] = field(default_factory=dict)  # jadedness, reputation, caps...
    dob: dt.date | None = None
    warnings: list[str] = field(default_factory=list)

    def attr(self, key: str) -> int:
        """Display value 1-20."""
        return round(self.attributes[key] / 5)


def _lpstr(mem: Memory, ptr: int) -> str | None:
    if not ptr:
        return None
    n = mem.i32(ptr)
    if n is None or not 0 < n < 128:
        return None
    raw = mem.proc.read(ptr + 4, n)
    return raw.decode("utf-8", "replace") if raw else None


def _field(blob: bytes, spec: dict):
    if spec["type"] == "bytes":
        return list(blob[spec["off"]:spec["off"] + spec["len"]])
    return struct.unpack_from(UNPACK.get(spec["type"], "<Q"), blob, spec["off"])[0]


def read_squad_players(proc: GameProcess, profile: dict | None = None) -> list[SquadPlayer]:
    """All valid squad-player objects in memory (several groups/copies; see group_squads)."""
    profile = profile or load_profile(proc.build_id())
    mem = Memory(proc)
    sp = profile["squad_player"]
    f = sp["fields"]
    order = profile["attribute_order"]
    vt = proc.module(profile["module"]).base + sp["vtable_rva"]

    players = []
    for addr in mem.find_bytes(struct.pack("<Q", vt), private_only=True, limit=100_000):
        if addr % 8:
            continue
        blob = proc.read(addr, sp["read_size"])
        if not blob or len(blob) < sp["read_size"]:
            continue
        name = _lpstr(mem, _field(blob, f["full_name"]))
        ca = _field(blob, f["ca"])
        attrs = _field(blob, f["attributes"])
        if not name or not 1 <= ca <= 200 or not all(1 <= a <= 100 for a in attrs):
            continue
        warnings = []
        person = _read_person(mem, _field(blob, f["person_ref"]), profile["person"]["fields"])
        pa = person.pop("pa", None)
        if pa is None or not ca <= pa <= 200:
            warnings.append(f"PA unreadable ({pa})")
            pa = None
        dob = _dob(person.pop("dob_day_of_year", None), person.pop("dob_year", None))
        if dob is None:
            warnings.append("DOB unreadable")
        players.append(SquadPlayer(
            address=addr,
            group=_field(blob, f["group"]),
            unique_id=_field(blob, f["unique_id"]),
            full_name=name,
            short_name=_lpstr(mem, _field(blob, f["short_name"])),
            ca=ca,
            pa=pa,
            attributes=dict(zip(order, attrs)),
            positions_raw=_field(blob, f["positions"]),
            person=person,
            dob=dob,
            warnings=warnings,
        ))
    return players


def _read_person(mem: Memory, ref: int, fields: dict) -> dict[str, int]:
    if not ref:
        return {}
    out = {}
    for key, spec in fields.items():
        v = mem.i16(ref + spec["off"])
        if v is not None:
            out[key] = v
    return out


def _dob(day_of_year: int | None, year: int | None) -> dt.date | None:
    """FM stores dates as 1-based day of year + year."""
    if not day_of_year or not year or not 1900 < year < 2100 or not 1 <= day_of_year <= 366:
        return None
    return dt.date(year, 1, 1) + dt.timedelta(days=day_of_year - 1)


def group_squads(players: list[SquadPlayer]) -> dict[int, list[SquadPlayer]]:
    groups: dict[int, list[SquadPlayer]] = {}
    for p in players:
        groups.setdefault(p.group, []).append(p)
    return groups
