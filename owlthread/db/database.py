"""SQLite Database Manager for OwlThread."""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from owlthread.config import DB_PATH


def get_iso_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thread-safe SQLite Database wrapper for OwlThread."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _create_connection(self, read_only: bool = False) -> sqlite3.Connection:
        """Create a connection configured with WAL mode and row factory."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA cache_size=-64000;")
        conn.execute("PRAGMA wal_autocheckpoint=1000;")
        if read_only:
            conn.execute("PRAGMA query_only=ON;")
        return conn

    @contextmanager
    def connection(self, read_only: bool = False, immediate: bool = False):
        """Context manager guaranteeing connection closure and transaction commit."""
        conn = self._create_connection(read_only=read_only)
        try:
            if immediate and not read_only:
                conn.execute("BEGIN IMMEDIATE;")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initialize database schema with projects and memory_entries tables."""
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            
            # 1. Projects table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    root_path TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

            # 2. Memory entries table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER REFERENCES projects(id),
                    timestamp TEXT NOT NULL,
                    source_app TEXT NOT NULL,
                    source_metadata TEXT,
                    raw_text TEXT NOT NULL,
                    quadrant TEXT,
                    summary TEXT,
                    status TEXT DEFAULT 'active',
                    superseded_by INTEGER REFERENCES memory_entries(id),
                    embedding BLOB,
                    created_at TEXT
                );
                """
            )

            # Schema migration check: Ensure all columns exist if table was previously created
            cursor.execute("PRAGMA table_info(memory_entries)")
            existing_cols = {row["name"] for row in cursor.fetchall()}
            if existing_cols:
                if "project_id" not in existing_cols:
                    cursor.execute("ALTER TABLE memory_entries ADD COLUMN project_id INTEGER REFERENCES projects(id)")
                if "source_metadata" not in existing_cols:
                    cursor.execute("ALTER TABLE memory_entries ADD COLUMN source_metadata TEXT")
                if "summary" not in existing_cols:
                    cursor.execute("ALTER TABLE memory_entries ADD COLUMN summary TEXT")
                if "status" not in existing_cols:
                    cursor.execute("ALTER TABLE memory_entries ADD COLUMN status TEXT DEFAULT 'active'")
                if "superseded_by" not in existing_cols:
                    cursor.execute("ALTER TABLE memory_entries ADD COLUMN superseded_by INTEGER REFERENCES memory_entries(id)")
                if "embedding" not in existing_cols:
                    cursor.execute("ALTER TABLE memory_entries ADD COLUMN embedding BLOB")
                if "created_at" not in existing_cols:
                    cursor.execute("ALTER TABLE memory_entries ADD COLUMN created_at TEXT")

            # 3. Connector state table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_state (
                    connector_name TEXT PRIMARY KEY,
                    last_scanned_at TEXT NOT NULL,
                    state_data TEXT NOT NULL
                );
                """
            )

            # 4. Indexes
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_project_quadrant_status 
                ON memory_entries (project_id, quadrant, status);
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_status 
                ON memory_entries (status);
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_source_app 
                ON memory_entries (source_app);
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_timestamp 
                ON memory_entries (timestamp);
                """
            )

            # 5. Lineage Graph Table for rebase and contradiction tracing
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_lineage (
                    successor_id INTEGER NOT NULL REFERENCES memory_entries(id) ON DELETE CASCADE,
                    predecessor_id INTEGER NOT NULL REFERENCES memory_entries(id) ON DELETE CASCADE,
                    conflict_rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (successor_id, predecessor_id)
                );
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lineage_predecessor ON memory_lineage(predecessor_id);
                """
            )

            # 6. Settings table for user-customizable config (system prompts, etc.)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # 7. Ensure default 'General' project exists
            cursor.execute("SELECT id FROM projects WHERE name = 'General'")
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO projects (name, root_path, created_at) VALUES ('General', NULL, ?)",
                    (get_iso_now(),)
                )

            conn.commit()

    def get_or_create_project(self, name: Optional[str] = None, root_path: Optional[str] = None) -> int:
        """
        Retrieve existing project ID by name/root_path, or create a new project.
        Defaults to 'General' if name is empty or not specified.
        """
        project_name = (name or "").strip() or "General"
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            if root_path:
                cursor.execute(
                    "SELECT id FROM projects WHERE root_path = ? OR name = ? ORDER BY id ASC LIMIT 1",
                    (root_path, project_name)
                )
            else:
                cursor.execute(
                    "SELECT id FROM projects WHERE name = ? ORDER BY id ASC LIMIT 1",
                    (project_name,)
                )
            row = cursor.fetchone()
            if row:
                return row["id"]

            cursor.execute(
                "INSERT INTO projects (name, root_path, created_at) VALUES (?, ?, ?)",
                (project_name, root_path, get_iso_now())
            )
            conn.commit()
            return cursor.lastrowid

    def get_project_by_id(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Fetch project dictionary by ID."""
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, root_path, created_at FROM projects WHERE id = ?", (project_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_projects(self) -> List[Dict[str, Any]]:
        """List all known projects."""
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, root_path, created_at FROM projects ORDER BY id ASC")
            return [dict(r) for r in cursor.fetchall()]

    def insert_entry(
        self,
        raw_text: str,
        source_app: str,
        project_id: Optional[int] = None,
        source_metadata: Optional[Any] = None,
        timestamp: Optional[str] = None,
        quadrant: Optional[str] = None,
        summary: Optional[str] = None,
        status: str = "active",
        superseded_by: Optional[int] = None,
        embedding: Optional[bytes] = None
    ) -> int:
        """
        Insert a new memory entry into memory_entries.
        """
        if not raw_text or not raw_text.strip():
            raise ValueError("raw_text must not be empty.")

        if not timestamp:
            timestamp = get_iso_now()

        if project_id is None:
            project_id = self.get_or_create_project("General")
        else:
            with self._lock, self.connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM projects WHERE id = ?", (project_id,))
                if not cursor.fetchone():
                    project_id = self.get_or_create_project("General")

        metadata_str = None
        if source_metadata is not None:
            if isinstance(source_metadata, (dict, list)):
                metadata_str = json.dumps(source_metadata, ensure_ascii=False)
            else:
                metadata_str = str(source_metadata)

        created_at = timestamp
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memory_entries (
                    project_id, timestamp, source_app, source_metadata, raw_text,
                    quadrant, summary, status, superseded_by, embedding, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    timestamp,
                    source_app,
                    metadata_str,
                    raw_text.strip(),
                    quadrant,
                    summary,
                    status,
                    superseded_by,
                    embedding,
                    created_at,
                )
            )
            conn.commit()
            return cursor.lastrowid

    def get_active_entries_for_rebase(
        self,
        project_id: int,
        quadrant: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Query up to 20 existing active entries in the same project_id + quadrant,
        most recent first.
        """
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, project_id, timestamp, source_app, source_metadata, raw_text, quadrant, summary, status, superseded_by
                FROM memory_entries
                WHERE project_id = ? AND quadrant = ? AND status = 'active'
                ORDER BY id DESC
                LIMIT ?
                """,
                (project_id, quadrant, limit)
            )
            return [dict(r) for r in cursor.fetchall()]

    def supersede_entry(self, old_entry_id: int, new_entry_id: int, rationale: str = "") -> bool:
        """
        Mark an older memory entry as superseded by a newer entry, and record the lineage edge.
        """
        with self._lock, self.connection(immediate=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE memory_entries
                SET status = 'superseded', superseded_by = ?
                WHERE id = ?
                """,
                (new_entry_id, old_entry_id)
            )
            success = cursor.rowcount > 0
            if success:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO memory_lineage (successor_id, predecessor_id, conflict_rationale, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (new_entry_id, old_entry_id, rationale or "Superseded by subsequent architectural update.", get_iso_now())
                )
            conn.commit()
            return success

    def update_entry_statement(self, entry_id: int, summary: str, raw_text: Optional[str] = None) -> bool:
        """Update the summary or raw_text of an existing active entry without changing its ID."""
        with self._lock, self.connection(immediate=True) as conn:
            cursor = conn.cursor()
            if raw_text is not None:
                cursor.execute(
                    """
                    UPDATE memory_entries
                    SET summary = ?, raw_text = ?
                    WHERE id = ? AND status = 'active'
                    """,
                    (summary, raw_text, entry_id)
                )
            else:
                cursor.execute(
                    """
                    UPDATE memory_entries
                    SET summary = ?
                    WHERE id = ? AND status = 'active'
                    """,
                    (summary, entry_id)
                )
            conn.commit()
            return cursor.rowcount > 0

    def get_entry_lineage(self, entry_id: int) -> List[Dict[str, Any]]:
        """Retrieve lineage trace history for a given entry ID."""
        with self.connection(read_only=True) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT l.successor_id, l.predecessor_id, l.conflict_rationale, l.created_at,
                       m.summary as predecessor_summary, m.quadrant
                FROM memory_lineage l
                LEFT JOIN memory_entries m ON l.predecessor_id = m.id
                WHERE l.successor_id = ?
                ORDER BY l.created_at DESC
                """,
                (entry_id,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_entries(
        self,
        limit: int = 50,
        offset: int = 0,
        source_app: Optional[str] = None,
        project_id: Optional[int] = None,
        quadrant: Optional[str] = None,
        status: str = "active",
        include_history: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieve rows from memory_entries ordered by id DESC.
        By default filters for status='active' unless include_history=True.
        """
        conditions = []
        params: List[Any] = []

        if not include_history:
            conditions.append("status = ?")
            params.append(status)

        if source_app:
            conditions.append("source_app = ?")
            params.append(source_app)

        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)

        if quadrant:
            conditions.append("quadrant = ?")
            params.append(quadrant)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT id, project_id, timestamp, source_app, source_metadata, raw_text, quadrant, summary, status, superseded_by
            FROM memory_entries
            {where_clause}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_entry_by_id(self, entry_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single memory entry by its primary key ID."""
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, project_id, timestamp, source_app, source_metadata, raw_text, quadrant, summary, status, superseded_by
                FROM memory_entries
                WHERE id = ?
                """,
                (entry_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_entry(self, entry_id: int) -> bool:
        """Delete an entry by ID. Returns True if deleted."""
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
            conn.commit()
            return cursor.rowcount > 0

    def count_entries(
        self,
        source_app: Optional[str] = None,
        project_id: Optional[int] = None,
        status: str = "active",
        include_history: bool = False
    ) -> int:
        """Count total entries matching filter criteria."""
        conditions = []
        params: List[Any] = []

        if not include_history:
            conditions.append("status = ?")
            params.append(status)

        if source_app:
            conditions.append("source_app = ?")
            params.append(source_app)

        if project_id is not None:
            conditions.append("project_id = ?")
            params.append(project_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT COUNT(*) FROM memory_entries {where_clause}"

        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchone()[0]

    def get_connector_state(self, connector_name: str) -> Dict[str, Any]:
        """Fetch the persisted state for a connector."""
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT state_data FROM connector_state WHERE connector_name = ?",
                (connector_name,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                try:
                    return json.loads(row[0])
                except json.JSONDecodeError:
                    return {}
            return {}

    def set_connector_state(self, connector_name: str, state_data: Dict[str, Any]) -> None:
        """Persist the state dictionary for a connector."""
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO connector_state (connector_name, last_scanned_at, state_data)
                VALUES (?, ?, ?)
                ON CONFLICT(connector_name) DO UPDATE SET
                    last_scanned_at = excluded.last_scanned_at,
                    state_data = excluded.state_data
                """,
                (connector_name, get_iso_now(), json.dumps(state_data, ensure_ascii=False))
            )
            conn.commit()

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a setting value by key. Returns default if not found."""
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Store or update a setting value."""
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, get_iso_now())
            )
            conn.commit()

    def get_all_settings(self) -> Dict[str, str]:
        """Retrieve all settings as a key-value dictionary."""
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings ORDER BY key")
            return {row["key"]: row["value"] for row in cursor.fetchall()}

    def delete_setting(self, key: str) -> bool:
        """Delete a setting by key. Returns True if deleted."""
        with self._lock, self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0

    def clear_entries(self) -> None:
        """Wipe all entries, projects, and settings (useful in testing)."""
        with self._lock, self.connection() as conn:
            conn.execute("DELETE FROM memory_entries")
            conn.execute("DELETE FROM projects")
            conn.execute("DELETE FROM connector_state")
            conn.execute("DELETE FROM settings")
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO projects (name, root_path, created_at) VALUES ('General', NULL, ?)",
                (get_iso_now(),)
            )
            conn.commit()
