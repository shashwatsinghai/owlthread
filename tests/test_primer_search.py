"""Unit tests for relevance search (keyword + recency scoring) in Primer Engine."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from owlthread.db.database import Database
from owlthread.primer.search import MemorySearcher, extract_keywords


class TestMemorySearcher(unittest.TestCase):
    """Test suite for memory search engine."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_search.db")
        self.db = Database(self.db_path)
        self.searcher = MemorySearcher(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp_dir.cleanup()

    def test_extract_keywords(self):
        """Verify keyword tokenization and stop word filtering."""
        kw = extract_keywords("I want to integrate Stripe billing for subscriptions")
        self.assertIn("integrate", kw)
        self.assertIn("stripe", kw)
        self.assertIn("billing", kw)
        self.assertIn("subscription", kw)
        self.assertNotIn("want", kw)
        self.assertNotIn("for", kw)

    def test_keyword_relevance_ranking(self):
        """Verify entries matching query keywords score higher than non-matching ones."""
        now = datetime.now(timezone.utc).isoformat()
        
        id1 = self.db.insert_entry(
            raw_text="Configured Stripe API webhook and billing customer portal.",
            source_app="cursor",
            timestamp=now,
            quadrant="settled_decisions"
        )
        id2 = self.db.insert_entry(
            raw_text="Updated CSS color palette for dark theme in main app layout.",
            source_app="clipboard",
            timestamp=now,
            quadrant="technical_architecture"
        )

        results = self.searcher.search("integrate Stripe billing")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["id"], id1)
        self.assertGreater(results[0]["score"], 0)

    def test_recency_weighting(self):
        """Verify that a recent matching entry outscores an identical older entry."""
        now_dt = datetime.now(timezone.utc)
        recent_ts = now_dt.isoformat()
        old_ts = (now_dt - timedelta(days=30)).isoformat()

        id_old = self.db.insert_entry(
            raw_text="Audit update: verified security tokens and access keys.",
            source_app="cli",
            timestamp=old_ts,
            quadrant="open_questions"
        )
        id_recent = self.db.insert_entry(
            raw_text="Audit update: verified security tokens and access keys.",
            source_app="cli",
            timestamp=recent_ts,
            quadrant="open_questions"
        )

        results = self.searcher.search("audit update")
        self.assertEqual(len(results), 2)
        # Recent entry must rank first due to recency weighting
        self.assertEqual(results[0]["id"], id_recent)
        self.assertEqual(results[1]["id"], id_old)
        self.assertGreater(results[0]["score"], results[1]["score"])
        self.assertGreater(results[0]["recency_weight"], results[1]["recency_weight"])

    def test_search_across_quadrants(self):
        """Verify search surfaces entries across all four quadrants and NULL."""
        now = datetime.now(timezone.utc).isoformat()
        quadrants = ["technical_architecture", "settled_decisions", "open_questions", "business_rules", None]
        for q in quadrants:
            self.db.insert_entry(
                raw_text=f"Stripe payment integration note in quadrant {q}",
                source_app="cursor",
                timestamp=now,
                quadrant=q
            )

        results = self.searcher.search("Stripe payment integration", limit=10)
        self.assertEqual(len(results), 5)


if __name__ == "__main__":
    unittest.main()
