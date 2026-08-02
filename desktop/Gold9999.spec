from pathlib import Path
﻿# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
)


PROJECT_ROOT = os.path.abspath(
    os.path.join(SPECPATH, "..")
)

LAUNCHER = os.path.join(
    PROJECT_ROOT,
    "desktop",
    "launcher.py",
)

datas = [
    (
        os.path.join(PROJECT_ROOT, "templates"),
        "templates",
    ),
    (
        os.path.join(PROJECT_ROOT, "static"),
        "static",
    ),
    (
        os.path.join(PROJECT_ROOT, "migrations"),
        "migrations",
    ),
]

binaries = []

hiddenimports = [
    "app",
    "openpyxl",
    "migrations",
    "migrations.versions",
]

hiddenimports += collect_submodules(
    "migrations.versions"
)

webview_datas, webview_binaries, webview_hiddenimports = (
    collect_all("webview")
)

datas += webview_datas
binaries += webview_binaries
hiddenimports += webview_hiddenimports


analysis = Analysis(
    [LAUNCHER],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Gold9999",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(
        Path(PROJECT_ROOT)
        / "desktop"
        / "assets"
        / "gold9999.ico"
    ),
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Gold9999",
)
