"""Behavioral checks for durability, races, boundaries and graceful degradation."""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from contextlib import closing
from unittest.mock import MagicMock,patch
from owlthread.security import local_token
from owlthread.db.database import DatabaseManager
from owlthread.extraction.pipeline import ExtractionPipeline
from owlthread.primer.llm import LLMClient
from owlthread.primer.engine import PrimerEngine
from owlthread.capture.server import LocalHttpListener
from owlthread.capture.connectors.vscode import VSCodeCopilotConnector
from owlthread.capture.clipboard import ClipboardWatcher


class Reliability(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name)/"reliability.db")
        self.db = DatabaseManager(self.path)
        self.db.set_setting("llm_provider","fallback")

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def test_concurrent_readers_writes_and_restart(self) -> None:
        def work(index: int) -> None:
            self.db.insert_capture(f"Decision: use local storage {index}","test")
            self.db.count_entries()
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(work,range(100)))
        self.assertEqual(self.db.pending_count(),100)
        self.db.close()
        self.db = DatabaseManager(self.path)
        self.assertEqual(self.db.pending_count(),100)
        self.assertEqual(self.db.execute_read("PRAGMA journal_mode")[0]["journal_mode"],"wal")

    def test_failed_write_does_not_kill_writer(self) -> None:
        with self.assertRaises(sqlite3.Error):
            self.db.execute_write("INSERT INTO missing_table VALUES (1)")
        self.assertGreater(self.db.insert_capture("still usable","test"),0)

    def test_legacy_database_upgrade_preserves_and_exposes_memories(self) -> None:
        path = str(Path(self.temp.name)/"legacy.db")
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript("""
                CREATE TABLE memory_entries (
                    id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, source_app TEXT NOT NULL,
                    raw_text TEXT NOT NULL, quadrant TEXT);
                INSERT INTO memory_entries VALUES(7,'2025-01-01T12:00:00+00:00','cursor','Use SQLite WAL','architecture');
                CREATE TABLE capture_buffer (
                    id INTEGER PRIMARY KEY, raw_text TEXT NOT NULL, source_app TEXT,
                    captured_at TEXT NOT NULL, processed INTEGER DEFAULT 0);
                INSERT INTO capture_buffer VALUES(3,'Decision: Keep audit history','manual','2025-01-02',0);
                CREATE TABLE settings (key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO settings VALUES('llm_provider','fallback');
            """)
        with DatabaseManager(path) as migrated:
            pid = migrated.get_or_create_project()
            entry = migrated.get_entries(project_id=pid)[0]
            self.assertEqual(entry["id"],7)
            self.assertEqual(entry["quadrant"],"technical_architecture")
            self.assertEqual(entry["summary"],"Use SQLite WAL")
            self.assertEqual(entry["created_at"],"2025-01-01T12:00:00+00:00")
            self.assertEqual(migrated.get_unprocessed_captures()[0]["project_id"],pid)
            self.assertEqual(ExtractionPipeline(migrated).handle_done_signal()["total_extracted"],1)
        with DatabaseManager(path) as reopened:
            self.assertEqual(reopened.count_entries(),2)
            self.assertEqual(reopened.pending_count(),0)

    def test_primer_is_copied_after_suppression_and_not_recaptured(self) -> None:
        self.db.insert_entry("SQLite uses WAL locally","manual")
        watcher = ClipboardWatcher(self.db)
        def copy(text: str) -> bool:
            self.assertEqual(self.db.get_setting("last_primer_clipboard_hash"),hashlib.sha256(text.encode()).hexdigest())
            with patch.object(watcher,"_read_clipboard",return_value=text):
                self.assertIsNone(watcher.poll())
            return True
        with patch("owlthread.primer.engine.copy_to_clipboard",side_effect=copy) as copied:
            result = PrimerEngine(self.db).generate_primer("fix SQLite locking",auto_copy=True)
        self.assertTrue(result.copied_to_clipboard)
        copied.assert_called_once_with(result.primer_text)
        self.assertEqual(self.db.pending_count(),0)

    @patch("owlthread.primer.engine.copy_to_clipboard",return_value=True)
    def test_status_samples_every_quadrant_and_counts_whole_project(self, copy: object) -> None:
        pid = self.db.get_or_create_project("Status test")
        other = self.db.get_or_create_project("Other project")
        for index in range(20):
            self.db.insert_entry(f"Architecture {index}","manual",pid)
        for quadrant in ("business_rules","settled_decisions","open_questions"):
            self.db.insert_entry("Unique "+quadrant,"manual",pid,quadrant=quadrant)
        self.db.insert_entry("Other project secret","manual",other)
        archived = self.db.insert_entry("Archived architecture","manual",pid)
        self.db.archive_entry(archived)
        result = PrimerEngine(self.db).generate_primer("current status",intent_override="status_query",project_id=pid)
        self.assertEqual(len(result.matched_entries),6)
        self.assertIn("Technical Architecture: 20",result.primer_text)
        self.assertIn("Open Questions: 1",result.primer_text)
        self.assertNotIn("Other project secret",result.primer_text)
        self.assertNotIn("Archived architecture",result.primer_text)

    @patch("owlthread.primer.engine.copy_to_clipboard",return_value=True)
    def test_done_reports_pending_failures_truthfully(self, copy: object) -> None:
        self.db.insert_capture("Decision: Keep local storage","manual")
        engine = PrimerEngine(self.db)
        with patch.object(engine.pipeline,"_commit",side_effect=sqlite3.OperationalError("disk full")):
            result = engine.generate_primer("done")
        self.assertIn("remain saved for retry",result.primer_text)
        self.assertNotIn("buffers were empty",result.primer_text)
        self.assertEqual(self.db.pending_count(),1)

    def test_invalid_project_is_rejected_without_deadlock(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.insert_entry("A valid fact","test",project_id=99999)
        self.assertEqual(self.db.count_entries(),0)

    def test_flush_from_different_instance_is_durable(self) -> None:
        ExtractionPipeline(self.db).ingest_capture("Decision: We chose SQLite WAL for local storage.","clipboard")
        with DatabaseManager(self.path) as second:
            result = ExtractionPipeline(second).handle_done_signal()
        self.assertEqual(result["total_extracted"],1)
        self.assertEqual(self.db.pending_count(),0)
        self.assertEqual(self.db.count_entries(),1)
        self.assertEqual(ExtractionPipeline(self.db).handle_done_signal()["batches_flushed"],0)

    def test_concurrent_flush_only_commits_once(self) -> None:
        self.db.insert_capture("Decision: use SQLite WAL locally.","manual")
        barrier = threading.Barrier(2)
        pipelines = [ExtractionPipeline(self.db),ExtractionPipeline(self.db)]
        for pipeline in pipelines:
            original = pipeline._actions
            def actions(text: str, existing: list, original: object = original) -> list:
                barrier.wait(timeout=5)
                return original(text,existing)
            pipeline._actions = actions
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda p:p.handle_done_signal(),pipelines))
        self.assertEqual(sum(r["total_extracted"] for r in results),1)
        self.assertEqual(self.db.count_entries(),1)

    def test_actions_and_checkpoints_are_one_transaction(self) -> None:
        pid = self.db.get_or_create_project()
        old = self.db.insert_entry("Use Redis","manual",pid,quadrant="technical_architecture")
        self.db.insert_capture("Use SQLite WAL. Free plan keeps data local","manual",pid)
        llm = MagicMock(spec=LLMClient)
        llm.is_available.return_value = True
        llm.chat_complete.return_value = json.dumps([
            {"action":"UPDATE","quadrant":"technical_architecture","summary":"Use SQLite WAL","source_snippet":"Use SQLite WAL","target_memory_id":old},
            {"action":"ADD","quadrant":"business_rules","summary":"Free plan keeps data local","source_snippet":"Free plan keeps data local"},
            {"action":"NOOP"}])
        result = ExtractionPipeline(self.db,llm).handle_done_signal()
        self.assertEqual(result["total_superseded"],1)
        self.assertEqual(self.db.get_entry_by_id(old)["status"],"superseded")
        self.assertEqual(self.db.pending_count(),0)
        self.assertEqual(len(self.db.get_entry_lineage(result["extracted_entries"][0]["entry_id"])),1)

    def test_failed_commit_preserves_capture_for_retry(self) -> None:
        self.db.insert_capture("Decision: Use SQLite WAL","manual")
        pipeline = ExtractionPipeline(self.db)
        with patch.object(pipeline,"_commit",side_effect=sqlite3.OperationalError("disk full")):
            result = pipeline.handle_done_signal()
        self.assertEqual(result["status"],"partial")
        self.assertEqual(self.db.pending_count(),1)
        self.assertEqual(pipeline.handle_done_signal()["total_extracted"],1)

    def test_batches_never_exceed_4000_characters(self) -> None:
        self.db.insert_capture("Decision: use local SQLite.\n"*700,"test")
        pipeline = ExtractionPipeline(self.db)
        lengths = []
        def actions(text: str, existing: list) -> list:
            lengths.append(len(text))
            return []
        pipeline._actions = actions
        result = pipeline.handle_done_signal()
        self.assertGreater(result["batches_flushed"],1)
        self.assertLessEqual(max(lengths),4000)
        self.assertEqual(sum(lengths),len("Decision: use local SQLite.\n"*700)-1)
        self.assertEqual(self.db.pending_count(),0)

    def test_clearing_credentials_and_custom_provider(self) -> None:
        client = LLMClient(provider="anthropic",api_key="old-key",base_url="https://example.com",model="old")
        self.db.set_setting("llm_provider","custom")
        self.db.set_setting("llm_api_key","")
        self.db.set_setting("llm_base_url","http://localhost:11434/v1")
        self.db.set_setting("llm_model","llama3")
        client.reload_from_db(self.db)
        self.assertEqual(client.api_key,"")
        self.assertTrue(client.is_available())
        self.db.set_setting("llm_provider","fallback")
        self.assertFalse(client.is_available())

    @patch("owlthread.primer.engine.copy_to_clipboard",return_value=False)
    def test_model_outage_still_returns_complete_brief(self, copy: object) -> None:
        self.db.insert_entry("SQLite uses WAL mode","manual",quadrant="technical_architecture")
        self.db.set_setting("llm_provider","ollama")
        client = LLMClient(provider="ollama")
        with patch.object(client,"_request",side_effect=RuntimeError("offline")):
            result = PrimerEngine(self.db,client).generate_primer("fix SQLite locking")
        self.assertIn("Relevant Architecture Decisions",result.primer_text)
        self.assertIn("WAL mode",result.primer_text)
        self.assertIn("Recommended Starting Point",result.primer_text)
        self.assertFalse(result.copied_to_clipboard)

    def test_partial_jsonl_and_restart_dedup(self) -> None:
        base = Path(self.temp.name)/"Code"/"User"
        path = base/"workspaceStorage"/"abc"/"chatSessions"/"one.jsonl"
        path.parent.mkdir(parents=True)
        raw = json.dumps({"kind":0,"v":{"requests":[{"message":{"text":"Decision: Use SQLite WAL"}}]}})
        path.write_text(raw[:30],encoding="utf-8")
        connector = VSCodeCopilotConnector(self.db,str(base))
        self.assertEqual(connector.poll(),0)
        path.write_text(raw+"\n",encoding="utf-8")
        self.assertEqual(connector.poll(),1)
        replacement = VSCodeCopilotConnector(self.db,str(base))
        self.assertEqual(replacement.poll(),0)
        path.write_text(raw.replace("SQLite WAL","Postgres")+"\n",encoding="utf-8")
        self.assertEqual(replacement.poll(),1)

    def test_http_validation_filters_and_retry_dedup(self) -> None:
        listener = LocalHttpListener(self.db,port=0)
        listener.start()
        try:
            url = f"http://127.0.0.1:{listener.port}"
            def post(path: str, payload: object) -> dict:
                req = urllib.request.Request(url+path,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+local_token(self.db)})
                with urllib.request.urlopen(req,timeout=5) as response:
                    return json.load(response)
            for payload in ([],{"text":5},{"text":""}):
                with self.assertRaises(urllib.error.HTTPError) as err:
                    post("/capture",payload)
                self.assertEqual(err.exception.code,400)
                err.exception.close()
            payload = {"text":"Decision: SQLite WAL is our local database","source":"browser_extension","dedup_key":"one"}
            post("/capture",payload)
            post("/capture",payload)
            self.assertEqual(self.db.pending_count(),1)
            post("/flush",{})
            with urllib.request.urlopen(urllib.request.Request(url+"/entries?quadrant=settled_decisions&limit=1",headers={"Authorization":"Bearer "+local_token(self.db)})) as response:
                self.assertEqual(json.load(response)["count"],1)
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(urllib.request.Request(url+"/entries?limit=-1",headers={"Authorization":"Bearer "+local_token(self.db)}))
            self.assertEqual(err.exception.code,400)
            err.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(urllib.request.Request(url+"/settings",headers={"Authorization":"Bearer "+local_token(self.db)}))
            self.assertEqual(err.exception.code,404)
            err.exception.close()
        finally:
            listener.stop()
