"""Unit tests for File Connectors (Cursor & VS Code Copilot)."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from owlthread.capture.connectors.cursor import CursorConnector
from owlthread.capture.connectors.vscode_copilot import VSCodeCopilotConnector
from owlthread.db.database import Database


class TestFileConnectors(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.db = Database(str(self.base_path / "owlthread_test.db"))

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_workspace_mapping_and_unknown_store_never_use_active_project(self):
        self.db.set_setting('active_project','Unrelated active project')
        workspace=self.base_path/'workspaceStorage'/'known'
        workspace.mkdir(parents=True)
        project_root=self.base_path/'Mapped project'
        (workspace/'workspace.json').write_text(json.dumps({'folder':project_root.as_uri()}))
        connector=CursorConnector(self.db,base_dir=str(self.base_path))
        connector.capture('Decision: Use SQLite for mapping tests.','cursor_ide',str(workspace/'state.vscdb'))
        connector.capture('Decision: Keep unknown global chats separate.','cursor_ide',str(self.base_path/'globalStorage'/'state.vscdb'))
        names={self.db.get_project_by_id(row['project_id'])['name'] for row in self.db.get_unprocessed_captures(10)}
        self.assertIn('Mapped project',names)
        self.assertTrue(any(name.startswith('Unassigned') for name in names))
        self.assertNotIn('Unrelated active project',names)

    def test_cursor_connector_workspace_db(self):
        cursor_dir = self.base_path / "Cursor" / "User"
        ws_dir = cursor_dir / "workspaceStorage" / "ws_alpha"
        ws_dir.mkdir(parents=True, exist_ok=True)
        db_file = ws_dir / "state.vscdb"

        # Create mock Cursor workspace state.vscdb
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        prompts = [{"text": "Build a React navbar component", "commandType": 1}]
        generations = [{"unixMs": 1780000000000, "generationUUID": "gen-123", "textDescription": "Here is the navbar code"}]
        composer_data = {
            "allComposers": [
                {
                    "composerId": "comp-456",
                    "name": "Refactor auth controller",
                    "conversation": [{"bubbleId": "bub-1", "type": "user", "text": "Add JWT validation"}]
                }
            ]
        }
        conn.execute("INSERT INTO ItemTable VALUES ('aiService.prompts', ?)", (json.dumps(prompts),))
        conn.execute("INSERT INTO ItemTable VALUES ('aiService.generations', ?)", (json.dumps(generations),))
        conn.execute("INSERT INTO ItemTable VALUES ('composer.composerData', ?)", (json.dumps(composer_data),))
        conn.commit()
        conn.close()

        connector = CursorConnector(self.db, base_dir=str(cursor_dir))
        connector.start()
        self.addCleanup(connector.stop)
        captured_count = connector.poll()

        self.assertGreaterEqual(captured_count, 3)
        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "cursor_ide"]), captured_count)

        entries = [c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "cursor_ide"]
        raw_texts = [e["raw_text"] for e in entries]
        self.assertIn("Build a React navbar component", raw_texts)
        self.assertIn("Here is the navbar code", raw_texts)
        self.assertIn("Add JWT validation", raw_texts)

        # Polling again without new records should capture 0
        self.assertEqual(connector.poll(), 0)
        connector.stop()

    def test_vscode_copilot_connector_chat_sessions(self):
        vscode_dir = self.base_path / "Code" / "User"
        chat_dir = vscode_dir / "workspaceStorage" / "ws_beta" / "chatSessions"
        chat_dir.mkdir(parents=True, exist_ok=True)
        session_file = chat_dir / "session-001.jsonl"

        # Write initial VS Code Copilot chat session jsonl
        line0 = {
            "kind": 0,
            "v": {
                "sessionId": "session-001",
                "creationDate": 1780000000000,
                "requests": [
                    {
                        "message": {"text": "How do I sort a list in Python?"},
                        "response": [{"value": "Use the sorted() function or list.sort()."}]
                    }
                ]
            }
        }
        with open(session_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(line0) + "\n")

        connector = VSCodeCopilotConnector(self.db, base_dir=str(vscode_dir))
        connector.start()
        self.addCleanup(connector.stop)
        captured_count = connector.poll()

        self.assertEqual(captured_count, 1)  # Complete user/assistant turn
        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "vscode_copilot"]), 1)

        entries = [c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "vscode_copilot"]
        raw_texts = [e["raw_text"] for e in entries]
        self.assertIn("How do I sort a list in Python?", "\n".join(raw_texts))
        self.assertIn("Use the sorted() function or list.sort().", "\n".join(raw_texts))

        # Append new message turn
        line1 = {
            "kind": 1,
            "v": {
                "requests": [
                    {
                        "message": {"text": "What about descending order?"},
                        "response": [{"value": "Pass reverse=True."}]
                    }
                ]
            }
        }
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(line1) + "\n")

        # Second poll captures newly appended items
        new_count = connector.poll()
        self.assertEqual(new_count, 1)
        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "vscode_copilot"]), 2)

        connector.stop()


if __name__ == "__main__":
    unittest.main()
