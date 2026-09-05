"""Configuration settings for OwlThread."""

import os
from pathlib import Path

# Base App Directory
DEFAULT_DATA_DIR = Path.home() / ".owlthread"
DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database path
DB_PATH = os.environ.get(
    "OWLTHREAD_DB_PATH",
    str(DEFAULT_DATA_DIR / "owlthread.db")
)

# HTTP Server settings
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = int(os.environ.get("OWLTHREAD_PORT", 41789))

# Polling intervals in seconds
CLIPBOARD_POLL_INTERVAL = float(os.environ.get("OWLTHREAD_CLIPBOARD_POLL", 0.5))
CONNECTOR_POLL_INTERVAL = float(os.environ.get("OWLTHREAD_CONNECTOR_POLL", 2.0))

# Standard source tags
SOURCE_CLIPBOARD = "clipboard"
SOURCE_CURSOR = "cursor"
SOURCE_COPILOT = "copilot"
SOURCE_CLI = "cli"
SOURCE_BROWSER = "browser"
