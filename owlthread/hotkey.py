"""Global primer shortcut, including Windows virtual keys without scan codes."""
from __future__ import annotations

import logging
import sys
from typing import Any, Callable

logger = logging.getLogger(__name__)


class WindowsHotkeyListener:
    """Use keyboard's normal shortcut registration plus its virtual-key events.

    Windows accessibility and remote-input tools may omit scan codes. keyboard
    represents those events as negative virtual-key codes, which cannot match
    its normal physical scan-code combinations. Track just this shortcut's
    modifiers in that case; no typed text is collected or retained.
    """

    def __init__(self, callback: Callable[[],None]) -> None:
        self.callback = callback
        self._handle: Any = None
        self._virtual_hook: Any = None
        self._virtual_pressed: set[int] = set()
        self.error: str | None = None

    def start(self) -> None:
        if self._handle is not None:
            return
        try:
            import keyboard
            self._handle = keyboard.add_hotkey("ctrl+shift+p",self.callback,suppress=False,trigger_on_release=True)
            if sys.platform=="win32":
                self._virtual_hook = keyboard.hook(self._virtual_event)
            self.error = None
        except Exception as exc:
            self.error = str(exc)
            logger.warning("Global shortcut unavailable; use the tray menu")

    def _virtual_event(self, event: Any) -> None:
        code = event.scan_code
        # VK_CONTROL/L/R, VK_SHIFT/L/R, and VK_P only.
        controls = {-17,-162,-163}
        shifts = {-16,-160,-161}
        if code not in controls|shifts|{-80}:
            return
        if event.event_type=="up":
            self._virtual_pressed.discard(code)
            return
        already_pressed = code in self._virtual_pressed
        self._virtual_pressed.add(code)
        if code==-80 and not already_pressed and self._virtual_pressed&controls and self._virtual_pressed&shifts:
            self.callback()

    def stop(self) -> None:
        if self._handle is None and self._virtual_hook is None:
            return
        import keyboard
        for handle,remove in ((self._handle,keyboard.remove_hotkey),(self._virtual_hook,keyboard.unhook)):
            if handle is not None:
                try:
                    remove(handle)
                except (KeyError,ValueError):
                    logger.debug("Shortcut callback was already removed")
        self._handle = self._virtual_hook = None
        self._virtual_pressed.clear()
