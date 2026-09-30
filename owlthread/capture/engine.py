"""Lifecycle owner for clipboard, connectors, HTTP and periodic extraction."""
from __future__ import annotations
import logging
import threading
from typing import Any, Callable, TYPE_CHECKING
if TYPE_CHECKING:
    from owlthread.capture.connectors.base import IConnector
from owlthread.capture.server import LocalHttpListener
from owlthread.config import DEFAULT_HTTP_PORT, CONNECTOR_POLL_INTERVAL
from owlthread.db.database import Database
from owlthread.extraction.pipeline import ExtractionPipeline
from owlthread.security import paired_origin_count

logger = logging.getLogger(__name__)


class CaptureEngine:
    def __init__(self, db: Database | None = None, http_port: int = DEFAULT_HTTP_PORT,
                 enable_clipboard: bool | None = None, enable_connectors: bool | None = None, enable_http: bool = True,
                 connector_poll_interval: float = CONNECTOR_POLL_INTERVAL,
                 pipeline: ExtractionPipeline | None = None, flush_interval: float = 60) -> None:
        self._owns_db = db is None
        self.db = db or Database()
        self.strict_site_isolation = self.db.get_setting("strict_site_isolation", "true") != "false"
        if enable_clipboard is None:
            # The clipboard has no trustworthy source URL. Keep it off by default
            # when immutable website blocking is required; explicit construction
            # remains available for advanced/test use.
            enable_clipboard = (not self.strict_site_isolation and
                                self.db.get_setting("clipboard_enabled", "false") == "true")
        if enable_connectors is None:
            enable_connectors = self.db.get_setting("ide_capture_enabled", "false") == "true"
        self.pipeline = pipeline or ExtractionPipeline(self.db)
        if enable_clipboard:
            from owlthread.capture.clipboard import ClipboardWatcher
            self.clipboard_watcher = ClipboardWatcher(self.db)
        else:
            self.clipboard_watcher = None
        self.http_listener = LocalHttpListener(self.db,port=http_port,pipeline=self.pipeline) if enable_http else None
        self.connectors: list[IConnector] = []
        if enable_connectors:
            from owlthread.capture.connectors.cursor import CursorConnector
            from owlthread.capture.connectors.vscode import VSCodeCopilotConnector
            self.connectors = [CursorConnector(self.db), VSCodeCopilotConnector(self.db)]
        for connector in self.connectors:
            connector.poll_interval = connector_poll_interval
        self.flush_interval = flush_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._is_running = False
        self.http_listener_error: str | None = None
        if self.http_listener:
            self.http_listener.status_callback = self.status

    @property
    def is_running(self) -> bool:
        return self._is_running

    def register_connector(self, connector: IConnector) -> None:
        self.connectors.append(connector)
        if self.is_running:
            connector.start()

    def add_capture_callback(self, callback: Callable[[dict[str,Any]],None]) -> None:
        if self.http_listener:
            self.http_listener.add_capture_callback(callback)

    def start(self) -> None:
        if self.is_running:
            return
        self.http_listener_error = None
        # Bind first; an occupied port must not start a second invisible capture daemon.
        if self.http_listener:
            try:
                self.http_listener.start()
            except OSError as exc:
                self.http_listener_error = str(exc)
                raise RuntimeError("OwlThread's port is already in use. Open the running app or choose another port.") from exc
        self._is_running = True
        if self.clipboard_watcher:
            self.clipboard_watcher.start()
        for connector in self.connectors:
            connector.start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._flush_loop,name="OwlThread-Extraction",daemon=True)
        self._thread.start()

    def _flush_loop(self) -> None:
        while not self._stop.wait(self.flush_interval):
            try:
                self.pipeline.handle_done_signal()
            except Exception:
                logger.exception("Periodic extraction failed; captures remain in SQLite")

    def stop(self) -> None:
        self._stop.set()
        if self.clipboard_watcher:
            self.clipboard_watcher.stop()
        for connector in self.connectors:
            connector.stop()
        if self.http_listener:
            self.http_listener.stop()
        if self._thread:
            self._thread.join()
        self._is_running = False
        if self._owns_db:
            self.db.close()

    def poll_connectors_once(self) -> dict[str,int]:
        counts = {}
        for connector in self.connectors:
            try:
                counts[connector.name] = connector.poll()
            except Exception:
                logger.exception("Connector poll failed: %s",connector.name)
                counts[connector.name] = 0
        return counts

    def handle_done_signal(self) -> dict[str,Any]:
        return self.pipeline.handle_done_signal()

    def status(self) -> dict[str,Any]:
        self.pipeline.llm_client.reload_from_db(self.db)
        return {"engine_running":self.is_running,"clipboard_watcher":bool(self.clipboard_watcher and self.clipboard_watcher.is_running),
                "http_listener":{"running":bool(self.http_listener and self.http_listener.is_running),
                                 "host":"127.0.0.1","port":self.http_listener.port if self.http_listener else None},
                "connectors":[{"name":c.name,"is_running":c.is_running,"error":c.last_error} for c in self.connectors],
                "total_entries":self.db.count_entries(),"pending_captures":self.db.pending_count(),
                "capture_transfer":self.db.capture_status(),"authorized_browser_count":paired_origin_count(self.db),
                "active_project":self.db.get_setting("active_project","General"),
                "capture_paused":self.db.get_setting("capture_paused","false")=="true",
                "strict_site_isolation":self.strict_site_isolation,
                "model_provider":self.pipeline.llm_client.provider,"model_name":self.pipeline.llm_client.model,
                "model_ready":self.pipeline.llm_client.is_available()}
