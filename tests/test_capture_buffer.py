"""Production SQLite capture buffering, restart recovery and explicit flushing."""
import tempfile
import unittest
from pathlib import Path
from owlthread.db.database import Database
from owlthread.extraction.pipeline import ExtractionPipeline

class TestCaptureBuffer(unittest.TestCase):
    def test_buffers_isolated_per_project_and_source(self):
        with tempfile.TemporaryDirectory() as temp, Database(str(Path(temp)/'memory.db')) as db:
            pipeline=ExtractionPipeline(db)
            pipeline.ingest_capture('Decision: Use SQLite WAL for durable writes.','cursor','A')
            pipeline.ingest_capture('Decision: Use PostgreSQL for account records.','cli','B')
            rows=db.execute_read('SELECT project_id,source_app FROM capture_buffer')
            self.assertEqual(len(rows),2)
            self.assertNotEqual(rows[0]['project_id'],rows[1]['project_id'])
            self.assertNotEqual(rows[0]['source_app'],rows[1]['source_app'])
    def test_pending_capture_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'memory.db')
            with Database(path) as db:
                db.insert_capture('Decision: Keep capture buffers in SQLite.','manual')
            with Database(path) as db:
                self.assertEqual(db.pending_count(),1)
                self.assertEqual(ExtractionPipeline(db).handle_done_signal()['total_extracted'],1)
    def test_flush_is_idempotent_and_retains_source(self):
        with tempfile.TemporaryDirectory() as temp, Database(str(Path(temp)/'memory.db')) as db:
            pipeline=ExtractionPipeline(db)
            source='Decision: Preserve capture source for audit history.'
            db.insert_capture(source,'manual')
            self.assertEqual(pipeline.handle_done_signal()['total_extracted'],1)
            self.assertEqual(pipeline.handle_done_signal()['total_extracted'],0)
            self.assertEqual(db.pending_count(),0)
            self.assertEqual(db.execute_read('SELECT raw_text FROM capture_buffer')[0]['raw_text'],source)
