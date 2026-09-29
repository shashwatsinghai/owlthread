"""Integration configuration grants only exact, bounded, non-secret scopes."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from owlthread.db.database import Database
from owlthread.integrations.registry import IntegrationRegistry, SETTING_PREFIX


class IntegrationPermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp=tempfile.TemporaryDirectory()
        self.db=Database(str(Path(self.temp.name)/"permissions.db"))
        self.registry=IntegrationRegistry(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def test_exact_read_and_ordinary_write_scopes_can_be_configured(self) -> None:
        pid=self.db.get_or_create_project("Infrastructure")
        status=self.registry.configure("cloudflare",enabled=True,scopes=["zones.read","dns.write"],project_id=pid,via_mcp=True)
        self.assertTrue(status["enabled"])
        self.assertFalse(status["connected"])
        self.assertFalse(status["can_execute"])
        self.assertEqual(status["project_id"],pid)
        raw=self.db.get_setting(SETTING_PREFIX+"cloudflare")
        self.assertEqual(set(json.loads(raw)),{"enabled","scopes","project_id"})
        self.assertNotIn("credential",raw.lower())
        self.assertNotIn("token",raw.lower())

    def test_unknown_duplicate_and_inexact_scopes_fail_without_overwrite(self) -> None:
        self.registry.configure("github",enabled=True,scopes=["repositories.read"],via_mcp=True)
        original=self.db.get_setting(SETTING_PREFIX+"github")
        for scopes in (["repositories.*"],["Repositories.read"],["repositories.read","repositories.read"]):
            with self.subTest(scopes=scopes), self.assertRaises(ValueError):
                self.registry.configure("github",enabled=True,scopes=scopes,via_mcp=True)
            self.assertEqual(self.db.get_setting(SETTING_PREFIX+"github"),original)
        with self.assertRaises(ValueError):
            self.registry.configure("not-a-connector",enabled=True,scopes=[],via_mcp=True)

    def test_mcp_cannot_grant_admin_destructive_or_trading_scopes(self) -> None:
        cases=(("cloudflare","account.admin"),("gmail","messages.delete"),("alpaca","orders.place"))
        for integration_id,scope in cases:
            with self.subTest(integration_id=integration_id,scope=scope), self.assertRaises(PermissionError):
                self.registry.configure(integration_id,enabled=True,scopes=[scope],via_mcp=True)
            self.assertIsNone(self.db.get_setting(SETTING_PREFIX+integration_id))

    def test_project_scope_must_reference_a_real_project(self) -> None:
        for invalid in (True,0,-1,99999):
            with self.subTest(project_id=invalid), self.assertRaises(ValueError):
                self.registry.configure("github",enabled=True,scopes=["repositories.read"],project_id=invalid,via_mcp=True)

    def test_corrupt_saved_configuration_fails_closed(self) -> None:
        self.db.set_setting(SETTING_PREFIX+"cloudflare",json.dumps({"enabled":True,"scopes":["account.admin"],"project_id":None,"secret":"bad"}))
        status=self.registry.status("cloudflare")
        self.assertFalse(status["enabled"])
        self.assertFalse(status["connected"])
        self.assertFalse(status["configuration_valid"])
        self.assertEqual(status["configured_scopes"],[])


if __name__ == "__main__":
    unittest.main()
