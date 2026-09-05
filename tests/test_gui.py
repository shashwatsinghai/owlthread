"""Unit tests for OwlThread Desktop GUI Application."""

import tempfile
import unittest
from pathlib import Path

from owlthread.db.database import Database
from owlthread.gui.app import OwlThreadDesktopApp
from owlthread.gui.feed_card import MemoryFeedCard


class TestDesktopGUI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_gui_owlthread.db"
        self.db = Database(str(self.db_path))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_gui_initialization_and_views(self):
        """Verify that the desktop application builds its layout, views, and cards cleanly."""
        # Insert a sample entry to verify card rendering
        self.db.insert_entry(
            raw_text="Stripe webhook billing architecture with signed tokens",
            source_app="browser",
            quadrant="technical_architecture",
            summary="Stripe Webhook Architecture",
            source_metadata={"url": "https://stripe.com/docs", "container_type": "user_selection"}
        )

        app = OwlThreadDesktopApp(db=self.db, port=41999, auto_start_engine=False)
        try:
            # Check views registered
            self.assertIn("live_feed", app.views)
            self.assertIn("quick_dump", app.views)
            self.assertIn("vault", app.views)
            self.assertIn("primer", app.views)
            self.assertIn("settings", app.views)

            # Check navigation
            app.show_view("quick_dump")
            self.assertEqual(app.current_view, "quick_dump")

            app.show_view("vault")
            self.assertEqual(app.current_view, "vault")

            app.show_view("live_feed")
            self.assertEqual(app.current_view, "live_feed")

            # Check card rendering
            app.refresh_feed()
            cards = [w for w in app.feed_scroll.winfo_children() if isinstance(w, MemoryFeedCard)]
            self.assertEqual(len(cards), 1)
            self.assertIn("Stripe Webhook Architecture", cards[0].entry["summary"])

            # Check sites view
            app.show_view("sites")
            self.assertEqual(app.current_view, "sites")

            # Check deleting entry
            app._handle_delete_entry(cards[0].entry["id"])
            self.assertEqual(self.db.count_entries(), 0)

        finally:
            app.destroy()
