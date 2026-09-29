"""Compatibility import for earlier OwlThread connectors."""
from __future__ import annotations
import logging
from owlthread.capture.connectors.vscode import VSCodeCopilotConnector
logger = logging.getLogger(__name__)
__all__ = ["VSCodeCopilotConnector"]
