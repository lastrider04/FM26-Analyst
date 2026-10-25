"""Read per-player match stats and group them into matches.

Layout:
  match-stats record (vt gp+0x449EA78, 0x110 bytes) -> one player in one match
  team-in-match block: vector<record*> line-up at +0, team totals just before it;
  the opponent's block sits 0x290 bytes earlier. Each match exists in ~4 identical copies.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import struct
from dataclasses import dataclass, field

import numpy as np

from .fixtures import Fixture
from .memory import Memory
from .people import _fmdate, enumerate_persons
from .process import GameProcess
from .profile import load_profile

UNPACK = {"i16": "<h", "i32": "<i", "u8": "<B", "f32": "<f"}
MIN_PLAYED = 11  # smaller vectors are partial copies, not full line-ups


@dataclass
class PlayerMatch:
    person_index: int
    unique_id: int | None
    stats: dict[str, float]
    raw: bytes = b""  # the full 0x110-byte record, kept so unlabelled counters can be decoded later

    @property
    def rating(self) -> float:
        return self.stats["rating_x100"] / 100

    @property
    def played(self) -> bool:
        s = self.stats
        return s["distance_m"] > 0 or s["passes_attempted"] > 0 or s["sub_on_minute"] > 0


@dataclass
class TeamMatch:
    club_id: int | None
    lineup: list[PlayerMatch]
    team_block: list[int] = field(default_factory=list)  # raw team totals, not yet labelled


@dataclass
class Match:
    key: str                        # content hash, stable across snapshots
    team: TeamMatch
    opponent: TeamMatch | None      # opponent line-up, only kept when it agrees with the fixture
    fixture: "Fixture | None" = None
    link_confidence: str = "none"   # "high" (goals + opponent agree), "goals", "none"

    @property
    def goals_by_players(self) -> int:
        return sum(pm.stats["goals"] for pm in self.team.lineup if pm.played)


def game_date(proc: GameProcess, profile: dict | None = None) -> dt.date | None:
    profile = profile or load_profile(proc.build_id())
    raw = proc.read(proc.module(profile["module"]).base + profile["game_date"]["module_rva"], 4)
    return _fmdate(raw) if raw else None


def game_datetime(proc: GameProcess, profile: dict | None = None) -> dt.datetime | None:
    """In-game date and clock (the date's flag bits hold the time, like fixture kick-offs)."""
    from .fixtures import kickoff
    profile = profile or load_profile(proc.build_id())
    raw = proc.read(proc.module(profile["module"]).base + profile["game_date"]["module_rva"], 4)
    d = _fmdate(raw) if raw else None
    t = kickoff(raw) if raw else None
    if not d:
        return None
    h, m = map(int, t.split(":")) if t else (0, 0)
    return dt.datetime(d.year, d.month, d.day, h, m)


def _record(blob: bytes, fields: dict) -> dict[str, float]:
    out = {}
    for k, spec in fields.items():
        v = struct.unpack_from(UNPACK[spec["type"]], blob, spec["off"])[0]
        out[k] = round(v, 4) if spec["type"] == "f32" else v
    return out


def _find_holders(mem: Memory, targets: np.ndarray) -> dict[int, int]:
    """Map holder address -> record address for every 8-byte slot holding a record pointer."""
    out = {}
    if not len(targets):
        return out
    lo, hi = targets.min(), targets.max()
    for base, data in mem.scan_regions(private_only=True):
        pad = (-base) % 8
        arr = np.frombuffer(data, dtype="<u8", offset=pad, count=(len(data) - pad) // 8)
        cand = np.nonzero((arr >= lo) & (arr <= hi))[0]  # cheap range filter before the exact lookup
        if not len(cand):
            continue
        vals = arr[cand]
        pos = np.searchsorted(targets, vals)
        pos[pos == len(targets)] = 0
        for i in cand[targets[pos] == vals]:
            out[base + pad + int(i) * 8] = int(arr[i])
    return out


def read_matches(proc: GameProcess, club_id: int, profile: dict | None = None) -> list[Match]:
    """All matches in memory in which `club_id` took part (one entry per match, copies merged)."""
    profile = profile or load_profile(proc.build_id())
    mem = Memory(proc)
    ms = profile["match_stats"]
    fields = {k: v for k, v in ms["fields"].items() if not k.startswith("_")}
    size = ms["size"]
    opp_delta = ms["lineup"]["opponent_owner_delta"]
    tb = ms["lineup"]["team_block"]
    gp = proc.module(profile["module"])
    vt = gp.base + ms["vtable_rva"]

    # person index -> (unique id, club id at, contract club id)
    pf = profile["person"]
    club_off = profile["club"]["fields"]["club_id"]["off"]
    persons: dict[int, tuple[int, int | None]] = {}
    for ref in enumerate_persons(proc, profile):
        idx = mem.i32(ref + pf["fields"]["db_index"]["off"])
        uid = mem.i32(ref + pf["fields"]["unique_id"]["off"])
        cptr = mem.ptr(ref + pf["contract_ptr"]["off"])
        owner_club = mem.ptr(cptr + profile["contract"]["fields"]["club_ptr"]["off"]) if cptr else None
        at_club = mem.ptr(ref + pf["club_ptr"]["off"])
        cid = mem.i32(at_club + club_off) if at_club else None
        persons[idx] = (uid, cid if cid is not None else (mem.i32(owner_club + club_off) if owner_club else None))

    records = np.array(sorted(a for a in mem.find_bytes(struct.pack("<Q", vt), private_only=True,
                                                         limit=500_000) if a % 8 == 0), dtype="<u8")
    holders = _find_holders(mem, records)

    # group holder slots into contiguous vectors (line-ups); remember each vector's start
    starts = sorted(h for h in holders if (h - 8) not in holders)
    lineups: dict[int, list[int]] = {}
    for s in starts:
        recs, h = [], s
        while h in holders:
            recs.append(holders[h])
            h += 8
        lineups[s] = recs

    # owner slot = an 8-byte field whose value is a line-up start (vector begin)
    owners = _find_holders(mem, np.array(sorted(lineups), dtype="<u8"))

    def team(owner: int) -> TeamMatch | None:
        begin = mem.ptr(owner)
        if begin not in lineups:
            return None
        lineup = []
        for r in lineups[begin]:
            blob = proc.read(r, size)
            if not blob or len(blob) < size:
                continue
            st = _record(blob, fields)
            uid, _ = persons.get(st["person_index"], (None, None))
            lineup.append(PlayerMatch(st["person_index"], uid, st, blob))
        clubs = [persons.get(pm.person_index, (None, None))[1] for pm in lineup if pm.played]
        club = max(set(clubs), key=clubs.count) if clubs else None
        block = list(struct.unpack(f"<{tb['len'] // 4}i", proc.read(owner + tb["off"], tb["len"]) or b"\0" * tb["len"]))
        return TeamMatch(club, lineup, block)

    matches: dict[str, Match] = {}
    for owner in owners:
        t = team(owner)
        if not t or t.club_id != club_id or sum(pm.played for pm in t.lineup) < MIN_PLAYED:
            continue
        # the two team blocks are |opp_delta| apart; ours can be either the first or the second
        opp = None
        for delta in (opp_delta, -opp_delta):
            cand = team(owner + delta)
            if cand and cand.club_id not in (None, club_id) and sum(pm.played for pm in cand.lineup) >= MIN_PLAYED:
                opp = cand
                break
        sig = repr(sorted((pm.person_index, pm.stats["rating_x100"], pm.stats["distance_m"]) for pm in t.lineup))
        key = hashlib.sha1(sig.encode()).hexdigest()[:16]
        if key not in matches or (matches[key].opponent is None and opp):
            matches[key] = Match(key, t, opp)
    return list(matches.values())


CURRENT_SQUAD_SHARE = 0.8  # goals-only links need this share of players still at the club


def link_fixtures(matches: list[Match], fixtures: list[Fixture], club_id: int,
                  today: dt.date | None, window_days: int = 60,
                  current_uids: set[int] | None = None) -> None:
    """Attach each line-up to its fixture (in place).

    Line-ups carry no date, so pairs are scored: our goals must be >= goals scored by our players
    (own goals by the opponent explain any surplus), equality scores higher, a neighbouring
    opponent block whose club matches the fixture opponent scores highest, recent fixtures win
    ties. Assignment is greedy on the best score, one fixture per line-up.

    Old line-ups (e.g. last season's) can linger in memory and happen to fit on goals. When
    `current_uids` is given, a link without opponent confirmation is only accepted if most of the
    line-up is still at the club.
    """
    recent = [f for f in fixtures if today is None or 0 <= (today - f.date).days <= window_days]
    pairs = []
    for m in matches:
        played = [pm.unique_id for pm in m.team.lineup if pm.played]
        share = (sum(u in current_uids for u in played) / len(played)) if current_uids and played else 1.0
        g = m.goals_by_players
        for f in recent:
            gf, _ = f.for_club(club_id)
            if gf < g:
                continue
            opp_id = f.away_id if f.home_id == club_id else f.home_id
            opp_ok = m.opponent is not None and m.opponent.club_id == opp_id
            if not opp_ok and share < CURRENT_SQUAD_SHARE:
                continue
            score =(100 if opp_ok else 0) + (10 if gf == g else 0) - ((today - f.date).days / 30 if today else 0)
            pairs.append((score, id(m), m, f, opp_ok))
    used_m, used_f = set(), set()
    for score, _, m, f, opp_ok in sorted(pairs, key=lambda x: -x[0]):
        if id(m) in used_m or id(f) in used_f:
            continue
        used_m.add(id(m))
        used_f.add(id(f))
        m.fixture = f
        m.link_confidence = "high" if opp_ok else "goals"
        if not opp_ok:
            m.opponent = None  # the neighbouring block belonged to a different match
