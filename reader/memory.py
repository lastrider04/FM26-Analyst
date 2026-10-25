"""Typed reads and scanning on top of GameProcess."""
from __future__ import annotations

import re
import struct
from typing import Iterator

from .process import GameProcess, Region

CHUNK = 16 << 20  # read big regions in 16 MiB pieces
MEM_PRIVATE = 0x20000


class Memory:
    def __init__(self, proc: GameProcess):
        self.proc = proc

    def _unpack(self, fmt: str, address: int):
        size = struct.calcsize(fmt)
        data = self.proc.read(address, size)
        if data is None or len(data) < size:
            return None
        return struct.unpack(fmt, data)[0]

    def u8(self, a): return self._unpack("<B", a)
    def i8(self, a): return self._unpack("<b", a)
    def u16(self, a): return self._unpack("<H", a)
    def i16(self, a): return self._unpack("<h", a)
    def i32(self, a): return self._unpack("<i", a)
    def u32(self, a): return self._unpack("<I", a)
    def i64(self, a): return self._unpack("<q", a)
    def f32(self, a): return self._unpack("<f", a)
    def f64(self, a): return self._unpack("<d", a)
    def ptr(self, a): return self._unpack("<Q", a)

    def utf16(self, address: int, max_chars: int = 128) -> str | None:
        data = self.proc.read(address, max_chars * 2)
        if not data:
            return None
        end = next((i for i in range(0, len(data) - 1, 2) if data[i] == 0 and data[i + 1] == 0), len(data))
        return data[:end].decode("utf-16-le", errors="replace")

    def utf8(self, address: int, max_len: int = 256) -> str | None:
        data = self.proc.read(address, max_len)
        if not data:
            return None
        return data.split(b"\0", 1)[0].decode("utf-8", errors="replace")

    def chain(self, base: int, offsets: list[int]) -> int | None:
        """Follow base -> [+o0] -> [+o1] ... ; the last offset is added, not dereferenced."""
        addr = base
        for off in offsets[:-1]:
            addr = self.ptr(addr + off)
            if not addr:
                return None
        return addr + (offsets[-1] if offsets else 0)

    # -- scanning ----------------------------------------------------------
    def scan_regions(self, private_only: bool = False) -> Iterator[tuple[int, bytes]]:
        """Yield (address, bytes) chunks of all readable committed memory."""
        for r in self.proc.regions():
            if private_only and r.type != MEM_PRIVATE:
                continue
            for off in range(0, r.size, CHUNK):
                n = min(CHUNK + 64, r.size - off)  # small overlap so matches across chunk edges are found
                data = self.proc.read(r.base + off, n)
                if data:
                    yield r.base + off, data

    def find_bytes(self, needle: bytes | re.Pattern, private_only: bool = False, limit: int = 10_000) -> list[int]:
        pat = needle if isinstance(needle, re.Pattern) else re.compile(re.escape(needle), re.DOTALL)
        hits: set[int] = set()
        for base, data in self.scan_regions(private_only):
            for m in pat.finditer(data):
                hits.add(base + m.start())
                if len(hits) >= limit:
                    return sorted(hits)
        return sorted(hits)

    def find_pointers_to(self, targets: list[int], private_only: bool = True, limit: int = 10_000) -> dict[int, list[int]]:
        """Find 8-byte aligned values equal to any target address."""
        out: dict[int, list[int]] = {t: [] for t in targets}
        if not targets:
            return out
        pat = re.compile(b"|".join(re.escape(struct.pack("<Q", t)) for t in targets), re.DOTALL)
        count = 0
        for base, data in self.scan_regions(private_only):
            for m in pat.finditer(data):
                addr = base + m.start()
                if addr % 8:
                    continue
                out[struct.unpack("<Q", m.group())[0]].append(addr)
                count += 1
                if count >= limit:
                    return out
        return out

    def find_pointers_into(self, ranges: list[tuple[int, int]], private_only: bool = True,
                           limit: int = 100_000) -> list[tuple[int, int]]:
        """Find 8-byte aligned values v with lo <= v < hi for any (lo, hi). Returns (where, value)."""
        import numpy as np

        out: list[tuple[int, int]] = []
        for base, data in self.scan_regions(private_only):
            pad = (-base) % 8
            arr = np.frombuffer(data, dtype="<u8", offset=pad, count=(len(data) - pad) // 8)
            mask = np.zeros(arr.shape, dtype=bool)
            for lo, hi in ranges:
                mask |= (arr >= lo) & (arr < hi)
            for i in np.nonzero(mask)[0]:
                out.append((base + pad + int(i) * 8, int(arr[i])))
                if len(out) >= limit:
                    return out
        return out

    @staticmethod
    def region_of(regions: list[Region], address: int) -> Region | None:
        for r in regions:
            if r.base <= address < r.base + r.size:
                return r
        return None
