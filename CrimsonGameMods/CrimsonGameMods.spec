# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
Path("quest_packs").mkdir(exist_ok=True)

# Embedded Save Editor (all-in-one): regenerate save_editor/ from
# ../CrimsonSaveEditor before the analysis, so the EXE always carries the
# current Save Editor. See tools/vendor_save_editor.py.
import runpy as _runpy_se
_runpy_se.run_path(os.path.join(SPECPATH, 'tools', 'vendor_save_editor.py'), run_name='__main__')
_SE_MODULES = ['save_editor'] + sorted(
    'save_editor.' + f[:-3] for f in os.listdir(os.path.join(SPECPATH, 'save_editor'))
    if f.endswith('.py') and f != '__init__.py') + [
    'save_editor.crimson_rs', 'save_editor.crimson_rs.pack_mod',
    'save_editor.crimson_rs.create_pack', 'save_editor.crimson_rs.enums',
    'save_editor.crimson_rs.validate_game_dir']

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[('dmm_parser/dmm_parser.pyd', 'dmm_parser'), ('dmm_parser/dmm_parser.abi3.so', 'dmm_parser')],
    datas=[('crimson_data.db.gz', '.'), ('data', 'data'), ('vfx_equip_attachments.json', '.'), ('parc_parser.dll', '.'), ('locale', 'locale'), ('knowledge_packs', 'knowledge_packs'), (os.path.join(SPECPATH, '..', 'knowledge_packs'), 'knowledge_packs'), ('quest_packs', 'quest_packs'), ('dropset_packs', 'dropset_packs'), ('localizationstring_eng_items.tsv', '.'), ('pabgb_parser_local.py', '.'), ('crimson_rs', 'crimson_rs'), ('dmm_parser', 'dmm_parser'), ('game_baselines', 'game_baselines'), ('save_editor', 'save_editor')],
    hiddenimports=['table_layout', 'game_version', 'mod_check', 'schema_item_index', 'save_parser', 'client_names', 'lz4', 'lz4.block', 'iteminfo_parser', 'cryptography', 'cryptography.hazmat.primitives.ciphers', 'cryptography.hazmat.primitives.ciphers.algorithms', 'parc_inserter3', 'storeinfo_parser', 'gamedata_editor', 'pabgb_field_parsers', 'universal_pabgb_parser', 'factionnode_operator_parser', 'fieldinfo_parser', 'vehicleinfo_parser', 'regioninfo_parser', 'armor_catalog', 'character_mesh_swap', 'gimmickinfo_parser', 'pipeline_report', 'characterinfo_full_parser', 'data_db', 'gui.tabs.buffs_v319', 'gui.tabs.field_edit', 'gui.tabs.skill_tree', 'gui.tabs.patches', 'gui.tabs.pas_editor', 'gui.tabs.reserveslot', 'gui.tabs.iteminfo_inspector', 'gui.tabs.mod_loader', 'gui.tabs.dmm_webview', 'gui.item_creator_dialog', 'gui.add_to_save_dialog', 'gui.iteminfo_index', 'gui.dialogs', 'gui.theme', 'gui.utils', 'gui.icon_preview', 'gui.flow_layout', 'selftest', 'gui.selftest_ui', 'mod_conflicts', 'gui.mod_conflicts_ui', 'gui_i18n', 'i18n', 'lang_pack_downloader', 'gui.language_picker', 'item_creator', 'skilltreeinfo_parser', 'skillinfo_parser', 'mercenaryinfo_parser', 'dropset_editor', 'equipslotinfo_parser', 'gui.tabs.stacker', 'gui.tabs.mercpets', 'gui.tabs.world', 'gui.tabs.bagspace', 'gui.tabs.items', 'gui.tabs.load_manager', 'gui.tabs.quest_mods', 'icon_cache', 'item_db', 'item_packs', 'item_scanner', 'models', 'paz_patcher', 'localization', 'overlay_coordinator', 'shared_state', 'reserveslot_parser', 'store_editor', 'wantedinfo_parser', 'terrain_spawn_parser'] + _SE_MODULES,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Draw splash.png from updater.APP_VERSION on every build. The PNG in the
# repository still said v2.0.7 long after the version had moved on, because
# regenerating it (tools/regen_splash.py) was a manual step nobody ran.
try:
    import runpy as _runpy
    _runpy.run_path(os.path.join(SPECPATH, 'tools', 'regen_splash.py'), run_name='__main__')
except Exception as _e:  # the build must not fail over a picture
    print(f"WARNING: splash.png not regenerated ({_e}); the old image is used")

# Read version from updater.py so splash always matches
import re as _re
with open('updater.py', 'r') as _f:
    _m = _re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)', _f.read())
_app_ver = _m.group(1) if _m else '?'

splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(24, 195),
    text_size=10,
    text_color='#F0F0F5',
    text_default=f'v{_app_ver} — Initializing...',
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='CrimsonGameMods',
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
