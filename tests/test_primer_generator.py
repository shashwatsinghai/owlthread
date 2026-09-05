"""Unit tests for Primer Generator."""

import unittest
from unittest.mock import MagicMock

from owlthread.primer.generator import PRIMER_SYSTEM_PROMPT, PrimerGenerator
from owlthread.primer.llm import LLMClient


class TestPrimerGenerator(unittest.TestCase):
    """Test suite for primer compilation and prompt formatting."""

    def setUp(self):
        self.generator = PrimerGenerator()

    def test_system_prompt_content(self):
        """Verify primer-generation system prompt contains the exact specified text."""
        self.assertIn("OwlThread's Context Primer", PRIMER_SYSTEM_PROMPT)
        self.assertIn("dev_task", PRIMER_SYSTEM_PROMPT)
        self.assertIn("external_comms", PRIMER_SYSTEM_PROMPT)
        self.assertIn("status_query", PRIMER_SYSTEM_PROMPT)
        self.assertIn("other", PRIMER_SYSTEM_PROMPT)
        self.assertIn("ONLY use information from the provided memory entries. Never invent facts.", PRIMER_SYSTEM_PROMPT)

    def test_generate_insufficient_memory(self):
        """Verify empty memory returns clear notice without hallucinating."""
        res = self.generator.generate(
            user_request="integrate Stripe billing",
            intent_tag="dev_task",
            matched_entries=[]
        )
        self.assertIn("Insufficient memory recorded in OwlThread", res)

    def test_generate_dev_task_offline(self):
        """Verify dev_task synthesis formatting."""
        entries = [
            {
                "id": 1,
                "raw_text": "Selected Stripe Checkout over custom Elements for v1 MVP.",
                "source_app": "cursor",
                "timestamp": "2026-08-25T10:00:00Z",
                "quadrant": "decisions",
            }
        ]
        res = self.generator.generate(
            user_request="integrate Stripe billing",
            intent_tag="dev_task",
            matched_entries=entries
        )
        self.assertIn("Technical Brief", res)
        self.assertIn("Stripe Checkout", res)

    def test_generate_external_comms_offline(self):
        """Verify external_comms synthesis formatting."""
        entries = [
            {
                "id": 2,
                "raw_text": "Completed core prototype showing 10x speedup in context retrieval.",
                "source_app": "clipboard",
                "timestamp": "2026-08-25T11:00:00Z",
                "quadrant": "status",
            }
        ]
        res = self.generator.generate(
            user_request="I want to send this idea to an investor",
            intent_tag="external_comms",
            matched_entries=entries
        )
        self.assertIn("Executive Overview", res)
        self.assertIn("Narrative Summary", res)

    def test_generate_status_query_offline(self):
        """Verify status_query synthesis formatting."""
        entries = [
            {
                "id": 3,
                "raw_text": "Updated SQLite schema with WAL mode and connector indexing.",
                "source_app": "cli",
                "timestamp": "2026-08-25T11:30:00Z",
                "quadrant": "architecture",
            }
        ]
        res = self.generator.generate(
            user_request="audit new update",
            intent_tag="status_query",
            matched_entries=entries
        )
        self.assertIn("Status Query", res)
        self.assertIn("Direct Status Answer", res)

    def test_generate_with_mock_llm(self):
        """Verify LLM client invocation with system and user prompts."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_available.return_value = True
        mock_llm.chat_complete.return_value = "# Custom LLM Brief\nEverything is ready."

        gen = PrimerGenerator(llm_client=mock_llm)
        entries = [{"id": 1, "raw_text": "Test memory", "source_app": "test", "timestamp": "2026-08-25"}]
        
        res = gen.generate(
            user_request="integrate Stripe billing",
            intent_tag="dev_task",
            matched_entries=entries
        )
        self.assertEqual(res, "# Custom LLM Brief\nEverything is ready.")
        mock_llm.chat_complete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
