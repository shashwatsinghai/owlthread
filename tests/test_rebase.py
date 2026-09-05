"""Unit tests for Phase 2 Rebase (supersede logic)."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from owlthread.db.database import Database
from owlthread.extraction.rebase import REBASE_SYSTEM_PROMPT, RebaseEngine
from owlthread.primer.llm import LLMClient


class TestRebaseEngine(unittest.TestCase):
    """Test suite for rebase & supersede engine."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_rebase.db")
        self.db = Database(self.db_path)
        self.rebase_engine = RebaseEngine(self.db)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_rebase_system_prompt_requirements(self):
        """Verify rebase system prompt contains the specified instructions."""
        self.assertIn("You are the Epistemological Memory Rebase Engine for OwlThread", REBASE_SYSTEM_PROMPT)
        self.assertIn('"action": "ADD" | "UPDATE" | "SUPERSEDE" | "NOOP"', REBASE_SYSTEM_PROMPT)
        self.assertIn("SUPERSEDE: Candidate fact directly contradicts", REBASE_SYSTEM_PROMPT)

    def test_rebase_supersede_execution(self):
        """Verify that when a supersede match occurs, old record is marked superseded and new record is active."""
        pid = self.db.get_or_create_project("BillingApp")

        # 1. Insert existing active decision
        old_id = self.db.insert_entry(
            raw_text="Decision: Use PayPal for payments.",
            source_app="cursor",
            project_id=pid,
            quadrant="settled_decisions",
            summary="Decision: Use PayPal for payments.",
            status="active"
        )

        # Mock LLM to return supersede match
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_available.return_value = True
        mock_llm.chat_complete.return_value = json.dumps({
            "supersedes_id": old_id,
            "reason": "Replaced PayPal with Stripe."
        })

        engine = RebaseEngine(db=self.db, llm_client=mock_llm)
        new_item = {
            "quadrant": "settled_decisions",
            "summary": "Decision: Switched from PayPal to Stripe Checkout.",
            "source_snippet": "We migrated away from PayPal."
        }

        new_id, superseded_id = engine.process_item(
            project_id=pid,
            source_app="cursor",
            item=new_item
        )

        self.assertEqual(superseded_id, old_id)
        self.assertGreater(new_id, old_id)

        # Check old entry status
        old_entry = self.db.get_entry_by_id(old_id)
        self.assertEqual(old_entry["status"], "superseded")
        self.assertEqual(old_entry["superseded_by"], new_id)

        # Check new entry status
        new_entry = self.db.get_entry_by_id(new_id)
        self.assertEqual(new_entry["status"], "active")
        self.assertIsNone(new_entry["superseded_by"])

    def test_rebase_no_match_inserts_active(self):
        """Verify that non-matching items are inserted as active without modifying prior entries."""
        pid = self.db.get_or_create_project("AuthApp")

        id1 = self.db.insert_entry(
            raw_text="Use JWT tokens for auth.",
            source_app="cursor",
            project_id=pid,
            quadrant="technical_architecture",
            summary="Use JWT tokens for auth.",
            status="active"
        )

        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.is_available.return_value = True
        mock_llm.chat_complete.return_value = json.dumps({
            "supersedes_id": None,
            "reason": None
        })

        engine = RebaseEngine(db=self.db, llm_client=mock_llm)
        new_item = {
            "quadrant": "technical_architecture",
            "summary": "Database runs on port 5432.",
            "source_snippet": "postgres port 5432"
        }

        id2, superseded_id = engine.process_item(
            project_id=pid,
            source_app="cursor",
            item=new_item
        )

        self.assertIsNone(superseded_id)
        self.assertEqual(self.db.get_entry_by_id(id1)["status"], "active")
        self.assertEqual(self.db.get_entry_by_id(id2)["status"], "active")

    def test_pure_python_candidate_ranking_without_vector_db(self):
        """Verify candidate ranking ranks relevant active memories using pure Python lexical heuristics."""
        from owlthread.extraction.rebase import rank_candidates_pure_python

        memories = [
            {"id": i, "summary": f"Irrelevant configuration detail #{i}", "raw_text": "nothing"}
            for i in range(1, 25)
        ]
        memories.append({"id": 99, "summary": "Decision: Migrated database to PostgreSQL on port 5432", "raw_text": "postgresql database"})

        ranked = rank_candidates_pure_python(
            candidate_fact="Switched from PostgreSQL to SQLite for local storage.",
            existing_memories=memories,
            max_candidates=5
        )

        self.assertEqual(len(ranked), 5)
        # Entry #99 should be ranked first due to PostgreSQL overlap and supersede cue
        self.assertEqual(ranked[0]["id"], 99)

    def test_rebase_memory_add_action(self):
        """Verify rebase_memory performs ADD when no existing memories are present."""
        from owlthread.extraction.rebase import rebase_memory

        pid = self.db.get_or_create_project("PurePyApp")
        res = rebase_memory(
            db=self.db,
            project_id=pid,
            quadrant="business_rules",
            candidate_fact="Enterprise plan includes SSO and audit logs.",
            source_app="cursor",
        )

        self.assertEqual(res["action"], "ADD")
        self.assertIsNotNone(res["entry_id"])
        self.assertIsNone(res["target_memory_id"])
        self.assertEqual(res["quadrant"], "business_rules")

        entry = self.db.get_entry_by_id(res["entry_id"])
        self.assertEqual(entry["status"], "active")
        self.assertEqual(entry["summary"], "Enterprise plan includes SSO and audit logs.")
        self.assertEqual(entry["quadrant"], "business_rules")

    def test_rebase_memory_update_action(self):
        """Verify rebase_memory performs UPDATE in-place without generating a new ID."""
        from owlthread.extraction.rebase import rebase_memory
        from unittest.mock import patch

        pid = self.db.get_or_create_project("PurePyApp")
        orig_id = self.db.insert_entry(
            raw_text="Database uses SQLite.",
            source_app="cursor",
            project_id=pid,
            quadrant="technical_architecture",
            summary="Database uses SQLite.",
            status="active"
        )

        mock_ollama_json = json.dumps({
            "action": "UPDATE",
            "target_memory_id": orig_id,
            "statement": "Database uses SQLite configured with PRAGMA journal_mode=WAL and busy_timeout=5000.",
            "conflict_rationale": None
        })

        with patch("owlthread.extraction.rebase.call_ollama_chat", return_value=mock_ollama_json):
            res = rebase_memory(
                db=self.db,
                project_id=pid,
                quadrant="technical_architecture",
                candidate_fact="Database uses SQLite with WAL mode and 5000ms busy timeout.",
            )

        self.assertEqual(res["action"], "UPDATE")
        self.assertEqual(res["entry_id"], orig_id)
        self.assertEqual(res["target_memory_id"], orig_id)

        # Database record should be updated in-place
        updated = self.db.get_entry_by_id(orig_id)
        self.assertEqual(updated["status"], "active")
        self.assertIn("PRAGMA journal_mode=WAL", updated["summary"])

    def test_rebase_memory_supersede_action_and_lineage(self):
        """Verify rebase_memory performs SUPERSEDE: predecessor marked superseded, successor active, lineage recorded."""
        from owlthread.extraction.rebase import rebase_memory
        from unittest.mock import patch

        pid = self.db.get_or_create_project("PurePyApp")
        old_id = self.db.insert_entry(
            raw_text="Team decision: Use React and Redux.",
            source_app="cursor",
            project_id=pid,
            quadrant="settled_decisions",
            summary="Team decision: Use React and Redux.",
            status="active"
        )

        mock_ollama_json = json.dumps({
            "action": "SUPERSEDE",
            "target_memory_id": old_id,
            "statement": "Decision: Migrated from Redux to Zustand for lightweight state management.",
            "conflict_rationale": "Redux boilerplate was excessive; Zustand selected for simplicity."
        })

        with patch("owlthread.extraction.rebase.call_ollama_chat", return_value=mock_ollama_json):
            res = rebase_memory(
                db=self.db,
                project_id=pid,
                quadrant="settled_decisions",
                candidate_fact="Switched from Redux to Zustand for state management.",
            )

        self.assertEqual(res["action"], "SUPERSEDE")
        new_id = res["entry_id"]
        self.assertGreater(new_id, old_id)

        # Predecessor verification
        old_entry = self.db.get_entry_by_id(old_id)
        self.assertEqual(old_entry["status"], "superseded")
        self.assertEqual(old_entry["superseded_by"], new_id)

        # Successor verification
        new_entry = self.db.get_entry_by_id(new_id)
        self.assertEqual(new_entry["status"], "active")
        self.assertIsNone(new_entry["superseded_by"])

        # Lineage graph verification
        lineage = self.db.get_entry_lineage(new_id)
        self.assertEqual(len(lineage), 1)
        self.assertEqual(lineage[0]["predecessor_id"], old_id)
        self.assertEqual(lineage[0]["conflict_rationale"], "Redux boilerplate was excessive; Zustand selected for simplicity.")

    def test_rebase_memory_noop_action(self):
        """Verify rebase_memory performs NOOP on duplicate facts without modifying the database."""
        from owlthread.extraction.rebase import rebase_memory
        from unittest.mock import patch

        pid = self.db.get_or_create_project("PurePyApp")
        entry_id = self.db.insert_entry(
            raw_text="Open Question: Evaluate tRPC vs GraphQL.",
            source_app="cursor",
            project_id=pid,
            quadrant="open_questions",
            summary="Open Question: Evaluate tRPC vs GraphQL.",
            status="active"
        )

        mock_ollama_json = json.dumps({
            "action": "NOOP",
            "target_memory_id": entry_id,
            "statement": "Open Question: Evaluate tRPC vs GraphQL.",
            "conflict_rationale": None
        })

        with patch("owlthread.extraction.rebase.call_ollama_chat", return_value=mock_ollama_json):
            res = rebase_memory(
                db=self.db,
                project_id=pid,
                quadrant="open_questions",
                candidate_fact="We still need to evaluate tRPC vs GraphQL.",
            )

        self.assertEqual(res["action"], "NOOP")
        self.assertIsNone(res["entry_id"])
        self.assertEqual(res["target_memory_id"], entry_id)

        # Database record should remain active and unchanged
        entry = self.db.get_entry_by_id(entry_id)
        self.assertEqual(entry["status"], "active")
        self.assertIsNone(entry["superseded_by"])

    def test_mem0_delete_mapping_to_supersede(self):
        """Verify that if an LLM responds with Mem0 DELETE format, it maps gracefully to SUPERSEDE."""
        from owlthread.extraction.rebase import rebase_memory
        from unittest.mock import patch

        pid = self.db.get_or_create_project("PurePyApp")
        old_id = self.db.insert_entry(
            raw_text="Billing: Flat pricing at $20/mo.",
            source_app="cursor",
            project_id=pid,
            quadrant="business_rules",
            summary="Flat pricing at $20/mo.",
            status="active"
        )

        # Mem0 returns "DELETE" when facts contradict
        mem0_response = json.dumps({
            "action": "DELETE",
            "target_memory_id": old_id,
            "statement": "Switched to usage-based pricing at $0.002 per event.",
            "conflict_rationale": "Contradicts flat monthly pricing."
        })

        with patch("owlthread.extraction.rebase.call_ollama_chat", return_value=mem0_response):
            res = rebase_memory(
                db=self.db,
                project_id=pid,
                quadrant="business_rules",
                candidate_fact="Switched to usage-based pricing at $0.002 per event.",
            )

        self.assertEqual(res["action"], "SUPERSEDE")
        self.assertEqual(self.db.get_entry_by_id(old_id)["status"], "superseded")
        self.assertEqual(self.db.get_entry_by_id(res["entry_id"])["status"], "active")


if __name__ == "__main__":
    unittest.main()
