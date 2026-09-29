"""Tk desktop entry points."""
from __future__ import annotations
import logging
from owlthread.gui.app import OwlThreadApp,OwlThreadDesktopApp,run_app
logger = logging.getLogger(__name__)
__all__ = ["OwlThreadApp","OwlThreadDesktopApp","run_app"]
