"""Capture package initialization."""

from __future__ import annotations

from owlthread.capture.clipboard import ClipboardWatcher
from owlthread.capture.connectors import CursorConnector, IConnector, VSCodeCopilotConnector
from owlthread.capture.engine import CaptureEngine
from owlthread.capture.server import LocalHttpListener

__all__ = [
    "CaptureEngine",
    "ClipboardWatcher",
    "LocalHttpListener",
    "IConnector",
    "CursorConnector",
    "VSCodeCopilotConnector",
]

import logging
logger = logging.getLogger(__name__)
