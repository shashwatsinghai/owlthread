"""Construct every Tk view and exercise user actions against an isolated database."""
from __future__ import annotations
import tempfile
import tkinter as tk
import unittest
import time
import threading
from pathlib import Path
from owlthread.db.database import Database
from owlthread.gui.app import OwlThreadApp
from owlthread.gui.feed_card import FeedCard


class TestDesktopGUI(unittest.TestCase):
    def test_event_loop_stays_responsive_during_slow_work(self):
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/'slow.db')) as db:
            app=OwlThreadApp(db=db,auto_start_engine=False)
            app.withdraw()
            release=threading.Event();ticks=[]
            try:
                app._job(lambda:release.wait(3),lambda _:None)
                app.after(30,lambda:ticks.append(True))
                deadline=time.monotonic()+.5
                while time.monotonic()<deadline and not ticks:
                    app.update();time.sleep(.005)
                self.assertTrue(ticks,'Tk timer must run while the worker is blocked')
            finally:
                release.set()
                for thread in app._workers:thread.join(3)
                app.destroy()

    def test_views_cards_settings_and_capture(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"gui.db")) as db:
            db.insert_entry(raw_text="Stripe uses signed webhooks",summary="Stripe Webhook Architecture",quadrant="technical_architecture")
            try:
                app = OwlThreadApp(db=db,auto_start_engine=False)
            except tk.TclError as exc:
                self.skipTest(f"Display unavailable: {exc}")
            app.withdraw()
            def drain():
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    app.update()
                    if not any(t.is_alive() for t in app._workers) and app._actions.empty():
                        return
                    time.sleep(.01)
                self.fail("Desktop worker did not settle")
            try:
                drain()
                for key in ("feed","search","quadrants","primer","capture","integrations","settings"):
                    app.show_view(key)
                    app.update_idletasks()
                    drain()
                    self.assertEqual(app.current_view,key)
                app.setting_vars["llm_provider"].set("ollama")
                app.setting_vars["llm_api_key"].set("")
                app._save_settings()
                drain()
                self.assertEqual(db.get_setting("llm_provider"),"ollama")
                app.show_view("capture")
                app.note.insert("1.0","We decided to retain local audit logs.")
                app._save_capture()
                drain()
                self.assertEqual(db.pending_count(),1)
                app.show_view("feed")
                cards = [w for w in app.feed_scroll.winfo_children() if isinstance(w,FeedCard)]
                self.assertEqual(len(cards),1)
                cards[0].toggle()
                self.assertTrue(cards[0].expanded)
                cards[0].action("archive")
                drain()
                self.assertEqual(db.count_entries(),0)
                app.open_primer()
                app.update_idletasks()
                app.open_primer()
                self.assertEqual(len(app._popups),1)
                self.assertEqual(app._popups[0].winfo_width(),400)
                panel = app._popups[0].panel
                self.assertTrue(panel.notice.winfo_ismapped())
                self.assertLessEqual(panel.notice.winfo_y()+panel.notice.winfo_height(),panel.winfo_height())
                app._popups[0].close()
                app.open_primer()
                self.assertEqual(len(app._popups),1)
                app._popups[0].close()
            finally:
                app.destroy()
