"""Cursor IDE Chat & Composer Connector."""

import glob
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from owlthread.capture.connectors.base import IConnector
from owlthread.config import SOURCE_CURSOR
from owlthread.db.database import Database

logger = logging.getLogger(__name__)


class CursorConnector(IConnector):
    """
    Watches Cursor's local storage paths for AI chat and composer entries.
    
    Monitors:
    - %APPDATA%/Cursor/User/workspaceStorage/*/state.vscdb (aiService.prompts, aiService.generations, composer.composerData)
    - %APPDATA%/Cursor/User/globalStorage/conversation-search.db (conversations & conversation_fts_content)
    """

    def __init__(self, db: Database, base_dir: Optional[str] = None):
        super().__init__(db, name="CursorConnector")
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                self.base_dir = Path(appdata) / "Cursor" / "User"
            else:
                self.base_dir = Path.home() / ".config" / "Cursor" / "User"
        
        self.seen_ids: Set[str] = set()

    def start(self) -> None:
        """Load state and start connector."""
        super().start()
        state = self.db.get_connector_state(self.name)
        saved_seen = state.get("seen_ids", [])
        self.seen_ids = set(saved_seen)
        logger.info("CursorConnector started with %d cached items.", len(self.seen_ids))

    def stop(self) -> None:
        """Stop connector and persist state."""
        self._save_state()
        super().stop()
        logger.info("CursorConnector stopped.")

    def _save_state(self) -> None:
        """Persist processed item IDs."""
        self.db.set_connector_state(self.name, {
            "seen_ids": list(self.seen_ids)[-5000:]
        })

    def _open_ro_sqlite(self, path: Path) -> Optional[sqlite3.Connection]:
        """Open a SQLite database in read-only mode to prevent lock contention."""
        if not path.exists():
            return None
        try:
            # Using URI read-only connection
            uri = f"file:{path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.debug("Failed to open SQLite db at %s: %s", path, e)
            return None

    def poll(self) -> int:
        """Scan Cursor databases for new prompts, generations, and conversations."""
        if not self.base_dir.exists():
            return 0

        new_entries_count = 0

        # 1. Scan globalStorage conversation-search.db
        new_entries_count += self._poll_conversation_search()

        # 2. Scan workspaceStorage state.vscdb files
        new_entries_count += self._poll_workspace_dbs()

        if new_entries_count > 0:
            self._save_state()

        return new_entries_count

    def _poll_conversation_search(self) -> int:
        """Poll conversation-search.db for searchable conversation docs."""
        conv_db_path = self.base_dir / "globalStorage" / "conversation-search.db"
        conn = self._open_ro_sqlite(conv_db_path)
        if not conn:
            return 0

        count = 0
        try:
            cursor = conn.cursor()
            # Check if conversation_fts_content and conversations tables exist
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'"
            )
            if not cursor.fetchone():
                return 0

            cursor.execute(
                """
                SELECT c.id, c.title, c.updated_at, f.c1 as full_text
                FROM conversations c
                LEFT JOIN conversation_fts_content f ON c.fts_rowid = f.rowid
                """
            )
            for row in cursor.fetchall():
                conv_id = str(row["id"])
                tracking_key = f"conv_search:{conv_id}"
                if tracking_key in self.seen_ids:
                    continue

                title = row["title"] or ""
                full_text = row["full_text"] or ""
                updated_at_ms = row["updated_at"]

                content_parts = []
                if title:
                    content_parts.append(f"Title: {title}")
                if full_text:
                    content_parts.append(full_text.strip())

                if not content_parts:
                    continue

                raw_text = "\n\n".join(content_parts)
                timestamp = None
                if updated_at_ms:
                    try:
                        timestamp = datetime.fromtimestamp(
                            int(updated_at_ms) / 1000.0, tz=timezone.utc
                        ).isoformat()
                    except Exception:
                        pass

                self.db.insert_entry(
                    raw_text=raw_text,
                    source_app=SOURCE_CURSOR,
                    source_metadata={
                        "source": "cursor_conversation_search",
                        "conversation_id": conv_id,
                        "title": title
                    },
                    timestamp=timestamp,
                    quadrant=None
                )
                self.seen_ids.add(tracking_key)
                count += 1
        except Exception as e:
            logger.error("Error polling Cursor conversation-search.db: %s", e)
        finally:
            conn.close()

        return count

    def _poll_workspace_dbs(self) -> int:
        """Poll workspace state.vscdb files for prompt and generation records."""
        count = 0
        workspace_pattern = str(self.base_dir / "workspaceStorage" / "*" / "state.vscdb")
        db_paths = glob.glob(workspace_pattern)

        for db_file in db_paths:
            path = Path(db_file)
            workspace_id = path.parent.name
            conn = self._open_ro_sqlite(path)
            if not conn:
                continue

            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT key, value FROM ItemTable 
                    WHERE key IN ('aiService.prompts', 'aiService.generations', 'composer.composerData')
                    """
                )
                for row in cursor.fetchall():
                    key = row["key"]
                    val_str = row["value"]
                    if not val_str:
                        continue

                    try:
                        data = json.loads(val_str)
                    except Exception:
                        continue

                    if key == "aiService.prompts" and isinstance(data, list):
                        count += self._process_prompts(data, workspace_id)
                    elif key == "aiService.generations" and isinstance(data, list):
                        count += self._process_generations(data, workspace_id)
                    elif key == "composer.composerData" and isinstance(data, dict):
                        count += self._process_composer_data(data, workspace_id)
            except Exception as e:
                logger.debug("Error reading workspace DB %s: %s", path, e)
            finally:
                conn.close()

        return count

    def _process_prompts(self, prompts: List[Dict[str, Any]], workspace_id: str) -> int:
        """Process aiService.prompts list."""
        count = 0
        for prompt in prompts:
            text = prompt.get("text", "").strip()
            if not text:
                continue

            tracking_key = f"prompt:{workspace_id}:{hash(text)}"
            if tracking_key in self.seen_ids:
                continue

            self.db.insert_entry(
                raw_text=text,
                source_app=SOURCE_CURSOR,
                source_metadata={
                    "source": "cursor_prompt",
                    "workspace_id": workspace_id,
                    "command_type": prompt.get("commandType")
                },
                quadrant=None
            )
            self.seen_ids.add(tracking_key)
            count += 1
        return count

    def _process_generations(self, generations: List[Dict[str, Any]], workspace_id: str) -> int:
        """Process aiService.generations list."""
        count = 0
        for gen in generations:
            gen_uuid = gen.get("generationUUID")
            text_desc = gen.get("textDescription", "").strip()
            if not text_desc:
                continue

            tracking_key = f"gen:{gen_uuid or hash(text_desc)}"
            if tracking_key in self.seen_ids:
                continue

            timestamp = None
            if "unixMs" in gen:
                try:
                    timestamp = datetime.fromtimestamp(
                        int(gen["unixMs"]) / 1000.0, tz=timezone.utc
                    ).isoformat()
                except Exception:
                    pass

            self.db.insert_entry(
                raw_text=text_desc,
                source_app=SOURCE_CURSOR,
                source_metadata={
                    "source": "cursor_generation",
                    "workspace_id": workspace_id,
                    "generation_uuid": gen_uuid,
                    "type": gen.get("type")
                },
                timestamp=timestamp,
                quadrant=None
            )
            self.seen_ids.add(tracking_key)
            count += 1
        return count

    def _process_composer_data(self, composer_data: Dict[str, Any], workspace_id: str) -> int:
        """Process composer conversation data."""
        count = 0
        all_composers = composer_data.get("allComposers", [])
        for composer in all_composers:
            composer_id = composer.get("composerId")
            name = composer.get("name") or ""
            text = composer.get("text") or ""
            conversation = composer.get("conversation", [])

            # Check individual messages in conversation if available
            for bubble in conversation:
                bubble_id = bubble.get("bubbleId") or bubble.get("id")
                bubble_text = bubble.get("text", "").strip()
                if not bubble_text:
                    continue

                tracking_key = f"composer_bubble:{composer_id}:{bubble_id or hash(bubble_text)}"
                if tracking_key in self.seen_ids:
                    continue

                self.db.insert_entry(
                    raw_text=bubble_text,
                    source_app=SOURCE_CURSOR,
                    source_metadata={
                        "source": "cursor_composer_bubble",
                        "workspace_id": workspace_id,
                        "composer_id": composer_id,
                        "composer_name": name,
                        "bubble_type": bubble.get("type")
                    },
                    quadrant=None
                )
                self.seen_ids.add(tracking_key)
                count += 1

            # Fallback if entire composer has a prompt/name
            if name or text:
                tracking_key = f"composer_head:{composer_id}"
                if tracking_key not in self.seen_ids:
                    content = f"{name}\n{text}".strip()
                    if content:
                        self.db.insert_entry(
                            raw_text=content,
                            source_app=SOURCE_CURSOR,
                            source_metadata={
                                "source": "cursor_composer",
                                "workspace_id": workspace_id,
                                "composer_id": composer_id,
                                "composer_name": name
                            },
                            quadrant=None
                        )
                        self.seen_ids.add(tracking_key)
                        count += 1

        return count
