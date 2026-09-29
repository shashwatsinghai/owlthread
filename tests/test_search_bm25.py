import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from owlthread.db.database import Database
from owlthread.primer.search import MemorySearcher


class BM25Search(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(str(Path(self.tmp.name)/"search.db"))
        self.search=MemorySearcher(self.db)
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def test_old_relevant_beats_new_weak(self):
        old=self.db.insert_entry("SQLite WAL checkpoint authentication rotation",timestamp=(datetime.now(timezone.utc)-timedelta(days=1000)).isoformat())
        self.db.insert_entry("authentication overview unrelated concepts")
        self.assertEqual(self.search.search("SQLite WAL checkpoint authentication rotation")[0]["id"],old)
    def test_phrase_and_synonym_limit(self):
        match=self.db.insert_entry("Use write ahead logging for local durability")
        self.db.insert_entry("Logging ahead of the next write")
        self.assertEqual([r["id"] for r in self.search.search('"write ahead logging"')],[match])
        self.assertEqual(self.search.search("persistent"),[])
    def test_stable_bounded_large_dataset(self):
        def seed(conn):
            for i in range(2000):
                conn.execute("INSERT INTO memory_entries(quadrant,summary,raw_text,project_id,created_at,updated_at) VALUES('technical_architecture',?,?,1,'2026-01-01','2026-01-01')",(f"SQLite checkpoint {i}","SQLite checkpoint"))
        self.db.execute_write(seed)
        first=self.search.search("checkpoint",limit=12)
        second=self.search.search("checkpoint",limit=12)
        self.assertEqual([r["id"] for r in first],[r["id"] for r in second])
        self.assertEqual(len(first),12)
        self.assertTrue(all(r["bm25_score"]>0 and r["citation"] for r in first))
    def test_fts_tracks_edit_delete_and_restart(self):
        eid=self.db.insert_entry("SQLite original")
        self.db.update_entry_statement(eid,"Redis successor")
        self.assertEqual(self.search.search("SQLite"),[])
        self.assertEqual(len(self.search.search("SQLite",include_history=True)),1)
        self.db.delete_entry(eid)
        self.assertEqual(self.search.search("SQLite",include_history=True),[])
        path=str(self.db.db_path);self.db.close();self.db=Database(path);self.search=MemorySearcher(self.db)
        self.assertEqual(len(self.search.search("Redis")),1)
    def test_fts_operators_are_untrusted_terms(self):
        self.db.insert_entry("Safe SQLite database")
        for query in ('"',"OR NOT NEAR()",'sqlite" OR 1=1 --'):
            self.search.search(query)
    def test_project_quadrant_and_empty_query(self):
        a=self.db.get_or_create_project("A");b=self.db.get_or_create_project("B")
        eid=self.db.insert_entry("SQLite A",project_id=a,quadrant="business_rules")
        self.db.insert_entry("SQLite B",project_id=b)
        self.assertEqual([r["id"] for r in self.search.search("",project_id=a)],[eid])
        self.assertEqual(self.search.search("SQLite",project_id=a,quadrant="open_questions"),[])
