"""Isolated real loopback server for the browser integration test; no user stores."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from owlthread.db.database import Database
from owlthread.capture.engine import CaptureEngine
from owlthread.security import local_token

with tempfile.TemporaryDirectory(prefix="owlthread-browser-api-") as directory:
    with Database(str(Path(directory)/"memory.db")) as db:
        db.set_setting("llm_provider","fallback")
        engine=CaptureEngine(db,http_port=0,enable_clipboard=False,enable_connectors=False,flush_interval=3600)
        engine.start()
        try:
            print(json.dumps({"port":engine.http_listener.port,"token":local_token(db)}),flush=True)
            sys.stdin.readline()
        finally:
            engine.stop()
