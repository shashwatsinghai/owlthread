"""Durable SQLite memory with thread-local readers and one queued writer.

A manager owns its connections; use close() or a with block to release them.
Writes return only after commit. Compound changes use a single queued callable.
WAL and busy_timeout also accommodate separate CLI/MCP processes.
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import queue
import sqlite3
import threading
from concurrent.futures import Future
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

from owlthread.config import DB_PATH, VALID_QUADRANTS
from owlthread.security import SECRET_SETTINGS, protect, unprotect, project_name, MAX_CAPTURE

logger = logging.getLogger(__name__)
T = TypeVar("T")


def get_iso_now() -> str:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class DatabaseManager:
    """Single-writer storage shared by all OwlThread subsystems."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path or os.environ.get("OWLTHREAD_DB_PATH") or DB_PATH).expanduser().resolve()
        self.unavailable_secret_settings: set[str] = set()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._readers: dict[threading.Thread, sqlite3.Connection] = {}
        self._lifecycle = threading.RLock()
        self._read_done = threading.Condition(self._lifecycle)
        self._active_reads = 0
        self._closed = False
        self._queue: queue.Queue[Any] = queue.Queue()
        ready: Future[None] = Future()
        self._writer = threading.Thread(target=self._write_loop, args=(ready,), name="OwlThread-DBWriter", daemon=True)
        self._writer.start()
        ready.result()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _write_loop(self, ready: Future[None]) -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = self._connect()
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._init_db(conn)
            if os.name != "nt":
                self.db_path.chmod(0o600)
            ready.set_result(None)
            while True:
                job = self._queue.get()
                try:
                    if job is None:
                        break
                    operation, future = job
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        value = operation(conn)
                        conn.commit()
                    except Exception as exc:
                        conn.rollback()
                        future.set_exception(exc)
                    else:
                        future.set_result(value)
                finally:
                    self._queue.task_done()
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            logger.exception("Database writer failed")
        finally:
            if conn:
                conn.close()

    def _init_db(self, conn: sqlite3.Connection) -> None:
        schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, root_path TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quadrant TEXT NOT NULL CHECK(quadrant IN ('technical_architecture','business_rules','settled_decisions','open_questions')),
                summary TEXT NOT NULL, raw_text TEXT, source_app TEXT DEFAULT 'manual',
                status TEXT DEFAULT 'active' CHECK(status IN ('active','superseded','archived')),
                project_id INTEGER REFERENCES projects(id),
                tags TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                timestamp TEXT, source_metadata TEXT,
                superseded_by INTEGER REFERENCES memory_entries(id) ON DELETE SET NULL, embedding BLOB);
            CREATE TABLE IF NOT EXISTS capture_buffer (
                id INTEGER PRIMARY KEY AUTOINCREMENT, raw_text TEXT NOT NULL, source_app TEXT,
                captured_at TEXT NOT NULL, processed INTEGER DEFAULT 0,
                project_id INTEGER REFERENCES projects(id), source_metadata TEXT,
                processed_chars INTEGER NOT NULL DEFAULT 0,
                extraction_status TEXT NOT NULL DEFAULT 'pending', extraction_reason TEXT,
                attempts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS capture_dedup (source_app TEXT, digest TEXT, PRIMARY KEY(source_app,digest));
            CREATE TABLE IF NOT EXISTS capture_receipts (
                source_app TEXT NOT NULL, project_id INTEGER NOT NULL, dedup_key TEXT NOT NULL,
                fingerprint TEXT NOT NULL, capture_id INTEGER NOT NULL,
                PRIMARY KEY(source_app,project_id,dedup_key));
            CREATE TABLE IF NOT EXISTS connector_state (
                connector_name TEXT PRIMARY KEY, last_scanned_at TEXT NOT NULL, state_data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_lineage (
                successor_id INTEGER REFERENCES memory_entries(id) ON DELETE CASCADE,
                predecessor_id INTEGER REFERENCES memory_entries(id) ON DELETE CASCADE,
                conflict_rationale TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(successor_id, predecessor_id));
            CREATE TABLE IF NOT EXISTS primer_cache (
                cache_key TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
                query TEXT NOT NULL, model_key TEXT NOT NULL, matched_revision TEXT NOT NULL,
                result_json TEXT NOT NULL, created_at TEXT NOT NULL, last_accessed TEXT NOT NULL);
        """)
        # Additive migration: preserve all older prototype data and lineage.
        additions = {
            "projects": {"root_path": "TEXT"},
            "settings": {"updated_at": "TEXT"},
            "memory_entries": {
                "project_id": "INTEGER", "timestamp": "TEXT", "source_metadata": "TEXT",
                "summary": "TEXT", "status": "TEXT DEFAULT 'active'", "superseded_by": "INTEGER",
                "embedding": "BLOB", "created_at": "TEXT", "updated_at": "TEXT", "tags": "TEXT",
            },
            "capture_buffer": {"project_id": "INTEGER", "source_metadata": "TEXT", "processed_chars": "INTEGER NOT NULL DEFAULT 0",
                               "extraction_status": "TEXT NOT NULL DEFAULT 'pending'", "extraction_reason": "TEXT", "attempts": "INTEGER NOT NULL DEFAULT 0"},
        }
        for table, columns in additions.items():
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, declaration in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
        # These repairs used to UPDATE every row on every startup. On an existing
        # database that also fired the external-content FTS trigger and rebuilt the
        # whole memory index even when no value changed.
        conn.execute("""UPDATE memory_entries SET created_at=COALESCE(created_at,timestamp,?),
            updated_at=COALESCE(updated_at,created_at,timestamp,?), timestamp=COALESCE(timestamp,created_at,?)
            WHERE created_at IS NULL OR updated_at IS NULL OR timestamp IS NULL""", (get_iso_now(),)*3)
        conn.execute("""UPDATE memory_entries SET summary=COALESCE(summary,substr(raw_text,1,160)),
            status=COALESCE(status,'active') WHERE summary IS NULL OR status IS NULL""")
        conn.execute("""UPDATE memory_entries SET quadrant=CASE quadrant
            WHEN 'architecture' THEN 'technical_architecture' WHEN 'decisions' THEN 'settled_decisions'
            WHEN 'context' THEN 'business_rules' WHEN 'status' THEN 'open_questions'
            ELSE COALESCE(quadrant,'technical_architecture') END
            WHERE quadrant IS NULL OR quadrant IN ('architecture','decisions','context','status')""")
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_memory_project_quadrant_status ON memory_entries(project_id,quadrant,status);
            CREATE INDEX IF NOT EXISTS idx_memory_timestamp ON memory_entries(timestamp);
            CREATE INDEX IF NOT EXISTS idx_capture_pending ON capture_buffer(processed,id);
        """)
        if not conn.execute("SELECT id FROM projects WHERE name='General'").fetchone():
            conn.execute("INSERT INTO projects(name,created_at) VALUES('General',?)", (get_iso_now(),))
        general = conn.execute("SELECT id FROM projects WHERE name='General' ORDER BY id LIMIT 1").fetchone()[0]
        conn.execute("UPDATE memory_entries SET project_id=? WHERE project_id IS NULL",(general,))
        conn.execute("UPDATE capture_buffer SET project_id=? WHERE project_id IS NULL",(general,))
        if schema_version < 4:
            # One-time activation for captures written before exact-content dedup
            # existed. Subsequent startups do no corpus scan.
            for row in conn.execute("SELECT project_id,source_app,raw_text FROM capture_buffer"):
                digest=hashlib.sha256((str(row["project_id"])+"\0"+(row["raw_text"] or "").strip()).encode()).hexdigest()
                conn.execute("INSERT OR IGNORE INTO capture_dedup(source_app,digest) VALUES(?,?)",
                             (row["source_app"] or "",digest))
        fts_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='memory_fts'").fetchone()
        capture_fts_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='capture_fts'").fetchone()
        conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                summary,raw_text,tags,content='memory_entries',content_rowid='id',tokenize='porter unicode61');
            CREATE TRIGGER IF NOT EXISTS memory_fts_insert AFTER INSERT ON memory_entries BEGIN
                INSERT INTO memory_fts(rowid,summary,raw_text,tags) VALUES(new.id,new.summary,new.raw_text,new.tags);
            END;
            CREATE TRIGGER IF NOT EXISTS memory_fts_delete AFTER DELETE ON memory_entries BEGIN
                INSERT INTO memory_fts(memory_fts,rowid,summary,raw_text,tags) VALUES('delete',old.id,old.summary,old.raw_text,old.tags);
            END;
            CREATE TRIGGER IF NOT EXISTS memory_fts_update AFTER UPDATE OF summary,raw_text,tags ON memory_entries BEGIN
                INSERT INTO memory_fts(memory_fts,rowid,summary,raw_text,tags) VALUES('delete',old.id,old.summary,old.raw_text,old.tags);
                INSERT INTO memory_fts(rowid,summary,raw_text,tags) VALUES(new.id,new.summary,new.raw_text,new.tags);
            END;
            CREATE VIRTUAL TABLE IF NOT EXISTS capture_fts USING fts5(
                raw_text,content='capture_buffer',content_rowid='id',tokenize='porter unicode61');
            CREATE TRIGGER IF NOT EXISTS capture_fts_insert AFTER INSERT ON capture_buffer BEGIN
                INSERT INTO capture_fts(rowid,raw_text) VALUES(new.id,new.raw_text);
            END;
            CREATE TRIGGER IF NOT EXISTS capture_fts_delete AFTER DELETE ON capture_buffer BEGIN
                INSERT INTO capture_fts(capture_fts,rowid,raw_text) VALUES('delete',old.id,old.raw_text);
            END;
            CREATE TRIGGER IF NOT EXISTS capture_fts_update AFTER UPDATE OF raw_text ON capture_buffer BEGIN
                INSERT INTO capture_fts(capture_fts,rowid,raw_text) VALUES('delete',old.id,old.raw_text);
                INSERT INTO capture_fts(rowid,raw_text) VALUES(new.id,new.raw_text);
            END;
        """)
        if not fts_exists:
            conn.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")
        if not capture_fts_exists:
            conn.execute("INSERT INTO capture_fts(capture_fts) VALUES('rebuild')")
        for key in SECRET_SETTINGS:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row and row[0]:
                conn.execute("UPDATE settings SET value=? WHERE key=?", (protect(row[0]), key))
        conn.execute("PRAGMA user_version=4")
        conn.commit()

    def execute_write(self, sql: str | Callable[[sqlite3.Connection], T], params: tuple[Any, ...] = ()) -> Any:
        """Queue SQL (return last row ID) or an atomic transaction callable."""
        if threading.current_thread() is self._writer:
            raise RuntimeError("Nested queued writes are not allowed; use the supplied transaction connection.")
        def operation(conn: sqlite3.Connection) -> Any:
            return conn.execute(sql, params).lastrowid if isinstance(sql, str) else sql(conn)
        future: Future[Any] = Future()
        with self._lifecycle:
            if self._closed:
                raise RuntimeError("Database is closed")
            self._queue.put((operation, future))
        return future.result()

    def _reader(self) -> sqlite3.Connection:
        with self._lifecycle:
            if self._closed:
                raise RuntimeError("Database is closed")
            current = threading.current_thread()
            # Reclaim connections of finished HTTP/worker threads.
            for thread, conn in list(self._readers.items()):
                if not thread.is_alive():
                    conn.close()
                    del self._readers[thread]
            conn = self._readers.get(current)
            if conn is None:
                conn = self._connect()
                conn.execute("PRAGMA query_only=ON")
                self._readers[current] = conn
                self._local.connection = conn
            return conn

    @contextmanager
    def connection(self, read_only: bool = True, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """Read-only compatibility context; writes must use execute_write."""
        with self._lifecycle:
            conn = self._reader()
            self._active_reads += 1
        try:
            yield conn
        finally:
            with self._read_done:
                self._active_reads -= 1
                self._read_done.notify_all()

    def execute_read(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def close(self) -> None:
        """Drain accepted writes, then close every connection. Idempotent."""
        with self._lifecycle:
            if self._closed:
                return
            self._closed = True
            self._queue.put(None)
        self._writer.join()
        with self._read_done:
            self._read_done.wait_for(lambda: self._active_reads == 0)
            for conn in self._readers.values():
                conn.close()
            self._readers.clear()

    def __enter__(self) -> DatabaseManager:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def get_or_create_project(self, name: str | None = None, root_path: str | None = None) -> int:
        clean_name = project_name(name if name else "General")
        def write(conn: sqlite3.Connection) -> int:
            if root_path:
                row = conn.execute("SELECT id FROM projects WHERE root_path=? LIMIT 1", (root_path,)).fetchone()
            else:
                row = conn.execute("SELECT id FROM projects WHERE name=? LIMIT 1", (clean_name,)).fetchone()
            if row:
                return int(row["id"])
            return int(conn.execute("INSERT INTO projects(name,root_path,created_at) VALUES(?,?,?)", (clean_name, root_path, get_iso_now())).lastrowid)
        return self.execute_write(write)

    def get_project_by_id(self, project_id: int) -> dict[str, Any] | None:
        rows = self.execute_read("SELECT * FROM projects WHERE id=?", (project_id,))
        return rows[0] if rows else None

    def list_projects(self) -> list[dict[str, Any]]:
        return self.execute_read("SELECT * FROM projects ORDER BY id")

    def insert_entry(self, raw_text: str = "", source_app: str = "manual", project_id: int | None = None,
                     source_metadata: Any = None, timestamp: str | None = None, quadrant: str | None = None,
                     summary: str | None = None, status: str = "active", superseded_by: int | None = None,
                     embedding: bytes | None = None, tags: Any = None) -> int:
        if not (raw_text or summary or "").strip():
            raise ValueError("Memory must not be empty")
        quadrant = quadrant or "technical_architecture"
        if quadrant not in VALID_QUADRANTS or status not in {"active", "superseded", "archived"}:
            raise ValueError("Invalid quadrant or status")
        if project_id is None:
            project_id = self.get_or_create_project()
        timestamp = timestamp or get_iso_now()
        return self.execute_write("""INSERT INTO memory_entries
            (project_id,timestamp,source_app,source_metadata,raw_text,quadrant,summary,status,superseded_by,embedding,created_at,updated_at,tags)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (project_id,timestamp,source_app,json.dumps(source_metadata) if source_metadata is not None else None,
             raw_text.strip(),quadrant,summary or raw_text[:160],status,superseded_by,embedding,timestamp,timestamp,
             json.dumps(tags) if isinstance(tags,(list,dict)) else tags))

    def get_entries(self, limit: int = 50, offset: int = 0, source_app: str | None = None,
                    project_id: int | None = None, quadrant: str | None = None, status: str = "active",
                    include_history: bool = False) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        for key, value in (("source_app",source_app),("project_id",project_id),("quadrant",quadrant),("status",None if include_history else status)):
            if value is not None:
                conditions.append(f"{key}=?")
                params.append(value)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return self.execute_read("SELECT * FROM memory_entries" + where + " ORDER BY id DESC LIMIT ? OFFSET ?", tuple(params+[max(0,limit),max(0,offset)]))

    def count_entries(self, source_app: str | None = None, project_id: int | None = None,
                      status: str = "active", include_history: bool = False) -> int:
        terms: list[str] = []
        params: list[Any] = []
        for key, value in (("source_app",source_app),("project_id",project_id),("status",None if include_history else status)):
            if value is not None:
                terms.append(f"{key}=?")
                params.append(value)
        where = " WHERE " + " AND ".join(terms) if terms else ""
        return self.execute_read("SELECT COUNT(*) AS n FROM memory_entries"+where,tuple(params))[0]["n"]

    def get_entry_by_id(self, entry_id: int) -> dict[str, Any] | None:
        rows = self.execute_read("SELECT * FROM memory_entries WHERE id=?", (entry_id,))
        return rows[0] if rows else None

    def get_active_entries_for_rebase(self, project_id: int, quadrant: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.get_entries(project_id=project_id,quadrant=quadrant,limit=limit)

    def supersede_entry(self, old_entry_id: int, new_entry_id: int | None = None, rationale: str = "") -> bool:
        def write(conn: sqlite3.Connection) -> bool:
            if old_entry_id == new_entry_id:
                raise ValueError("A memory cannot supersede itself")
            if new_entry_id is not None and not conn.execute("""SELECT 1 FROM memory_entries old JOIN memory_entries new
                ON old.project_id=new.project_id AND old.quadrant=new.quadrant
                WHERE old.id=? AND new.id=? AND old.status='active' AND new.status='active'""",(old_entry_id,new_entry_id)).fetchone():
                raise ValueError("Replacement must be active in the same project and quadrant")
            result = conn.execute("UPDATE memory_entries SET status='superseded',superseded_by=?,updated_at=? WHERE id=? AND status='active'",
                                  (new_entry_id,get_iso_now(),old_entry_id))
            if result.rowcount and new_entry_id is not None:
                conn.execute("INSERT INTO memory_lineage VALUES(?,?,?,?)",(new_entry_id,old_entry_id,rationale,get_iso_now()))
            return result.rowcount > 0
        return self.execute_write(write)

    def archive_entry(self, entry_id: int) -> None:
        self.execute_write("UPDATE memory_entries SET status='archived',updated_at=? WHERE id=?", (get_iso_now(),entry_id))

    def update_entry_statement(self, entry_id: int, summary: str, raw_text: str | None = None) -> bool:
        """Deprecated API: refinements now create successors, preserving the old row."""
        from owlthread.extraction.rebase import apply_actions
        def write(conn: sqlite3.Connection) -> bool:
            old=conn.execute("SELECT * FROM memory_entries WHERE id=? AND status='active'",(entry_id,)).fetchone()
            if not old:
                return False
            return bool(apply_actions(conn,dict(old),[{"action":"UPDATE","quadrant":old["quadrant"],
                "summary":summary,"source_snippet":raw_text or summary,
                "target_memory_id":entry_id,"rationale":"Explicit refinement via compatibility API"}]))
        return self.execute_write(write)

    def get_entry_lineage(self, entry_id: int) -> list[dict[str, Any]]:
        return self.execute_read("""SELECT l.*,m.summary AS predecessor_summary,m.quadrant FROM memory_lineage l
            LEFT JOIN memory_entries m ON m.id=l.predecessor_id WHERE l.successor_id=?""",(entry_id,))

    def delete_entry(self, entry_id: int) -> bool:
        def write(conn: sqlite3.Connection) -> bool:
            conn.execute("UPDATE memory_entries SET superseded_by=NULL WHERE superseded_by=?", (entry_id,))
            return conn.execute("DELETE FROM memory_entries WHERE id=?", (entry_id,)).rowcount > 0
        return self.execute_write(write)

    def insert_capture(self, raw_text: str, source_app: str = "manual", project_id: int | None = None,
                       source_metadata: Any = None, timestamp: str | None = None, dedup_key: str | None = None, **_: Any) -> int:
        if not isinstance(raw_text,str) or not raw_text.strip() or len(raw_text) > MAX_CAPTURE:
            raise ValueError("Capture text must not be empty")
        if project_id is None:
            project_id = self.get_or_create_project(self.get_setting("active_project","General"))
        def write(conn: sqlite3.Connection) -> int:
            clean_text = raw_text.strip()
            fingerprint = hashlib.sha256(clean_text.encode()).hexdigest()
            if dedup_key:
                previous = conn.execute("SELECT fingerprint,capture_id FROM capture_receipts WHERE source_app=? AND project_id=? AND dedup_key=?",
                                        (source_app,project_id,dedup_key)).fetchone()
                if previous:
                    if previous["fingerprint"] != fingerprint:
                        raise ValueError("dedup_key was already used for different text")
                    return 0
            # Exact content dedup is durable even when a producer has no idempotency
            # key. Folding the project into the digest preserves intentional copies
            # in separate projects while suppressing A -> B -> A and restart repeats.
            # Browser turns supply a stable event key: identical words in two
            # different turns are distinct evidence. Content-only sources such as
            # clipboard/manual input use exact persistent deduplication.
            if dedup_key is None:
                content_digest = hashlib.sha256((str(project_id)+"\0"+clean_text).encode()).hexdigest()
                if not conn.execute("INSERT OR IGNORE INTO capture_dedup(source_app,digest) VALUES(?,?)",
                                    (source_app,content_digest)).rowcount:
                    return 0
            cid = int(conn.execute("""INSERT INTO capture_buffer(raw_text,source_app,captured_at,project_id,source_metadata)
                VALUES(?,?,?,?,?)""",(clean_text,source_app,timestamp or get_iso_now(),project_id,
                                    json.dumps(source_metadata) if source_metadata is not None else None)).lastrowid)
            if dedup_key:
                conn.execute("INSERT INTO capture_receipts VALUES(?,?,?,?,?)", (source_app,project_id,dedup_key,fingerprint,cid))
            return cid
        return self.execute_write(write)

    def get_unprocessed_captures(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.execute_read("SELECT * FROM capture_buffer WHERE processed=0 ORDER BY id LIMIT ?", (max(0,limit),))

    def mark_capture_processed(self, capture_id: int) -> None:
        self.execute_write("UPDATE capture_buffer SET processed=1,processed_chars=length(raw_text) WHERE id=?", (capture_id,))

    def pending_count(self) -> int:
        return self.execute_read("SELECT COUNT(*) AS n FROM capture_buffer WHERE processed=0")[0]["n"]

    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self.execute_read("SELECT value FROM settings WHERE key=?", (key,))
        value = rows[0]["value"] if rows else default
        return self._setting_value(key,value)

    def _setting_value(self, key: str, value: Any) -> Any:
        if key not in SECRET_SETTINGS or not value:
            return value
        try:
            decoded = unprotect(value)
        except RuntimeError:
            if key not in self.unavailable_secret_settings:
                logger.warning("Stored %s cannot be unlocked on this Windows account",key)
            self.unavailable_secret_settings.add(key)
            return ""
        self.unavailable_secret_settings.discard(key)
        return decoded

    def set_setting(self, key: str, value: str) -> None:
        if key in SECRET_SETTINGS:
            value = protect(value)
        self.execute_write("""INSERT INTO settings(key,value,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""",(key,value,get_iso_now()))
        self.unavailable_secret_settings.discard(key)

    def get_all_settings(self) -> dict[str,str]:
        return {r["key"]:self._setting_value(r["key"],r["value"])
                for r in self.execute_read("SELECT key,value FROM settings")}

    def delete_setting(self, key: str) -> bool:
        deleted = self.execute_write(lambda conn: conn.execute("DELETE FROM settings WHERE key=?",(key,)).rowcount > 0)
        if deleted:
            self.unavailable_secret_settings.discard(key)
        return deleted

    def get_primer_cache(self, cache_key: str) -> dict[str, Any] | None:
        rows = self.execute_read("SELECT result_json FROM primer_cache WHERE cache_key=?", (cache_key,))
        if not rows:
            return None
        try:
            value = json.loads(rows[0]["result_json"])
        except (ValueError,TypeError):
            self.execute_write("DELETE FROM primer_cache WHERE cache_key=?", (cache_key,))
            return None
        if not isinstance(value,dict):
            return None
        self.execute_write("UPDATE primer_cache SET last_accessed=? WHERE cache_key=?", (get_iso_now(),cache_key))
        return value

    def set_primer_cache(self, cache_key: str, project_id: int, query: str, model_key: str,
                         matched_revision: str, result: dict[str, Any], max_entries: int = 200) -> None:
        if not 1 <= max_entries <= 1000:
            raise ValueError("Invalid primer cache size")
        encoded = json.dumps(result,ensure_ascii=False,separators=(",",":"))
        now = get_iso_now()
        def write(conn: sqlite3.Connection) -> None:
            conn.execute("""INSERT INTO primer_cache
                (cache_key,project_id,query,model_key,matched_revision,result_json,created_at,last_accessed)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET
                result_json=excluded.result_json,last_accessed=excluded.last_accessed""",
                (cache_key,project_id,query,model_key,matched_revision,encoded,now,now))
            conn.execute("""DELETE FROM primer_cache WHERE cache_key IN (
                SELECT cache_key FROM primer_cache ORDER BY last_accessed DESC,created_at DESC,cache_key DESC
                LIMIT -1 OFFSET ?)""", (max_entries,))
        self.execute_write(write)

    def get_connector_state(self, connector_name: str) -> dict[str,Any]:
        rows = self.execute_read("SELECT state_data FROM connector_state WHERE connector_name=?", (connector_name,))
        try:
            return json.loads(rows[0]["state_data"]) if rows else {}
        except (ValueError,TypeError):
            logger.warning("Ignoring invalid saved connector state: %s",connector_name)
            return {}

    def set_connector_state(self, connector_name: str, state_data: dict[str,Any]) -> None:
        self.execute_write("""INSERT INTO connector_state VALUES(?,?,?) ON CONFLICT(connector_name)
            DO UPDATE SET last_scanned_at=excluded.last_scanned_at,state_data=excluded.state_data""",
            (connector_name,get_iso_now(),json.dumps(state_data)))

    def clear_entries(self) -> None:
        def write(conn: sqlite3.Connection) -> None:
            conn.execute("UPDATE memory_entries SET superseded_by=NULL")
            for table in ("memory_lineage","memory_entries","capture_buffer","capture_dedup","capture_receipts",
                          "primer_cache","projects","connector_state","settings"):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("INSERT INTO projects(name,created_at) VALUES('General',?)",(get_iso_now(),))
        self.execute_write(write)


# Older integrations import Database; both names share the same implementation.
Database = DatabaseManager
