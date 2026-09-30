"""Real local transport receipts, project isolation and protected connector keys."""
import http.client
import json
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from owlthread.capture.engine import CaptureEngine
from owlthread.db.database import Database
from owlthread.security import local_token


class TransferDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/"memory.db"
        self.db = Database(str(self.path))
        self.db.set_setting("llm_provider", "fallback")
        self.engine = CaptureEngine(self.db, http_port=0, enable_clipboard=False, enable_connectors=False)
        self.engine.start()
        self.token = local_token(self.db)

    def tearDown(self):
        self.engine.stop()
        self.db.close()
        self.temp.cleanup()

    def call(self, path, payload=None):
        with closing(http.client.HTTPConnection("127.0.0.1", self.engine.http_listener.port, timeout=3)) as client:
            client.request("GET" if payload is None else "POST", path,
                body=None if payload is None else json.dumps(payload),
                headers={"Authorization":"Bearer "+self.token, "Content-Type":"application/json"})
            response = client.getresponse()
            return response.status, json.loads(response.read())

    def test_receipt_is_visible_before_extraction_and_duplicate_does_not_notify(self):
        events = []
        self.engine.add_capture_callback(events.append)
        payload = {"text":"Decision: keep transport evidence local", "source":"browser_extension",
                   "project":"Browser", "dedup_key":"browser-one"}
        self.assertEqual(self.call("/capture",payload)[1]["stage"],"buffered")
        self.assertEqual(self.call("/capture",payload)[1]["stage"],"duplicate")
        self.assertEqual(len(events),1)
        status = self.call("/status")[1]
        self.assertEqual(status["total_entries"],0)
        self.assertEqual(status["capture_transfer"]["browser_captures"],1)
        self.assertEqual(status["capture_transfer"]["browser_pending"],1)
        self.assertTrue(status["capture_transfer"]["last_browser_capture_at"])
        self.assertNotIn(payload["text"],json.dumps(status))
        self.assertNotIn(self.token,json.dumps(status))
        self.call("/flush",{})
        status = self.call("/status")[1]
        self.assertEqual(status["capture_transfer"]["browser_captures"],1)
        self.assertEqual(status["capture_transfer"]["browser_pending"],0)
        self.assertGreater(status["total_entries"],0)

    def test_project_receive_status_detects_other_process_and_failed_extraction(self):
        a = self.db.get_or_create_project("A")
        b = self.db.get_or_create_project("B")
        with Database(str(self.path)) as producer:
            cid = producer.insert_capture("External browser raw note","browser_extension",a)
            producer.execute_write("UPDATE capture_buffer SET extraction_status='failed' WHERE id=?",(cid,))
            producer.insert_capture("Other project note","manual",b)
        status = self.db.capture_status(a)
        self.assertEqual(status["total_captures"],1)
        self.assertEqual(status["pending_captures"],1)
        self.assertEqual(status["failed_captures"],1)
        self.assertEqual(status["last_capture_source"],"browser_extension")
        self.assertEqual(self.db.capture_status(b)["browser_captures"],0)
        self.assertEqual(self.db.capture_status()["total_captures"],2)
        for invalid in (0,-1,True,"A"):
            with self.assertRaises(ValueError):self.db.capture_status(invalid)

    def test_pairing_count_handles_malformed_and_repeated_origins(self):
        origin="chrome-extension://"+"a"*32
        self.db.set_setting("authorized_origins",json.dumps([origin,origin,"https://example.com",3]))
        self.assertEqual(self.engine.status()["authorized_browser_count"],1)
        self.db.set_setting("authorized_origins","{}")
        self.assertEqual(self.engine.status()["authorized_browser_count"],0)

    def test_integration_credentials_are_protected_and_unreadable_values_preserved(self):
        key="integration_credential:cloudflare"
        self.db.set_setting(key,"fixture-provider-token")
        raw = self.db.execute_read("SELECT value FROM settings WHERE key=?",(key,))[0]["value"]
        if sys.platform=="win32":
            self.assertTrue(raw.startswith("dpapi:"))
            self.assertNotIn("fixture-provider-token",raw)
        self.assertEqual(self.db.get_setting(key),"fixture-provider-token")
        self.assertNotIn(key,self.db.get_all_settings())
        self.db.execute_write("UPDATE settings SET value='dpapi:invalid' WHERE key=?",(key,))
        self.assertEqual(self.db.get_setting(key),"")
        self.assertIn(key,self.db.unavailable_secret_settings)
        self.assertEqual(self.db.execute_read("SELECT value FROM settings WHERE key=?",(key,))[0]["value"],"dpapi:invalid")
        self.db.set_setting(key,"replacement")
        self.assertEqual(self.db.get_setting(key),"replacement")


if __name__=="__main__":unittest.main()
