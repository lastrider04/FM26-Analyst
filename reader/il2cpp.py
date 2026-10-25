"""Minimal read-only helpers for IL2CPP managed objects (Unity C# layer).

Il2CppObject:  +0x00 Il2CppClass*, +0x08 monitor
Il2CppClass:   +0x10 const char* name, +0x18 const char* namespace
Il2CppString:  +0x10 i32 length, +0x14 UTF-16 chars
Il2CppArray:   +0x18 u64 max_length, +0x20 data
"""
from __future__ import annotations

import struct

from .memory import Memory

USER_MIN, USER_MAX = 0x10000, 0x7FFFFFFFFFFF


def is_ptr(v: int | None) -> bool:
    return bool(v) and USER_MIN < v < USER_MAX


class Il2Cpp:
    def __init__(self, mem: Memory):
        self.mem = mem
        self._names: dict[int, str | None] = {}

    def class_name(self, obj: int | None) -> str | None:
        if not is_ptr(obj):
            return None
        k = self.mem.ptr(obj)
        if not is_ptr(k):
            return None
        if k not in self._names:
            n, ns = self.mem.ptr(k + 0x10), self.mem.ptr(k + 0x18)
            name = self.mem.utf8(n, 96) if is_ptr(n) else None
            if not name or not name.isprintable():
                self._names[k] = None
            else:
                nsn = self.mem.utf8(ns, 96) if is_ptr(ns) else ""
                self._names[k] = f"{nsn}.{name}" if nsn else name
        return self._names[k]

    def string(self, obj: int | None) -> str | None:
        if self.class_name(obj) != "System.String":
            return None
        n = self.mem.i32(obj + 0x10)
        if n is None or not 0 <= n < 4096:
            return None
        raw = self.mem.proc.read(obj + 0x14, n * 2)
        return raw.decode("utf-16-le", "replace") if raw is not None else None

    def array(self, obj: int, elem_size: int = 8) -> list[bytes]:
        n = self.mem.i64(obj + 0x18)
        if n is None or not 0 <= n < 1_000_000:
            return []
        data = self.mem.proc.read(obj + 0x20, n * elem_size) or b""
        return [data[i:i + elem_size] for i in range(0, len(data), elem_size)]

    def describe_fields(self, obj: int, size: int = 0x80) -> list[str]:
        """One line per 8-byte slot after the header: pointer class / string / numbers."""
        blob = self.mem.proc.read(obj, size) or b""
        out = []
        for off in range(0x10, len(blob) - 7, 8):
            q = struct.unpack_from("<Q", blob, off)[0]
            cn = self.class_name(q) if is_ptr(q) else None
            if cn == "System.String":
                desc = f"'{self.string(q)}'"
            elif cn:
                desc = f"-> {cn} @0x{q:X}"
            else:
                i0, i1 = struct.unpack_from("<ii", blob, off)
                f0, f1 = struct.unpack_from("<ff", blob, off)
                d = struct.unpack_from("<d", blob, off)[0]
                desc = f"i32=({i0},{i1}) f32=({f0:.4g},{f1:.4g}) f64={d:.6g}"
            out.append(f"+0x{off:X} {desc}")
        return out
