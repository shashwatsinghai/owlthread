"""Universal Capture Engine orchestrator for OwlThread."""

import logging
import threading
from typing import Any, Dict, List, Optional

from owlthread.capture.clipboard import ClipboardWatcher
from owlthread.capture.connectors.base import IConnector
from owlthread.capture.connectors.cursor import CursorConnector
from owlthread.capture.connectors.vscode_copilot import VSCodeCopilotConnector
from owlthread.capture.server import LocalHttpListener
from owlthread.config import (
    CONNECTOR_POLL_INTERVAL,
    DEFAULT_HTTP_PORT,
)
from owlthread.db.database import Database
from owlthread.extraction.pipeline import ExtractionPipeline

logger = logging.getLogger(__name__)


class CaptureEngine:
    """
    Coordinates and manages all capture surfaces:
    1. Clipboard Watcher
    2. File Connectors (Cursor, VS Code Copilot, etc.)
    3. Local HTTP Server (for browser extension)
    4. Phase 2 Extraction & Rebase Pipeline
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        http_port: int = DEFAULT_HTTP_PORT,
        enable_clipboard: bool = True,
        enable_connectors: bool = True,
        enable_http: bool = True,
        connector_poll_interval: float = CONNECTOR_POLL_INTERVAL,
        pipeline: Optional[ExtractionPipeline] = None,
    ):
        self.db = db or Database()
        self.http_port = http_port
        self.enable_clipboard = enable_clipboard
        self.enable_connectors = enable_connectors
        self.enable_http = enable_http
        self.connector_poll_interval = connector_poll_interval
        self.pipeline = pipeline or ExtractionPipeline(db=self.db)

        # Components
        self.clipboard_watcher: Optional[ClipboardWatcher] = None
        if self.enable_clipboard:
            self.clipboard_watcher = ClipboardWatcher(self.db)

        self.http_listener: Optional[LocalHttpListener] = None
        if self.enable_http:
            self.http_listener = LocalHttpListener(self.db, port=self.http_port)

        self.connectors: List[IConnector] = []
        if self.enable_connectors:
            self.connectors.append(CursorConnector(self.db))
            self.connectors.append(VSCodeCopilotConnector(self.db))

        self._connector_stop_event = threading.Event()
        self._connector_thread: Optional[threading.Thread] = None
        self._is_running = False
        self.http_listener_error: Optional[str] = None

    @property
    def is_running(self) -> bool:
        """Return True if engine is running."""
        return self._is_running

    def register_connector(self, connector: IConnector) -> None:
        """Register a custom IConnector."""
        self.connectors.append(connector)
        if self._is_running:
            connector.start()

    def add_capture_callback(self, callback) -> None:
        """Register a callback for new captures arriving via HTTP server."""
        if self.http_listener:
            self.http_listener.add_capture_callback(callback)

    def start(self) -> None:
        """Start all capture components."""
        if self._is_running:
            return

        logger.info("Starting Universal Capture Engine...")
        self._is_running = True
        self.http_listener_error = None

        # 1. Start HTTP Server
        if self.http_listener:
            try:
                self.http_listener.start()
            except Exception as e:
                self.http_listener_error = str(e)
                logger.error("Failed starting HTTP listener: %s", e)

        # 2. Start Clipboard Watcher
        if self.clipboard_watcher:
            try:
                self.clipboard_watcher.start()
            except Exception as e:
                logger.error("Failed starting Clipboard Watcher: %s", e)

        # 3. Start Connectors
        for connector in self.connectors:
            try:
                connector.start()
            except Exception as e:
                logger.error("Failed starting connector %s: %s", connector.name, e)

        if self.connectors:
            self._connector_stop_event.clear()
            self._connector_thread = threading.Thread(
                target=self._run_connector_loop,
                name="OwlThread-ConnectorPoller",
                daemon=True
            )
            self._connector_thread.start()

        logger.info("Universal Capture Engine running.")

    def stop(self) -> None:
        """Stop all capture components."""
        if not self._is_running:
            return

        logger.info("Stopping Universal Capture Engine...")
        self._is_running = False

        # Stop connector loop
        self._connector_stop_event.set()
        if self._connector_thread and self._connector_thread.is_alive():
            self._connector_thread.join(timeout=2.0)

        # Stop connectors
        for connector in self.connectors:
            try:
                connector.stop()
            except Exception as e:
                logger.error("Error stopping connector %s: %s", connector.name, e)

        # Stop clipboard watcher
        if self.clipboard_watcher:
            try:
                self.clipboard_watcher.stop()
            except Exception as e:
                logger.error("Error stopping clipboard watcher: %s", e)

        # Stop HTTP server
        if self.http_listener:
            try:
                self.http_listener.stop()
            except Exception as e:
                logger.error("Error stopping HTTP listener: %s", e)

        logger.info("Universal Capture Engine stopped.")

    def poll_connectors_once(self) -> Dict[str, int]:
        """Manually trigger a synchronous poll for all registered connectors."""
        results = {}
        for connector in self.connectors:
            try:
                captured = connector.poll()
                results[connector.name] = captured
            except Exception as e:
                logger.error("Error during manual poll of %s: %s", connector.name, e)
                results[connector.name] = 0
        return results

    def handle_done_signal(self) -> Dict[str, Any]:
        """Trigger buffer flush and extraction."""
        return self.pipeline.handle_done_signal()

    def _run_connector_loop(self) -> None:
        """Background thread polling file connectors periodically."""
        while not self._connector_stop_event.is_set():
            for connector in self.connectors:
                if self._connector_stop_event.is_set():
                    break
                try:
                    connector.poll()
                except Exception as e:
                    logger.error("Error polling connector %s: %s", connector.name, e)

            self._connector_stop_event.wait(self.connector_poll_interval)

    def status(self) -> Dict[str, Any]:
        """Return operational status of all surfaces."""
        connector_statuses = [
            {"name": c.name, "is_running": c.is_running}
            for c in self.connectors
        ]
        return {
            "engine_running": self._is_running,
            "clipboard_watcher": self.clipboard_watcher.is_running if self.clipboard_watcher else False,
            "http_listener": {
                "running": self.http_listener.is_running if self.http_listener else False,
                "host": self.http_listener.host if self.http_listener else None,
                "port": self.http_listener.port if self.http_listener else None,
            },
            "connectors": connector_statuses,
            "total_entries": self.db.count_entries(),
            "active_buffers": self.pipeline.buffer_manager.get_stats(),
        }
