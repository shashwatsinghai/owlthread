"""Unit tests for CLI execution wrapper."""

import sys
import tempfile
import unittest
from pathlib import Path

from owlthread.cli import run_wrapped_command
from owlthread.db.database import Database


class TestCLIWrapper(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp_dir.name) / "test_cli.db"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_wrapped_command_success(self):
        cmd = [sys.executable, "-c", "print('CLI stdout test payload'); import sys; sys.stderr.write('CLI stderr line\\n')"]
        exit_code = run_wrapped_command(cmd, db=self.db)

        self.assertEqual(exit_code, 0)
        self.assertEqual(self.db.count_entries(source_app="cli"), 1)

        entry = self.db.get_entries(source_app="cli")[0]
        self.assertIn("CLI stdout test payload", entry["raw_text"])
        self.assertIn("CLI stderr line", entry["raw_text"])
        self.assertEqual(entry["source_app"], "cli")
        self.assertIsNone(entry["quadrant"])
        self.assertIn('"exit_code": 0', entry["source_metadata"])

    def test_run_wrapped_command_exit_code_preserved(self):
        cmd = [sys.executable, "-c", "import sys; sys.stderr.write('fatal error\\n'); sys.exit(42)"]
        exit_code = run_wrapped_command(cmd, db=self.db)

        self.assertEqual(exit_code, 42)
        self.assertEqual(self.db.count_entries(source_app="cli"), 1)
        entry = self.db.get_entries(source_app="cli")[0]
        self.assertIn("fatal error", entry["raw_text"])
        self.assertIn('"exit_code": 42', entry["source_metadata"])


if __name__ == "__main__":
    unittest.main()
