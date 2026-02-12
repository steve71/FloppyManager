# -*- mode: python ; coding: utf-8 -*-
import sys

exe_name = 'FloppyManager'

a = Analysis(
    ['floppymanager.py'],
    pathex=[],
    binaries=[],
    datas=[('floppy_icon.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name=exe_name,
    console=False,
    icon='floppy_icon.ico',
)