# PyInstaller distribution: desktop and console entry points share bundled files.
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

datas = copy_metadata("mcp") + copy_metadata("owlthread")
hiddenimports = collect_submodules("mcp", filter=lambda name: not name.startswith("mcp.cli")) + ["pystray._win32", "keyboard", "win32clipboard", "win32crypt"]
a = Analysis(["main.py"], pathex=[], binaries=[], datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=["customtkinter", "pytest", "IPython", "matplotlib", "numpy", "pandas"], noarchive=False)
pyz = PYZ(a.pure)
desktop = EXE(pyz, a.scripts, [], exclude_binaries=True, name="OwlThread",
              console=False, icon="owlthread.ico", upx=False)
console = EXE(pyz, a.scripts, [], exclude_binaries=True, name="owlthread-cli",
              console=True, icon="owlthread.ico", upx=False)
coll = COLLECT(desktop, console, a.binaries, a.datas, name="OwlThread", upx=False)
