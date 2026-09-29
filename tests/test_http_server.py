"""Unit tests for Local HTTP Listener."""

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

from owlthread.capture.server import LocalHttpListener
from owlthread.security import local_token
from owlthread.db.database import Database


class TestHttpServer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp_dir.name) / "test_http.db"))
        # Use an ephemeral test port
        self.port = 41999
        self.listener = LocalHttpListener(self.db, port=self.port)
        self.listener.start()
        self.db.set_setting("authorized_origins",json.dumps(["chrome-extension://"+"a"*32]))
        self.base_url = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.listener.stop()
        self.db.close()
        self.temp_dir.cleanup()

    def test_health_endpoint(self):
        req = urllib.request.Request(f"{self.base_url}/health")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["app"], "OwlThread")

    def test_cors_options(self):
        req = urllib.request.Request(f"{self.base_url}/capture", method="OPTIONS",headers={"Origin":"chrome-extension://"+"a"*32,"Access-Control-Request-Method":"POST"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "chrome-extension://"+"a"*32)
            self.assertIn("POST", resp.headers.get("Access-Control-Allow-Methods"))

    def test_post_capture_success(self):
        payload = {
            "text": "Captured selected text from webpage",
            "source_app": "browser_extension",
            "url": "https://example.com/chat",
            "title": "Example Chat",
            "metadata": {"custom_tag": "test"}
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/capture",
            data=data_bytes,
            headers={"Content-Type": "application/json", "Authorization":"Bearer "+local_token(self.db)}
        )

        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertIn("id", data)

        self.assertEqual(len([c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "browser_extension"]), 1)
        entry = [c for c in self.db.get_unprocessed_captures(100) if c["source_app"] == "browser_extension"][0]
        self.assertEqual(entry["raw_text"], "Captured selected text from webpage")
        self.assertEqual(entry["source_app"], "browser_extension")
        self.assertEqual(self.db.count_entries(), 0)
        self.assertIn("https://example.com/chat", entry["source_metadata"])

    def test_post_empty_payload_rejected(self):
        payload = {"text": "   "}
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/capture",
            data=data_bytes,
            headers={"Content-Type": "application/json", "Authorization":"Bearer "+local_token(self.db)}
        )

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_page_context_is_on_demand_and_does_not_create_a_capture(self):
        self.listener._server.page_intelligence.describe_page = MagicMock(return_value={
            "summary":"Documentation about local memory.","page_kind":"docs","useful":True,"intelligence":"model"})
        payload = {"url":"https://docs.example.com/local-memory","title":"Local memory documentation",
                   "selection":"","visible_text":"Visible transcript"}
        req = urllib.request.Request(f"{self.base_url}/context",data=json.dumps(payload).encode(),
                                     headers={"Content-Type":"application/json","Authorization":"Bearer "+local_token(self.db)})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        self.assertEqual(data["page_kind"],"docs")
        self.assertEqual(self.db.pending_count(),0)
        self.listener._server.page_intelligence.describe_page.assert_called_once_with(payload)

    def test_hard_blocked_site_is_rejected_for_context_and_capture(self):
        for path,payload in (("context",{"url":"https://m.youtube.com/watch?v=abc","title":"Video",
                                         "selection":"","visible_text":"Should not be read"}),
                             ("capture",{"url":"https://open.spotify.com/track/abc","title":"Music",
                                         "text":"Should not be stored","source":"browser_extension"})):
            req = urllib.request.Request(f"{self.base_url}/{path}",data=json.dumps(payload).encode(),
                headers={"Content-Type":"application/json","Authorization":"Bearer "+local_token(self.db)})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code,400)
        self.assertEqual(self.db.pending_count(),0)

    def test_smart_capture_skips_noise_before_database_storage(self):
        self.listener._server.page_intelligence.assess_capture = MagicMock(return_value={
            "important":False,"reason":"Generic filler","intelligence":"model"})
        payload = {"text":"Sure, happy to help!","source":"browser_extension","capture_mode":"automatic",
                   "url":"https://chatgpt.com/c/one","title":"Chat"}
        req = urllib.request.Request(f"{self.base_url}/capture-smart",data=json.dumps(payload).encode(),
                                     headers={"Content-Type":"application/json","Authorization":"Bearer "+local_token(self.db)})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        self.assertFalse(data["accepted"])
        self.assertEqual(self.db.pending_count(),0)

    def test_smart_capture_stores_model_approved_context(self):
        self.listener._server.page_intelligence.assess_capture = MagicMock(return_value={
            "important":True,"reason":"Durable decision","intelligence":"model"})
        payload = {"text":"Decision: use a local write queue.","source":"browser_extension","capture_mode":"automatic",
                   "url":"https://chatgpt.com/c/two","title":"Architecture chat"}
        req = urllib.request.Request(f"{self.base_url}/capture-smart",data=json.dumps(payload).encode(),
                                     headers={"Content-Type":"application/json","Authorization":"Bearer "+local_token(self.db)})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        self.assertTrue(data["accepted"])
        self.assertEqual(self.db.pending_count(),1)


if __name__ == "__main__":
    unittest.main()
