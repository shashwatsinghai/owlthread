"""Unit tests for Local HTTP Listener."""

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from owlthread.capture.server import LocalHttpListener
from owlthread.db.database import Database


class TestHttpServer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp_dir.name) / "test_http.db"))
        # Use an ephemeral test port
        self.port = 41999
        self.listener = LocalHttpListener(self.db, port=self.port)
        self.listener.start()
        self.base_url = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.listener.stop()
        self.temp_dir.cleanup()

    def test_health_endpoint(self):
        req = urllib.request.Request(f"{self.base_url}/health")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "healthy")
            self.assertEqual(data["app"], "OwlThread")

    def test_cors_options(self):
        req = urllib.request.Request(f"{self.base_url}/capture", method="OPTIONS")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 204)
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
            self.assertIn("POST", resp.headers.get("Access-Control-Allow-Methods"))

    def test_post_capture_success(self):
        payload = {
            "text": "Captured selected text from webpage",
            "source_app": "browser",
            "url": "https://example.com/chat",
            "title": "Example Chat",
            "metadata": {"custom_tag": "test"}
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/capture",
            data=data_bytes,
            headers={"Content-Type": "application/json"}
        )

        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertIn("id", data)

        self.assertEqual(self.db.count_entries(source_app="browser"), 1)
        entry = self.db.get_entries(source_app="browser")[0]
        self.assertEqual(entry["raw_text"], "Captured selected text from webpage")
        self.assertEqual(entry["source_app"], "browser")
        self.assertIsNotNone(entry["quadrant"])
        self.assertIn("https://example.com/chat", entry["source_metadata"])

    def test_post_empty_payload_rejected(self):
        payload = {"text": "   "}
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/capture",
            data=data_bytes,
            headers={"Content-Type": "application/json"}
        )

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
