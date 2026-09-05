"""Unit tests for OwlThread Database Manager."""

import tempfile
import unittest
from pathlib import Path

from owlthread.db.database import Database


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_owlthread.db"
        self.db = Database(str(self.db_path))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_initialization(self):
        self.assertTrue(self.db_path.exists())
        self.assertEqual(self.db.count_entries(), 0)

    def test_insert_and_retrieve_entry(self):
        entry_id = self.db.insert_entry(
            raw_text="Hello OwlThread clipboard",
            source_app="clipboard",
            source_metadata={"foo": "bar"},
            quadrant=None
        )
        self.assertGreater(entry_id, 0)
        
        entry = self.db.get_entry_by_id(entry_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["raw_text"], "Hello OwlThread clipboard")
        self.assertEqual(entry["source_app"], "clipboard")
        self.assertIsNone(entry["quadrant"], "Quadrant must explicitly be NULL for Phase 0/1")
        self.assertIn('"foo": "bar"', entry["source_metadata"])

    def test_empty_raw_text_rejected(self):
        with self.assertRaises(ValueError):
            self.db.insert_entry(raw_text="   ", source_app="clipboard")

    def test_filter_by_source_app(self):
        self.db.insert_entry("Clip 1", "clipboard")
        self.db.insert_entry("Cursor 1", "cursor")
        self.db.insert_entry("Cursor 2", "cursor")
        self.db.insert_entry("Copilot 1", "copilot")

        self.assertEqual(self.db.count_entries(), 4)
        self.assertEqual(self.db.count_entries(source_app="cursor"), 2)
        self.assertEqual(self.db.count_entries(source_app="clipboard"), 1)

        cursor_entries = self.db.get_entries(source_app="cursor")
        self.assertEqual(len(cursor_entries), 2)
        self.assertEqual(cursor_entries[0]["source_app"], "cursor")

    def test_connector_state_persistence(self):
        state = self.db.get_connector_state("TestConnector")
        self.assertEqual(state, {})

        self.db.set_connector_state("TestConnector", {"last_id": 42, "seen": ["a", "b"]})
        updated = self.db.get_connector_state("TestConnector")
        self.assertEqual(updated["last_id"], 42)
        self.assertEqual(updated["seen"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
