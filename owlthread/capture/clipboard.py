"""Windows Clipboard Watcher background service."""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Optional

from owlthread.config import CLIPBOARD_POLL_INTERVAL, SOURCE_CLIPBOARD
from owlthread.db.database import Database

logger = logging.getLogger(__name__)


from owlthread.clipboard_io import read_clipboard as _get_clipboard_text_win32


class ClipboardWatcher:
    """
    Background service polling Windows clipboard for text changes.
    
    On change, durably saves the text to capture_buffer for later extraction.
    """

    def __init__(
        self,
        db: Database,
        poll_interval: float = CLIPBOARD_POLL_INTERVAL
    ) -> None:
        self.db = db
        self.poll_interval = poll_interval
        self._last_hash: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Return True if background poller thread is running."""
        return self._is_running

    def start(self) -> None:
        """Start the clipboard polling background thread."""
        if self._is_running:
            return

        self._stop_event.clear()
        self._is_running = True

        # Initialize last_hash with current clipboard text so we don't immediately capture old clip
        initial_text = self._read_clipboard()
        if initial_text:
            self._last_hash = self._hash_text(initial_text)

        self._thread = threading.Thread(
            target=self._run_loop,
            name="OwlThread-ClipboardWatcher",
            daemon=True
        )
        self._thread.start()
        logger.info("ClipboardWatcher started (poll interval: %.2fs).", self.poll_interval)

    def stop(self) -> None:
        """Signal and wait for the clipboard poller thread to exit."""
        if not self._is_running:
            return

        self._is_running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join()
        logger.info("ClipboardWatcher stopped.")

    def poll(self) -> Optional[int]:
        """
        Poll clipboard once synchronously.
        
        Returns:
            Inserted entry ID if new text was captured, None otherwise.
        """
        text = self._read_clipboard()
        if not text:
            return None

        current_hash = self._hash_text(text)
        if current_hash == self._last_hash:
            return None
        # Advance before policy checks: text copied while paused/too short/self-produced
        # must never become a stale capture on a later polling cycle.
        self._last_hash = current_hash
        if (len(text.strip()) <= 20 or self.db.get_setting("capture_paused", "false") == "true" or
                current_hash == self.db.get_setting("last_primer_clipboard_hash")):
            return None

        active_project = self.db.get_setting("active_project", "General") or "General"
        project_id = self.db.get_or_create_project(name=active_project)

        entry_id = self.db.insert_capture(
            raw_text=text,
            source_app=SOURCE_CLIPBOARD,
            project_id=project_id,
            source_metadata={"length": len(text)}
        )
        logger.debug("Captured new clipboard entry #%d (%d chars) in '%s'.", entry_id, len(text), active_project)
        return entry_id

    def _read_clipboard(self) -> Optional[str]:
        """Safely fetch current clipboard text."""
        return _get_clipboard_text_win32()

    def _hash_text(self, text: str) -> str:
        """Compute SHA-256 hash of text for change detection."""
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

    def _run_loop(self) -> None:
        """Main polling loop for background thread."""
        while not self._stop_event.is_set():
            try:
                self.poll()
            except Exception as e:
                logger.error("Error in clipboard poll loop: %s", e)
            self._stop_event.wait(self.poll_interval)
