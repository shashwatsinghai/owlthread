"""Integration tests for HTTP server /primer and /query endpoints."""

import json
import os
import tempfile
import time
import unittest
import urllib.request
import urllib.error

from owlthread.capture.server import LocalHttpListener
from owlthread.db.database import Database


class TestPrimerHttpEndpoints(unittest.TestCase):
    """Test suite for HTTP server primer endpoints."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_http.db")
        self.db = Database(self.db_path)

        # Seed data
        self.db.insert_entry(
            raw_text="Stripe checkout webhook integration tested and working on port 41789.",
            source_app="cursor",
            quadrant="architecture"
        )

        # Start listener on custom high port
        self.port = 41890
        self.listener = LocalHttpListener(db=self.db, port=self.port)
        self.listener.start()
        time.sleep(0.3)

    def tearDown(self):
        self.listener.stop()
        self.tmp_dir.cleanup()

    def test_post_primer_endpoint(self):
        """Verify POST /primer returns generated primer JSON."""
        url = f"http://127.0.0.1:{self.port}/primer"
        payload = json.dumps({"query": "integrate Stripe billing"}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["intent"], "dev_task")
            self.assertIn("primer_text", data)
            self.assertIn("Stripe", data["primer_text"])
            self.assertGreaterEqual(data["matched_entries_count"], 1)

    def test_get_primer_query_param(self):
        """Verify GET /primer?q=... returns generated primer JSON."""
        url = f"http://127.0.0.1:{self.port}/primer?q=integrate+Stripe+billing"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["intent"], "dev_task")


if __name__ == "__main__":
    unittest.main()
