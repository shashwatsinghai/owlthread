"""Static integration definitions are honest, unique and explicit."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from owlthread.db.database import Database
from owlthread.integrations import list_catalog
from owlthread.integrations.registry import IntegrationRegistry, SETTING_PREFIX


class IntegrationCatalogTests(unittest.TestCase):
    def test_catalog_has_at_least_twenty_four_unique_connectors_and_cloudflare(self) -> None:
        catalog = list_catalog()
        self.assertGreaterEqual(len(catalog),24)
        self.assertEqual(len({item.integration_id for item in catalog}),len(catalog))
        self.assertIn("cloudflare",{item.integration_id for item in catalog})
        for item in catalog:
            names=[scope.name for scope in item.scopes]
            self.assertTrue(names)
            self.assertEqual(len(names),len(set(names)))
            self.assertTrue({scope.risk for scope in item.scopes} <= {"read","write","admin"})

    def test_catalog_reads_do_not_persist_or_claim_connections(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"catalog.db")) as db:
            statuses=IntegrationRegistry(db).list()
            self.assertTrue(all(not item["enabled"] and not item["connected"] and not item["can_execute"] for item in statuses))
            self.assertTrue(all(item["connection_state"]=="disabled_unconnected" for item in statuses))
            self.assertFalse(any(key.startswith(SETTING_PREFIX) for key in db.get_all_settings()))


if __name__ == "__main__":
    unittest.main()
