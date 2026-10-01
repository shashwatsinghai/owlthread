"""Construct every Tk view and exercise user actions against an isolated database."""
from __future__ import annotations
import tempfile
import tkinter as tk
from tkinter import ttk
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
    def test_rounded_buttons_and_section_selector_keep_keyboard_behavior(self) -> None:
        from owlthread.gui.theme import button
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"rounded-controls.db")) as db:
            app=OwlThreadApp(db=db,auto_start_engine=False)
            calls=[]
            try:
                self._drain(app)
                control=button(app.page,"Keyboard action",lambda:calls.append(True))
                control.pack();app.update()
                control.focus_force();app.update()
                control.event_generate("<Return>");app.update()
                self.assertEqual(calls,[True])
                control.configure(state="disabled")
                control.event_generate("<Return>");app.update()
                self.assertEqual(calls,[True],"Disabled rounded buttons must not perform an action")
                app.show_view("settings");app.update()
                tabs=app.settings_tabs
                tabs._buttons[0].focus_force();app.update()
                tabs._buttons[0].event_generate("<Right>");app.update()
                self.assertEqual(tabs.select(),str(tabs._panes[1]))
                self.assertTrue(app._scrolls[1].canvas.winfo_ismapped())
                self.assertFalse(app._scrolls[0].canvas.winfo_ismapped())
                tabs._buttons[1].event_generate("<Left>");app.update()
                self.assertEqual(tabs.select(),str(tabs._panes[0]))
            finally: self._drain(app);app.destroy()

    def test_note_drafts_survive_navigation_and_stay_with_their_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"draft-navigation.db")) as db:
            app=OwlThreadApp(db=db,auto_start_engine=False);app.withdraw()
            try:
                self._drain(app);app.show_view("capture")
                app.note.insert("1.0","General project draft")
                app.show_view("feed");app.show_view("capture")
                self.assertEqual(app.note.get("1.0","end-1c"),"General project draft")
                app.project.set("Second project");app._project_changed();self._drain(app)
                self.assertEqual(app.note.get("1.0","end-1c"),"")
                app.note.insert("1.0","Second project draft")
                app.project.set("General");app._project_changed();self._drain(app)
                self.assertEqual(app.note.get("1.0","end-1c"),"General project draft")
                app._save_capture();app._save_capture();self._drain(app)
                self.assertEqual(db.pending_count(),1,"Repeated save must not duplicate a capture")
                app.show_view("feed");app.show_view("capture")
                self.assertEqual(app.note.get("1.0","end-1c"),"")
                app.project.set("Second project");app._project_changed();self._drain(app)
                self.assertEqual(app.note.get("1.0","end-1c"),"Second project draft")
            finally: self._drain(app);app.destroy()

    def test_settings_drafts_and_search_query_survive_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"navigation.db")) as db:
            app=OwlThreadApp(db=db,auto_start_engine=False);app.withdraw()
            try:
                self._drain(app);app.show_view("settings")
                original=db.get_setting("llm_model","")
                app.setting_vars["llm_model"].set("draft-model")
                app.capture_options["ide_capture_enabled"].set(True)
                app.show_view("search");self._drain(app)
                app.search_query.set("a query without matches");app._search();self._drain(app)
                self.assertEqual(app.search_notice.cget("text"),"0 results")
                self.assertTrue(any(isinstance(w,tk.Label) and w.cget("text")=="No matching memories" for w in app.search_results.winfo_children()))
                app.show_view("settings")
                self.assertEqual(app.setting_vars["llm_model"].get(),"draft-model")
                self.assertTrue(app.capture_options["ide_capture_enabled"].get())
                self.assertEqual(db.get_setting("llm_model",""),original,"Navigating must not save settings")
                app.show_view("search");self._drain(app)
                self.assertEqual(app.search_query.get(),"a query without matches")
            finally: self._drain(app);app.destroy()

    def test_minimum_window_keeps_capture_and_settings_actions_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"actions.db")) as db:
            app=OwlThreadApp(db=db,auto_start_engine=False)
            app.geometry("920x650+20+20")
            try:
                self._drain(app);app.show_view("capture");app.update_idletasks()
                save=app.save_capture_button
                self.assertTrue(save.winfo_ismapped())
                self.assertGreaterEqual(save.winfo_height(),save.winfo_reqheight())
                self.assertLessEqual(save.winfo_rooty()+save.winfo_height(),app.footer.winfo_rooty())
                for nav in app.nav.values():
                    self.assertGreaterEqual(nav.winfo_height(),nav.winfo_reqheight())
                app._save_capture()
                self.assertIn("Write or paste",app.footer.cget("text"))
                app.note.insert("1.0","Keep the complete note when using a shortcut")
                app.note.mark_set("insert","1.0")
                app.note.focus_force();app.update()
                app.note.event_generate("<Control-k>");self._drain(app)
                self.assertEqual(app.current_view,"search")
                app._shortcut("capture")
                self.assertEqual(app.note.get("1.0","end-1c"),"Keep the complete note when using a shortcut")
                app.show_view("settings");app.update_idletasks()
                for index in range(4):
                    app.settings_tabs.select(index);app.update_idletasks()
                    scroll=app._scrolls[index]
                    self.assertTrue(scroll.canvas.winfo_ismapped())
                    self.assertGreater(scroll.canvas.winfo_height(),100)
            finally: self._drain(app);app.destroy()

    def test_other_integrations_are_coming_soon_without_setup_controls(self) -> None:
        from owlthread.integrations.catalog import list_catalog
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"coming-soon.db")) as db:
            pid=db.get_or_create_project("General")
            previous='{"enabled":true,"scopes":["messages.read"],"project_id":'+str(pid)+'}'
            db.set_setting("integration_config:gmail",previous)
            app=OwlThreadApp(db=db,auto_start_engine=False);app.withdraw()
            def descendants(widget: tk.Misc) -> list[tk.Misc]:
                children=widget.winfo_children()
                return children+[nested for child in children for nested in descendants(child)]
            try:
                self._drain(app);app.show_view("integrations");app.update_idletasks()
                cards=[widget for widget in app._scrolls[0].content.winfo_children() if isinstance(widget,tk.Frame)]
                for spec in list_catalog():
                    if spec.integration_id in {"cloudflare","github"}: continue
                    with self.subTest(integration=spec.integration_id):
                        matching=[card for card in cards if any(isinstance(widget,tk.Label) and widget.cget("text")==spec.display_name for widget in descendants(card))]
                        self.assertEqual(len(matching),1)
                        widgets=descendants(matching[0])
                        self.assertTrue(any(isinstance(widget,tk.Label) and widget.cget("text")=="Coming soon" for widget in widgets))
                        self.assertFalse(any(isinstance(widget,(tk.Button,ttk.Button,tk.Entry,ttk.Entry,ttk.Combobox,tk.Checkbutton)) for widget in widgets))
                self.assertEqual(db.get_setting("integration_config:gmail"),previous,"Existing grants must remain untouched")
                self.assertEqual(set(app._browser_fields),{"cloudflare","github"})
            finally: self._drain(app);app.destroy()

    def test_browser_connect_is_primary_and_token_setup_is_collapsed(self) -> None:
        with patch("owlthread.integrations.browser_login.GITHUB_CLIENT_ID",""), patch.dict("os.environ",{"OWLTHREAD_GITHUB_CLIENT_ID":""}), tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"browser-ui.db")) as db:
            app=OwlThreadApp(db=db,auto_start_engine=False)
            app.withdraw()
            try:
                self._drain(app);app.show_view("integrations");app.update_idletasks()
                fields=app._browser_fields["cloudflare"]
                self.assertEqual(fields["connect"].cget("text"),"Sign in with Cloudflare")
                self.assertEqual(fields["connect"].cget("state"),"normal")
                self.assertFalse(app._connector_advanced_open.get("cloudflare",False))
                self.assertFalse(app.integration_fields["cloudflare"]["token_widget"].winfo_ismapped())
                self.assertEqual(app._browser_fields["github"]["connect"].cget("state"),"disabled")
            finally: self._drain(app);app.destroy()

    def test_browser_accounts_with_duplicate_names_remain_selectable(self) -> None:
        import json
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"duplicate-resource-ui.db")) as db:
            account_a,account_b,account_c="a"*32,"b"*32,"c"*32
            db.set_setting("integration_credential:cloudflare","synthetic-oauth-credential")
            def save_resources(resources: list[dict]) -> None:
                db.set_setting("integration_auth:cloudflare",json.dumps({"method":"browser","label":"Fixture","resources":resources}))
            save_resources([{"id":account_a,"label":"Team","options":{"account_id":account_a}}])
            app=OwlThreadApp(db=db,auto_start_engine=False);app.withdraw()
            try:
                self._drain(app);app.show_view("integrations")
                fields=app._browser_fields["cloudflare"]
                self.assertEqual(fields["choice"].get(),"Team")
                save_resources([
                    {"id":account_a,"label":"Team","options":{"account_id":account_a}},
                    {"id":account_b,"label":"Team","options":{"account_id":account_b}},
                    {"id":account_c,"label":f"Team ({account_a})","options":{"account_id":account_c}},
                ])
                app._poll_browser_logins();app.update_idletasks()
                choices=fields["resource_map"]
                self.assertEqual(len(choices),3)
                self.assertEqual(set(choices.values()),{account_a,account_b,account_c})
                self.assertEqual(choices[fields["choice"].get()],account_a,"Discovery must preserve the selected account by ID")
                self.assertEqual(tuple(fields["resources"].cget("values")),tuple(choices))
                for choice,account_id in choices.items():
                    fields["choice"].set(choice)
                    with patch.object(app.login_service,"select",return_value={"ok":True,"imported_count":0}) as select:
                        app._import_browser_context("cloudflare");self._drain(app)
                        select.assert_called_once_with("cloudflare",account_id)
            finally: self._drain(app);app.destroy()

    def test_browser_resources_update_without_erasing_selection_or_drafts(self) -> None:
        import json
        with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"resource-ui.db")) as db:
            db.set_setting("integration_credential:cloudflare","synthetic-oauth-credential")
            db.set_setting("integration_auth:cloudflare",json.dumps({"method":"browser","label":"Fixture","resources":[{"id":"a"*32,"label":"A","options":{"account_id":"a"*32}},{"id":"b"*32,"label":"B","options":{"account_id":"b"*32}}]}))
            app=OwlThreadApp(db=db,auto_start_engine=False);app.withdraw()
            try:
                self._drain(app);app.show_view("integrations")
                fields=app._browser_fields["cloudflare"]
                fields["choice"].set("B");app.integration_fields["cloudflare"]["account_id"].set("manual draft")
                app._poll_browser_logins();app.update_idletasks()
                self.assertEqual(fields["choice"].get(),"B")
                self.assertEqual(app.integration_fields["cloudflare"]["account_id"].get(),"manual draft")
                self.assertEqual(fields["import"].cget("state"),"normal")
                app.login_service.close()
            finally: self._drain(app);app.destroy()

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
