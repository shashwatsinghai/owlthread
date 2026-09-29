"""MCP tools exercise the same durable database as every other entry point."""
from __future__ import annotations
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from owlthread.db.database import DatabaseManager
from owlthread.mcp_server import (mcp,attach_database_manager,search_memory,record_decision,
                                  get_quadrant,get_memory_stats,generate_primer,list_integrations,
                                  get_integration_status,configure_integration)


class TestMCPServer(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(str(Path(self.temp.name)/"memory.db"))
        attach_database_manager(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def test_registered_tools(self) -> None:
        tools = asyncio.run(mcp.list_tools())
        self.assertEqual({tool.name for tool in tools},
                         {"search_memory","record_decision","get_quadrant","generate_primer","get_memory_stats",
                          "list_integrations","get_integration_status","configure_integration"})

    def test_integration_tools_are_catalog_only_and_permission_scoped(self) -> None:
        available = list_integrations()
        self.assertGreaterEqual(available["count"],24)
        self.assertEqual(available["connected_count"],0)
        cloudflare = get_integration_status("cloudflare")
        self.assertFalse(cloudflare["enabled"])
        self.assertFalse(cloudflare["connected"])
        configured = configure_integration("cloudflare",True,["zones.read","dns.write"])
        self.assertTrue(configured["enabled"])
        self.assertFalse(configured["connected"])
        self.assertEqual(configured["configured_scopes"],["dns.write","zones.read"])
        with self.assertRaises(PermissionError):
            configure_integration("cloudflare",True,["account.admin"])

    def test_record_and_supersede(self) -> None:
        old = record_decision("Use PostgreSQL","settled_decisions")
        new = record_decision("Use SQLite WAL","settled_decisions",supersedes_id=old["id"])
        self.assertEqual(self.db.get_entry_by_id(old["id"])["superseded_by"],new["id"])
        self.assertEqual(len(self.db.get_entry_lineage(new["id"])),1)
        self.assertEqual(get_memory_stats()["total_entries"],1)

    def test_cross_project_supersede_rejected_without_insert(self) -> None:
        old = record_decision("Use SQLite","technical_architecture")
        pid = self.db.get_or_create_project("Other")
        with self.assertRaises(ValueError):
            record_decision("Use Redis","technical_architecture",project_id=pid,supersedes_id=old["id"])
        self.assertEqual(self.db.count_entries(),1)

    def test_search_and_quadrant(self) -> None:
        record_decision("OAuth2 tokens authenticate FastAPI endpoints","technical_architecture")
        self.assertEqual(search_memory("OAuth2")["count"],1)
        self.assertEqual(get_quadrant("business_rules")["count"],0)
        with self.assertRaises(ValueError):
            get_quadrant("invalid")

    @patch("owlthread.primer.engine.copy_to_clipboard",return_value=True)
    def test_generate_primer(self, copy: object) -> None:
        record_decision("Stripe subscriptions require signed webhooks","business_rules")
        result = generate_primer("implement Stripe billing")
        self.assertIn("signed webhooks",result["primer_text"])
        self.assertTrue(result["copied_to_clipboard"])
