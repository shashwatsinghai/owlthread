"""OwlThread Desktop Application entry point."""

import sys
import os

# Ensure project root is in sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from owlthread.gui.app import run_app

if __name__ == "__main__":
    run_app()
