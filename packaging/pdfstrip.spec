# PyInstaller spec: builds a single-file, windowed (no console) app on the current OS.
#   pyinstaller packaging/pdfstrip.spec
from PyInstaller.utils.hooks import collect_all

# tkinterdnd2 ships native tkdnd libraries that must be bundled for drag-and-drop.
datas, binaries, hiddenimports = [], [], []
try:
    datas, binaries, hiddenimports = collect_all("tkinterdnd2")
except Exception:
    pass  # not installed: the app falls back to the file picker

a = Analysis(
    ["../run_pdfstrip.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["numpy", "matplotlib", "scipy", "pandas", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="pdfstrip",
    console=False,
    upx=False,
)
