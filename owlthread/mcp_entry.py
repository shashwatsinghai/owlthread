"""
Model Context Protocol (MCP) Server for OwlThread.
Enables Cursor, Windsurf, Claude Code CLI, and Continue to natively query active
architectural patterns, business rules, settled decisions, and record in-session decisions.
"""

import argparse
import sys
from typing import List, Optional

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
    except ImportError:
        try:
            from fastmcp import FastMCP as MCPServer
        except ImportError:
            MCPServer = None

from owlthread.db.database import Database

server = MCPServer("OwlThread Context Engine") if MCPServer is not None else None
_db_instance: Optional[Database] = None


def get_db(db_path: Optional[str] = None) -> Database:
    """Get or initialize singleton Database reference."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(db_path=db_path)
    return _db_instance


if server is not None:

    @server.resource("owlthread://taxonomy/{quadrant}")
    def read_quadrant_resource(quadrant: str) -> str:
        """Returns a markdown list of active memories for a given epistemological quadrant."""
        db = get_db()
        valid_quadrants = {
            "technical_architecture",
            "business_rules",
            "settled_decisions",
            "open_questions",
        }
        if quadrant not in valid_quadrants:
            return f"# Error\nUnknown quadrant: '{quadrant}'. Valid quadrants: {sorted(list(valid_quadrants))}"

        records = db.get_entries(
            limit=50,
            quadrant=quadrant,
            status="active"
        )
        title = quadrant.replace("_", " ").title()
        if not records:
            return f"# {title}\n\nNo active records found."

        lines = [f"# {title}\n"]
        for row in records:
            summary = row.get("summary") or row.get("raw_text", "")
            lines.append(f"- {summary.strip()}")
        return "\n".join(lines)

    @server.tool()
    def query_context(
        search_query: str,
        quadrant_filter: Optional[str] = None,
        max_results: int = 5
    ) -> str:
        """
        Query active architectural patterns, business rules, and decisions stored in OwlThread.
        Filters out superseded records to prevent context poisoning.
        """
        db = get_db()
        records = db.get_entries(
            limit=max(10, max_results * 2),
            quadrant=quadrant_filter if quadrant_filter else None,
            status="active"
        )
        if not records:
            return f"No active memories found in OwlThread for query: '{search_query}'."

        q_lower = search_query.lower()
        terms = [t for t in q_lower.split() if len(t) > 2]
        matches = []

        for r in records:
            summary = (r.get("summary") or "").lower()
            raw = (r.get("raw_text") or "").lower()
            text = f"{summary} {raw}"
            score = sum(1 for term in terms if term in text)
            if not terms or score > 0 or q_lower in text:
                matches.append((score, r))

        matches.sort(key=lambda x: x[0], reverse=True)
        top = [m[1] for m in matches[:max_results]]
        if not top:
            top = records[:max_results]

        output = ["### OwlThread Context Matches:"]
        for row in top:
            quad = (row.get("quadrant") or "UNKNOWN").upper()
            sum_text = row.get("summary") or row.get("raw_text", "")[:120]
            output.append(f"- [{quad}] {sum_text.strip()} (ID: {row.get('id')})")

        return "\n".join(output)

    @server.tool()
    def record_decision(
        quadrant: str,
        statement: str,
        supersedes_id: Optional[int] = None,
        conflict_rationale: Optional[str] = None
    ) -> str:
        """
        Record a new architecture decision, business rule, or resolved trade-off.
        Optionally marks an earlier conflicting memory as superseded.
        """
        db = get_db()
        valid_quadrants = {
            "technical_architecture",
            "business_rules",
            "settled_decisions",
            "open_questions",
        }
        if quadrant not in valid_quadrants:
            return f"Error: Invalid quadrant '{quadrant}'. Must be one of: {sorted(list(valid_quadrants))}"

        new_id = db.insert_entry(
            raw_text=statement,
            source_app="mcp_ide",
            quadrant=quadrant,
            summary=statement,
            status="active"
        )

        if supersedes_id is not None:
            db.supersede_entry(
                old_entry_id=supersedes_id,
                new_entry_id=new_id,
                rationale=conflict_rationale or "Superseded via in-IDE MCP tool call."
            )
            return f"Decision recorded successfully (ID: #{new_id}), superseding earlier record #{supersedes_id}."

        return f"Decision recorded successfully in [{quadrant}] (ID: #{new_id})."

    @server.tool()
    def compile_task_brief(task_goal: str) -> str:
        """
        Compile a structured, primed markdown context brief across all active quadrants
        tailored for the given developer task or query.
        """
        from owlthread.primer.engine import PrimerEngine
        db = get_db()
        primer_engine = PrimerEngine(db=db)
        res = primer_engine.generate_primer(user_request=task_goal, auto_copy=False)
        return res.primer_text


def run_mcp_service(db_path: Optional[str] = None, transport: str = "stdio") -> None:
    """Launch the MCP server loop."""
    if server is None:
        sys.stderr.write("Error: 'mcp' library is not installed. Run `pip install mcp`.\n")
        sys.exit(1)

    get_db(db_path=db_path)
    server.run(transport=transport)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OwlThread MCP Server for Cursor and Claude Code")
    parser.add_argument("--db-path", type=str, default=None, help="Path to owlthread.db")
    parser.add_argument("--transport", type=str, default="stdio", choices=["stdio", "sse"], help="MCP transport")
    args = parser.parse_args()
    run_mcp_service(db_path=args.db_path, transport=args.transport)
