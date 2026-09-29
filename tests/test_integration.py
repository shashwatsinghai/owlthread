"""Integration test verifying capture across all four surfaces."""

import json
import sqlite3
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from owlthread.capture.connectors.cursor import CursorConnector
from owlthread.capture.connectors.vscode_copilot import VSCodeCopilotConnector
from owlthread.capture.engine import CaptureEngine
from owlthread.cli import run_wrapped_command
from owlthread.security import local_token
from owlthread.db.database import Database


class TestMultiSurfaceIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "integration.db"
        self.db = Database(str(self.db_path))

        # Setup mock directories for Cursor and VS Code
        self.cursor_dir = self.root / "Cursor" / "User"
        self.vscode_dir = self.root / "Code" / "User"

        self.port = 41998
        self.engine = CaptureEngine(
            db=self.db,
            http_port=self.port,
            enable_clipboard=False,  # We will manually test clipboard with mocked read
            enable_connectors=False,
            enable_http=True
        )
        self.engine.start()

    def tearDown(self):
        self.engine.stop()
        self.db.close()
        self.temp_dir.cleanup()

    def test_all_four_surfaces_capture(self):
        # Surface 1: Clipboard
        with patch("owlthread.capture.clipboard.ClipboardWatcher._read_clipboard") as mock_clip:
            from owlthread.capture.clipboard import ClipboardWatcher
            watcher = ClipboardWatcher(self.db)
            mock_clip.return_value = "Pasted text from clipboard"
            watcher.poll()
            watcher.stop()

        # Surface 2: IDE Connectors (Cursor & VS Code)
        # 2a. Cursor
        ws_cursor = self.cursor_dir / "workspaceStorage" / "ws_int"
        ws_cursor.mkdir(parents=True, exist_ok=True)
        cursor_vscdb = ws_cursor / "state.vscdb"
        conn = sqlite3.connect(str(cursor_vscdb))
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO ItemTable VALUES ('aiService.prompts', ?)",
            (json.dumps([{"text": "Cursor prompt test"}]),)
        )
        conn.commit()
        conn.close()

        cursor_conn = CursorConnector(self.db, base_dir=str(self.cursor_dir))
        cursor_conn.start()
        cursor_conn.poll()
        cursor_conn.stop()

        # 2b. VS Code Copilot
        chat_vsc = self.vscode_dir / "workspaceStorage" / "ws_int" / "chatSessions"
        chat_vsc.mkdir(parents=True, exist_ok=True)
        vsc_file = chat_vsc / "sess.jsonl"
        with open(vsc_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "kind": 0,
                "v": {
                    "sessionId": "s-1",
                    "requests": [{"message": {"text": "Copilot prompt test"}, "response": []}]
                }
            }) + "\n")

        vsc_conn = VSCodeCopilotConnector(self.db, base_dir=str(self.vscode_dir))
        vsc_conn.start()
        vsc_conn.poll()
        vsc_conn.stop()

        # Surface 3: CLI Execution Wrapper
        run_wrapped_command(
            [sys.executable, "-c", "print('CLI stdout captured turn')"],
            db=self.db
        )

        # Surface 4: Browser Extension HTTP POST
        payload = {
            "text": "Browser selected text",
            "source_app": "browser_extension",
            "url": "https://example.org/chat",
            "title": "Chat Page"
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/capture",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization":"Bearer "+local_token(self.db)}
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)

        # Verification across all surfaces
        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "clipboard"]), 1)
        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "cursor_ide"]), 1)
        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "vscode_copilot"]), 1)
        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "cli_run"]), 1)
        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "browser_extension"]), 1)

        total_entries = self.db.get_unprocessed_captures(limit=10)
        self.assertEqual(len(total_entries), 5)

        for entry in total_entries:
            # Quadrant is now either classified immediately or populated by pipeline
            self.assertIn("source_app", entry)


if __name__ == "__main__":
    unittest.main()
