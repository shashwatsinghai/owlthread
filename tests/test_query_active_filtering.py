"""Unit and integration tests for active query filtering, history toggle, and done signals."""

import os
import tempfile
import unittest

from owlthread.db.database import Database
from owlthread.extraction.pipeline import ExtractionPipeline
from owlthread.primer.engine import PrimerEngine
from owlthread.primer.search import MemorySearcher


class TestQueryActiveFiltering(unittest.TestCase):
    """Test suite for Step 5 query filtering and task done signals."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_filter.db")
        self.db = Database(self.db_path)
        self.searcher = MemorySearcher(self.db)
        self.pipeline = ExtractionPipeline(db=self.db)
        self.engine = PrimerEngine(db=self.db, extraction_pipeline=self.pipeline)

    def tearDown(self):
        self.db.close()
        self.tmp_dir.cleanup()

    def test_default_search_excludes_superseded_entries(self):
        """Verify search filters out status='superseded' entries by default."""
        pid = self.db.get_or_create_project("ProjectA")

        # 1. Insert active entry first so its ID exists
        id_active = self.db.insert_entry(
            raw_text="Stripe monthly tier updated to 29 USD.",
            source_app="cursor",
            project_id=pid,
            quadrant="business_rules",
            summary="Stripe pricing tier updated to $29.",
            status="active"
        )

        # 2. Insert superseded entry pointing to valid active entry
        id_old = self.db.insert_entry(
            raw_text="Stripe monthly tier is 10 USD.",
            source_app="cursor",
            project_id=pid,
            quadrant="business_rules",
            summary="Stripe pricing tier is $10.",
            status="superseded",
            superseded_by=id_active
        )

        # Default search: only active
        results = self.searcher.search("Stripe pricing", include_history=False)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], id_active)

    def test_include_history_flag_returns_superseded_entries(self):
        """Verify include_history=True returns both active and superseded records."""
        pid = self.db.get_or_create_project("ProjectB")

        id_active = self.db.insert_entry(
            raw_text="Stripe monthly tier updated to 29 USD.",
            source_app="cursor",
            project_id=pid,
            quadrant="business_rules",
            summary="Stripe pricing tier updated to $29.",
            status="active"
        )
        id_old = self.db.insert_entry(
            raw_text="Stripe monthly tier is 10 USD.",
            source_app="cursor",
            project_id=pid,
            quadrant="business_rules",
            summary="Stripe pricing tier is $10.",
            status="superseded",
            superseded_by=id_active
        )

        results = self.searcher.search("Stripe pricing", include_history=True)
        self.assertEqual(len(results), 2)
        result_ids = {r["id"] for r in results}
        self.assertIn(id_old, result_ids)
        self.assertIn(id_active, result_ids)

    def test_done_signal_flushes_buffer(self):
        """Verify typing 'done' / 'shipped' flushes buffer and executes extraction."""
        # Buffer capture
        self.pipeline.ingest_capture(
            raw_text="Decision: Standardized on FastAPI for microservices with OAuth2 token validation.",
            source_app="cursor",
            project_name="ServiceApp"
        )

        # Generate primer with "done" query
        res = self.engine.generate_primer("done")
        self.assertTrue(res.is_flush_signal)
        self.assertIn("Task Done / Shipped Signal Processed", res.primer_text)
        self.assertGreaterEqual(res.flush_summary["batches_flushed"], 1)

        # Verify entry is now in database as active
        entries = self.db.get_entries(include_history=False)
        self.assertGreaterEqual(len(entries), 1)


if __name__ == "__main__":
    unittest.main()
