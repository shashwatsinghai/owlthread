"""Construct every Tk view and exercise user actions against an isolated database."""
from __future__ import annotations
import tempfile
import tkinter as tk
import unittest
import time
import threading
import gc
from unittest.mock import patch
from pathlib import Path
from owlthread.db.database import Database
from owlthread.gui.app import OwlThreadApp
from owlthread.gui.feed_card import FeedCard, CaptureCard


class TestDesktopGUI(unittest.TestCase):
    def tearDown(self) -> None:
        # Collect closed Tk widget/variable cycles on the creating thread.
        gc.collect()

    def _drain(self, app: OwlThreadApp, timeout: float = 5) -> None:
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            app.update()
            if not any(t.is_alive() for t in app._workers) and app._actions.empty(): return
            time.sleep(.01)
        self.fail("Desktop worker did not settle")

    def test_external_browser_capture_appears_without_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/"external.db")
            with Database(path) as db, Database(path) as producer:
                app=OwlThreadApp(db=db,auto_start_engine=False)
                app.withdraw()
                try:
                    self._drain(app)
                    cid=producer.insert_capture("Assistant: Use signed webhook events before processing payments.","browser_extension",source_metadata={"title":"Webhook design","url":"https://chatgpt.com/c/synthetic"})
                    deadline=time.monotonic()+4
                    while time.monotonic()<deadline and not app._captures:
                        app.update();time.sleep(.01)
                    self.assertEqual(app._counts,(0,1))
                    cards=[w for w in app.feed_scroll.winfo_children() if isinstance(w,CaptureCard)]
                    self.assertEqual([card.capture["id"] for card in cards],[cid])
                    self.assertIn("Last browser capture",app.browser_status.cget("text"))
                    self.assertIn("Webhook design",cards[0].source_details.cget("text"))
                    cards[0].toggle()
                    self.assertTrue(cards[0].expanded)
                    self.assertEqual(cards[0].detail.get("1.0","end-1c"),app._captures[0]["raw_text"])
                    self.assertEqual(db.count_entries(),0,"Receive must not be presented as an extracted memory")
                finally:
                    self._drain(app);app.destroy()

    def test_receive_refresh_preserves_drafts_and_project_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"drafts.db")) as db:
            other=db.get_or_create_project("Other")
            db.insert_capture("Other project note","manual",other)
            app=OwlThreadApp(db=db,auto_start_engine=False)
            app.withdraw()
            try:
                self._drain(app)
                self.assertEqual(app._counts[1],0)
                app.show_view("capture")
                app.note.insert("1.0","Unsaved note draft")
                db.insert_capture("New browser turn","browser_extension",app._pid())
                app._request_refresh();self._drain(app)
                self.assertEqual(app.note.get("1.0","end-1c"),"Unsaved note draft")
                app.show_view("settings")
                app.setting_vars["llm_model"].set("unsaved-model")
                db.insert_capture("Another browser turn","browser_extension",app._pid())
                app._request_refresh();self._drain(app)
                self.assertEqual(app.setting_vars["llm_model"].get(),"unsaved-model")
                self.assertEqual(app._counts[1],2)
            finally:
                self._drain(app);app.destroy()

    def test_search_updates_when_another_process_adds_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"search.db")) as db:
            app=OwlThreadApp(db=db,auto_start_engine=False)
            app.withdraw()
            try:
                self._drain(app);app.show_view("search");self._drain(app)
                db.insert_entry(raw_text="Webhook signatures require verification",summary="Webhook signature validation",quadrant="technical_architecture",project_id=app._pid())
                app._request_refresh();self._drain(app)
                cards=[w for w in app.search_results.winfo_children() if isinstance(w,FeedCard)]
                self.assertEqual(len(cards),1)
            finally:
                self._drain(app);app.destroy()

    def test_connect_save_import_and_disconnect_keep_credentials_masked(self) -> None:
        from owlthread.integrations.context import ContextConnectorService
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"connect.db")) as db:
            app=OwlThreadApp(db=db,auto_start_engine=False)
            app.withdraw()
            try:
                self._drain(app);app.show_view("integrations")
                fields=app.integration_fields["github"]
                fields["repository"].set("example/project")
                fields["token"].set("synthetic-test-token")
                fields["scopes"]["repositories.read"].set(True)
                app._integration_action("github","save");self._drain(app)
                self.assertTrue(ContextConnectorService(db).status("github")["credential_stored"])
                self.assertEqual(app.integration_fields["github"]["token"].get(),"")
                app.integration_fields["github"]["repository"].set("example/draft")
                with patch.object(ContextConnectorService,"sync") as sync:
                    app._integration_action("github","sync")
                    sync.assert_not_called()
                self.assertIn("Save connection changes",app.integration_fields["github"]["notice"].cget("text"))
                app.integration_fields["github"]["repository"].set("example/project")
                pid=app._pid()
                def import_capture(_service: object, provider: str) -> dict:
                    db.insert_capture("Synthetic provider context","integration:"+provider,pid)
                    return {"ok":True,"imported_count":1,"duplicate_count":0}
                with patch.object(ContextConnectorService,"sync",import_capture):
                    app._integration_action("github","sync");self._drain(app)
                self.assertEqual(app._counts[1],1)
                self.assertIn("Imported 1 captures",app.footer.cget("text"))
                # Disconnect must recover even if the visible options are an invalid draft.
                app.integration_fields["github"]["repository"].set("bad draft")
                app._integration_action("github","disconnect");self._drain(app)
                status=ContextConnectorService(db).status("github")
                self.assertFalse(status["enabled"])
                self.assertFalse(status["credential_stored"])
                self.assertEqual(db.pending_count(),1)
            finally:
                self._drain(app);app.destroy()

    def test_invalid_connector_setup_preserves_editable_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"invalid.db")) as db:
            app=OwlThreadApp(db=db,auto_start_engine=False)
            app.withdraw()
            try:
                self._drain(app);app.show_view("integrations")
                fields=app.integration_fields["cloudflare"]
                fields["account_id"].set("not-an-account-id")
                fields["scopes"]["workers.read"].set(True)
                app._integration_action("cloudflare","save");self._drain(app)
                self.assertEqual(fields["account_id"].get(),"not-an-account-id")
                self.assertIn("32-character",fields["notice"].cget("text"))
                self.assertTrue(all(control.cget("state")=="normal" for control in fields["buttons"]))
            finally:
                self._drain(app);app.destroy()

    def test_failed_ui_callback_does_not_stop_event_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"callbacks.db")) as db:
            app=OwlThreadApp(db=db,auto_start_engine=False)
            app.withdraw()
            reached=[]
            try:
                self._drain(app)
                def broken() -> None: raise RuntimeError("synthetic callback error")
                app._actions.put(broken)
                app._actions.put(lambda:reached.append(True))
                with self.assertLogs("owlthread.gui.app",level="ERROR"):
                    self._drain(app)
                self.assertEqual(reached,[True])
                self.assertIsNotNone(app._tick_id)
            finally:
                self._drain(app);app.destroy()

    def test_minimum_window_reserves_footer_for_every_long_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"layout.db")) as db:
            for index in range(6):
                db.insert_capture(f"Browser conversation {index}: keep this local note for context.","browser_extension")
            app=OwlThreadApp(db=db,auto_start_engine=False)
            app.geometry("920x650+20+20")
            try:
                self._drain(app)
                for view in ("feed","captures","integrations","settings"):
                    app.show_view(view);app.update_idletasks()
                    self.assertGreaterEqual(app.footer.winfo_height(),app.footer.winfo_reqheight(),view)
                    self.assertLessEqual(app.footer.winfo_rooty()+app.footer.winfo_height(),app.winfo_rooty()+app.winfo_height()-20,view)
                    self.assertGreater(app._scrolls[0].canvas.winfo_height(),100,view)
            finally:
                self._drain(app);app.destroy()

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
