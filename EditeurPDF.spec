# -*- mode: python ; coding: utf-8 -*-
import os

has_icon = os.path.exists('Logo.ico')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('Logo.ico', '.')] if has_icon else [],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='EditeurPDF',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['Logo.ico'] if has_icon else [],
)
