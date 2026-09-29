"""Shared local database API."""
from __future__ import annotations
import logging
from owlthread.db.database import Database, DatabaseManager
logger = logging.getLogger(__name__)
__all__ = ["Database", "DatabaseManager"]
