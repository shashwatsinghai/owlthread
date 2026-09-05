"""Unit tests for Clipboard Watcher."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from owlthread.capture.clipboard import ClipboardWatcher
from owlthread.db.database import Database


class TestClipboardWatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp_dir.name) / "test.db"))
        self.watcher = ClipboardWatcher(self.db, poll_interval=0.05)

    def tearDown(self):
        self.watcher.stop()
        self.temp_dir.cleanup()

    @patch("owlthread.capture.clipboard.ClipboardWatcher._read_clipboard")
    def test_clipboard_change_detection(self, mock_read):
        # 1. First poll with text
        mock_read.return_value = "Initial copied text"
        entry_id = self.watcher.poll()
        self.assertIsNotNone(entry_id)

        entry = self.db.get_entry_by_id(entry_id)
        self.assertEqual(entry["raw_text"], "Initial copied text")
        self.assertEqual(entry["source_app"], "clipboard")
        self.assertIsNone(entry["quadrant"])

        # 2. Same text should not produce duplicate entry
        entry_id2 = self.watcher.poll()
        self.assertIsNone(entry_id2)
        self.assertEqual(self.db.count_entries(), 1)

        # 3. New text should produce new entry
        mock_read.return_value = "Second distinct copied text"
        entry_id3 = self.watcher.poll()
        self.assertIsNotNone(entry_id3)
        self.assertEqual(self.db.count_entries(), 2)

    @patch("owlthread.capture.clipboard.ClipboardWatcher._read_clipboard")
    def test_empty_or_whitespace_clipboard_ignored(self, mock_read):
        mock_read.return_value = ""
        self.assertIsNone(self.watcher.poll())

        mock_read.return_value = "   \n\t  "
        self.assertIsNone(self.watcher.poll())

        self.assertEqual(self.db.count_entries(), 0)


if __name__ == "__main__":
    unittest.main()
