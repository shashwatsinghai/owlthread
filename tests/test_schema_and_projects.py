"""Unit tests for Phase 2 database schema, projects table, and General fallback."""

import os
import tempfile
import unittest

from owlthread.db.database import Database


class TestSchemaAndProjects(unittest.TestCase):
    """Test suite for Phase 2 schema and project management."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_schema.db")
        self.db = Database(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_projects_table_and_general_fallback(self):
        """Verify projects table exists and 'General' project is created automatically."""
        projects = self.db.list_projects()
        self.assertGreaterEqual(len(projects), 1)
        names = [p["name"] for p in projects]
        self.assertIn("General", names)

    def test_get_or_create_project(self):
        """Verify project lookup and creation."""
        pid1 = self.db.get_or_create_project(name="OwlThread", root_path="/path/to/owlthread")
        pid2 = self.db.get_or_create_project(name="OwlThread", root_path="/path/to/owlthread")
        self.assertEqual(pid1, pid2)

        # Fallback to General if no name provided
        gen_id = self.db.get_or_create_project(name=None)
        gen_proj = self.db.get_project_by_id(gen_id)
        self.assertIsNotNone(gen_proj)
        self.assertEqual(gen_proj["name"], "General")

    def test_memory_entries_schema_columns(self):
        """Verify memory_entries table contains all required Step 1 columns."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(memory_entries)")
            cols = {row["name"]: row["type"] for row in cursor.fetchall()}

        required_cols = [
            "id", "project_id", "timestamp", "source_app",
            "raw_text", "quadrant", "summary", "status",
            "superseded_by", "embedding"
        ]
        for col in required_cols:
            self.assertIn(col, cols, f"Missing required column: {col}")

    def test_insert_and_retrieve_entry_fields(self):
        """Verify full insertion with status, summary, and project reference."""
        pid = self.db.get_or_create_project(name="TestProj")
        eid = self.db.insert_entry(
            raw_text="Decision: Use SQLite WAL mode for local concurrency.",
            source_app="cursor",
            project_id=pid,
            quadrant="settled_decisions",
            summary="Decision: Use SQLite WAL mode for concurrency.",
            status="active"
        )
        self.assertGreater(eid, 0)

        entry = self.db.get_entry_by_id(eid)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["project_id"], pid)
        self.assertEqual(entry["quadrant"], "settled_decisions")
        self.assertEqual(entry["status"], "active")
        self.assertIsNone(entry["superseded_by"])


if __name__ == "__main__":
    unittest.main()
