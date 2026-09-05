"""Connectors package for OwlThread."""

from owlthread.capture.connectors.base import IConnector
from owlthread.capture.connectors.cursor import CursorConnector
from owlthread.capture.connectors.vscode_copilot import VSCodeCopilotConnector

__all__ = ["IConnector", "CursorConnector", "VSCodeCopilotConnector"]
