"""Unit tests for Clipboard Watcher."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from owlthread.capture.clipboard import ClipboardWatcher
from owlthread.capture.engine import CaptureEngine
from owlthread.db.database import Database


class TestClipboardWatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp_dir.name) / "test.db"))
        self.watcher = ClipboardWatcher(self.db, poll_interval=0.05)

    def tearDown(self):
        self.watcher.stop()
        self.db.close()
        self.temp_dir.cleanup()

    @patch("owlthread.capture.clipboard.ClipboardWatcher._read_clipboard")
    def test_clipboard_change_detection(self, mock_read):
        # 1. First poll with text
        mock_read.return_value = "Initial copied text longer than twenty"
        entry_id = self.watcher.poll()
        self.assertIsNotNone(entry_id)

        entry = self.db.get_unprocessed_captures()[0]
        self.assertEqual(entry["raw_text"], "Initial copied text longer than twenty")
        self.assertEqual(entry["source_app"], "clipboard")
        self.assertEqual(self.db.count_entries(), 0)

        # 2. Same text should not produce duplicate entry
        entry_id2 = self.watcher.poll()
        self.assertIsNone(entry_id2)
        self.assertEqual(self.db.pending_count(), 1)

        # 3. New text should produce new entry
        mock_read.return_value = "Second distinct copied text"
        entry_id3 = self.watcher.poll()
        self.assertIsNotNone(entry_id3)
        self.assertEqual(self.db.pending_count(), 2)

    @patch("owlthread.capture.clipboard.ClipboardWatcher._read_clipboard")
    def test_empty_or_whitespace_clipboard_ignored(self, mock_read):
        mock_read.return_value = ""
        self.assertIsNone(self.watcher.poll())

        mock_read.return_value = "   \n\t  "
        self.assertIsNone(self.watcher.poll())

        self.assertEqual(self.db.count_entries(), 0)

    @patch("owlthread.capture.clipboard.ClipboardWatcher._read_clipboard")
    def test_text_seen_while_paused_never_becomes_a_stale_capture(self, mock_read):
        mock_read.return_value = "Text copied while capture was intentionally paused"
        self.db.set_setting("capture_paused", "true")
        self.assertIsNone(self.watcher.poll())
        self.db.set_setting("capture_paused", "false")
        self.assertIsNone(self.watcher.poll())
        self.assertEqual(self.db.pending_count(), 0)

    def test_strict_site_isolation_disables_implicit_clipboard_watcher(self):
        self.db.set_setting("clipboard_enabled", "true")
        strict = CaptureEngine(self.db, enable_http=False)
        self.assertTrue(strict.strict_site_isolation)
        self.assertIsNone(strict.clipboard_watcher)
        self.db.set_setting("strict_site_isolation", "false")
        relaxed = CaptureEngine(self.db, enable_http=False)
        self.assertFalse(relaxed.strict_site_isolation)
        self.assertIsNotNone(relaxed.clipboard_watcher)


if __name__ == "__main__":
    unittest.main()
