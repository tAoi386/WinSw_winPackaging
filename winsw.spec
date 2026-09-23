# -*- mode: python ; coding: utf-8 -*-
# One self-contained application. UAC is embedded in this executable.
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['PyQt5', 'requests', 'win32api', 'win32con', 'win32service', 'win32serviceutil'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WinSw_winPackaging',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    manifest='admin.manifest',
    uac_admin=True,
)
