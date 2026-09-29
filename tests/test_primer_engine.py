"""Integration tests for PrimerEngine."""

import os
import tempfile
import unittest

from owlthread.db.database import Database
from owlthread.primer.engine import PrimerEngine, copy_to_clipboard


class TestPrimerEngine(unittest.TestCase):
    """End-to-end test suite for PrimerEngine."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_engine.db")
        self.db = Database(self.db_path)
        self.engine = PrimerEngine(db=self.db)

        # Seed sample data across quadrants
        self.db.insert_entry(
            raw_text="Architected Stripe webhook listener in owlthread/capture/server.py with event signatures.",
            source_app="cursor",
            quadrant="technical_architecture"
        )
        self.db.insert_entry(
            raw_text="Decision: Standardized on Stripe Checkout session creation for monthly tier.",
            source_app="cursor",
            quadrant="settled_decisions"
        )
        self.db.insert_entry(
            raw_text="Pitch note for investors: OwlThread captures developer context across tools to build company memory.",
            source_app="clipboard",
            quadrant="business_rules"
        )
        self.db.insert_entry(
            raw_text="Audit update report: Verified system integrity, database migrations, and connector tests.",
            source_app="cli",
            quadrant="open_questions"
        )

    def tearDown(self):
        self.db.close()
        self.tmp_dir.cleanup()

    def test_dev_task_pipeline(self):
        """Verify full pipeline for dev task."""
        res = self.engine.generate_primer("integrate Stripe billing", auto_copy=False)
        self.assertEqual(res.query, "integrate Stripe billing")
        self.assertEqual(res.intent, "dev_task")
        self.assertGreaterEqual(len(res.matched_entries), 2)
        self.assertIn("Relevant Architecture Decisions", res.primer_text)
        self.assertIn("Stripe", res.primer_text)

    def test_external_comms_pipeline(self):
        """Verify full pipeline for external comms."""
        res = self.engine.generate_primer("I want to send this idea to an investor", auto_copy=False)
        self.assertEqual(res.intent, "external_comms")
        self.assertIn("Current Project Status", res.primer_text)

    def test_status_query_pipeline(self):
        """Verify full pipeline for status query."""
        res = self.engine.generate_primer("audit new update", auto_copy=False)
        self.assertEqual(res.intent, "status_query")
        self.assertIn("Technical Architecture", res.primer_text)

    def test_intent_override(self):
        """Verify explicit intent override is respected."""
        res = self.engine.generate_primer("random note", intent_override="external_comms", auto_copy=False)
        self.assertEqual(res.intent, "external_comms")

    def test_copy_to_clipboard_function(self):
        """Verify copy_to_clipboard executes without error."""
        success = copy_to_clipboard("OwlThread test clipboard payload")
        # Should succeed or return boolean
        self.assertIsInstance(success, bool)


if __name__ == "__main__":
    unittest.main()
