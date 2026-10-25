"""Read players from the game's Person records (the database entity, not a UI cache).

    with GameProcess() as p:
        squad = read_club_players(p, club_id=your_club_id)
"""
from __future__ import annotations

import datetime as dt
import struct
from dataclasses import dataclass, field

from .memory import Memory
from .process import GameProcess
from .profile import load_profile

UNPACK = {"i16": "<h", "u16": "<H", "i32": "<i", "u8": "<B", "f32": "<f", "ptr": "<Q"}


@dataclass
class Player:
    unique_id: int
    name: str | None                    # common name if set, else "First Last"
    first_name: str | None
    last_name: str | None
    ca: int
    pa: int | None
    attributes: dict[str, int]          # raw 1-100; display = round(raw / 5)
    positions: dict[str, int]           # familiarity 1-20 per position (GK, DL, DC, ... ST)
    fitness: float                     # FM "Condition" %, 0-100
    match_exercise: float               # FM "Match Sharpness" %, 0-100
    jadedness: int
    value: int
    dob: dt.date | None
    club_id: int | None                 # club owning the contract
    at_club_id: int | None              # team the player is at now (may be own U21/U18 team)
    at_own_club: bool = True            # at_club_id is in the owning/viewing club's family
    contract: dict = field(default_factory=dict)
    reputation: dict = field(default_factory=dict)
    caps: int | None = None
    intl_goals: int | None = None
    injuries: list[dict] = field(default_factory=list)   # current injuries: {start: date, min_days, max_days}
    address: int = 0

    def attr(self, key: str) -> int:
        return round(self.attributes[key] / 5)

    def loaned_out(self, club_id: int) -> bool:
        return self.club_id == club_id and not self.at_own_club

    def loaned_in(self, club_id: int) -> bool:
        return self.at_own_club and self.club_id is not None and self.club_id != club_id

    @property
    def uncontracted(self) -> bool:
        """At the club without a contract (academy kids, trialists)."""
        return self.club_id is None

    def youth_team(self, club_id: int) -> bool:
        """At one of the club's own other teams (U21, U18, ...)."""
        return self.at_own_club and self.at_club_id != club_id

    @property
    def blended_condition(self) -> int:
        """The single condition figure scouting tools show: a blend of fitness and match exercise, not a stored field."""
        return round(0.86 * self.fitness + 0.14 * self.match_exercise)


def _fmdate(raw: bytes) -> dt.date | None:
    day, year = struct.unpack("<hh", raw)
    day &= 0x1FF  # upper bits are flags
    if not 1900 < year < 2100 or not 1 <= day <= 366:
        return None
    return dt.date(year, 1, 1) + dt.timedelta(days=day - 1)


def _read(mem: Memory, addr: int, spec: dict):
    t = spec.get("type", "ptr")
    if t == "fmdate":
        raw = mem.proc.read(addr + spec["off"], 4)
        return _fmdate(raw) if raw else None
    fmt = UNPACK[t]
    raw = mem.proc.read(addr + spec["off"], struct.calcsize(fmt))
    if not raw:
        return None
    v = struct.unpack(fmt, raw)[0]
    return v * spec["scale"] if "scale" in spec else v


def enumerate_persons(proc: GameProcess, profile: dict) -> list[int]:
    mem = Memory(proc)
    vt = proc.module(profile["module"]).base + profile["person"]["vtable_rva"]
    return [a for a in mem.find_bytes(struct.pack("<Q", vt), private_only=True, limit=2_000_000) if a % 8 == 0]


def _name(mem: Memory, ref: int, off: int) -> str | None:
    """Person field -> name-table entry -> lpstr (i32 length + UTF-8)."""
    entry = mem.ptr(ref + off)
    s = mem.ptr(entry) if entry else None
    n = mem.i32(s) if s else None
    if not n or not 0 < n < 128:
        return None
    raw = mem.proc.read(s + 4, n)
    return raw.decode("utf-8", "replace") if raw else None


def read_person_names(proc: GameProcess, unique_ids: set[int], profile: dict | None = None
                      ) -> dict[int, tuple[str | None, str | None, str | None]]:
    """UniqueID -> (display name, first, last) for any people, e.g. players who have left the club."""
    profile = profile or load_profile(proc.build_id())
    if not unique_ids:
        return {}
    mem = Memory(proc)
    pf = profile["person"]
    nm = pf["names"]
    out = {}
    for ref in enumerate_persons(proc, profile):
        uid = mem.i32(ref + pf["fields"]["unique_id"]["off"])
        if uid in unique_ids and uid not in out:
            first, last = _name(mem, ref, nm["first"]), _name(mem, ref, nm["last"])
            common = _name(mem, ref, nm["common"])
            out[uid] = (common or " ".join(x for x in (first, last) if x) or None, first, last)
    return out


MAX_INJURIES = 8


def read_injuries(mem: Memory, ref: int, spec: dict | None) -> list[dict]:
    """Current injuries: Person[holder] -> vector<Injury*>; each gives start date and expected length (days)."""
    if not spec:
        return []
    holder = mem.ptr(ref + spec["holder_ptr"])
    if not holder:
        return []
    beg, end = mem.ptr(holder), mem.ptr(holder + 8)
    if not beg or not end or end <= beg or (end - beg) % 8 or (end - beg) // 8 > MAX_INJURIES:
        return []
    out = []
    for k in range((end - beg) // 8):
        inj = mem.ptr(beg + 8 * k)
        if not inj:
            continue
        e = {name: _read(mem, inj, s) for name, s in spec["entry"].items()}
        if e.get("start") and e.get("max_days") is not None and 0 <= e["max_days"] <= 2000 \
                and 0 <= (e.get("min_days") or 0) <= e["max_days"]:
            out.append(e)
    return out


def read_club_players(proc: GameProcess, club_id: int, profile: dict | None = None) -> list[Player]:
    """Players contracted to `club_id` (incl. loaned out) or currently at it (incl. loaned in)."""
    profile = profile or load_profile(proc.build_id())
    mem = Memory(proc)
    pf = profile["person"]
    f = pf["fields"]
    nm = pf["names"]
    club_id_off = profile["club"]["fields"]["club_id"]["off"]
    family_off = profile["club"]["fields"]["family_ptr"]["off"]
    contract_club_off = profile["contract"]["fields"]["club_ptr"]["off"]
    order = profile["attribute_order"]

    clubs: dict[int, tuple[int | None, int | None]] = {}  # club ptr -> (id, family ptr)

    def club_of(ptr: int | None) -> tuple[int | None, int | None]:
        if not ptr:
            return None, None
        if ptr not in clubs:
            clubs[ptr] = (mem.i32(ptr + club_id_off), mem.ptr(ptr + family_off))
        return clubs[ptr]

    persons = enumerate_persons(proc, profile)
    family = None  # the viewing club's family pointer, found from any player at the club itself
    for ref in persons:
        cid, fam = club_of(mem.ptr(ref + pf["club_ptr"]["off"]))
        if cid == club_id:
            family = fam
            break

    players: dict[int, Player] = {}
    for ref in persons:
        at_club, at_family = club_of(mem.ptr(ref + pf["club_ptr"]["off"]))
        cptr = mem.ptr(ref + pf["contract_ptr"]["off"])
        owner = club_of(mem.ptr(cptr + contract_club_off))[0] if cptr else None
        at_own = family is not None and at_family == family
        if owner != club_id and not at_own:
            continue
        uid = _read(mem, ref, f["unique_id"])
        if uid in players:
            continue
        ca, pa = _read(mem, ref, f["ca"]), _read(mem, ref, f["pa"])
        attrs = proc.read(ref + pf["attributes"]["off"], pf["attributes"]["len"]) or b""
        if not ca or not 1 <= ca <= 200 or len(attrs) != 54 or not all(1 <= a <= 100 for a in attrs):
            continue  # staff or non-player person
        contract = {}
        if cptr:
            for k, spec in profile["contract"]["fields"].items():
                if not k.endswith("_ptr"):
                    contract[k] = _read(mem, cptr, spec)
        first, last = _name(mem, ref, nm["first"]), _name(mem, ref, nm["last"])
        common = _name(mem, ref, nm["common"])
        day, year = _read(mem, ref, f["dob_day_of_year"]), _read(mem, ref, f["dob_year"])
        dob = _fmdate(struct.pack("<hh", day, year)) if day is not None and year is not None else None
        players[uid] = Player(
            unique_id=uid,
            name=common or " ".join(x for x in (first, last) if x) or None,
            first_name=first,
            last_name=last,
            ca=ca,
            pa=pa if pa is not None and ca <= pa <= 200 else None,
            attributes=dict(zip(order, attrs)),
            positions=dict(zip(pf["positions"]["order"],
                               proc.read(ref + pf["positions"]["off"], pf["positions"]["len"]) or b"")),
            fitness=_read(mem, ref, f["fitness"]),
            match_exercise=_read(mem, ref, f["match_exercise"]),
            jadedness=_read(mem, ref, f["jadedness"]),
            value=_read(mem, ref, f["value"]),
            dob=dob,
            club_id=owner,
            at_club_id=at_club,
            at_own_club=at_own,
            contract=contract,
            reputation={k: _read(mem, ref, f[f"rep_{k}"]) for k in ("home", "current", "world")},
            caps=_read(mem, ref, f["caps"]),
            intl_goals=_read(mem, ref, f["intl_goals"]),
            injuries=read_injuries(mem, ref, pf.get("injuries")),
            address=ref,
        )
    return list(players.values())
