"""VS Code Copilot JSON/JSONL chat and editing-session capture."""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from owlthread.capture.connectors.base import IConnector, extract_text
from owlthread.config import SOURCE_VSCODE
from owlthread.db.database import Database

logger = logging.getLogger(__name__)


class VSCodeCopilotConnector(IConnector):
    def __init__(self, db: Database, base_dir: str | None = None) -> None:
        super().__init__(db)
        self.base_dir = Path(base_dir) if base_dir else Path(os.environ.get("APPDATA",str(Path.home()/".config")))/"Code"/"User"

    def poll(self) -> int:
        count = 0
        with self._poll_lock:
            patterns = ("workspaceStorage/*/chatSessions/*.jsonl","workspaceStorage/*/chatSessions/*.json",
                        "workspaceStorage/*/editingSessions/*.json","workspaceStorage/*/chatEditingSessions/*/state.json")
            for pattern in patterns:
                for path in self.base_dir.glob(pattern):
                    try:
                        if path.stat().st_size>2_000_000:
                            self.last_error="Session exceeds the 2 MB experimental parser limit"
                            continue
                        # Re-read snapshots so file rotations and revised turns are detected.
                        # Hashes in SQLite prevent recapturing unchanged records after restart.
                        with path.open(encoding="utf-8") as stream:
                            if path.suffix == ".jsonl":
                                records = []
                                for line in stream:
                                    if not line.endswith("\n"):
                                        break  # A writer has not finished this record yet.
                                    try:
                                        records.append(json.loads(line))
                                    except ValueError:
                                        logger.debug("Skipping malformed complete JSONL record")
                            else:
                                records = [json.load(stream)]
                        for record in records:
                            if isinstance(record,dict) and isinstance(record.get("v"),dict):
                                record = record["v"]
                            if isinstance(record,dict) and isinstance(record.get("requests"),list):
                                turns = record["requests"]
                            else:
                                turns = [record]
                            for turn in turns:
                                count += self.capture(extract_text(turn),SOURCE_VSCODE,str(path),
                                                      {"workspace_id":path.parent.parent.name,"session_id":path.stem})
                        self.last_error = None
                    except (OSError,ValueError,UnicodeError) as exc:
                        self.last_error = str(exc)
                        logger.debug("Copilot session unavailable or incomplete: %s",path.name)
        return count
