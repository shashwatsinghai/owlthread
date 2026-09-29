"""Unit tests for Intent Classifier in Primer Engine."""

import unittest
from unittest.mock import MagicMock

from owlthread.primer.classifier import (
    INTENT_DEV_TASK,
    INTENT_EXTERNAL_COMMS,
    INTENT_OTHER,
    INTENT_STATUS_QUERY,
    IntentClassifier,
)
from owlthread.primer.llm import LLMClient


class TestIntentClassifier(unittest.TestCase):
    """Test suite for intent classification."""

    def setUp(self):
        self.classifier = IntentClassifier()

    def test_heuristic_classification_dev_task(self):
        """Verify dev_task examples."""
        examples = [
            "integrate Stripe billing",
            "fix sqlite database lock issue",
            "refactor auth module and endpoints",
            "debug python test failure",
            "build new frontend UI component",
        ]
        for query in examples:
            intent = self.classifier.heuristic_classify(query)
            self.assertEqual(intent, INTENT_DEV_TASK, f"Failed for query: {query}")

    def test_heuristic_classification_external_comms(self):
        """Verify external_comms examples."""
        examples = [
            "I want to send this idea to an investor",
            "draft a pitch deck update for founders",
            "write customer newsletter announcement",
            "message to partner about partnership proposal",
        ]
        for query in examples:
            intent = self.classifier.heuristic_classify(query)
            self.assertEqual(intent, INTENT_EXTERNAL_COMMS, f"Failed for query: {query}")

    def test_heuristic_classification_status_query(self):
        """Verify status_query examples."""
        examples = [
            "audit new update",
            "what is the status of the capture engine",
            "how is the build progress",
            "check latest release overview",
        ]
        for query in examples:
            intent = self.classifier.heuristic_classify(query)
            self.assertEqual(intent, INTENT_STATUS_QUERY, f"Failed for query: {query}")

    def test_heuristic_classification_other(self):
        """Verify other category for arbitrary text."""
        examples = [
            "hello world",
            "random note about weather",
            "12345",
        ]
        for query in examples:
            intent = self.classifier.heuristic_classify(query)
            self.assertEqual(intent, INTENT_OTHER, f"Failed for query: {query}")

    def test_classify_with_mock_llm(self):
        """Verify ambiguous requests can still use LLM-based classification."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_available.return_value = True
        mock_llm.chat_complete.return_value = "dev_task"
        classifier = IntentClassifier(llm_client=mock_llm)

        result = classifier.classify("please categorize this request")
        self.assertEqual(result, INTENT_DEV_TASK)
        mock_llm.chat_complete.assert_called_once()

    def test_known_intent_does_not_spend_a_classifier_call(self):
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_available.return_value = True
        classifier = IntentClassifier(llm_client=mock_llm)
        self.assertEqual(classifier.classify("I am going to build a billing app"),INTENT_DEV_TASK)
        mock_llm.chat_complete.assert_not_called()

    def test_hinglish_build_intent(self):
        self.assertEqual(self.classifier.classify("Main ek billing app banane ja raha hoon"),INTENT_DEV_TASK)

    def test_empty_query(self):
        """Empty queries should return 'other'."""
        self.assertEqual(self.classifier.classify(""), INTENT_OTHER)
        self.assertEqual(self.classifier.classify("   "), INTENT_OTHER)


if __name__ == "__main__":
    unittest.main()
