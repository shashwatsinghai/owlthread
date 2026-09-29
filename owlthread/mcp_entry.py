"""Compatibility entry point for the shared MCP server."""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)


def run_mcp_service(db_path: str | None = None, transport: str = "stdio") -> None:
    if transport != "stdio":
        raise ValueError("Only stdio transport is supported")
    from owlthread.db.database import DatabaseManager
    from owlthread.mcp_server import attach_database_manager,mcp
    with DatabaseManager(db_path) as db:
        attach_database_manager(db)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_mcp_service()
