# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['simple_launcher.py'],
    pathex=[],
    binaries=[('dmm_parser/dmm_parser.pyd', 'dmm_parser')],
    datas=[('dmm_parser', 'dmm_parser')],
    hiddenimports=[
        'lz4', 'lz4.block',
        'dmm_parser', 'dmm_parser.dmm_parser', 'dmm_parser.enums',
        'table_layout', 'simple_engine', 'simple_report', 'game_version', 'paz_patcher', 'paz_parse',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5'],
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
    name='CrimsonGameModsSimple',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon='app_icon.ico',
    codesign_identity=None,
    entitlements_file=None,
)
