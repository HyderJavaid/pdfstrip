# PyInstaller spec: builds a single-file, windowed (no console) app on the current OS.
#   pyinstaller packaging/stripsafe.spec
a = Analysis(
    ["../run_stripsafe.py"],
    pathex=[".."],
    excludes=[
        # Not used by StripSafe; keeps the download smaller.
        "numpy", "matplotlib", "scipy", "pandas", "IPython", "pytest", "tkinter",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork", "PySide6.QtPdf", "PySide6.QtOpenGL",
    ],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="StripSafe",
    console=False,
    upx=False,
)
