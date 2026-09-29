"""Visual test window with synthetic data and automatic capture disabled."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from owlthread.db.database import Database
from owlthread.gui.app import OwlThreadApp
from owlthread.tray import WindowsHotkeyListener

path = Path(__file__).resolve().parent.parent/"artifacts"/"gui-preview.db"
with Database(str(path)) as db:
    db.set_setting("llm_provider","fallback")
    db.set_setting("active_project","Preview · sample data")
    pid = db.get_or_create_project("Preview · sample data")
    if not db.count_entries(project_id=pid):
        for quadrant,summary,source in (
            ("technical_architecture","SQLite WAL keeps the local memory store responsive during capture.","cursor_ide"),
            ("settled_decisions","We chose a single writer queue so captures and memory updates commit in order.","manual"),
            ("business_rules","All memory stays on this device unless a remote model is configured.","browser_extension"),
            ("open_questions","Should archived memories be included in a project export?","vscode_copilot"),
        ):
            db.insert_entry(summary,source,pid,quadrant=quadrant,summary=summary)
    app = OwlThreadApp(db=db,auto_start_engine=False)
    app.title("OwlThread — Preview (sample data)")
    def shortcut() -> None:
        print("Global shortcut received",flush=True)
        app._actions.put(app.open_primer)
    hotkey = WindowsHotkeyListener(shortcut)
    hotkey.start()
    print("Shortcut registration:",hotkey.error or "ready",flush=True)
    app.on_quit = hotkey.stop
    app.after(600000,app._on_close)
    app.mainloop()
