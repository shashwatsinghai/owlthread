"""Unit tests for embedded FastMCP Server (mcp_server.py)."""

import gc
import json
import os
import tempfile
import time
import unittest

from mcp_server import (
    DatabaseManager,
    attach_database_manager,
    read_quadrant_resource,
    query_context,
    record_decision,
    compile_task_brief,
    VALID_QUADRANTS,
    QUAD_TECHNICAL_ARCHITECTURE,
    QUAD_SETTLED_DECISIONS,
)


class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_mcp.db")
        self.db_manager = DatabaseManager(self.db_path)
        attach_database_manager(self.db_manager)

    def tearDown(self):
        self.db_manager.close()
        gc.collect()
        time.sleep(0.1)
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_database_manager_read_and_write(self):
        """Verify execute_read and execute_write work with zero SQLITE_BUSY errors."""
        res_id = self.db_manager.execute_write(
            "INSERT INTO projects (name, root_path, created_at) VALUES (?, ?, ?)",
            "TestProject", "/test/path", "2026-09-03T12:00:00Z"
        )
        self.assertIsNotNone(res_id)

        rows = self.db_manager.execute_read("SELECT * FROM projects WHERE name = ?", ("TestProject",))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "TestProject")

    def test_record_decision_tool_add_and_supersede(self):
        """Verify record_decision tool inserts with UUID and properly supersedes older records."""
        # 1. Initial decision (ADD)
        add_res = record_decision(
            quadrant=QUAD_SETTLED_DECISIONS,
            statement="Use PostgreSQL 16 for persistent document storage."
        )
        self.assertIn("Success: Decision recorded into [settled_decisions]", add_res)
        self.assertIn("with UUID:", add_res)
        self.assertIn("Entry #1", add_res)

        rows = self.db_manager.execute_read("SELECT * FROM memory_entries WHERE id = 1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "active")
        meta = json.loads(rows[0]["source_metadata"])
        self.assertIn("uuid", meta)

        # 2. Subsequent decision that supersedes #1
        sup_res = record_decision(
            quadrant=QUAD_SETTLED_DECISIONS,
            statement="Switched to SQLite in WAL mode for embedded deployment.",
            supersedes_id="1"
        )
        self.assertIn("Entry #2", sup_res)
        self.assertIn("Predecessor #1 was marked SUPERSEDED", sup_res)

        old_rows = self.db_manager.execute_read("SELECT * FROM memory_entries WHERE id = 1")
        self.assertEqual(old_rows[0]["status"], "superseded")
        self.assertEqual(old_rows[0]["superseded_by"], 2)

        lineage_rows = self.db_manager.execute_read("SELECT * FROM memory_lineage WHERE successor_id = 2")
        self.assertEqual(len(lineage_rows), 1)
        self.assertEqual(lineage_rows[0]["predecessor_id"], 1)

    def test_read_quadrant_resource(self):
        """Verify reading MCP resource returns active entries."""
        record_decision(
            quadrant=QUAD_TECHNICAL_ARCHITECTURE,
            statement="Event-driven queue worker architecture."
        )

        res_text = read_quadrant_resource(QUAD_TECHNICAL_ARCHITECTURE)
        self.assertIn("# Technical Architecture", res_text)
        self.assertIn("Event-driven queue worker architecture.", res_text)

        bad_res = read_quadrant_resource("invalid_quadrant_name")
        self.assertIn("Invalid Quadrant", bad_res)

    def test_query_context_tool(self):
        """Verify query_context tool matches and filters active records."""
        record_decision(
            quadrant=QUAD_TECHNICAL_ARCHITECTURE,
            statement="FastAPI endpoints authenticated using OAuth2 tokens."
        )

        res = query_context("OAuth2 tokens")
        self.assertIn("FastAPI endpoints authenticated using OAuth2 tokens.", res)
        self.assertIn("TECHNICAL_ARCHITECTURE", res)

    def test_compile_task_brief_tool(self):
        """Verify compile_task_brief compiles across all 4 quadrants."""
        record_decision(
            quadrant="technical_architecture",
            statement="Microservices run on Docker with Traefik reverse proxy."
        )
        record_decision(
            quadrant="business_rules",
            statement="Free trial is 14 days without requiring credit card."
        )
        record_decision(
            quadrant="settled_decisions",
            statement="Standardized on ruff and mypy for code quality."
        )
        record_decision(
            quadrant="open_questions",
            statement="TBD: Should we support self-hosted airgapped setups?"
        )

        brief = compile_task_brief("Implement billing upgrade flow")
        self.assertIn("# Project Architectural & Context Brief", brief)
        self.assertIn("**Task Objective:** Implement billing upgrade flow", brief)
        self.assertIn("1. Technical Architecture & Constraints", brief)
        self.assertIn("2. Settled Decisions & Conventions", brief)
        self.assertIn("3. Business Rules & Domain Logic", brief)
        self.assertIn("4. Open Questions & Uncertainties", brief)
        self.assertIn("Traefik", brief)
        self.assertIn("14 days", brief)
        self.assertIn("ruff", brief)
        self.assertIn("airgapped", brief)


if __name__ == "__main__":
    unittest.main()
