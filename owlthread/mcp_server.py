"""
Model Context Protocol (MCP) Server for OwlThread.
Enables Cursor IDE and Claude Code CLI to directly read memory quadrants
and record architectural decisions over standard I/O (transport="stdio").
"""

import argparse
import concurrent.futures
import json
import logging
import os
import queue
import sqlite3
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Official Python MCP SDK import (with graceful MCP 2.x / FastMCP compatibility)
try:
    from mcp.server.fastmcp import FastMCP
except (ImportError, ModuleNotFoundError):
    try:
        from mcp.server.mcpserver import MCPServer as FastMCP
    except ImportError:
        try:
            from fastmcp import FastMCP
        except ImportError:
            FastMCP = None

logger = logging.getLogger("owlthread.mcp_server")

# 4-Quadrant Taxonomy Constants
QUAD_TECHNICAL_ARCHITECTURE = "technical_architecture"
QUAD_BUSINESS_RULES = "business_rules"
QUAD_SETTLED_DECISIONS = "settled_decisions"
QUAD_OPEN_QUESTIONS = "open_questions"

VALID_QUADRANTS: Set[str] = {
    QUAD_TECHNICAL_ARCHITECTURE,
    QUAD_BUSINESS_RULES,
    QUAD_SETTLED_DECISIONS,
    QUAD_OPEN_QUESTIONS,
}

DEFAULT_DATA_DIR = Path.home() / ".owlthread"
DEFAULT_DB_PATH = str(DEFAULT_DATA_DIR / "owlthread.db")


def get_iso_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# DatabaseManager: Thread-Local Reads & Single-Writer Queue (Zero SQLITE_BUSY)
# ---------------------------------------------------------------------------

class DatabaseManager:
    """
    Concurrency-safe SQLite manager for OwlThread MCP.
    - Reads: Uses thread-local read-only connections (execute_read).
    - Writes: Serialized through a single-writer background thread queue (execute_write),
      guaranteeing zero SQLITE_BUSY errors in SQLite WAL mode.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or os.environ.get("OWLTHREAD_DB_PATH") or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()
        self._write_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

        # Dedicated single-writer background thread
        self._writer_thread = threading.Thread(target=self._writer_loop, name="OwlThread-SingleWriter", daemon=True)
        self._writer_thread.start()

        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize schema tables via the single-writer queue."""
        def _schema_task(conn: sqlite3.Connection) -> None:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    root_path TEXT,
                    created_at TEXT NOT NULL
                );
            """)
            cur.execute("""
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
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS memory_lineage (
                    successor_id INTEGER NOT NULL REFERENCES memory_entries(id) ON DELETE CASCADE,
                    predecessor_id INTEGER NOT NULL REFERENCES memory_entries(id) ON DELETE CASCADE,
                    conflict_rationale TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (successor_id, predecessor_id)
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_mcp_mem_proj_quad_status
                ON memory_entries (project_id, quadrant, status);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_mcp_mem_status
                ON memory_entries (status);
            """)
            cur.execute("SELECT id FROM projects WHERE name = 'General'")
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO projects (name, root_path, created_at) VALUES ('General', NULL, ?)",
                    (get_iso_now(),)
                )

        self.execute_write(_schema_task)

    # -----------------------------------------------------------------------
    # Thread-Local Read Connections (execute_read)
    # -----------------------------------------------------------------------

    def get_read_connection(self) -> sqlite3.Connection:
        """Get or initialize thread-local read-only SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA query_only=ON;")
            self._local.conn = conn
        return self._local.conn

    def execute_read(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        """
        Execute read query using thread-local read-only connection.
        Lock-free concurrency supported by WAL mode.
        """
        conn = self.get_read_connection()
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchall()

    # -----------------------------------------------------------------------
    # Single-Writer Thread Queue (execute_write)
    # -----------------------------------------------------------------------

    def execute_write(self, fn_or_query: Union[str, Callable[[sqlite3.Connection], Any]], *args, **kwargs) -> Any:
        """
        Execute write operation via dedicated single-writer queue.
        Guarantees zero SQLITE_BUSY errors.
        """
        if self._stop_event.is_set():
            raise RuntimeError("DatabaseManager writer thread is stopped.")

        future: concurrent.futures.Future = concurrent.futures.Future()
        self._write_queue.put((future, fn_or_query, args, kwargs))
        return future.result(timeout=30.0)

    def _writer_loop(self) -> None:
        """Worker loop for serial write transactions."""
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

        while not self._stop_event.is_set():
            try:
                item = self._write_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            future, task, args, kwargs = item
            try:
                conn.execute("BEGIN IMMEDIATE;")
                if callable(task):
                    result = task(conn, *args, **kwargs)
                elif isinstance(task, str):
                    if len(args) == 1 and isinstance(args[0], (tuple, list)):
                        params = args[0]
                    else:
                        params = args
                    cur = conn.cursor()
                    cur.execute(task, params)
                    result = cur.lastrowid
                else:
                    raise ValueError(f"Unsupported task type: {type(task)}")
                conn.commit()
                future.set_result(result)
            except Exception as e:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
                future.set_exception(e)
            finally:
                self._write_queue.task_done()

        conn.close()

    def close(self) -> None:
        """Shutdown writer thread and clean up resources."""
        self._stop_event.set()
        if self._writer_thread.is_alive():
            self._writer_thread.join(timeout=2.0)
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None


# ---------------------------------------------------------------------------
# Global Server & Database Injection
# ---------------------------------------------------------------------------

_db_manager: Optional[DatabaseManager] = None

# Initialize FastMCP Server
if FastMCP is not None:
    mcp = FastMCP("OwlThread Context Engine")
else:
    mcp = None


def attach_database_manager(db: DatabaseManager) -> None:
    """Inject the singleton DatabaseManager instance."""
    global _db_manager
    _db_manager = db


def get_active_db() -> DatabaseManager:
    """Retrieve the injected DatabaseManager or lazily initialize default."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------

if mcp is not None:

    @mcp.resource("owlthread://taxonomy/{quadrant}")
    def read_quadrant_resource(quadrant: str) -> str:
        """
        Returns a markdown bulleted list of active memories for a given quadrant:
        technical_architecture, business_rules, settled_decisions, or open_questions.
        """
        db = get_active_db()
        norm_quadrant = quadrant.strip().lower()

        if norm_quadrant not in VALID_QUADRANTS:
            return (
                f"# Invalid Quadrant\n\n"
                f"Quadrant '{quadrant}' is not valid.\n"
                f"Valid quadrants are: {', '.join(sorted(list(VALID_QUADRANTS)))}"
            )

        rows = db.execute_read(
            """
            SELECT id, summary, raw_text, timestamp, source_app, source_metadata
            FROM memory_entries
            WHERE quadrant = ? AND status = 'active'
            ORDER BY id DESC
            LIMIT 50
            """,
            (norm_quadrant,)
        )

        title = norm_quadrant.replace("_", " ").title()
        if not rows:
            return f"# {title}\n\nNo active records found in quadrant `{norm_quadrant}`."

        lines = [f"# {title}\n"]
        for r in rows:
            summary = (r["summary"] or r["raw_text"] or "").strip()
            meta_str = r["source_metadata"] or ""
            uuid_str = ""
            if meta_str:
                try:
                    meta_dict = json.loads(meta_str)
                    if isinstance(meta_dict, dict) and "uuid" in meta_dict:
                        uuid_str = f" `[{meta_dict['uuid'][:8]}]`"
                except Exception:
                    pass
            lines.append(f"- **[#{r['id']}]**{uuid_str} {summary}")

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # MCP Tools
    # -----------------------------------------------------------------------

    @mcp.tool()
    def query_context(
        search_query: str,
        quadrant_filter: Optional[str] = None,
        max_results: int = 5
    ) -> str:
        """
        Search active memories in OwlThread matching the search query.
        Filters out superseded records to prevent context poisoning.
        
        Args:
            search_query: The keywords or concept to query.
            quadrant_filter: Optional filter (technical_architecture, business_rules, settled_decisions, open_questions).
            max_results: Maximum results to return (default 5).
        """
        db = get_active_db()
        params: List[Any] = []
        sql = """
            SELECT id, quadrant, summary, raw_text, timestamp, source_app, source_metadata
            FROM memory_entries
            WHERE status = 'active'
        """

        if quadrant_filter and quadrant_filter.strip().lower() in VALID_QUADRANTS:
            sql += " AND quadrant = ?"
            params.append(quadrant_filter.strip().lower())

        sql += " ORDER BY id DESC LIMIT 100"

        rows = db.execute_read(sql, tuple(params))
        if not rows:
            return f"No active memories found in OwlThread for query: '{search_query}'."

        # Pure Python token overlap ranking
        q_lower = search_query.lower()
        terms = [w for w in q_lower.split() if len(w) > 2]

        scored: List[Tuple[float, sqlite3.Row]] = []
        for r in rows:
            text = f"{r['summary'] or ''} {r['raw_text'] or ''}".lower()
            score = sum(1.0 for t in terms if t in text)
            if q_lower in text:
                score += 3.0
            if not terms or score > 0:
                scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [item[1] for item in scored[:max_results]]
        if not top:
            top = rows[:max_results]

        output = [f"### OwlThread Context Matches for '{search_query}':\n"]
        for r in top:
            quad = (r["quadrant"] or "unknown").upper()
            sum_text = (r["summary"] or r["raw_text"] or "").strip()
            meta_str = r["source_metadata"] or ""
            uuid_str = ""
            if meta_str:
                try:
                    meta_dict = json.loads(meta_str)
                    if isinstance(meta_dict, dict) and "uuid" in meta_dict:
                        uuid_str = f" [UUID: {meta_dict['uuid']}]"
                except Exception:
                    pass
            output.append(f"- **[{quad}]** #{r['id']}: {sum_text}{uuid_str}")

        return "\n".join(output)

    @mcp.tool()
    def record_decision(
        quadrant: str,
        statement: str,
        supersedes_id: Optional[str] = None
    ) -> str:
        """
        Record a new architecture decision, business rule, or resolved trade-off.
        If supersedes_id is provided, invalidates the older memory and creates a lineage edge.
        Inserts the new memory and returns confirmation with the generated UUID.
        
        Args:
            quadrant: Target quadrant (technical_architecture, business_rules, settled_decisions, open_questions).
            statement: Clear declarative statement of the decision or rule.
            supersedes_id: Optional ID or UUID of an earlier conflicting memory to supersede.
        """
        db = get_active_db()
        norm_quadrant = quadrant.strip().lower()
        if norm_quadrant not in VALID_QUADRANTS:
            return f"Error: Invalid quadrant '{quadrant}'. Valid: {', '.join(sorted(list(VALID_QUADRANTS)))}"

        statement_clean = statement.strip()
        if not statement_clean:
            return "Error: statement cannot be empty."

        generated_uuid = str(uuid.uuid4())

        def _record_task(conn: sqlite3.Connection) -> Tuple[int, Optional[int]]:
            cur = conn.cursor()

            # Ensure default General project
            cur.execute("SELECT id FROM projects WHERE name = 'General' LIMIT 1")
            p_row = cur.fetchone()
            project_id = p_row["id"] if p_row else 1

            meta_json = json.dumps({"uuid": generated_uuid, "recorded_via": "mcp"})
            now_iso = get_iso_now()

            # 1. Insert new active memory entry
            cur.execute(
                """
                INSERT INTO memory_entries (
                    project_id, timestamp, source_app, source_metadata,
                    raw_text, quadrant, summary, status, created_at
                ) VALUES (?, ?, 'mcp_ide', ?, ?, ?, ?, 'active', ?)
                """,
                (project_id, now_iso, meta_json, statement_clean, norm_quadrant, statement_clean, now_iso)
            )
            new_id = cur.lastrowid

            # 2. Invalidate predecessor if supersedes_id supplied
            pred_id_int: Optional[int] = None
            if supersedes_id is not None and str(supersedes_id).strip():
                raw_sid = str(supersedes_id).strip()
                # Resolve if numeric integer ID or UUID string
                if raw_sid.isdigit():
                    cur.execute("SELECT id FROM memory_entries WHERE id = ?", (int(raw_sid),))
                else:
                    cur.execute("SELECT id FROM memory_entries WHERE source_metadata LIKE ?", (f'%"{raw_sid}"%',))
                old_row = cur.fetchone()

                if old_row:
                    pred_id_int = old_row["id"]
                    cur.execute(
                        "UPDATE memory_entries SET status = 'superseded', superseded_by = ? WHERE id = ?",
                        (new_id, pred_id_int)
                    )
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO memory_lineage (successor_id, predecessor_id, conflict_rationale, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (new_id, pred_id_int, "Superseded via in-IDE MCP tool call.", now_iso)
                    )

            return new_id, pred_id_int

        new_entry_id, invalidated_id = db.execute_write(_record_task)

        if invalidated_id is not None:
            return (
                f"Success: Decision recorded into [{norm_quadrant}] as Entry #{new_entry_id} "
                f"with UUID: {generated_uuid}. "
                f"Predecessor #{invalidated_id} was marked SUPERSEDED and lineage edge recorded."
            )

        return (
            f"Success: Decision recorded into [{norm_quadrant}] as Entry #{new_entry_id} "
            f"with UUID: {generated_uuid}."
        )

    @mcp.tool()
    def compile_task_brief(task_goal: str) -> str:
        """
        Compile active records across all 4 quadrants into a complete,
        markdown-primed developer brief ready for LLM consumption.
        
        Args:
            task_goal: The developer's task, goal, or feature request.
        """
        db = get_active_db()
        rows = db.execute_read(
            """
            SELECT id, quadrant, summary, raw_text, timestamp, source_app
            FROM memory_entries
            WHERE status = 'active'
            ORDER BY id DESC
            """
        )

        by_quadrant: Dict[str, List[sqlite3.Row]] = {
            QUAD_TECHNICAL_ARCHITECTURE: [],
            QUAD_SETTLED_DECISIONS: [],
            QUAD_BUSINESS_RULES: [],
            QUAD_OPEN_QUESTIONS: [],
        }

        for r in rows:
            q = r["quadrant"]
            if q in by_quadrant:
                by_quadrant[q].append(r)

        brief = [
            "# Project Architectural & Context Brief",
            f"**Task Objective:** {task_goal.strip()}\n",
            "---",
        ]

        section_titles = [
            (QUAD_TECHNICAL_ARCHITECTURE, "1. Technical Architecture & Constraints"),
            (QUAD_SETTLED_DECISIONS, "2. Settled Decisions & Conventions"),
            (QUAD_BUSINESS_RULES, "3. Business Rules & Domain Logic"),
            (QUAD_OPEN_QUESTIONS, "4. Open Questions & Uncertainties"),
        ]

        total_entries = 0
        for quad_key, title in section_titles:
            entries = by_quadrant[quad_key]
            total_entries += len(entries)
            brief.append(f"### {title}")
            if not entries:
                brief.append("*No active items recorded.*\n")
            else:
                for item in entries[:15]:
                    sum_text = (item["summary"] or item["raw_text"] or "").strip()
                    brief.append(f"- [#{item['id']}] {sum_text}")
                brief.append("")

        brief.append("---")
        brief.append(f"*Compiled by OwlThread Context Engine from {total_entries} active memory records.*")
        return "\n".join(brief)


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI Runner for OwlThread MCP Server."""
    parser = argparse.ArgumentParser(description="OwlThread MCP Server for Cursor and Claude Code")
    parser.add_argument("--db-path", type=str, default=None, help="Path to owlthread.db")
    parser.add_argument("--transport", type=str, default="stdio", choices=["stdio", "sse"], help="MCP transport (default: stdio)")
    args = parser.parse_args()

    if mcp is None:
        sys.stderr.write("Error: MCP SDK is not installed. Please run: pip install mcp\n")
        sys.exit(1)

    db_manager = DatabaseManager(db_path=args.db_path)
    attach_database_manager(db_manager)

    try:
        # Run over standard I/O for Cursor / Claude
        mcp.run(transport=args.transport)
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
