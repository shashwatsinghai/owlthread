"""Local-first defaults. Importing configuration never creates files."""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = int(os.environ.get("OWLTHREAD_PORT", "41789"))
DEFAULT_DATA_DIR = Path.home() / ".owlthread"
DEFAULT_DB_PATH = str(DEFAULT_DATA_DIR / "owlthread.db")
DB_PATH = os.environ.get("OWLTHREAD_DB_PATH", DEFAULT_DB_PATH)
SOURCE_CLIPBOARD = "clipboard"
SOURCE_BROWSER = "browser_extension"
SOURCE_CURSOR = "cursor_ide"
SOURCE_VSCODE = SOURCE_COPILOT = "vscode_copilot"
SOURCE_CLI = "cli_run"
SOURCE_MANUAL = "manual"
SOURCE_MCP = "mcp"
VALID_QUADRANTS = {"technical_architecture", "business_rules", "settled_decisions", "open_questions"}
QUADRANT_COLORS = {"technical_architecture": "#3b82f6", "business_rules": "#8b5cf6", "settled_decisions": "#10b981", "open_questions": "#f59e0b"}
CLIPBOARD_POLL_INTERVAL_SEC = CLIPBOARD_POLL_INTERVAL = float(os.environ.get("OWLTHREAD_CLIPBOARD_POLL", "1.5"))
CLIPBOARD_MIN_LENGTH = 20
CONNECTOR_POLL_INTERVAL_SEC = CONNECTOR_POLL_INTERVAL = float(os.environ.get("OWLTHREAD_CONNECTOR_POLL", "60"))
DEFAULT_LLM_PROVIDER = "fallback"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
