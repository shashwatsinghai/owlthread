"""Unit tests for Phase 2 LLM memory extraction across 4 quadrants."""

import json
import unittest
from unittest.mock import MagicMock

from owlthread.extraction.extractor import (
    EXTRACTION_SYSTEM_PROMPT,
    QUAD_BUSINESS_RULES,
    QUAD_OPEN_QUESTIONS,
    QUAD_SETTLED_DECISIONS,
    QUAD_TECHNICAL_ARCHITECTURE,
    MemoryExtractor,
)
from owlthread.primer.llm import LLMClient


class TestMemoryExtractor(unittest.TestCase):
    """Test suite for memory extractor."""

    def setUp(self):
        self.extractor = MemoryExtractor()

    def test_extraction_system_prompt_requirements(self):
        """Verify extraction prompt contains required instructions and 4 categories."""
        self.assertIn("You are OwlThread", EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("ambient memory engine for builders", EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("technical_architecture", EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("business_rules", EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("settled_decisions", EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("open_questions", EXTRACTION_SYSTEM_PROMPT)
        self.assertIn("strict JSON array", EXTRACTION_SYSTEM_PROMPT)

    def test_mock_llm_json_extraction(self):
        """Verify parser converts model JSON response into structured items."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_available.return_value = True
        mock_llm.chat_complete.return_value = json.dumps([
            {
                "action": "ADD", "quadrant": "technical_architecture",
                "summary": "SQLite configured with WAL mode and 30s timeout.",
                "source_snippet": "conn.execute('PRAGMA journal_mode=WAL;')"
            },
            {
                "action": "ADD", "quadrant": "business_rules",
                "summary": "Pro tier pricing fixed at $29 per month.",
                "source_snippet": "We agreed on $29/mo for Pro."
            }
        ])

        extractor = MemoryExtractor(llm_client=mock_llm)
        items = extractor.extract("conn.execute('PRAGMA journal_mode=WAL;')\nWe agreed on $29/mo for Pro.")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["quadrant"], QUAD_TECHNICAL_ARCHITECTURE)
        self.assertEqual(items[1]["quadrant"], QUAD_BUSINESS_RULES)
        self.assertEqual(items[0]["summary"], "SQLite configured with WAL mode and 30s timeout.")

    def test_empty_or_noise_capture_returns_empty_list(self):
        """Verify filler / greetings return empty list."""
        self.assertEqual(self.extractor.extract(""), [])
        self.assertEqual(self.extractor.extract("   "), [])
        self.assertEqual(self.extractor.extract("hello"), [])

    def test_heuristic_extraction_categories(self):
        """Verify rule-based fallback tags quadrants accurately."""
        dec_text = "We settled on using Stripe Checkout rather than custom elements."
        res_dec = self.extractor.heuristic_extract(dec_text)
        self.assertTrue(any(r["quadrant"] == QUAD_SETTLED_DECISIONS for r in res_dec))

        biz_text = "The monthly subscription pricing tier is set to 29 USD per month."
        res_biz = self.extractor.heuristic_extract(biz_text)
        self.assertTrue(any(r["quadrant"] == QUAD_BUSINESS_RULES for r in res_biz))

        quest_text = "Open question: decide later whether to use Redis or SQLite for queue."
        res_quest = self.extractor.heuristic_extract(quest_text)
        self.assertTrue(any(r["quadrant"] == QUAD_OPEN_QUESTIONS for r in res_quest))


if __name__ == "__main__":
    unittest.main()
