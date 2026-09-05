from setuptools import setup, find_packages

setup(
    name="owlthread",
    version="0.3.0",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "owlthread = owlthread.cli:main",
        ],
        "gui_scripts": [
            "owlthread-gui = owlthread.gui.app:run_app",
        ],
    },
)
