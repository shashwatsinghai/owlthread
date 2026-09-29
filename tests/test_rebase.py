"""Production-path extraction, successor chains and transactional conflicts."""
import concurrent.futures
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from owlthread.db.database import Database
from owlthread.extraction.pipeline import ExtractionPipeline
from owlthread.primer.llm import LLMClient
from owlthread.primer.search import MemorySearcher


class TestRebaseEngine(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(str(Path(self.tmp.name)/"rebase.db"))
        self.pid=self.db.get_or_create_project()
        self.llm=MagicMock(spec=LLMClient)
        self.llm.is_available.return_value=True
        self.pipeline=ExtractionPipeline(self.db,self.llm)

    def tearDown(self):
        self.db.close();self.tmp.cleanup()

    def extract(self,actions,text="Decision: use SQLite WAL"):
        self.llm.chat_complete.return_value=json.dumps(actions)
        self.db.insert_capture(text,"manual",self.pid)
        return self.pipeline.handle_done_signal()

    def action(self,kind="ADD",target=None,text="Decision: use SQLite WAL",quadrant="settled_decisions"):
        return {"action":kind,"quadrant":quadrant,"summary":text,"source_snippet":text,
                "target_memory_id":target,"rationale":"Refinement" if kind=="UPDATE" else "Explicit replacement"}

    def test_add_then_normalized_duplicate(self):
        self.assertEqual(self.extract([self.action()])["total_extracted"],1)
        variant="decision:  use SQLite WAL."
        self.assertEqual(self.extract([self.action(text=variant)],variant)["total_extracted"],0)
        self.assertEqual(self.db.count_entries(),1)

    def test_noop_commits_checkpoint_without_memory(self):
        self.assertEqual(self.extract([{"action":"NOOP"}])["total_extracted"],0)
        self.assertEqual(self.db.pending_count(),0)

    def test_update_and_supersede_create_successors(self):
        self.extract([self.action()])
        old=self.db.get_entries()[0]["id"]
        for kind in ("UPDATE","SUPERSEDE"):
            text="Decision: use SQLite WAL "+kind
            result=self.extract([self.action(kind,old,text)],text)
            new=result["extracted_entries"][0]["entry_id"]
            self.assertNotEqual(new,old)
            self.assertEqual(self.db.get_entry_by_id(old)["superseded_by"],new)
            self.assertEqual(self.db.get_entry_lineage(new)[0]["predecessor_id"],old)
            self.assertEqual(self.db.count_entries(),1)
            old=new

    def test_long_chain_only_latest_in_search(self):
        self.extract([self.action()])
        old=self.db.get_entries()[0]["id"]
        for index in range(30):
            text=f"Decision: use SQLite WAL with revision {index}"
            result=self.extract([self.action("UPDATE",old,text)],text)
            old=result["extracted_entries"][0]["entry_id"]
        self.assertEqual(self.db.count_entries(include_history=True),31)
        self.assertEqual([r["id"] for r in MemorySearcher(self.db).search("SQLite")],[old])
        self.assertEqual(len(self.db.execute_read("SELECT * FROM memory_lineage")),30)

    def test_cross_project_target_rejected(self):
        other=self.db.get_or_create_project("Other")
        old=self.db.insert_entry("Other project","manual",other,quadrant="settled_decisions")
        result=self.extract([self.action("SUPERSEDE",old)])
        self.assertEqual(result["status"],"partial")
        self.assertEqual(self.db.pending_count(),1)
        self.assertEqual(self.db.count_entries(),1)

    def test_cross_quadrant_target_rejected(self):
        old=self.db.insert_entry("Architecture","manual",self.pid,quadrant="technical_architecture")
        self.assertEqual(self.extract([self.action("UPDATE",old)])["status"],"partial")
        self.assertEqual(self.db.count_entries(),1)

    def test_invalid_second_action_rolls_back_entire_slice(self):
        invalid=self.action();invalid["source_snippet"]="Not present"
        self.assertEqual(self.extract([self.action(),invalid])["status"],"partial")
        self.assertEqual(self.db.count_entries(),0)
        self.assertEqual(self.db.get_unprocessed_captures()[0]["processed_chars"],0)

    def test_missing_evidence_boolean_target_and_oversize_rejected(self):
        for change in ({"source_snippet":""},{"summary":"a"*241},{"action":"UPDATE","target_memory_id":True},{"confidence":"high"}):
            with self.subTest(change=change):
                result=self.extract([{**self.action(),**change}])
                self.assertEqual(result["status"],"partial")
                self.assertEqual(self.db.count_entries(),0)

    def test_low_confidence_is_skipped(self):
        result=self.extract([{**self.action(),"confidence":.5}])
        self.assertEqual(result["total_extracted"],0)
        self.assertEqual(self.db.pending_count(),0)

    def test_model_outage_and_invalid_json_remain_pending(self):
        self.db.insert_capture("Decision: keep audit history","manual")
        for response in ("not json","{}",'["not an action"]'):
            self.llm.chat_complete.return_value=response
            self.assertEqual(self.pipeline.handle_done_signal()["status"],"partial")
            self.assertEqual(self.db.pending_count(),1)
        self.llm.chat_complete.side_effect=RuntimeError("private provider response")
        result=self.pipeline.handle_done_signal()
        self.assertNotIn("private provider",json.dumps(result))
        self.assertEqual(self.db.get_unprocessed_captures()[0]["extraction_status"],"failed")

    def test_concurrent_conflicting_successors_one_wins_one_pending(self):
        old=self.db.insert_entry("Original","manual",self.pid,quadrant="settled_decisions")
        for index in range(2): self.db.insert_capture(f"Decision: revision {index}","manual",self.pid)
        captures=self.db.get_unprocessed_captures()
        barrier=threading.Barrier(2)
        def commit(capture):
            item=self.action("UPDATE",old,capture["raw_text"])
            barrier.wait()
            try: return self.pipeline._commit(capture,len(capture["raw_text"]),[item])
            except ValueError: return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(commit,captures))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.db.pending_count(),1)
        self.assertEqual(self.db.count_entries(),1)
        self.assertEqual(len(self.db.execute_read("SELECT * FROM memory_lineage")),1)
