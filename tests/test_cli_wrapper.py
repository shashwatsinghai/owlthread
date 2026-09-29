"""Unit tests for CLI execution wrapper."""

import sys
import tempfile
import unittest
import io
import contextlib
import json
from pathlib import Path

from owlthread.cli import run_wrapped_command
from owlthread.db.database import Database


class TestCLIWrapper(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp_dir.name) / "test_cli.db"))

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_run_wrapped_command_success(self):
        cmd = [sys.executable, "-c", "print('CLI stdout test payload'); import sys; sys.stderr.write('CLI stderr line\\n')"]
        exit_code = run_wrapped_command(cmd, db=self.db)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "cli_run"]), 1)

        entry = [c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "cli_run"][0]
        self.assertIn("CLI stdout test payload", entry["raw_text"])
        self.assertIn("CLI stderr line", entry["raw_text"])
        self.assertEqual(entry["source_app"], "cli_run")
        self.assertEqual(self.db.count_entries(), 0)
        self.assertIn('"exit_code": 0', entry["source_metadata"])

    def test_run_wrapped_command_exit_code_preserved(self):
        cmd = [sys.executable, "-c", "import sys; sys.stderr.write('fatal error\\n'); sys.exit(42)"]
        exit_code = run_wrapped_command(cmd, db=self.db)

        self.assertEqual(exit_code, 42)
        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "cli_run"]), 1)
        entry = [c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "cli_run"][0]
        self.assertIn("fatal error", entry["raw_text"])
        self.assertIn('"exit_code": 42', entry["source_metadata"])

    def test_output_cap_preserves_streaming_and_explicit_project(self):
        stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            code=run_wrapped_command([sys.executable,'-c',"print('x'*10000)"],db=self.db,project='Bounded project',max_output_bytes=1024)
        self.assertEqual(code,0)
        self.assertEqual(len(stdout.getvalue().strip()),10000)
        rows=self.db.get_unprocessed_captures(10)
        self.assertLessEqual(sum(len(r['raw_text'].encode()) for r in rows),1024)
        self.assertTrue(json.loads(rows[0]['source_metadata'])['truncated'])
        self.assertEqual(self.db.get_project_by_id(rows[0]['project_id'])['name'],'Bounded project')


if __name__ == "__main__":
    unittest.main()
