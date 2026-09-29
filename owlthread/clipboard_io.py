"""Clipboard access without creating Tk roots on background threads."""
from __future__ import annotations
import ctypes
import logging
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)
_clipboard_lock = threading.Lock()


def _windows_api() -> tuple[Any,Any]:
    from ctypes import wintypes
    user = ctypes.WinDLL("user32",use_last_error=True)
    kernel = ctypes.WinDLL("kernel32",use_last_error=True)
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.OpenClipboard.restype = wintypes.BOOL
    user.GetClipboardData.argtypes = [wintypes.UINT]
    user.GetClipboardData.restype = wintypes.HANDLE
    user.SetClipboardData.argtypes = [wintypes.UINT,wintypes.HANDLE]
    user.SetClipboardData.restype = wintypes.HANDLE
    kernel.GlobalAlloc.argtypes = [wintypes.UINT,ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.restype = wintypes.HGLOBAL
    return user,kernel


def read_clipboard() -> str | None:
    if sys.platform != "win32":
        return None
    with _clipboard_lock:
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                return win32clipboard.GetClipboardData(13) if win32clipboard.IsClipboardFormatAvailable(13) else None
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            logger.debug("Using native clipboard fallback")
        try:
            user,kernel = _windows_api()
            if not user.OpenClipboard(None):
                return None
            try:
                handle = user.GetClipboardData(13)
                pointer = kernel.GlobalLock(handle) if handle else None
                if not pointer:
                    return None
                try:
                    return ctypes.wstring_at(pointer)
                finally:
                    kernel.GlobalUnlock(handle)
            finally:
                user.CloseClipboard()
        except Exception:
            logger.debug("Clipboard is temporarily unavailable")
            return None


def copy_to_clipboard(text: str) -> bool:
    if not text:
        return False
    with _clipboard_lock:
        if sys.platform == "win32":
            handle = None
            transferred = False
            try:
                user,kernel = _windows_api()
                data = text.encode("utf-16le")+b"\0\0"
                handle = kernel.GlobalAlloc(2,len(data))
                pointer = kernel.GlobalLock(handle) if handle else None
                if not pointer:
                    raise OSError("Clipboard allocation failed")
                ctypes.memmove(pointer,data,len(data))
                kernel.GlobalUnlock(handle)
                for _ in range(5):
                    if user.OpenClipboard(None):
                        break
                    time.sleep(0.03)
                else:
                    raise OSError("Clipboard busy")
                try:
                    if not user.EmptyClipboard():
                        raise OSError("Clipboard clear failed")
                    if not user.SetClipboardData(13,handle):
                        raise OSError("Clipboard write failed")
                    transferred = True
                    return True
                finally:
                    user.CloseClipboard()
            except Exception:
                logger.debug("Clipboard copy failed")
            finally:
                if handle and not transferred:
                    kernel.GlobalFree(handle)
        else:
            candidates = [["pbcopy"]] if sys.platform=="darwin" else [["wl-copy"],["xclip","-selection","clipboard"],["xsel","--clipboard","--input"]]
            for command in candidates:
                if shutil.which(command[0]):
                    try:
                        subprocess.run(command,input=text.encode("utf-8"),check=True,timeout=3,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                        return True
                    except (OSError,subprocess.SubprocessError):
                        logger.debug("Clipboard utility unavailable")
    return False
