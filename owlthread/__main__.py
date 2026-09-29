"""Run OwlThread with python -m owlthread."""
from __future__ import annotations
import logging
from owlthread.cli import main
logger = logging.getLogger(__name__)
if __name__ == "__main__":
    raise SystemExit(main())
