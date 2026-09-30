"""Render only synthetic desktop data for repeatable Windows layout inspection.

Run: python -m tests.gui_visual_smoke
No provider requests, user settings, user database, or extension profile are used.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import ImageGrab
from owlthread.db.database import Database
from owlthread.gui.app import OwlThreadApp
from owlthread.integrations.context import ContextConnectorService


def drain(app: OwlThreadApp) -> None:
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        app.update()
        if not any(thread.is_alive() for thread in app._workers) and app._actions.empty(): return
        time.sleep(.01)
    raise RuntimeError("Desktop did not settle")


def main() -> None:
    output=Path(__file__).resolve().parents[1]/"artifacts"/"audit-2026-09-30"
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory, Database(str(Path(directory)/"visual.db")) as db:
        project_id=db.get_or_create_project("Demo project")
        db.set_setting("active_project","Demo project")
        db.insert_entry(raw_text="Validate Stripe webhook signatures before processing payment events.",summary="Validate signed payment events before processing",quadrant="technical_architecture",project_id=project_id)
        db.insert_entry(raw_text="We decided to keep captures on this device.",summary="Keep raw captures on this device",quadrant="settled_decisions",project_id=project_id)
        db.insert_capture("User: How should we validate webhooks?\nAssistant: Verify the signature before accepting the event, then save an idempotency key.","browser_extension",project_id,source_metadata={"title":"Webhook design review","url":"https://chatgpt.com/c/synthetic-example"})
        failed=db.insert_capture("Decision: Retry provider imports after the connection becomes available.","browser_extension",project_id)
        db.execute_write("UPDATE capture_buffer SET extraction_status='failed',extraction_reason='Provider connection unavailable; original text remains saved',attempts=1 WHERE id=?",(failed,))
        processed=db.insert_capture("Keep the local audit log for development diagnostics.","manual",project_id)
        db.mark_capture_processed(processed)
        ContextConnectorService(db).configure("cloudflare",token="synthetic-demo-token",options={"account_id":"a"*32,"zone_id":""},scopes=["workers.read","pages.read"],project_id=project_id)
        app=OwlThreadApp(db=db,port=19876,auto_start_engine=False)
        try:
            app.attributes("-topmost",True)
            app.lift()
            drain(app)
            app.engine=SimpleNamespace(status=lambda:{"http_listener":{"running":True,"port":19876},"authorized_browser_count":1,"capture_paused":False},http_listener_error=None)
            app._request_refresh();drain(app)
            images=[]
            for size,width,height in (("normal",1180,800),("minimum",920,650)):
                app.geometry(f"{width}x{height}+20+20")
                for view in ("feed","captures","integrations","settings"):
                    app.show_view(view)
                    drain(app)
                    deadline=time.monotonic()+.35
                    while time.monotonic()<deadline:
                        app.update();time.sleep(.01)
                    app.attributes("-alpha",1)
                    app.update_idletasks()
                    x,y=app.winfo_rootx(),app.winfo_rooty()
                    path=output/f"desktop-{view}-{size}.png"
                    ImageGrab.grab(window=app.winfo_id()).save(path)
                    images.append({"path":str(path),"width":app.winfo_width(),"height":app.winfo_height()})
            print(json.dumps(images,indent=2))
        finally:
            drain(app)
            app.destroy()


if __name__=="__main__": main()
