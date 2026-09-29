"""Shortcut lifecycle and Windows accessibility/remote-input key handling."""
from __future__ import annotations
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from owlthread.hotkey import WindowsHotkeyListener


class HotkeyTests(unittest.TestCase):
    def test_virtual_key_chord_requires_modifiers_and_fires_once(self) -> None:
        callback = Mock()
        listener = WindowsHotkeyListener(callback)
        def key(code: int, direction: str = "down") -> None:
            listener._virtual_event(SimpleNamespace(scan_code=code,event_type=direction))
        key(-80)
        key(-80,"up")
        callback.assert_not_called()
        key(-162)
        key(-160)
        key(-80)
        key(-80)
        callback.assert_called_once()
        key(-80,"up")
        key(-160,"up")
        key(-80)
        callback.assert_called_once()
        key(25) # Physical keys are handled by keyboard.add_hotkey only.
        callback.assert_called_once()

    def test_start_and_stop_are_idempotent(self) -> None:
        callback = Mock()
        with patch("owlthread.hotkey.sys.platform","win32"), \
             patch("keyboard.add_hotkey",return_value="physical") as add, \
             patch("keyboard.hook",return_value="virtual") as hook, \
             patch("keyboard.remove_hotkey") as remove,patch("keyboard.unhook") as unhook:
            listener = WindowsHotkeyListener(callback)
            listener.start()
            listener.start()
            add.assert_called_once()
            hook.assert_called_once()
            add.call_args.args[1]()
            callback.assert_called_once()
            listener.stop()
            listener.stop()
            remove.assert_called_once_with("physical")
            unhook.assert_called_once_with("virtual")
