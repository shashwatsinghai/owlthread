"""Windows Clipboard Watcher background service."""

import ctypes
import hashlib
import logging
import threading
import time
from typing import Optional

from owlthread.config import CLIPBOARD_POLL_INTERVAL, SOURCE_CLIPBOARD
from owlthread.db.database import Database

logger = logging.getLogger(__name__)


def _get_clipboard_text_win32() -> Optional[str]:
    """Retrieve text from Windows clipboard using win32clipboard or ctypes."""
    # Attempt 1: Try pywin32 win32clipboard
    try:
        import win32clipboard
        import win32con

        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                        return data
                    return None
                finally:
                    win32clipboard.CloseClipboard()
            except Exception:
                time.sleep(0.02)
        return None
    except ImportError:
        pass

    # Attempt 2: Fallback using ctypes
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        CF_UNICODETEXT = 13

        for _ in range(5):
            if user32.OpenClipboard(None):
                try:
                    h_clip = user32.GetClipboardData(CF_UNICODETEXT)
                    if h_clip:
                        p_data = kernel32.GlobalLock(h_clip)
                        if p_data:
                            try:
                                text = ctypes.c_wchar_p(p_data).value
                                return text
                            finally:
                                kernel32.GlobalUnlock(h_clip)
                    return None
                finally:
                    user32.CloseClipboard()
            time.sleep(0.02)
        return None
    except Exception as e:
        logger.debug("ctypes clipboard error: %s", e)
        return None


class ClipboardWatcher:
    """
    Background service polling Windows clipboard for text changes.
    
    On change, writes a row to memory_entries (raw_text, source_app="clipboard", timestamp),
    quadrant=NULL.
    """

    def __init__(
        self,
        db: Database,
        poll_interval: float = CLIPBOARD_POLL_INTERVAL
    ):
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
            self._thread.join(timeout=2.0)
        logger.info("ClipboardWatcher stopped.")

    def poll(self) -> Optional[int]:
        """
        Poll clipboard once synchronously.
        
        Returns:
            Inserted entry ID if new text was captured, None otherwise.
        """
        text = self._read_clipboard()
        if not text or not text.strip():
            return None

        current_hash = self._hash_text(text)
        if current_hash == self._last_hash:
            return None

        self._last_hash = current_hash
        active_project = self.db.get_setting("active_project", "General") or "General"
        project_id = self.db.get_or_create_project(name=active_project)

        entry_id = self.db.insert_entry(
            raw_text=text,
            source_app=SOURCE_CLIPBOARD,
            project_id=project_id,
            source_metadata={"length": len(text)},
            quadrant=None,
            status="active"
        )
        logger.info("Captured new clipboard entry #%d (%d chars) in '%s'.", entry_id, len(text), active_project)
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
