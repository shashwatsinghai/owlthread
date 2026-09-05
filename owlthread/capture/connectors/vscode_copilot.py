"""VS Code Copilot Chat Connector."""

import glob
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from owlthread.capture.connectors.base import IConnector
from owlthread.config import SOURCE_COPILOT
from owlthread.db.database import Database

logger = logging.getLogger(__name__)


class VSCodeCopilotConnector(IConnector):
    """
    Watches VS Code's workspaceStorage for GitHub Copilot Chat session data.
    
    Monitors:
    - %APPDATA%/Code/User/workspaceStorage/*/chatSessions/*.jsonl
    - %APPDATA%/Code/User/workspaceStorage/*/chatEditingSessions/*/state.json
    """

    def __init__(self, db: Database, base_dir: Optional[str] = None):
        super().__init__(db, name="VSCodeCopilotConnector")
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                self.base_dir = Path(appdata) / "Code" / "User"
            else:
                self.base_dir = Path.home() / ".config" / "Code" / "User"

        self.file_offsets: Dict[str, int] = {}
        self.seen_message_keys: Set[str] = set()

    def start(self) -> None:
        """Load state and start connector."""
        super().start()
        state = self.db.get_connector_state(self.name)
        self.file_offsets = state.get("file_offsets", {})
        self.seen_message_keys = set(state.get("seen_message_keys", []))
        logger.info("VSCodeCopilotConnector started with %d tracked files.", len(self.file_offsets))

    def stop(self) -> None:
        """Stop connector and persist state."""
        self._save_state()
        super().stop()
        logger.info("VSCodeCopilotConnector stopped.")

    def _save_state(self) -> None:
        """Persist file offsets and seen keys."""
        self.db.set_connector_state(self.name, {
            "file_offsets": self.file_offsets,
            "seen_message_keys": list(self.seen_message_keys)[-5000:]
        })

    def poll(self) -> int:
        """Scan VS Code chat sessions and editing sessions for new turns."""
        if not self.base_dir.exists():
            return 0

        new_entries_count = 0
        new_entries_count += self._poll_chat_sessions()
        new_entries_count += self._poll_chat_editing_sessions()

        if new_entries_count > 0:
            self._save_state()

        return new_entries_count

    def _poll_chat_sessions(self) -> int:
        """Scan workspaceStorage/*/chatSessions/*.jsonl files."""
        count = 0
        pattern = str(self.base_dir / "workspaceStorage" / "*" / "chatSessions" / "*.jsonl")
        jsonl_files = glob.glob(pattern)

        for filepath in jsonl_files:
            p = Path(filepath)
            workspace_id = p.parent.parent.name
            session_id = p.stem

            try:
                current_mtime = p.stat().st_mtime
                last_offset = self.file_offsets.get(str(p), 0)

                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    if last_offset > 0:
                        f.seek(last_offset)

                    line_number = 0
                    while True:
                        line = f.readline()
                        if not line:
                            break
                        line_number += 1
                        line_str = line.strip()
                        if not line_str:
                            continue

                        try:
                            record = json.loads(line_str)
                            count += self._process_chat_record(record, workspace_id, session_id)
                        except Exception as parse_err:
                            logger.debug("Failed parsing json line in %s: %s", p, parse_err)

                    self.file_offsets[str(p)] = f.tell()

            except Exception as e:
                logger.debug("Error processing chat session file %s: %s", p, e)

        return count

    def _process_chat_record(self, record: Dict[str, Any], workspace_id: str, session_id: str) -> int:
        """Extract user queries and assistant responses from a chat jsonl line."""
        count = 0
        kind = record.get("kind")
        v = record.get("v")

        # Kind 0 is the initial session object
        if kind == 0 and isinstance(v, dict):
            requests = v.get("requests", [])
            for req_idx, req in enumerate(requests):
                count += self._process_request_item(req, workspace_id, session_id, req_idx)

        # Kind 1 / other mutations that might contain requests or messages
        elif isinstance(v, dict):
            if "requests" in v and isinstance(v["requests"], list):
                for req_idx, req in enumerate(v["requests"]):
                    count += self._process_request_item(req, workspace_id, session_id, req_idx)
            elif "message" in v:
                msg_text = self._extract_message_text(v.get("message"))
                if msg_text:
                    key = f"vsc_msg:{session_id}:{hash(msg_text)}"
                    if key not in self.seen_message_keys:
                        self.db.insert_entry(
                            raw_text=msg_text,
                            source_app=SOURCE_COPILOT,
                            source_metadata={
                                "source": "vscode_copilot",
                                "workspace_id": workspace_id,
                                "session_id": session_id,
                                "type": "mutation_message"
                            },
                            quadrant=None
                        )
                        self.seen_message_keys.add(key)
                        count += 1

        elif isinstance(v, list):
            # List of requests / parts
            for item in v:
                if isinstance(item, dict) and ("message" in item or "response" in item):
                    count += self._process_request_item(item, workspace_id, session_id)

        return count

    def _process_request_item(
        self,
        req: Dict[str, Any],
        workspace_id: str,
        session_id: str,
        idx: Optional[int] = None
    ) -> int:
        """Extract prompt message and assistant response from a request structure."""
        count = 0
        msg_obj = req.get("message")
        user_text = self._extract_message_text(msg_obj)

        if user_text:
            key = f"copilot_req:{session_id}:{hash(user_text)}"
            if key not in self.seen_message_keys:
                self.db.insert_entry(
                    raw_text=user_text,
                    source_app=SOURCE_COPILOT,
                    source_metadata={
                        "source": "vscode_copilot_request",
                        "workspace_id": workspace_id,
                        "session_id": session_id,
                        "index": idx
                    },
                    quadrant=None
                )
                self.seen_message_keys.add(key)
                count += 1

        # Extract assistant responses
        responses = req.get("response", [])
        if isinstance(responses, list):
            for r_idx, resp in enumerate(responses):
                resp_text = self._extract_response_text(resp)
                if resp_text:
                    resp_key = f"copilot_resp:{session_id}:{hash(resp_text)}"
                    if resp_key not in self.seen_message_keys:
                        self.db.insert_entry(
                            raw_text=resp_text,
                            source_app=SOURCE_COPILOT,
                            source_metadata={
                                "source": "vscode_copilot_response",
                                "workspace_id": workspace_id,
                                "session_id": session_id,
                                "response_index": r_idx
                            },
                            quadrant=None
                        )
                        self.seen_message_keys.add(resp_key)
                        count += 1

        return count

    def _extract_message_text(self, msg_obj: Any) -> str:
        """Extract clean text from message payload."""
        if isinstance(msg_obj, str):
            return msg_obj.strip()
        if isinstance(msg_obj, dict):
            if "text" in msg_obj and isinstance(msg_obj["text"], str):
                return msg_obj["text"].strip()
            if "value" in msg_obj and isinstance(msg_obj["value"], str):
                return msg_obj["value"].strip()
            if "parts" in msg_obj and isinstance(msg_obj["parts"], list):
                parts = [p.get("text", "") for p in msg_obj["parts"] if isinstance(p, dict)]
                return "\n".join(p.strip() for p in parts if p.strip())
        return ""

    def _extract_response_text(self, resp_obj: Any) -> str:
        """Extract text from a response object."""
        if isinstance(resp_obj, str):
            return resp_obj.strip()
        if isinstance(resp_obj, dict):
            if "value" in resp_obj and isinstance(resp_obj["value"], str):
                return resp_obj["value"].strip()
            if "response" in resp_obj and isinstance(resp_obj["response"], str):
                return resp_obj["response"].strip()
            if "markdown" in resp_obj and isinstance(resp_obj["markdown"], str):
                return resp_obj["markdown"].strip()
        return ""

    def _poll_chat_editing_sessions(self) -> int:
        """Scan workspaceStorage/*/chatEditingSessions/*/state.json files."""
        count = 0
        pattern = str(self.base_dir / "workspaceStorage" / "*" / "chatEditingSessions" / "*" / "state.json")
        for state_file in glob.glob(pattern):
            p = Path(state_file)
            session_id = p.parent.name
            workspace_id = p.parent.parent.parent.name

            try:
                key = f"editing_session:{session_id}:{p.stat().st_mtime}"
                if key in self.seen_message_keys:
                    continue

                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)

                timeline = data.get("timeline", {})
                checkpoints = timeline.get("checkpoints", [])
                for cp in checkpoints:
                    desc = cp.get("description") or cp.get("label") or ""
                    req_id = cp.get("requestId") or ""
                    if desc and desc != "Initial State":
                        cp_text = f"Editing Session: {desc}\nRequest: {req_id}".strip()
                        self.db.insert_entry(
                            raw_text=cp_text,
                            source_app=SOURCE_COPILOT,
                            source_metadata={
                                "source": "vscode_chat_editing_session",
                                "workspace_id": workspace_id,
                                "session_id": session_id,
                                "checkpoint_id": cp.get("checkpointId")
                            },
                            quadrant=None
                        )
                        count += 1

                self.seen_message_keys.add(key)
            except Exception as e:
                logger.debug("Error processing chat editing session %s: %s", p, e)

        return count
