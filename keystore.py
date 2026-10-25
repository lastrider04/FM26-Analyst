"""Encrypt secrets at rest with Windows DPAPI (bound to the current Windows user), no extra packages."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

_ENTROPY = b"fm-analyst/llm-api-key/v1"   # app-specific: other DPAPI users of this account can't decrypt by accident


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _call(fn, data: bytes) -> bytes:
    src, ent, out = _blob(data), _blob(_ENTROPY), _Blob()
    if not fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out)):  # UI_FORBIDDEN
        raise OSError(ctypes.WinError())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(secret: str) -> str:
    return base64.b64encode(_call(ctypes.windll.crypt32.CryptProtectData, secret.encode())).decode()


def unprotect(token: str) -> str:
    return _call(ctypes.windll.crypt32.CryptUnprotectData, base64.b64decode(token)).decode()
