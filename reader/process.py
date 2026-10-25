"""Read-only access to a running process via the Win32 API (ctypes only).

The handle is opened with PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, so this
module can never write to or inject into the game.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import os
from dataclasses import dataclass
from typing import Iterator

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}  # R, RW, WC, XR, XRW, XWC
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE), ("szModule", wt.WCHAR * 256), ("szExePath", wt.WCHAR * 260),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD),
        ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD),
        ("Protect", wt.DWORD), ("Type", wt.DWORD),
    ]


kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Module32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p,
                                    ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]


class ProcessNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class Module:
    name: str
    base: int
    size: int
    path: str


@dataclass(frozen=True)
class Region:
    base: int
    size: int
    protect: int
    type: int  # MEM_IMAGE 0x1000000, MEM_MAPPED 0x40000, MEM_PRIVATE 0x20000


def find_pid(exe_name: str = "fm.exe") -> int:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe_name.lower():
                return entry.th32ProcessID
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    raise ProcessNotFound(f"{exe_name} is not running")


class GameProcess:
    """A read-only handle to the game process."""

    def __init__(self, exe_name: str = "fm.exe"):
        self.exe_name = exe_name
        self.pid = find_pid(exe_name)
        self.handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, self.pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._modules: dict[str, Module] | None = None

    def close(self) -> None:
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self) -> "GameProcess":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- modules -----------------------------------------------------------
    def modules(self) -> dict[str, Module]:
        if self._modules is None:
            snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid)
            if snap == INVALID_HANDLE_VALUE:
                raise ctypes.WinError(ctypes.get_last_error())
            mods: dict[str, Module] = {}
            try:
                entry = MODULEENTRY32W()
                entry.dwSize = ctypes.sizeof(entry)
                ok = kernel32.Module32FirstW(snap, ctypes.byref(entry))
                while ok:
                    mods[entry.szModule.lower()] = Module(entry.szModule, entry.modBaseAddr or 0,
                                                          entry.modBaseSize, entry.szExePath)
                    ok = kernel32.Module32NextW(snap, ctypes.byref(entry))
            finally:
                kernel32.CloseHandle(snap)
            self._modules = mods
        return self._modules

    def module(self, name: str) -> Module:
        return self.modules()[name.lower()]

    def build_id(self, module_name: str = "game_plugin.dll") -> str:
        """Short hash identifying the game build; offset profiles are keyed by it."""
        path = self.module(module_name).path
        h = hashlib.sha256()
        h.update(str(os.path.getsize(path)).encode())
        with open(path, "rb") as f:
            h.update(f.read(1 << 20))  # first MiB (headers + start of .text) is enough to fingerprint
        return h.hexdigest()[:12]

    # -- memory ------------------------------------------------------------
    def read(self, address: int, size: int) -> bytes | None:
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)):
            return None
        return buf.raw[: got.value]

    def regions(self, readable_only: bool = True) -> Iterator[Region]:
        mbi = MEMORY_BASIC_INFORMATION()
        addr = 0
        while kernel32.VirtualQueryEx(self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if mbi.State == MEM_COMMIT and (not readable_only or (
                    (mbi.Protect & 0xFF) in READABLE and not mbi.Protect & PAGE_GUARD)):
                yield Region(base, size, mbi.Protect, mbi.Type)
            addr = base + size
            if addr >= 0x7FFFFFFFFFFF:
                break
