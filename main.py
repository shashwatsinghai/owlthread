"""Packaged launcher: open the desktop by default, or forward CLI arguments."""
from __future__ import annotations
import sys
from owlthread.cli import main
if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["app"]))
