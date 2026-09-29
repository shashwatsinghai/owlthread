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
        self.assertIn("ONLY use the supplied memories", PRIMER_SYSTEM_PROMPT)
        self.assertIn("untrusted data", PRIMER_SYSTEM_PROMPT)

    def test_generate_insufficient_memory(self):
        """Verify empty memory returns clear notice without hallucinating."""
        res = self.generator.generate(
            user_request="integrate Stripe billing",
            intent_tag="dev_task",
            matched_entries=[]
        )
        self.assertIn("Insufficient memory", res)

    def test_generate_dev_task_offline(self):
        """Verify dev_task synthesis formatting."""
        entries = [
            {
                "id": 1,
                "raw_text": "Selected Stripe Checkout over custom Elements for v1 MVP.",
                "source_app": "cursor",
                "timestamp": "2026-08-25T10:00:00Z",
                "quadrant": "settled_decisions",
            }
        ]
        res = self.generator.generate(
            user_request="integrate Stripe billing",
            intent_tag="dev_task",
            matched_entries=entries
        )
        self.assertIn("Relevant Architecture Decisions", res)
        self.assertIn("Stripe Checkout", res)

    def test_generate_external_comms_offline(self):
        """Verify external_comms synthesis formatting."""
        entries = [
            {
                "id": 2,
                "raw_text": "Completed core prototype showing 10x speedup in context retrieval.",
                "source_app": "clipboard",
                "timestamp": "2026-08-25T11:00:00Z",
                "quadrant": "open_questions",
            }
        ]
        res = self.generator.generate(
            user_request="I want to send this idea to an investor",
            intent_tag="external_comms",
            matched_entries=entries
        )
        self.assertIn("Current Project Status", res)
        self.assertIn("Key Achievements & Milestones", res)

    def test_generate_status_query_offline(self):
        """Verify status_query synthesis formatting."""
        entries = [
            {
                "id": 3,
                "raw_text": "Updated SQLite schema with WAL mode and connector indexing.",
                "source_app": "cli",
                "timestamp": "2026-08-25T11:30:00Z",
                "quadrant": "technical_architecture",
            }
        ]
        res = self.generator.generate(
            user_request="audit new update",
            intent_tag="status_query",
            matched_entries=entries
        )
        self.assertIn("Technical Architecture", res)
        self.assertIn("Open Questions", res)

    def test_generate_with_mock_llm(self):
        """Verify LLM client invocation with system and user prompts."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_available.return_value = True
        mock_llm.chat_complete.return_value = "# Custom LLM Brief\nTest memory [#1]."

        gen = PrimerGenerator(llm_client=mock_llm)
        entries = [{"id": 1, "raw_text": "Test memory", "source_app": "test", "timestamp": "2026-08-25"}]
        
        res = gen.generate(
            user_request="integrate Stripe billing",
            intent_tag="dev_task",
            matched_entries=entries
        )
        self.assertEqual(res, "# Custom LLM Brief\nTest memory [#1].")
        mock_llm.chat_complete.assert_called_once()

    def test_unknown_citations_and_unbounded_briefs_use_local_evidence(self):
        mock_llm=MagicMock(spec=LLMClient)
        mock_llm.is_available.return_value=True
        gen=PrimerGenerator(mock_llm)
        entries=[{'id':1,'summary':'Use SQLite WAL','quadrant':'technical_architecture'}]
        for text in ('Unsupported statement [#999]','Uncited statement','word '*501+'[#1]'):
            mock_llm.chat_complete.return_value=text
            brief=gen.generate('SQLite task','dev_task',entries)
            self.assertIn('Local synthesis',brief)
            self.assertIn('Use SQLite WAL',brief)


if __name__ == "__main__":
    unittest.main()
