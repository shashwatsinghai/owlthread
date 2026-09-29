"""System tray and keyboard shortcut dispatch into a single Tk event loop."""
from __future__ import annotations
import logging
from typing import Any, Callable
from PIL import Image, ImageDraw
from owlthread.config import DEFAULT_HTTP_PORT
from owlthread.gui.app import OwlThreadApp
from owlthread.hotkey import WindowsHotkeyListener

logger = logging.getLogger(__name__)


def create_tray_icon_image(is_active: bool = True) -> Image.Image:
    image = Image.new("RGBA",(64,64),(0,0,0,0))
    draw = ImageDraw.Draw(image)
    color = "#a7a1ff" if is_active else "#6b7280"
    draw.polygon([(8,8),(20,18),(44,18),(56,8),(53,46),(32,60),(11,46)],fill=color)
    for x in (23,41):
        draw.ellipse((x-10,22,x+10,42),fill="#1a1a2e")
        draw.ellipse((x-3,27,x+3,36),fill="#e2e8f0")
    draw.polygon([(28,43),(36,43),(32,49)],fill="#e2e8f0")
    return image


class OwlThreadTray:
    def __init__(self, port: int = DEFAULT_HTTP_PORT, enable_clipboard: bool | None = None,
                 enable_connectors: bool | None = None) -> None:
        self.app = OwlThreadApp(port=port,auto_start_engine=False)
        from owlthread.capture.engine import CaptureEngine
        self.app.engine = CaptureEngine(self.app.db,http_port=port,enable_clipboard=enable_clipboard,enable_connectors=enable_connectors)
        self.app.primer_engine.pipeline = self.app.engine.pipeline
        self.hotkey = WindowsHotkeyListener(lambda:self.app._actions.put(self.app.open_primer))
        self.icon: Any = None

    def run(self) -> None:
        import pystray
        try:
            self.app.engine.start()
        except Exception:
            self.app.db.close()
            self.app.destroy()
            raise
        def show(view: str) -> None:
            def display() -> None:
                self.app.deiconify()
                self.app.show_view(view)
                self.app.lift()
            self.app._actions.put(display)
        def sync() -> None:
            def display() -> None:
                self.app.deiconify()
                self.app._job(self.app.engine.status,lambda status:self.app.footer.configure(text=f"Capture {'running' if status['engine_running'] else 'stopped'} · {status['pending_captures']} pending · {status['total_entries']} memories"))
            self.app._actions.put(display)
        menu = pystray.Menu(
            pystray.MenuItem("State Task & Get Primer…",lambda *_:self.app._actions.put(self.app.open_primer),default=True),
            pystray.MenuItem("View Memory Feed",lambda *_:show("feed")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Prompts & Settings",lambda *_:show("settings")),
            pystray.MenuItem("Sync Status",lambda *_:sync()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit OwlThread",lambda *_:self.app._actions.put(self.app._on_close)))
        self.icon = pystray.Icon("OwlThread",create_tray_icon_image(),"OwlThread — State your task, get context.",menu)
        self.app.on_quit = self._stop
        self.icon.run_detached()
        self.hotkey.start()
        self.app.withdraw()
        self.app.mainloop()

    def _stop(self) -> None:
        self.hotkey.stop()
        if self.icon:
            self.icon.stop()


OwlThreadTrayApp = OwlThreadTray


def run_tray(port: int = DEFAULT_HTTP_PORT, enable_clipboard: bool | None = None, enable_connectors: bool | None = None) -> None:
    OwlThreadTray(port,enable_clipboard,enable_connectors).run()
