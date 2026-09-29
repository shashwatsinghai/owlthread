"""Pluggable periodic connectors with persistent content deduplication."""
from __future__ import annotations
import hashlib
import json
import logging
import threading
from pathlib import Path
from urllib.parse import unquote,urlsplit
from abc import ABC, abstractmethod
from typing import Any
from owlthread.config import CONNECTOR_POLL_INTERVAL
from owlthread.db.database import Database

logger = logging.getLogger(__name__)


def extract_text(value: Any) -> str:
    """Read chat text from nested IDE records without treating it as instructions."""
    if isinstance(value,str):
        return value
    if isinstance(value,list):
        return "\n".join(filter(None,(extract_text(item) for item in value)))
    if isinstance(value,dict):
        keys = ("text","content","prompt","message","response","value","v","requests","messages",
                "conversation","allComposers","bubbles","parts","code","description","textDescription")
        return "\n".join(filter(None,(extract_text(value[key]) for key in keys if key in value)))
    return ""


class IConnector(ABC):
    def __init__(self, db: Database, name: str | None = None) -> None:
        self.db = db
        self.name = name or type(self).__name__
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._poll_lock = threading.Lock()
        self.poll_interval = CONNECTOR_POLL_INTERVAL
        self.last_error: str | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop,name="OwlThread-"+self.name,daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_interval):
            try:
                if self.db.get_setting("capture_paused","false") != "true":
                    self.poll()
                    self.last_error = None
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning("%s could not read its source",self.name)

    @abstractmethod
    def poll(self) -> int:
        """Capture new complete records; return number persisted."""
        raise NotImplementedError

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join()

    def capture(self, text: str, source: str, location: str, metadata: dict[str,Any] | None = None) -> int:
        if not text.strip() or len(text)>200000 or self.db.get_setting("capture_paused","false")=="true":
            return 0
        digest = hashlib.sha256((location+"\0"+text).encode("utf-8")).hexdigest()
        # Durable dedup is committed in the same transaction as the capture.
        path=Path(location)
        workspace=next((parent for parent in path.parents if parent.parent.name=="workspaceStorage"),None)
        if workspace is not None:
            name=f"{self.name}: {workspace.name}"
            root=None
            try:
                data=json.loads((workspace/"workspace.json").read_text(encoding="utf-8"))
                uri=data.get("folder") or data.get("workspace")
                parsed=urlsplit(uri or "")
                if parsed.scheme=="file":
                    root=unquote(parsed.path).lstrip("/") if parsed.path.startswith("/") and len(parsed.path)>2 and parsed.path[2]==":" else unquote(parsed.path)
                    name=Path(root).name or name
            except (OSError,ValueError,TypeError):
                pass
            pid=self.db.get_or_create_project(name,root)
        else:
            # Unknown global chats must never silently join the currently active project.
            pid=self.db.get_or_create_project(f"Unassigned {self.name}")
        return int(bool(self.db.insert_capture(text,source,project_id=pid,source_metadata=metadata,dedup_key=digest)))

    def Start(self) -> None:
        self.start()

    def Poll(self) -> int:
        return self.poll()

    def Stop(self) -> None:
        self.stop()
