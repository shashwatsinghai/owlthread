"""System Tray Application for OwlThread."""

import ctypes
import logging
import sys
import threading
import webbrowser
from typing import Optional

from PIL import Image, ImageDraw

from owlthread.capture.engine import CaptureEngine
from owlthread.config import DEFAULT_HTTP_PORT
from owlthread.db.database import Database
from owlthread.primer.engine import PrimerEngine
from owlthread.primer.ui import open_primer_popup

logger = logging.getLogger(__name__)


def create_tray_icon_image(is_active: bool = True) -> Image.Image:
    """Generate a clean OwlThread tray icon."""
    width = 64
    height = 64
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Outer circle background
    bg_color = (67, 56, 202) if is_active else (100, 116, 139)  # Indigo when active, Slate when paused
    draw.ellipse((4, 4, 60, 60), fill=bg_color)

    # Owl eyes
    eye_color = (255, 255, 255)
    pupil_color = (15, 23, 42)
    # Left eye
    draw.ellipse((16, 20, 30, 34), fill=eye_color)
    draw.ellipse((22, 24, 28, 30), fill=pupil_color)
    # Right eye
    draw.ellipse((34, 20, 48, 34), fill=eye_color)
    draw.ellipse((36, 24, 42, 30), fill=pupil_color)

    # Beak (downward triangle)
    beak_color = (245, 158, 11)  # Amber
    draw.polygon([(32, 36), (27, 44), (37, 44)], fill=beak_color)

    # Small status indicator dot at bottom right
    status_color = (34, 197, 94) if is_active else (239, 68, 68)  # Green or Red
    draw.ellipse((46, 46, 58, 58), fill=status_color, outline=(255, 255, 255), width=1)

    return image


class WindowsHotkeyListener:
    """Background listener for global hotkeys on Windows (e.g. Ctrl+Shift+P)."""

    def __init__(self, callback):
        self.callback = callback
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._thread_id: Optional[int] = None

    def start(self) -> None:
        if sys.platform != "win32":
            return
        self._running = True
        self._thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if sys.platform == "win32" and self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass

    def _hotkey_loop(self) -> None:
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._thread_id = kernel32.GetCurrentThreadId()

            # Hotkey 1: Ctrl + Shift + P
            MOD_CONTROL = 0x0002
            MOD_SHIFT = 0x0004
            MOD_NOREPEAT = 0x4000
            VK_P = 0x50
            HOTKEY_ID_1 = 101

            success = user32.RegisterHotKey(
                None, HOTKEY_ID_1, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_P
            )
            if success:
                logger.info("Global hotkey registered: Ctrl+Shift+P")
            else:
                logger.debug("Failed to register Ctrl+Shift+P hotkey (may already be in use).")

            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", ctypes.c_void_p),
                    ("message", ctypes.c_uint),
                    ("wParam", ctypes.c_void_p),
                    ("lParam", ctypes.c_void_p),
                    ("time", ctypes.c_ulong),
                    ("pt_x", ctypes.c_long),
                    ("pt_y", ctypes.c_long),
                ]

            msg = MSG()
            while self._running:
                # Peek or Get message
                res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if res == 0 or res == -1:  # WM_QUIT or Error
                    break
                if msg.message == 0x0312:  # WM_HOTKEY
                    try:
                        self.callback()
                    except Exception as ex:
                        logger.error("Error in hotkey callback: %s", ex)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            user32.UnregisterHotKey(None, HOTKEY_ID_1)
        except Exception as e:
            logger.debug("Hotkey loop terminated: %s", e)


class OwlThreadTrayApp:
    """System Tray Application managing CaptureEngine and Primer Engine."""

    def __init__(
        self,
        port: int = DEFAULT_HTTP_PORT,
        enable_clipboard: bool = True,
        enable_connectors: bool = True
    ):
        self.db = Database()
        self.port = port
        self.engine = CaptureEngine(
            db=self.db,
            http_port=port,
            enable_clipboard=enable_clipboard,
            enable_connectors=enable_connectors,
            enable_http=True
        )
        self.primer_engine = PrimerEngine(db=self.db)
        self.hotkey_listener = WindowsHotkeyListener(self.open_primer_popup)
        self.icon = None
        self._is_paused = False

    def open_primer_popup(self, icon=None, item=None):
        """Open the Primer Query popup window in a dedicated UI thread."""
        def _launch():
            try:
                open_primer_popup(engine=self.primer_engine)
            except Exception as e:
                logger.exception("Failed to open primer popup: %s", e)

        threading.Thread(target=_launch, daemon=True).start()

    def on_toggle_pause(self, icon, item):
        """Toggle capture engine state."""
        if self._is_paused:
            self.engine.start()
            self._is_paused = False
            icon.icon = create_tray_icon_image(is_active=True)
            icon.title = f"OwlThread - Active ({self.db.count_entries()} entries)"
        else:
            self.engine.stop()
            self._is_paused = True
            icon.icon = create_tray_icon_image(is_active=False)
            icon.title = "OwlThread - Paused"

    def on_open_health(self, icon, item):
        """Open local status endpoint in default browser."""
        url = f"http://127.0.0.1:{self.port}/health"
        webbrowser.open(url)

    def on_open_entries(self, icon, item):
        """Open entries endpoint in default browser."""
        url = f"http://127.0.0.1:{self.port}/entries"
        webbrowser.open(url)

    def on_exit(self, icon, item):
        """Cleanly stop engine, hotkey listener, and terminate tray icon."""
        logger.info("Exiting OwlThread Tray App...")
        self.hotkey_listener.stop()
        self.engine.stop()
        icon.stop()

    def get_status_label(self, item) -> str:
        count = self.db.count_entries()
        state = "Paused" if self._is_paused else "Active"
        return f"Status: {state} ({count} memories captured)"

    def run(self) -> None:
        """Start engine, hotkey listener, and run system tray loop."""
        import pystray

        # Start capture engine
        self.engine.start()

        # Start global hotkey listener
        self.hotkey_listener.start()

        menu_items = (
            pystray.MenuItem("⚡ State Task & Get Primer... (Ctrl+Shift+P)", self.open_primer_popup, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self.get_status_label, lambda icon, item: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: "Resume Capture" if self._is_paused else "Pause Capture",
                self.on_toggle_pause
            ),
            pystray.MenuItem("View Recent Entries (/entries)", self.on_open_entries),
            pystray.MenuItem("Check Server Health (/health)", self.on_open_health),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit OwlThread", self.on_exit),
        )

        self.icon = pystray.Icon(
            "OwlThread",
            create_tray_icon_image(is_active=True),
            f"OwlThread - Active ({self.db.count_entries()} entries)",
            menu=pystray.Menu(*menu_items)
        )

        logger.info("OwlThread system tray initialized.")
        self.icon.run()


def run_tray(
    port: int = DEFAULT_HTTP_PORT,
    enable_clipboard: bool = True,
    enable_connectors: bool = True
) -> None:
    """Convenience helper to launch tray app."""
    app = OwlThreadTrayApp(
        port=port,
        enable_clipboard=enable_clipboard,
        enable_connectors=enable_connectors
    )
    app.run()


if __name__ == "__main__":
    run_tray()
