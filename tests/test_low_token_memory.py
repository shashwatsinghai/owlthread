"""Focused regressions for cheap retrieval over durable raw and canonical memory."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

from owlthread.config import VALID_QUADRANTS
from owlthread.db.database import Database
from owlthread.primer.classifier import INTENT_DEV_TASK,IntentClassifier
from owlthread.primer.engine import PrimerEngine
from owlthread.primer.llm import LLMClient
from owlthread.primer.search import MemorySearcher


class LowTokenLargeMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.temp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.temp.name)/"memory.db")
        self.db=Database(self.path)
        self.pid=self.db.get_or_create_project("Builder")

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def test_raw_capture_is_searchable_without_successful_extraction(self) -> None:
        cid=self.db.insert_capture(
            "User plans a billing service. Assistant says signed webhook verification is mandatory.",
            "browser_extension",self.pid)
        searcher=MemorySearcher(self.db)
        rows=searcher.search_captures("signed webhook verification",project_id=self.pid)
        self.assertEqual([row["id"] for row in rows],[cid])
        context=searcher.search_context("build signed webhook billing",project_id=self.pid,char_budget=2000)
        self.assertIn(f"[C#{cid}]",context["context_text"])
        result=PrimerEngine(self.db).generate_primer(
            "I am going to build signed webhook billing",project_id=self.pid,auto_copy=False,context_char_budget=2000)
        self.assertIn(f"[C#{cid}]",result.primer_text)
        self.assertEqual(result.diagnostics["capture_matches"],1)

    def test_context_fans_across_more_than_twelve_memories(self) -> None:
        for quadrant in VALID_QUADRANTS:
            for index in range(4):
                self.db.insert_entry(f"Nebula {quadrant} fact {index}",project_id=self.pid,
                                     quadrant=quadrant,summary=f"Nebula {quadrant} fact {index}")
        context=MemorySearcher(self.db).search_context(
            "nebula",project_id=self.pid,per_quadrant_limit=4,capture_limit=0,char_budget=20_000)
        memories=[item for item in context["items"] if item["context_kind"]=="memory"]
        self.assertEqual(len(memories),16)
        self.assertEqual({item["quadrant"] for item in memories},set(VALID_QUADRANTS))
        self.assertLessEqual(context["chars_used"],context["char_budget"])
        self.assertTrue(all(item["citation"].startswith("[#") for item in memories))

    def test_context_enforces_hard_budget(self) -> None:
        for index in range(20):
            self.db.insert_entry("Budget marker "+str(index)+" "+("detail "*80),project_id=self.pid)
        context=MemorySearcher(self.db).search_context(
            "budget marker",project_id=self.pid,per_quadrant_limit=20,capture_limit=0,char_budget=700)
        self.assertLessEqual(len(context["context_text"]),700)
        self.assertTrue(context["truncated"])

    def test_hinglish_build_intent_is_local(self) -> None:
        llm=MagicMock(spec=LLMClient)
        llm.is_available.return_value=True
        classifier=IntentClassifier(llm)
        self.assertEqual(classifier.classify("Main ye billing system banane ja raha hoon"),INTENT_DEV_TASK)
        llm.chat_complete.assert_not_called()

    def test_persistent_cache_avoids_repeat_synthesis_and_invalidates_on_revision(self) -> None:
        first=self.db.insert_entry("Use SQLite WAL for the billing engine",project_id=self.pid,
                                   quadrant="technical_architecture")
        llm=MagicMock(spec=LLMClient)
        llm.provider="openai"
        llm.model="small-test-model"
        llm.is_available.return_value=True
        llm.chat_complete.return_value=f"# Context Primer\n\nSQLite WAL is recorded [#{first}]."
        one=PrimerEngine(self.db,llm).generate_primer(
            "I am going to build the SQLite billing engine",project_id=self.pid,auto_copy=False)
        two=PrimerEngine(self.db,llm).generate_primer(
            "I am going to build the SQLite billing engine",project_id=self.pid,auto_copy=False)
        self.assertFalse(one.diagnostics["cache_hit"])
        self.assertTrue(two.diagnostics["cache_hit"])
        self.assertEqual(llm.chat_complete.call_count,1)
        self.db.insert_entry("Billing engine requires signed webhooks",project_id=self.pid,
                             quadrant="business_rules")
        three=PrimerEngine(self.db,llm).generate_primer(
            "I am going to build the SQLite billing engine",project_id=self.pid,auto_copy=False)
        self.assertFalse(three.diagnostics["cache_hit"])
        self.assertEqual(llm.chat_complete.call_count,2)

    def test_auto_copy_false_never_touches_clipboard(self) -> None:
        self.db.insert_entry("Build API with FastAPI",project_id=self.pid)
        engine=PrimerEngine(self.db)
        with patch.object(engine,"_copy",return_value=True) as copy:
            result=engine.generate_primer("build FastAPI API",project_id=self.pid,auto_copy=False)
        copy.assert_not_called()
        self.assertFalse(result.copied_to_clipboard)

    def test_exact_capture_dedup_survives_restart_and_is_project_scoped(self) -> None:
        text="The user will build a durable local memory system."
        self.assertGreater(self.db.insert_capture(text,"browser_extension",self.pid),0)
        self.assertEqual(self.db.insert_capture(text,"browser_extension",self.pid),0)
        self.db.close()
        self.db=Database(self.path)
        pid=self.db.get_or_create_project("Builder")
        self.assertEqual(self.db.insert_capture(text,"browser_extension",pid),0)
        other=self.db.get_or_create_project("Other")
        self.assertGreater(self.db.insert_capture(text,"browser_extension",other),0)

    def test_clean_startup_does_not_fire_summary_update_trigger(self) -> None:
        self.db.insert_entry("Stable indexed summary",project_id=self.pid)
        def install_audit(conn: sqlite3.Connection) -> None:
            conn.executescript("""CREATE TABLE startup_update_audit(n INTEGER);
                CREATE TRIGGER audit_summary_update AFTER UPDATE OF summary ON memory_entries
                BEGIN INSERT INTO startup_update_audit VALUES(1); END;""")
        self.db.execute_write(install_audit)
        self.db.close()
        self.db=Database(self.path)
        self.assertEqual(self.db.execute_read("SELECT COUNT(*) AS n FROM startup_update_audit")[0]["n"],0)


if __name__ == "__main__":
    unittest.main()
