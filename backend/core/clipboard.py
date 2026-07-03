"""Small OS clipboard helper used by desktop bridges and the local API fallback."""
from __future__ import annotations

import subprocess
import sys


def set_clipboard_text(text: str) -> None:
    value = str(text or "")
    if sys.platform == "win32":
        _set_windows_clipboard(value)
    elif sys.platform == "darwin":
        subprocess.run(["pbcopy"], input=value.encode("utf-8"), check=True, timeout=5)
    else:
        subprocess.run(["xclip", "-selection", "clipboard"], input=value.encode("utf-8"), check=True, timeout=5)


def _set_windows_clipboard(text: str) -> None:
    import ctypes
    from ctypes import wintypes

    cf_unicode_text = 13
    gmem_moveable = 0x0002

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
    kernel32.GlobalFree.restype = wintypes.HANDLE

    data = (text + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(gmem_moveable, len(data))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    clipboard_open = False
    try:
        locked = kernel32.GlobalLock(handle)
        if not locked:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ctypes.memmove(locked, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)

        if not user32.OpenClipboard(None):
            raise ctypes.WinError(ctypes.get_last_error())
        clipboard_open = True
        if not user32.EmptyClipboard():
            raise ctypes.WinError(ctypes.get_last_error())
        if not user32.SetClipboardData(cf_unicode_text, handle):
            raise ctypes.WinError(ctypes.get_last_error())
        handle = None  # SetClipboardData owns the handle after success.
    finally:
        if clipboard_open:
            user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)
