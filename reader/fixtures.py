"""Club names and fixtures/results (date, home, away, score, competition).

Fixture records (vt gp+0x4330778) cover several seasons, with several copies per match
(competition round lists and team-perspective copies). goals_a/goals_b and venue_a always
refer to club_a/club_b, so any copy gives the right score and venue.
"""
from __future__ import annotations

import datetime as dt
import struct
from dataclasses import dataclass

from .memory import Memory
from .people import _fmdate
from .process import GameProcess
from .profile import load_profile

# competition index (+0x8) -> name. FM gives cup stages their own index. "?" = inferred from
# the numbering pattern, not yet seen on a fixture screen; everything else was confirmed from
# the user's fixture screenshots (2026-10-24).
COMPETITION_NAMES = {
    232: "Premier League",
    2798: "Friendly",
    5829: "Friendly Cup Semi Final",
    5834: "Friendly Cup Final",
    214: "FA Community Shield",
    100: "UEFA Super Cup",
    3072: "UEFA Champions League League Phase",
    3263: "UEFA Champions League Round of 16 First Leg",
    3264: "UEFA Champions League Round of 16 Second Leg",
    3266: "UEFA Champions League Quarter Final First Leg",
    3267: "UEFA Champions League Quarter Final Second Leg",
    3269: "UEFA Champions League Semi Final First Leg",
    3270: "UEFA Champions League Semi Final Second Leg",
    3272: "UEFA Champions League Final",
    4178: "The Emirates FA Cup Fourth Round",
    4179: "The Emirates FA Cup Fifth Round",
    4180: "The Emirates FA Cup Quarter Final",
    4181: "The Emirates FA Cup Semi Final",
    4182: "The Emirates FA Cup Final ?",
    3252: "The Emirates FA Cup Third Round ?",
    3254: "Carabao Cup Third Round",
    3740: "Carabao Cup Fourth Round",
    3741: "Carabao Cup Quarter Final",
    3742: "Carabao Cup Semi Final First Leg ?",
    3743: "Carabao Cup Semi Final Second Leg",
    3745: "Carabao Cup Final ?",
}


@dataclass
class Fixture:
    date: dt.date
    home_id: int
    away_id: int
    home: str
    away: str
    home_goals: int
    away_goals: int
    home_pens: int | None
    away_pens: int | None
    competition_index: int | None
    competition: str
    fixture_id: int | None
    neutral: bool = False               # home/away are then just listing order
    kickoff: str | None = None          # "HH:MM"

    @property
    def played(self) -> bool:
        return self.home_goals is not None

    def venue(self, club_id: int) -> str:
        """H / A / N from club_id's point of view."""
        return "N" if self.neutral else "H" if club_id == self.home_id else "A"

    def for_club(self, club_id: int) -> tuple[int, int] | None:
        """(goals for, goals against) from club_id's point of view."""
        if club_id == self.home_id:
            return self.home_goals, self.away_goals
        if club_id == self.away_id:
            return self.away_goals, self.home_goals
        return None

    def opponent(self, club_id: int) -> str:
        return self.away if club_id == self.home_id else self.home


def kickoff(raw_date: bytes) -> str | None:
    """Kick-off time from an fmdate's flag bits: quarter-hours after 05:45."""
    flags = struct.unpack_from("<H", raw_date)[0] >> 9
    minutes = (flags + 23) * 15
    return f"{minutes // 60:02d}:{minutes % 60:02d}" if 0 <= minutes < 24 * 60 else None


def _lpstr(mem: Memory, s: int | None) -> str | None:
    n = mem.i32(s) if s else None
    if not n or not 0 < n < 128:
        return None
    raw = mem.proc.read(s + 4, n)
    return raw.decode("utf-8", "replace") if raw else None


def read_club_names(proc: GameProcess, profile: dict | None = None) -> dict[int, str]:
    profile = profile or load_profile(proc.build_id())
    mem = Memory(proc)
    cn = profile["club_names"]
    root = mem.ptr(proc.module(profile["module"]).base + cn["module_rva"])
    names: dict[int, str] = {}
    size = cn["record_size"]
    for i in range(cn["pages"]):
        page = mem.ptr(root + i * 8)
        data = proc.read(page, cn["per_page"] * size) if page else None
        if not data:
            continue
        for r in range(cn["per_page"]):
            ptr, = struct.unpack_from("<Q", data, r * size + cn["name_ptr"])
            cid, = struct.unpack_from("<i", data, r * size + cn["club_id"])
            name = _lpstr(mem, ptr) if ptr else None
            if name:
                names[cid] = name
    return names


def read_fixtures(proc: GameProcess, club_id: int, profile: dict | None = None,
                  names: dict[int, str] | None = None) -> list[Fixture]:
    """All fixtures in memory involving club_id, one per match, oldest first."""
    profile = profile or load_profile(proc.build_id())
    mem = Memory(proc)
    names = names if names is not None else read_club_names(proc, profile)
    gp = proc.module(profile["module"])
    fx = profile["fixture"]["fields"]
    club_vt = gp.base + profile["club"]["vtable_rva"]
    comp_vt = gp.base + profile["competition"]["vtable_rva"]
    club_id_off = profile["club"]["fields"]["club_id"]["off"]
    vt = gp.base + profile["fixture"]["vtable_rva"]

    copies: dict[tuple, list[dict]] = {}
    for f in mem.find_bytes(struct.pack("<Q", vt), private_only=True, limit=2_000_000):
        if f % 8:
            continue
        blob = proc.read(f, 0xA0)
        if not blob or len(blob) < 0xA0:
            continue
        a, b = (struct.unpack_from("<Q", blob, fx[k]["off"])[0] for k in ("club_a", "club_b"))
        if mem.ptr(a) != club_vt or mem.ptr(b) != club_vt:
            continue
        aid, bid = mem.i32(a + club_id_off), mem.i32(b + club_id_off)
        if club_id not in (aid, bid):
            continue
        date = _fmdate(blob[fx["date"]["off"]:fx["date"]["off"] + 4])
        if not date:
            continue
        u8 = lambda k: blob[fx[k]["off"]]
        ga, gb = u8("goals_a"), u8("goals_b")
        pa, pb = u8("pens_a"), u8("pens_b")
        comp = struct.unpack_from("<Q", blob, fx["competition"]["off"])[0]
        cidx = mem.i32(comp + profile["competition"]["fields"]["index"]["off"]) if mem.ptr(comp) == comp_vt else None
        fid = struct.unpack_from("<i", blob, fx["fixture_id"]["off"])[0]
        copies.setdefault((date, frozenset((aid, bid))), []).append(dict(
            a=aid, b=bid, ga=ga, gb=gb, pa=pa, pb=pb, cidx=cidx,
            fid=fid if fid > 1000 else None, venue=u8("venue_a"),
            kickoff=kickoff(blob[fx["date"]["off"]:fx["date"]["off"] + 4]),
            home_first=(u8("goals_home"), u8("goals_away")) == (ga, gb)))

    out = []
    for (date, _), cs in copies.items():
        c = next((x for x in cs if x["venue"] in (1, 2, 3)), cs[0])
        if c["venue"] == 3 and c["ga"] != c["gb"]:
            # neutral ground: FM still designates a "home" side (listed first); goals_home tells which
            home = c["a"] if c["home_first"] else c["b"]
        else:
            home = c["b"] if c["venue"] == 2 else c["a"]
        away = c["b"] if home == c["a"] else c["a"]
        hg, ag = (c["ga"], c["gb"]) if home == c["a"] else (c["gb"], c["ga"])
        hp, ap = (c["pa"], c["pb"]) if home == c["a"] else (c["pb"], c["pa"])
        fid = min((x["fid"] for x in cs if x["fid"]), default=None)
        out.append(Fixture(
            date=date, home_id=home, away_id=away,
            home=names.get(home, str(home)), away=names.get(away, str(away)),
            home_goals=hg, away_goals=ag,
            home_pens=None if hp == 255 else hp, away_pens=None if ap == 255 else ap,
            competition_index=c["cidx"], competition=COMPETITION_NAMES.get(c["cidx"], f"competition {c['cidx']}"),
            fixture_id=fid, neutral=c["venue"] == 3, kickoff=c["kickoff"],
        ))
    return sorted(out, key=lambda f: f.date)


def read_upcoming(proc: GameProcess, club_id: int, today: dt.date | None, profile: dict | None = None,
                  names: dict[int, str] | None = None) -> list[Fixture]:
    """Unplayed fixtures for club_id from today on (scheduled-fixture records), soonest first."""
    profile = profile or load_profile(proc.build_id())
    mem = Memory(proc)
    names = names if names is not None else read_club_names(proc, profile)
    gp = proc.module(profile["module"])
    sf = profile["scheduled_fixture"]
    f = sf["fields"]
    club_vt = gp.base + profile["club"]["vtable_rva"]
    comp_vt = gp.base + profile["competition"]["vtable_rva"]
    club_id_off = profile["club"]["fields"]["club_id"]["off"]

    copies: dict[tuple, int] = {}
    info: dict[tuple, tuple] = {}
    for rec in mem.find_bytes(struct.pack("<Q", gp.base + sf["vtable_rva"]), private_only=True, limit=1_000_000):
        if rec % 8:
            continue
        b = proc.read(rec, sf["size"])
        if not b or len(b) < sf["size"]:
            continue
        h, a = struct.unpack_from("<Q", b, f["home"]["off"])[0], struct.unpack_from("<Q", b, f["away"]["off"])[0]
        if mem.ptr(h) != club_vt or mem.ptr(a) != club_vt:
            continue
        hid, aid = mem.i32(h + club_id_off), mem.i32(a + club_id_off)
        if club_id not in (hid, aid):
            continue
        raw_date = b[f["date"]["off"]:f["date"]["off"] + 4]
        date = _fmdate(raw_date)
        if not date or (today and date < today):
            continue
        comp = struct.unpack_from("<Q", b, f["competition"]["off"])[0]
        cidx = mem.i32(comp + profile["competition"]["fields"]["index"]["off"]) if mem.ptr(comp) == comp_vt else None
        key = (date, hid, aid, cidx)
        copies[key] = copies.get(key, 0) + 1
        info[key] = (kickoff(raw_date),)

    # a rescheduled match can leave a stale copy at its old date: per (home, away, competition) keep
    # the date with most copies (ties: the later date). Cup ties and two-legged rounds have
    # different competition indexes, so they're unaffected.
    best: dict[tuple, tuple] = {}
    for (date, hid, aid, cidx), n in copies.items():
        k = (hid, aid, cidx)
        if k not in best or (n, date) > (copies[best[k]], best[k][0]):
            best[k] = (date, hid, aid, cidx)
    out = [Fixture(date=d, home_id=h, away_id=a, home=names.get(h, str(h)), away=names.get(a, str(a)),
                   home_goals=None, away_goals=None, home_pens=None, away_pens=None, competition_index=c,
                   competition=COMPETITION_NAMES.get(c, f"competition {c}"), fixture_id=None,
                   kickoff=info[(d, h, a, c)][0])
           for d, h, a, c in best.values()]
    return sorted(out, key=lambda x: (x.date, x.kickoff or ""))
