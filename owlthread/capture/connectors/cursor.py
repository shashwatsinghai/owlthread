"""Read Cursor's local chat storage using read-only SQLite connections."""
from __future__ import annotations
import json
import logging
import os
import sqlite3
from pathlib import Path
from owlthread.capture.connectors.base import IConnector, extract_text
from owlthread.config import SOURCE_CURSOR
from owlthread.db.database import Database

logger = logging.getLogger(__name__)


class CursorConnector(IConnector):
    def __init__(self, db: Database, base_dir: str | None = None) -> None:
        super().__init__(db)
        self.base_dir = Path(base_dir) if base_dir else Path(os.environ.get("APPDATA",str(Path.home()/".config")))/"Cursor"/"User"

    def poll(self) -> int:
        count = 0
        with self._poll_lock:
            paths = list(self.base_dir.glob("workspaceStorage/*/state.vscdb"))
            paths += [self.base_dir/"globalStorage"/"conversation-search.db",self.base_dir/"globalStorage"/"state.vscdb"]
            for path in paths:
                if not path.is_file():
                    continue
                conn: sqlite3.Connection | None = None
                try:
                    conn = sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)
                    conn.row_factory = sqlite3.Row
                    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    for table in ("ItemTable","cursorDiskKV"):
                        if table not in tables:
                            continue
                        for row in conn.execute(f'SELECT key,value FROM "{table}" WHERE length(value)<=2000000 LIMIT 10000'):
                            key = str(row["key"])
                            if not any(k in key.lower() for k in ("prompt","generation","composer","bubble","chat")):
                                continue
                            try:
                                data = json.loads(row["value"])
                            except (ValueError,TypeError):
                                continue
                            records = data if isinstance(data,list) else [data]
                            for record in records:
                                text = extract_text(record)
                                count += self.capture(text,SOURCE_CURSOR,str(path),{"storage_key":key,"workspace_id":path.parent.name})
                    if {"conversations","conversation_fts_content"} <= tables:
                        for row in conn.execute("SELECT c.id,c.title,f.c1 AS text FROM conversations c LEFT JOIN conversation_fts_content f ON c.fts_rowid=f.rowid"):
                            text = "\n".join(filter(None,(row["title"],row["text"])))
                            count += self.capture(text,SOURCE_CURSOR,str(path),{"conversation_id":row["id"]})
                    self.last_error = None
                except (OSError,sqlite3.Error,ValueError,TypeError) as exc:
                    self.last_error = str(exc)
                    logger.warning("Cursor storage unavailable or schema unsupported: %s",path.name)
                finally:
                    if conn:
                        conn.close()
        return count
