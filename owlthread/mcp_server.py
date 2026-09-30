"""OwlThread memory tools served over MCP stdio; diagnostics stay on stderr."""
from __future__ import annotations
import argparse
import json
import logging
import sqlite3
import uuid
from typing import Any
try:
    # MCP 1.x. MCP 2.x deliberately raises from this compatibility module.
    from mcp.server.fastmcp import FastMCP as _MCPServer
except (ImportError, ModuleNotFoundError):
    from mcp.server.mcpserver import MCPServer as _MCPServer
from owlthread.config import VALID_QUADRANTS
from owlthread.db.database import DatabaseManager, get_iso_now
from owlthread.integrations.registry import IntegrationRegistry
from owlthread.integrations.context import ContextConnectorService
from owlthread.primer.engine import PrimerEngine
from owlthread.primer.search import MemorySearcher
from owlthread.extraction.rebase import apply_actions, normalized

logger = logging.getLogger(__name__)
QUAD_TECHNICAL_ARCHITECTURE = "technical_architecture"
QUAD_SETTLED_DECISIONS = "settled_decisions"
mcp = _MCPServer("OwlThread Memory")
_database: DatabaseManager | None = None


def attach_database_manager(db: DatabaseManager) -> None:
    global _database
    _database = db


def get_active_db() -> DatabaseManager:
    global _database
    if _database is None:
        _database = DatabaseManager()
    return _database


def _quadrant(quadrant: str) -> None:
    if quadrant not in VALID_QUADRANTS:
        raise ValueError("Invalid quadrant; choose "+", ".join(sorted(VALID_QUADRANTS)))


def _project(project_id: int | None) -> int:
    db=get_active_db()
    if project_id is None:
        return db.get_or_create_project(db.get_setting("active_project","General"))
    if type(project_id) is not int or project_id<=0 or not db.get_project_by_id(project_id):
        raise ValueError("Unknown project_id")
    return project_id


def _limit(limit: int) -> int:
    if type(limit) is not int or not 1<=limit<=200:
        raise ValueError("limit must be an integer from 1 to 200")
    return limit


@mcp.tool()
def search_memory(query: str, quadrant: str | None = None, limit: int = 10, project_id: int | None = None) -> dict[str,Any]:
    """Search active local memories by task, with optional quadrant and project filters."""
    if quadrant:
        _quadrant(quadrant)
    if not isinstance(query,str) or len(query)>4000:
        raise ValueError("query must be text of at most 4000 characters")
    entries = MemorySearcher(get_active_db()).search(query,limit=_limit(limit),quadrant=quadrant,project_id=_project(project_id))
    return {"entries":entries,"count":len(entries)}


@mcp.tool()
def record_decision(summary: str, quadrant: str, raw_text: str | None = None, project_id: int | None = None,
                    supersedes_id: int | None = None) -> dict[str,Any]:
    """Record a durable knowledge item, optionally replacing an older memory in the same project."""
    _quadrant(quadrant)
    if not isinstance(summary,str) or not 1<=len(summary.strip())<=240 or len(summary.split())>30:
        raise ValueError("summary must contain 1 to 240 characters and at most 30 words")
    if raw_text is not None and (not isinstance(raw_text,str) or len(raw_text)>4000):
        raise ValueError("raw_text must contain at most 4000 characters")
    if supersedes_id is not None and (type(supersedes_id) is not int or supersedes_id<=0):
        raise ValueError("Invalid supersedes_id")
    db = get_active_db()
    pid = _project(project_id)
    uid = str(uuid.uuid4())
    def write(conn: sqlite3.Connection) -> dict[str,Any]:
        result=apply_actions(conn,{"project_id":pid,"source_app":"mcp","source_metadata":json.dumps({"uuid":uid})},
            [{"action":"SUPERSEDE" if supersedes_id else "ADD","quadrant":quadrant,"summary":summary.strip(),
              "source_snippet":raw_text or summary,"target_memory_id":supersedes_id,"rationale":"Explicit replacement via MCP"}])
        if result:
            return {"id":result[0]["entry_id"],"uuid":uid,"quadrant":quadrant,"superseded_id":supersedes_id,"duplicate":False}
        row=next(row for row in conn.execute("SELECT id,summary,source_metadata FROM memory_entries WHERE project_id=? AND quadrant=? AND status='active'",(pid,quadrant)) if normalized(row["summary"])==normalized(summary))
        try: previous_uid=json.loads(row["source_metadata"] or '{}').get('uuid')
        except (ValueError,AttributeError): previous_uid=None
        return {"id":row["id"],"uuid":previous_uid,"quadrant":quadrant,"superseded_id":None,"duplicate":True}
    return db.execute_write(write)


@mcp.tool()
def get_quadrant(quadrant: str, limit: int = 20, project_id: int | None = None) -> dict[str,Any]:
    """Read active items in a quadrant."""
    _quadrant(quadrant)
    entries = get_active_db().get_entries(quadrant=quadrant,project_id=_project(project_id),limit=_limit(limit))
    return {"entries":entries,"count":len(entries)}


@mcp.tool()
def generate_primer(task: str, project_id: int | None = None) -> dict[str,Any]:
    """Compile a task brief from local memory and automatically copy it."""
    if not isinstance(task,str) or not 1<=len(task.strip())<=4000:
        raise ValueError("task must contain 1 to 4000 characters")
    return PrimerEngine(get_active_db()).generate_primer(task,project_id=_project(project_id)).to_dict()


@mcp.tool()
def get_memory_stats() -> dict[str,Any]:
    """Return quadrant totals, project counts and pending captures."""
    db = get_active_db()
    counts = {q:0 for q in VALID_QUADRANTS}
    counts.update({r["quadrant"]:r["n"] for r in db.execute_read("SELECT quadrant,COUNT(*) AS n FROM memory_entries WHERE status='active' GROUP BY quadrant")})
    return {"total_entries":db.count_entries(),"quadrants":counts,"pending_captures":db.pending_count(),"projects":db.list_projects()}


@mcp.tool()
def list_integrations() -> dict[str,Any]:
    """List available integration definitions and their local, non-secret configuration state."""
    integrations = IntegrationRegistry(get_active_db()).list()
    return {"integrations":integrations,"count":len(integrations),
            "connected_count":sum(item["connected"] for item in integrations)}


@mcp.tool()
def get_integration_status(integration_id: str) -> dict[str,Any]:
    """Inspect one integration's exact scopes; availability never implies connectivity."""
    return IntegrationRegistry(get_active_db()).status(integration_id)


@mcp.tool()
def configure_integration(integration_id: str, enabled: bool, scopes: list[str],
                          project_id: int | None = None) -> dict[str,Any]:
    """Configure non-secret integration grants; powerful scopes cannot be granted over MCP."""
    return IntegrationRegistry(get_active_db()).configure(
        integration_id,enabled=enabled,scopes=scopes,project_id=project_id,via_mcp=True)


@mcp.tool()
def test_integration_connection(integration_id: str) -> dict[str, Any]:
    """Test a locally configured bundled connector with authenticated, read-only provider calls.

    Set its token and resource IDs in the desktop Connect screen first. This does
    not import context. Connectivity is reported only after a provider response.
    """
    return ContextConnectorService(get_active_db()).test(integration_id)


@mcp.tool()
def sync_integration_context(integration_id: str, limit: int = 25) -> dict[str, Any]:
    """Read bounded provider context into the connector's configured local project.

    Cloudflare and GitHub clients are bundled. Only exact granted read scopes are
    fetched; repeated unchanged snapshots are deduplicated. Provider writes and
    deployment are unavailable. Limit is 1 to 100 records per selected scope.
    """
    return ContextConnectorService(get_active_db()).sync(integration_id, limit)


@mcp.resource("owlthread://quadrants/{quadrant}")
def read_quadrant_resource(quadrant: str) -> str:
    return json.dumps(get_quadrant(quadrant),ensure_ascii=False)


def query_context(search_query: str, max_results: int = 10) -> str:
    return json.dumps(search_memory(search_query,limit=max_results),ensure_ascii=False)


def compile_task_brief(task_goal: str) -> str:
    return generate_primer(task_goal)["primer_text"]


def main() -> None:
    parser = argparse.ArgumentParser(description="OwlThread MCP stdio server")
    parser.add_argument("--db-path")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    with DatabaseManager(args.db_path) as db:
        attach_database_manager(db)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
