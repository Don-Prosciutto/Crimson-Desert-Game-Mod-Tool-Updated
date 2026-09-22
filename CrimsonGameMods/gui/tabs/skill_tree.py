"""SkillTree Editor tab — cross-character skill / moveset swapping.

Modifies skilltreeinfo.pabgb root package IDs so one character can
use another character's melee moveset. Deploys as PAZ overlay to
group 0063.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import struct
import sys
import tempfile
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QSpinBox,
    QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

OVERLAY_GROUP = "0063"
INTERNAL_DIR = "gamedata/binary__/client/bin"


class SkillTreeTab(QWidget):
    """Tab for viewing and swapping skill tree root packages."""

    status_message = Signal(str)
    config_save_requested = Signal()

    def __init__(
        self,
        config: dict,
        rebuild_papgt_fn: Optional[Callable[[str, str], str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._rebuild_papgt_fn = rebuild_papgt_fn
        self._game_path: str = ""

        # Parser state — skilltreeinfo
        self._records: list = []
        self._original_pabgh: bytes = b""
        self._original_pabgb: bytes = b""
        # Parser state — skilltreegroupinfo
        self._group_records: list = []
        self._original_grp_pabgh: bytes = b""
        self._original_grp_pabgb: bytes = b""
        self._loaded = False

        # UI state — skilltreeinfo combo table + preset buttons
        self._table: 'QTableWidget | None' = None
        self._preset_btns: list = []
        self._root_combos: dict = {}
        self._btn_swap_export: 'QPushButton | None' = None

        # Parser state — skillinfo (skill.pabgb stamina/cooldown editor)
        self._skill_entries: list[dict] = []
        self._skill_vanilla_entries: list[dict] = []
        self._skill_pabgh: bytes = b""
        self._skill_pabgb: bytes = b""
        self._skill_loaded = False

        self._build_ui()

    # -- public --------------------------------------------------------

    def set_game_path(self, path: str) -> None:
        self._game_path = path

    # -- UI construction -----------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # --- top row: Extract + Apply + Restore ---
        top_row = QHBoxLayout()
        self._btn_extract = QPushButton("Extract from Game")
        self._btn_extract.clicked.connect(self._on_extract)
        top_row.addWidget(self._btn_extract)

        self._btn_swap_export = QPushButton("Export Swap as Field JSON v3")
        self._btn_swap_export.setEnabled(False)
        self._btn_swap_export.setToolTip(
            "Export the current Cross-Character Skill Swap combo box selections\n"
            "as a Format 3 _buff_data_raw JSON for DMM (skilltreeinfo.pabgb).")
        self._btn_swap_export.clicked.connect(self._on_swap_export)
        top_row.addWidget(self._btn_swap_export)

        top_row.addStretch()

        self._btn_apply = QPushButton("Apply to Game")
        self._btn_apply.setStyleSheet(
            f"background-color: {COLORS['accent']}; color: white; "
            f"font-weight: bold; padding: 6px 16px;"
        )
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_apply.setEnabled(False)
        top_row.addWidget(self._btn_apply)

        # Overlay group number — configurable. Default 64 because 63 is
        # taken by Stacker's equipslotinfo overlay (applying both would
        # clobber). User can still pick 63 if they don't use Stacker.
        top_row.addWidget(QLabel("Overlay:"))
        self._overlay_spin = QSpinBox()
        self._overlay_spin.setRange(1, 9999)
        self._overlay_spin.setValue(self._config.get("skilltree_overlay_dir", 64))
        self._overlay_spin.setFixedWidth(70)
        self._overlay_spin.setToolTip(
            "Overlay group number (0064 = default). 0063 is reserved for\n"
            "Stacker's equipslotinfo — changing this avoids the clash.\n"
            "Apply writes to <game>/NNNN/; Restore removes the same NNNN/.")
        self._overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"skilltree_overlay_dir": int(v)}))
        top_row.addWidget(self._overlay_spin)

        self._btn_restore = QPushButton("Restore")
        self._btn_restore.clicked.connect(self._on_restore)
        top_row.addWidget(self._btn_restore)

        root.addLayout(top_row)

        # ═══════════════════════════════════════════════════════════════
        # Cross-Character Skill Swap  (skilltreeinfo.pabgb)
        # ═══════════════════════════════════════════════════════════════
        swap_grp = QGroupBox("Cross-Character Skill Swap (skilltreeinfo.pabgb)")
        swap_grp.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: {COLORS['accent']}; "
            f"border: 1px solid {COLORS.get('border', '#555')}; "
            f"border-radius: 4px; margin-top: 8px; padding-top: 14px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}"
        )
        swap_layout = QVBoxLayout(swap_grp)

        # Preset buttons row
        preset_btn_row = QHBoxLayout()
        preset_btn_row.addWidget(QLabel("Presets:"))

        from skilltreeinfo_parser import CHAR_MELEE_ROOT
        for label, color, tip, swaps in [
            ("Kliff = Oongka",   "#00695C",
             "Give Kliff the Oongka melee moveset.",
             {50: CHAR_MELEE_ROOT[51]}),
            ("Kliff = Damiane",  "#00695C",
             "Give Kliff the Damiane melee moveset.",
             {50: CHAR_MELEE_ROOT[52]}),
            ("Oongka = Kliff",   "#1565C0",
             "Give Oongka the Kliff melee moveset.",
             {51: CHAR_MELEE_ROOT[50]}),
            ("Oongka = Damiane", "#1565C0",
             "Give Oongka the Damiane melee moveset.",
             {51: CHAR_MELEE_ROOT[52]}),
            ("Damiane = Kliff",  "#6A1B9A",
             "Give Damiane the Kliff melee moveset.",
             {52: CHAR_MELEE_ROOT[50]}),
            ("Damiane = Oongka", "#6A1B9A",
             "Give Damiane the Oongka melee moveset.",
             {52: CHAR_MELEE_ROOT[51]}),
            ("Reset All",       "#B71C1C",
             "Restore all characters to their native movesets.",
             None),
        ]:
            btn = self._make_preset_btn(label, color, tip, swaps)
            preset_btn_row.addWidget(btn)

        preset_btn_row.addStretch()
        swap_layout.addLayout(preset_btn_row)

        # Skill tree table
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["Key", "Name", "Character", "Category", "Size", "Melee Root"])
        th = self._table.horizontalHeader()
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setMaximumHeight(260)
        swap_layout.addWidget(self._table)

        swap_status = QLabel("Click 'Extract from Game' to load skill tree entries.")
        swap_status.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        swap_layout.addWidget(swap_status)
        self._lbl_swap_status = swap_status

        root.addWidget(swap_grp)

        # ═══════════════════════════════════════════════════════════════
        # Skill Editor — Stamina & Cooldown Mods  (skill.pabgb)
        # ═══════════════════════════════════════════════════════════════
        self._skill_group = QGroupBox("Skill Editor — Stamina + Cooldown Mods")
        self._skill_group.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: {COLORS['accent']}; "
            f"border: 1px solid {COLORS.get('border', '#555')}; "
            f"border-radius: 4px; margin-top: 8px; padding-top: 14px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}"
        )
        sg_layout = QVBoxLayout(self._skill_group)

        # --- buttons row ---
        skill_btn_row = QHBoxLayout()

        self._btn_skill_load = QPushButton("Load SkillInfo")
        self._btn_skill_load.setToolTip(
            "Extract skill.pabgb + skill.pabgh from the game.\n"
            "Populates the table below with all skill entries.")
        self._btn_skill_load.clicked.connect(self._on_skill_load)
        skill_btn_row.addWidget(self._btn_skill_load)


        self._btn_skill_export = QPushButton("Export Field JSON v3")
        self._btn_skill_export.setStyleSheet("background-color: #0277BD; color: white; font-weight: bold;")
        self._btn_skill_export.setToolTip(
            "Export current modifications as Format 3 field-name JSON.\n"
            "This format survives game updates.")
        self._btn_skill_export.clicked.connect(self._on_skill_export_json)
        self._btn_skill_export.setEnabled(False)
        skill_btn_row.addWidget(self._btn_skill_export)



        skill_btn_row.addStretch()
        sg_layout.addLayout(skill_btn_row)

        # --- stamina preset row ---
        # --- stamina preset row ---
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        preset_lbl = QLabel("Stamina/Spirit:")
        preset_lbl.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold;")
        preset_row.addWidget(preset_lbl)

        stamina_presets = [
            ("10%", 0.10, "10% stamina drain — barely noticeable reduction."),
            ("25%", 0.25, "25% stamina drain — mild reduction."),
            ("50%", 0.50, "50% stamina drain — half drain rate."),
            ("75%", 0.75, "75% stamina drain — significant reduction."),
            ("Infinite", 0.0, "Infinite stamina — zero drain."),
        ]
        for label, factor, tip in stamina_presets:
            btn = QPushButton(label)
            btn.setToolTip(f"Apply Stamina Preset: {tip}")
            btn.setStyleSheet(
                "QPushButton { background-color: #00695C; color: white; "
                "font-weight: bold; padding: 4px 10px; }")
            btn.clicked.connect(
                lambda _c=False, f=factor: self._on_stamina_preset(f))
            preset_row.addWidget(btn)

        preset_row.addStretch()
        sg_layout.addLayout(preset_row)

        bulk_row = QHBoxLayout()
        bulk_row.setSpacing(4)
        bulk_lbl = QLabel("Bulk Mods:")
        bulk_lbl.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold;")
        bulk_row.addWidget(bulk_lbl)

        for label, tip, handler in [
            ("Zero Cooldown", "Set cooldown to 0 on ALL skills.",
             self._bulk_zero_cooldown),
            ("Free Skills", "Zero out all resource costs (stamina, MP, etc.).",
             self._bulk_free_skills),
        ]:
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "QPushButton { background-color: #B71C1C; color: white; "
                "font-weight: bold; padding: 4px 10px; }")
            btn.clicked.connect(handler)
            bulk_row.addWidget(btn)

        bulk_row.addStretch()
        sg_layout.addLayout(bulk_row)

        # --- skill table ---
        self._skill_table = QTableWidget()
        self._skill_table.setColumnCount(6)
        self._skill_table.setHorizontalHeaderLabels([
            "Name", "Key", "Cooltime", "MaxLevel", "BuffLevels", "Modified",
        ])
        sh = self._skill_table.horizontalHeader()
        sh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._skill_table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked |
            QTableWidget.EditTrigger.EditKeyPressed)
        self._skill_table.cellChanged.connect(self._on_skill_cell_changed)
        self._skill_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self._skill_table.setAlternatingRowColors(True)
        sg_layout.addWidget(self._skill_table)

        # --- skill status ---
        self._lbl_skill_status = QLabel("")
        sg_layout.addWidget(self._lbl_skill_status)

        root.addWidget(self._skill_group)

        # --- status ---
        self._lbl_status = QLabel("")
        root.addWidget(self._lbl_status)

    def _make_preset_btn(
        self, label: str, color: str, tooltip: str,
        swaps: Optional[dict[int, int]],
    ) -> QPushButton:
        """Create a styled preset button with hover tooltip."""
        btn = QPushButton(label)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(
            f"background-color: {color}; color: white; "
            f"font-weight: bold; padding: 4px 10px;"
        )
        btn.setEnabled(False)
        btn.clicked.connect(
            lambda checked=False, s=swaps: self._apply_preset(s)
        )
        self._preset_btns.append(btn)
        return btn

    # -- extract -------------------------------------------------------

    def _on_extract(self) -> None:
        game_path = self._game_path or self._config.get("game_install_path", "")
        if not game_path:
            QMessageBox.warning(self, "No game path",
                                "Set the game install path in the Patches tab first.")
            return

        try:
            import crimson_rs
            dp = INTERNAL_DIR
            pabgb = crimson_rs.extract_file(game_path, "0008", dp,
                                            "skilltreeinfo.pabgb")
            pabgh = crimson_rs.extract_file(game_path, "0008", dp,
                                            "skilltreeinfo.pabgh")
            grp_gb = crimson_rs.extract_file(game_path, "0008", dp,
                                             "skilltreegroupinfo.pabgb")
            grp_gh = crimson_rs.extract_file(game_path, "0008", dp,
                                             "skilltreegroupinfo.pabgh")
        except Exception as e:
            QMessageBox.critical(self, "Extract failed", str(e))
            return

        self._original_pabgh = bytes(pabgh)
        self._original_pabgb = bytes(pabgb)
        self._original_grp_pabgh = bytes(grp_gh)
        self._original_grp_pabgb = bytes(grp_gb)

        from skilltreeinfo_parser import parse_all, parse_groups
        self._records = parse_all(self._original_pabgh, self._original_pabgb)
        self._group_records = parse_groups(
            self._original_grp_pabgh, self._original_grp_pabgb
        )
        self._loaded = True
        self._populate_table()
        for btn in self._preset_btns:
            btn.setEnabled(True)
        self._btn_apply.setEnabled(True)
        if self._btn_swap_export is not None:
            self._btn_swap_export.setEnabled(True)
        n = len(self._records)
        if hasattr(self, '_lbl_swap_status'):
            self._lbl_swap_status.setText(
                f"{n} skill tree entries loaded — use combo boxes to redirect movesets.")
        self.status_message.emit(
            f"Loaded {n} skill tree entries "
            f"({len(self._original_pabgb)} bytes)"
        )

    def _populate_table(self) -> None:
        if self._table is None:
            return
        from skilltreeinfo_parser import ROOT_PACKAGES, CHAR_MELEE_ROOT, MAIN_TREE_KEYS

        # Sort: main tree entries (50/51/52) first so combo boxes are immediately visible
        self._records = sorted(
            self._records,
            key=lambda r: (0 if r.key in MAIN_TREE_KEYS else 1, r.key)
        )

        self._table.setRowCount(len(self._records))
        self._root_combos: dict[int, QComboBox] = {}

        pkg_labels = {v: k for k, v in ROOT_PACKAGES.items()}

        for row, rec in enumerate(self._records):
            # Key
            item_key = QTableWidgetItem(str(rec.key))
            item_key.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 0, item_key)

            # Name -- display localized name with internal name in tooltip
            item_name = QTableWidgetItem(rec.display_name)
            item_name.setToolTip(rec.name)
            self._table.setItem(row, 1, item_name)

            # Character
            item_char = QTableWidgetItem(rec.character)
            item_char.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 2, item_char)

            # Category
            item_cat = QTableWidgetItem(rec.category)
            item_cat.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 3, item_cat)

            # Size
            item_size = QTableWidgetItem(f"{len(rec.to_bytes())}B")
            item_size.setTextAlignment(Qt.AlignmentFlag.AlignRight |
                                       Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 4, item_size)

            # Melee Root -- combo for main trees, text for others
            pkgs = rec.find_root_packages()
            if rec.is_main_tree and pkgs:
                combo = QComboBox()
                for label, pkg_id in ROOT_PACKAGES.items():
                    combo.addItem(f"{label} (0x{pkg_id:04X})", pkg_id)
                # Set current to whatever the record has
                current_root = pkgs[0][1]
                for i in range(combo.count()):
                    if combo.itemData(i) == current_root:
                        combo.setCurrentIndex(i)
                        break
                self._table.setCellWidget(row, 5, combo)
                self._root_combos[rec.key] = combo
            elif pkgs:
                labels = [f"{pkg_labels.get(v, '?')} @0x{o:X}" for o, v in pkgs]
                self._table.setItem(row, 5,
                                    QTableWidgetItem("; ".join(labels)))
            else:
                self._table.setItem(row, 5, QTableWidgetItem("--"))

        self._table.resizeColumnsToContents()
        # Re-stretch name and root columns
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

    # -- presets -------------------------------------------------------

    def _apply_preset(self, swaps: Optional[dict[int, int]]) -> None:
        """Apply a preset by updating the table combo boxes."""
        if not self._loaded:
            QMessageBox.warning(self, "Not loaded",
                "Click 'Extract from Game' first to load skill tree entries.")
            return
        from skilltreeinfo_parser import CHAR_MELEE_ROOT

        if swaps is None:
            # Reset to vanilla
            swaps = dict(CHAR_MELEE_ROOT)

        first_row = None
        for key, new_root in swaps.items():
            if key in self._root_combos:
                combo = self._root_combos[key]
                for i in range(combo.count()):
                    if combo.itemData(i) == new_root:
                        combo.setCurrentIndex(i)
                        break
                # Find the row for this key to scroll to it
                if first_row is None and self._table is not None:
                    for row in range(self._table.rowCount()):
                        item = self._table.item(row, 0)
                        if item and item.text() == str(key):
                            first_row = row
                            break

        # Scroll to the first modified row so the user can see the change
        if first_row is not None and self._table is not None:
            self._table.scrollToItem(
                self._table.item(first_row, 0),
                QTableWidget.ScrollHint.PositionAtCenter)

    # -- export swap as field json -------------------------------------

    def _on_swap_export(self) -> None:
        """Export the current combo box selections as _buff_data_raw intents
        targeting skilltreeinfo.pabgb via DMM's skill_tree_info dispatcher."""
        if not self._loaded:
            QMessageBox.warning(self, "Not loaded",
                "Click 'Extract from Game' first.")
            return

        import json as _json
        from PySide6.QtWidgets import QFileDialog
        from skilltreeinfo_parser import (
            parse_all, serialize_all, CHAR_MELEE_ROOT
        )

        # Parse vanilla records from the original bytes
        vanilla_records = parse_all(
            self._original_pabgh, self._original_pabgb)
        van_by_key = {r.key: r for r in vanilla_records}

        # Build modified records by applying current combo selections
        import copy as _copy
        mod_records = parse_all(
            self._original_pabgh, self._original_pabgb)
        mod_by_key = {r.key: r for r in mod_records}

        intents = []
        changed = 0

        # Build the full set of swaps from the current combo selections
        # {native_root: new_root} for each character whose combo changed
        root_swaps: dict[int, int] = {}
        for char_key, combo in self._root_combos.items():
            new_root = combo.currentData()
            if new_root is None:
                continue
            native_root = CHAR_MELEE_ROOT.get(char_key)
            if native_root is None or new_root == native_root:
                continue
            root_swaps[native_root] = new_root

        if not root_swaps:
            QMessageBox.information(self, "Export Swap",
                "No changes detected — all combos are at their vanilla values.\n"
                "Select a different moveset from the combo boxes first.")
            return

        # Patch ALL records that contain any of the native root package IDs
        # (not just the main tree entry — weapon/martial art/special skill
        # entries also reference the melee root and need to be updated too)
        for van_rec, mod_rec in zip(vanilla_records, mod_records):
            van_bytes = van_rec.to_bytes()
            patched = False
            for native_root, new_root in root_swaps.items():
                count = mod_rec.patch_root_package(native_root, new_root)
                if count > 0:
                    patched = True
            if not patched:
                continue
            mod_bytes = mod_rec.to_bytes()
            if van_bytes == mod_bytes:
                continue
            intents.append({
                'entry': mod_rec.name,
                'key': mod_rec.key,
                'field': '_buff_data_raw',
                'old': van_bytes.hex(),
                'new': mod_bytes.hex(),
            })
            changed += 1

        doc = {
            'modinfo': {
                'title': 'Cross-Character Skill Swap',
                'version': '1.0',
                'author': 'CrimsonGameMods SkillTree',
                'description': f'{changed} skilltreeinfo entry swap(s)',
                'note': 'Format 3 — _buff_data_raw byte-replace via dmmski dispatcher',
            },
            'format': 3,
            'format_minor': 1,
            'target': 'skilltreeinfo.pabgb',
            'intents': intents,
            'targets': [{'file': 'skilltreeinfo.pabgb', 'intents': intents}],
        }

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Skill Swap",
            "SkillSwap.field.json",
            "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            return

        with open(path, 'w', encoding='utf-8') as f:
            _json.dump(doc, f, indent=2, ensure_ascii=False)

        QMessageBox.information(self, "Export Swap",
            f"Exported {len(intents)} swap intent(s).\n\n"
            f"Drop the JSON into your DMM mods folder.")

    # -- apply to game -------------------------------------------------

    def _on_apply(self) -> None:
        if not self._loaded and not self._skill_loaded:
            QMessageBox.warning(self, "Not loaded",
                                "Extract skill tree data or load SkillInfo first.")
            return

        game_path = self._game_path or self._config.get("game_install_path", "")
        if not game_path:
            QMessageBox.warning(self, "No game path",
                                "Set the game install path first.")
            return

        try:
            self._apply_to_game(game_path)
        except Exception as e:
            log.exception("SkillTree apply failed")
            QMessageBox.critical(self, "Apply failed", str(e))

    def get_staged_files(self) -> dict[str, bytes]:
        if not self._loaded or not self._original_pabgh:
            return {}
        result = {}
        try:
            from skilltreeinfo_parser import (
                CHAR_MELEE_ROOT, parse_all, serialize_all,
                parse_groups, serialize_groups,
            )
            records = parse_all(self._original_pabgh, self._original_pabgb)
            groups = parse_groups(self._original_grp_pabgh, self._original_grp_pabgb)
            any_change = False
            root_combos = getattr(self, '_root_combos', {})
            for rec in records:
                if rec.key not in root_combos:
                    continue
                combo = root_combos[rec.key]
                new_root = combo.currentData()
                native_root = CHAR_MELEE_ROOT.get(rec.key)
                if native_root is not None and new_root != native_root:
                    rec.patch_root_package(native_root, new_root)
                    any_change = True
            if any_change:
                pabgh, pabgb = serialize_all(records)
                grp_gh, grp_gb = serialize_groups(groups)
                result["skilltreeinfo.pabgb"] = bytes(pabgb)
                result["skilltreeinfo.pabgh"] = bytes(pabgh)
                result["skilltreegroupinfo.pabgb"] = bytes(grp_gb)
                result["skilltreegroupinfo.pabgh"] = bytes(grp_gh)
        except Exception:
            pass
        # Also include skill.pabgb if stamina/cooldown edits are pending
        try:
            if self._has_skill_modifications():
                if getattr(self, '_skill_dmm_loaded', False):
                    import dmm_parser as _dmp_ser
                    new_pabgb = bytes(_dmp_ser.serialize_table(
                        'skill_info', self._skill_entries))
                    result["skill.pabgb"] = new_pabgb
                    result["skill.pabgh"] = self._skill_pabgh
                else:
                    import skillinfo_parser as sip
                    skill_pabgh, skill_pabgb = sip.serialize_all(self._skill_entries)
                    result["skill.pabgb"] = bytes(skill_pabgb)
                    result["skill.pabgh"] = bytes(skill_pabgh)
        except Exception:
            pass
        return result

    def _apply_to_game(self, game_path: str) -> None:
        import crimson_rs
        from skilltreeinfo_parser import (
            CHAR_MELEE_ROOT, VANILLA_GROUP_KEYS,
            parse_all, serialize_all, parse_groups, serialize_groups,
        )

        any_change = False
        changes: list[str] = []
        records = []
        groups = []

        # Re-parse from originals to get clean state (only if skilltree was loaded)
        if self._loaded and self._original_pabgh:
            records = parse_all(self._original_pabgh, self._original_pabgb)
            groups = parse_groups(self._original_grp_pabgh, self._original_grp_pabgb)

        # --- Apply root package combo selections (skilltreeinfo) ---
        root_combos = getattr(self, '_root_combos', {})
        for rec in records:
            if rec.key not in root_combos:
                continue
            combo = root_combos[rec.key]
            new_root = combo.currentData()
            native_root = CHAR_MELEE_ROOT.get(rec.key)
            if native_root is None:
                continue
            if new_root != native_root:
                count = rec.patch_root_package(native_root, new_root)
                if count > 0:
                    any_change = True
                    changes.append(
                        f"{rec.name}: root 0x{native_root:04X} -> "
                        f"0x{new_root:04X} ({count} refs)"
                    )

        # --- Apply group key redirects (skilltreegroupinfo) ---
        # Detect which main tree combos point to a different character
        # and redirect the corresponding group
        main_key_to_char = {50: "Kliff", 51: "Oongka", 52: "Damiane"}
        char_to_main_key = {"Kliff": 50, "Oongka": 51, "Damiane": 52}
        char_to_weapon_keys = {
            "Kliff": [1, 2, 3, 4],
            "Oongka": [11, 12, 13],
            "Damiane": [21, 22, 23],
        }
        char_to_main_grp = {
            "Kliff": 1000000, "Oongka": 1000001, "Damiane": 1000002,
        }
        char_to_wpn_grp = {
            "Kliff": 1000007, "Oongka": 1000011, "Damiane": 1000014,
        }

        for rec_key, combo in root_combos.items():
            new_root = combo.currentData()
            native_root = CHAR_MELEE_ROOT.get(rec_key)
            if native_root is None or new_root == native_root:
                continue

            # Figure out which character this record belongs to and
            # which character's tree we're swapping in
            owner_char = main_key_to_char.get(rec_key)
            source_char = None
            for ch, root in CHAR_MELEE_ROOT.items():
                if root == new_root:
                    source_char = main_key_to_char.get(ch)
                    break
            if not owner_char or not source_char:
                continue

            # Redirect main skill group
            main_grp_key = char_to_main_grp[owner_char]
            source_main_key = char_to_main_key[source_char]
            for grp in groups:
                if grp.key == main_grp_key:
                    vanilla = VANILLA_GROUP_KEYS.get(main_grp_key, grp.tree_keys)
                    if grp.tree_keys != [source_main_key]:
                        grp.tree_keys = [source_main_key]
                        any_change = True
                        changes.append(
                            f"{grp.name}: tree keys "
                            f"{vanilla} -> [{source_main_key}]"
                        )
                    break

            # Redirect weapon skill group
            wpn_grp_key = char_to_wpn_grp[owner_char]
            source_wpn_keys = char_to_weapon_keys[source_char]
            for grp in groups:
                if grp.key == wpn_grp_key:
                    vanilla = VANILLA_GROUP_KEYS.get(wpn_grp_key, grp.tree_keys)
                    if grp.tree_keys != source_wpn_keys:
                        grp.tree_keys = list(source_wpn_keys)
                        any_change = True
                        changes.append(
                            f"{grp.name}: tree keys "
                            f"{vanilla} -> {source_wpn_keys}"
                        )
                    break

        # Check if we have skill.pabgb edits too
        has_skill_edits = self._has_skill_modifications()

        if not any_change and not has_skill_edits:
            QMessageBox.information(self, "No changes",
                                    "All trees are at their vanilla values and\n"
                                    "no skill edits are pending.\n"
                                    "Nothing to deploy.")
            return

        from gui.utils import resolve_overlay_group
        requested = self._overlay_spin.value()
        group_num = resolve_overlay_group(game_path, requested, "SkillTree", parent=self)
        if group_num is None:
            return
        if group_num != requested:
            self._overlay_spin.setValue(group_num)
        overlay_group = f"{group_num:04d}"

        # Build overlay with PackGroupBuilder(NONE)
        with tempfile.TemporaryDirectory() as tmp_dir:
            group_dir = os.path.join(tmp_dir, overlay_group)
            os.makedirs(group_dir, exist_ok=True)

            builder = crimson_rs.PackGroupBuilder(
                group_dir,
                crimson_rs.Compression.NONE,
                crimson_rs.Crypto.NONE,
            )

            # Pack skilltreeinfo + skilltreegroupinfo if tree swaps changed
            if any_change:
                new_pabgh, new_pabgb = serialize_all(records)
                new_grp_gh, new_grp_gb = serialize_groups(groups)
                builder.add_file(INTERNAL_DIR, "skilltreeinfo.pabgb", new_pabgb)
                builder.add_file(INTERNAL_DIR, "skilltreeinfo.pabgh", new_pabgh)
                builder.add_file(INTERNAL_DIR, "skilltreegroupinfo.pabgb", new_grp_gb)
                builder.add_file(INTERNAL_DIR, "skilltreegroupinfo.pabgh", new_grp_gh)

            # Pack skill.pabgb + skill.pabgh if skill edits are active
            if has_skill_edits:
                if getattr(self, '_skill_dmm_loaded', False):
                    import dmm_parser as _dmp_ser2
                    _new_pabgb = bytes(_dmp_ser2.serialize_table(
                        'skill_info', self._skill_entries))
                    builder.add_file(INTERNAL_DIR, "skill.pabgb", _new_pabgb)
                    builder.add_file(INTERNAL_DIR, "skill.pabgh", self._skill_pabgh)
                else:
                    import skillinfo_parser as sip
                    skill_pabgh, skill_pabgb = sip.serialize_all(self._skill_entries)
                    builder.add_file(INTERNAL_DIR, "skill.pabgb", skill_pabgb)
                    builder.add_file(INTERNAL_DIR, "skill.pabgh", skill_pabgh)
                mod_count = self._count_skill_modifications()
                changes.append(f"skill.pabgb: {mod_count} skill(s) modified")

            pamt_bytes = bytes(builder.finish())

            # Get PAMT self-reported checksum
            pamt_checksum = crimson_rs.parse_pamt_bytes(pamt_bytes)[
                "checksum"
            ]

            # Deploy files to game directory
            game_mod = os.path.join(game_path, overlay_group)
            if os.path.isdir(game_mod):
                shutil.rmtree(game_mod)
            os.makedirs(game_mod, exist_ok=True)

            shutil.copy2(
                os.path.join(group_dir, "0.paz"),
                os.path.join(game_mod, "0.paz"),
            )
            shutil.copy2(
                os.path.join(group_dir, "0.pamt"),
                os.path.join(game_mod, "0.pamt"),
            )

        # Update PAPGT -- read CURRENT, dedupe, add our entry
        papgt_path = os.path.join(game_path, "meta", "0.papgt")
        papgt = crimson_rs.parse_papgt_file(papgt_path)
        papgt["entries"] = [
            e for e in papgt["entries"]
            if e.get("group_name") != overlay_group
        ]
        papgt = crimson_rs.add_papgt_entry(
            papgt, overlay_group, pamt_checksum, 0, 16383
        )
        crimson_rs.write_papgt_file(papgt, papgt_path)

        try:
            from shared_state import record_overlay
            overlay_files = []
            if any_change:
                overlay_files.extend([
                    "skilltreeinfo.pabgb", "skilltreeinfo.pabgh",
                    "skilltreegroupinfo.pabgb", "skilltreegroupinfo.pabgh",
                ])
            if has_skill_edits:
                overlay_files.extend(["skill.pabgb", "skill.pabgh"])
            record_overlay(game_path, overlay_group, "SkillTree swaps",
                           overlay_files)
        except Exception:
            pass

        # Write marker file
        with open(os.path.join(game_mod, ".se_skilltree"), "w") as f:
            f.write("Created by CrimsonGameMods SkillTree tab\n")
            for c in changes:
                f.write(f"  {c}\n")

        summary = "\n".join(changes)
        self._lbl_status.setText(f"Deployed to {overlay_group}/")
        self.status_message.emit(
            f"SkillTree overlay deployed to {overlay_group}/ "
            f"({len(changes)} swap(s))"
        )
        QMessageBox.information(
            self, "Deployed",
            f"Skill tree overlay deployed to {overlay_group}/\n\n"
            f"{summary}\n\n"
            f"Restart the game to apply changes.",
        )

    # -- restore -------------------------------------------------------

    def _on_restore(self) -> None:
        game_path = self._game_path or self._config.get("game_install_path", "")
        if not game_path:
            QMessageBox.warning(self, "No game path",
                                "Set the game install path first.")
            return

        overlay_group = f"{self._overlay_spin.value():04d}"
        game_mod = os.path.join(game_path, overlay_group)
        if not os.path.isdir(game_mod):
            QMessageBox.information(self, "Nothing to restore",
                                    f"No {overlay_group}/ overlay found.")
            return

        try:
            # Remove PAPGT entry first
            if self._rebuild_papgt_fn:
                msg = self._rebuild_papgt_fn(game_path, overlay_group)
                log.info("PAPGT restore: %s", msg)

            # Remove overlay directory
            shutil.rmtree(game_mod)
            try:
                from overlay_coordinator import post_restore
                post_restore(game_path, overlay_group)
            except Exception:
                pass

            self._lbl_status.setText("Restored -- overlay removed")
            self.status_message.emit(
                f"SkillTree overlay {overlay_group}/ removed"
            )
            QMessageBox.information(
                self, "Restored",
                f"Removed {overlay_group}/ overlay.\n"
                f"Restart the game to revert to vanilla skill trees.",
            )
        except Exception as e:
            log.exception("SkillTree restore failed")
            QMessageBox.critical(self, "Restore failed", str(e))

    # ══════════════════════════════════════════════════════════════════
    # Skill Editor — skill.pabgb stamina / cooldown mods
    # ══════════════════════════════════════════════════════════════════

    def _on_skill_load(self) -> None:
        """Extract skill.pabgb + skill.pabgh from the game."""
        game_path = self._game_path or self._config.get("game_install_path", "")
        if not game_path:
            QMessageBox.warning(self, "No game path",
                                "Set the game install path in the Patches tab first.")
            return

        try:
            import crimson_rs
            dp = INTERNAL_DIR
            pabgb = bytes(crimson_rs.extract_file(game_path, "0008", dp,
                                                   "skill.pabgb"))
            pabgh = bytes(crimson_rs.extract_file(game_path, "0008", dp,
                                                   "skill.pabgh"))
        except Exception as e:
            QMessageBox.critical(self, "Extract failed", str(e))
            return

        self._skill_pabgh = pabgh
        self._skill_pabgb = pabgb

        # Try dmm_parser first — gives proper field names and structured data.
        # Fall back to skillinfo_parser if dmm_parser doesn't support skill_info
        # or returns 0 entries (older bundled version).
        dmm_loaded = False
        try:
            import dmm_parser as _dmp_sk
            import copy as _copy_sk
            dmm_entries = list(_dmp_sk.parse_table('skill_info', pabgb, pabgh))
            if dmm_entries:
                self._skill_entries = dmm_entries
                self._skill_vanilla_entries = _copy_sk.deepcopy(dmm_entries)
                self._skill_dmm_loaded = True
                dmm_loaded = True
                self._skill_loaded = True
                self._skill_dirty_keys: set = set()
                self._btn_skill_export.setEnabled(True)
                self._btn_apply.setEnabled(True)
                self._populate_skill_table()
                self._lbl_skill_status.setText(
                    f"Loaded {len(self._skill_entries)} skills via dmm_parser "
                    f"({len(pabgb):,} bytes)")
                self.status_message.emit(
                    f"Loaded {len(self._skill_entries)} skill entries (dmm_parser)")
            else:
                log.warning("dmm_parser returned 0 skill_info entries — "
                            "falling back to skillinfo_parser")
        except Exception as _dmp_err:
            log.warning("dmm_parser skill_info failed (%s) — "
                        "falling back to skillinfo_parser", _dmp_err)

        if not dmm_loaded:
            try:
                import skillinfo_parser as sip
                self._skill_entries = sip.parse_all(pabgh, pabgb)
                self._skill_vanilla_entries = sip.parse_all(pabgh, pabgb)
                self._skill_dmm_loaded = False
            except Exception as e:
                QMessageBox.critical(self, "Parse failed",
                                     f"skillinfo_parser.parse_all failed:\n{e}")
                return

            self._skill_loaded = True
            self._skill_dirty_keys: set = set()
            self._btn_skill_export.setEnabled(True)
            self._btn_apply.setEnabled(True)
            self._populate_skill_table()
            self._lbl_skill_status.setText(
                f"Loaded {len(self._skill_entries)} skills "
                f"({len(pabgb):,} bytes)")
            self.status_message.emit(
                f"Loaded {len(self._skill_entries)} skill entries from skill.pabgb")

    def _populate_skill_table(self) -> None:
        """Fill the skill table from self._skill_entries."""
        import skillinfo_parser as sip

        entries = self._skill_entries
        self._skill_table.setRowCount(len(entries))

        self._skill_table_updating = True
        for row, e in enumerate(entries):
            # Name — dmm_parser uses 'string_key', skillinfo_parser uses 'name'
            display_name = e.get('name', e.get('string_key', str(e.get('key', row))))
            item = QTableWidgetItem(display_name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            dn = e.get('dev_skill_name', b'')
            if isinstance(dn, bytes):
                dn = dn.decode('utf-8', 'replace')
            item.setToolTip(dn if dn else display_name)
            self._skill_table.setItem(row, 0, item)

            # Key (read-only)
            ki = QTableWidgetItem(str(e['key']))
            ki.setFlags(ki.flags() & ~Qt.ItemFlag.ItemIsEditable)
            ki.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._skill_table.setItem(row, 1, ki)

            # Cooltime: dmm_parser='cooltime', IDA parser='field_12', legacy='_cooltime'
            ct_val = e.get('cooltime', e.get('field_12', e.get('_cooltime', 0)))
            if isinstance(ct_val, dict): ct_val = next(iter(ct_val.values()), 0)
            ct = QTableWidgetItem(str(ct_val))
            ct.setTextAlignment(Qt.AlignmentFlag.AlignRight |
                                Qt.AlignmentFlag.AlignVCenter)
            self._skill_table.setItem(row, 2, ct)

            # MaxLevel (editable)
            ml = QTableWidgetItem(str(e.get('max_level', e.get('_maxLevel', 0))))
            ml.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._skill_table.setItem(row, 3, ml)

            # BuffLevels (read-only) — dmm_parser has 'buff_level_list', skillinfo_parser has '_buffLevelCount'
            bl_count = e.get('_buffLevelCount', len(e.get('buff_level_list', [])))
            bl = QTableWidgetItem(str(bl_count))
            bl.setFlags(bl.flags() & ~Qt.ItemFlag.ItemIsEditable)
            bl.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._skill_table.setItem(row, 4, bl)

            # Modified (read-only)
            mod = self._is_skill_entry_modified(row)
            mi = QTableWidgetItem("Yes" if mod else "")
            mi.setFlags(mi.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if mod:
                mi.setForeground(Qt.GlobalColor.yellow)
            mi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._skill_table.setItem(row, 5, mi)
        self._skill_table_updating = False

        self._skill_table.resizeColumnsToContents()
        sh = self._skill_table.horizontalHeader()
        sh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def _on_skill_cell_changed(self, row: int, col: int) -> None:
        if getattr(self, '_skill_table_updating', False):
            return
        if not self._skill_loaded or row >= len(self._skill_entries):
            return
        e = self._skill_entries[row]
        self._skill_dirty_keys.add(e.get('key', row))
        item = self._skill_table.item(row, col)
        if not item:
            return
        try:
            val = int(item.text())
        except ValueError:
            self._lbl_skill_status.setText(f"Invalid value — must be an integer.")
            return

        if col == 2:  # Cooltime
            e['_cooltime'] = val
            e['cooltime'] = val
            e['field_12'] = val
            e.pop('_raw', None)
        elif col == 3:  # MaxLevel
            e['max_level'] = val
            e.pop('_raw', None)
        else:
            return

        # Update Modified column
        self._skill_table_updating = True
        mod = self._is_skill_entry_modified(row)
        mi = self._skill_table.item(row, 5)
        if mi:
            mi.setText("Yes" if mod else "")
            if mod:
                mi.setForeground(Qt.GlobalColor.yellow)
        self._skill_table_updating = False
        self._lbl_skill_status.setText(
            f"{e['name']}: {'cooltime' if col == 2 else 'max_level'} = {val}")

    def _is_skill_entry_modified(self, idx: int) -> bool:
        """Check if skill entry at idx differs from vanilla."""
        if idx >= len(self._skill_vanilla_entries):
            return True
        if getattr(self, '_skill_dmm_loaded', False):
            return self._skill_entries[idx] != self._skill_vanilla_entries[idx]
        import skillinfo_parser as sip
        cur = sip.serialize_entry(self._skill_entries[idx])
        van = sip.serialize_entry(self._skill_vanilla_entries[idx])
        return cur != van

    def _has_skill_modifications(self) -> bool:
        """Return True if any skill entry has been modified."""
        if not self._skill_loaded or not self._skill_entries:
            return False
        if getattr(self, '_skill_dmm_loaded', False):
            return any(self._skill_entries[i] != self._skill_vanilla_entries[i]
                       for i in range(min(len(self._skill_entries),
                                          len(self._skill_vanilla_entries))))
        import skillinfo_parser as sip
        for i, e in enumerate(self._skill_entries):
            if i >= len(self._skill_vanilla_entries):
                return True
            if sip.serialize_entry(e) != sip.serialize_entry(
                    self._skill_vanilla_entries[i]):
                return True
        return False

    def _count_skill_modifications(self) -> int:
        """Count how many skill entries are modified."""
        if not self._skill_loaded:
            return 0
        import skillinfo_parser as sip
        count = 0
        for i, e in enumerate(self._skill_entries):
            if i >= len(self._skill_vanilla_entries):
                count += 1
            elif sip.serialize_entry(e) != sip.serialize_entry(
                    self._skill_vanilla_entries[i]):
                count += 1
        return count

    # -- Import Legacy Mod -----------------------------------------------

    def _on_skill_import_legacy(self, preset_path: str = None) -> None:
        """Import a CrimsonWings-style Format 2 JSON targeting skill.pabgb."""
        if not self._skill_loaded:
            QMessageBox.warning(self, "Not loaded",
                                "Load SkillInfo first.")
            return

        if preset_path:
            path = preset_path
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import Legacy skill.pabgb Mod", "",
                "JSON files (*.json);;All Files (*)")
        if not path:
            return

        try:
            with open(path, encoding='utf-8') as f:
                doc = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Import Failed",
                                 f"Could not read JSON:\n{e}")
            return

        # Extract changes
        changes = []
        for p in doc.get('patches', []):
            changes.extend(p.get('changes', []))
        if not changes:
            QMessageBox.warning(self, "Import Failed",
                                "No changes found in the JSON file.")
            return

        # Find best baseline
        baselines = self._discover_skill_baselines()
        if not baselines:
            QMessageBox.critical(self, "Import Failed",
                                 "No skill.pabgb baselines found in game_baselines/.\n"
                                 "Place a vanilla skill.pabgb in game_baselines/<version>/")
            return

        best_ver, best_data, best_pabgh = self._score_skill_baselines(
            baselines, changes)
        if best_data is None:
            QMessageBox.critical(self, "Import Failed",
                                 "Could not match any baseline to this mod.")
            return

        # Apply byte patches to baseline (reverse-offset-sorted for inserts)
        patched_data = bytearray(best_data)
        applied = 0
        sorted_changes = sorted(
            changes,
            key=lambda c: self._parse_offset(c.get('offset', 0)),
            reverse=True)
        for c in sorted_changes:
            applied += _apply_one_skill_patch(patched_data, best_data, c)

        # Parse both vanilla baseline and patched with skillinfo_parser
        # Use the baseline's OWN pabgh — different game versions have
        # different entry counts and offsets.
        import skillinfo_parser as sip
        try:
            vanilla_entries = sip.parse_all(best_pabgh, best_data)
            patched_entries = sip.parse_all(best_pabgh,
                                            bytes(patched_data))
        except Exception as e:
            QMessageBox.critical(self, "Import Failed",
                                 f"Failed to parse patched data:\n{e}")
            return

        # Build name lookup for patched entries
        patched_by_name = {e['name']: e for e in patched_entries}
        vanilla_by_name = {e['name']: e for e in vanilla_entries}

        # Diff: find entries where serialized bytes differ
        modified_names = []
        for name, van_e in vanilla_by_name.items():
            pat_e = patched_by_name.get(name)
            if pat_e is None:
                continue
            if sip.serialize_entry(van_e) != sip.serialize_entry(pat_e):
                modified_names.append(name)

        if not modified_names:
            QMessageBox.information(self, "Import Complete",
                                    f"Applied {applied} patches but no skill "
                                    f"entries changed (mod may be for a different "
                                    f"game version).")
            return

        # Transfer changes to current game entries.
        # Only copy fields that ACTUALLY DIFFER between old vanilla and old
        # patched — don't blindly overwrite the whole entry, since the new
        # game version may have different structure in unchanged fields.
        current_by_name = {e['name']: i for i, e in
                           enumerate(self._skill_entries)}
        transferred = 0
        for name in modified_names:
            van_e = vanilla_by_name[name]
            pat_e = patched_by_name[name]
            idx = current_by_name.get(name)
            if idx is None:
                continue
            cur_e = self._skill_entries[idx]
            changed_fields = 0
            for field in pat_e:
                if field in ('key', 'name', 'name_len', '_raw'):
                    continue
                if pat_e.get(field) != van_e.get(field):
                    cur_e[field] = pat_e[field]
                    changed_fields += 1
            cur_e.pop('_raw', None)
            if changed_fields > 0:
                transferred += 1

        self._populate_skill_table()
        self._lbl_skill_status.setText(
            f"Imported: {transferred} skill(s) modified from {os.path.basename(path)}")
        self.status_message.emit(
            f"Imported legacy mod: {transferred}/{len(modified_names)} "
            f"skills transferred (baseline: {best_ver})")
        QMessageBox.information(
            self, "Import Complete",
            f"Baseline: {best_ver}\n"
            f"Patches applied: {applied}/{len(changes)}\n"
            f"Skills modified: {transferred}\n\n"
            "")

    def _discover_skill_baselines(self) -> list[tuple[str, str]]:
        """Find all available skill.pabgb baselines."""
        baselines: list[tuple[str, str]] = []
        for base in [os.path.dirname(os.path.abspath(__file__)),
                     getattr(sys, '_MEIPASS', ''), os.getcwd()]:
            for rel in [os.path.join(base, '..', '..', 'game_baselines'),
                        os.path.join(base, 'game_baselines')]:
                bd = os.path.normpath(rel)
                if not os.path.isdir(bd):
                    continue
                for ver in sorted(os.listdir(bd)):
                    candidate = os.path.join(bd, ver, 'skill.pabgb')
                    if os.path.isfile(candidate):
                        baselines.append((ver, candidate))
            if baselines:
                break

        # Also consider the currently loaded vanilla as a baseline
        if self._skill_pabgb and not baselines:
            baselines.append(("current", "__loaded__"))

        return baselines

    def _score_skill_baselines(
        self, baselines: list[tuple[str, str]], changes: list[dict],
    ) -> tuple[str, bytes | None, bytes | None]:
        """Score baselines by how many 'original' hex values match.
        Returns (version, raw_pabgb, raw_pabgh) of the best match."""
        best_ver = ""
        best_score = -1
        best_data: bytes | None = None
        best_pabgh: bytes | None = None

        for ver, path in baselines:
            if path == "__loaded__":
                data = self._skill_pabgb
                pabgh = self._skill_pabgh
            else:
                try:
                    with open(path, 'rb') as f:
                        data = f.read()
                    pabgh_path = path.replace('.pabgb', '.pabgh')
                    with open(pabgh_path, 'rb') as f:
                        pabgh = f.read()
                except Exception:
                    continue

            score = 0
            for c in changes:
                off = c.get('offset')
                orig_hex = c.get('original', '')
                if off is None or not orig_hex:
                    continue
                off = self._parse_offset(off)
                try:
                    orig_bytes = bytes.fromhex(orig_hex)
                except ValueError:
                    continue
                if off + len(orig_bytes) <= len(data):
                    if data[off:off + len(orig_bytes)] == orig_bytes:
                        score += 1

            if score > best_score:
                best_score = score
                best_ver = ver
                best_data = data
                best_pabgh = pabgh

        return best_ver, best_data, best_pabgh

    @staticmethod
    def _parse_offset(off) -> int:
        """Parse an offset value that may be int or hex string."""
        if isinstance(off, int):
            return off
        if isinstance(off, str):
            s = off.strip()
            if s.lower().startswith('0x'):
                return int(s, 16)
            try:
                return int(s, 16)
            except ValueError:
                return int(s)
        return int(off)

    # -- Export Field JSON -----------------------------------------------

    def _bulk_ensure_loaded(self) -> bool:
        if not self._skill_loaded:
            self._on_skill_load()
        return self._skill_loaded

    def _bulk_zero_cooldown(self) -> None:
        if not self._bulk_ensure_loaded():
            return
        count = 0
        for e in self._skill_entries:
            # Try all known field name variants for cooltime:
            # dmm_parser: 'cooltime' | IDA parser: 'field_12' | legacy: '_cooltime'
            _ct_val = e.get('cooltime', e.get('field_12', e.get('_cooltime', 0)))
            if isinstance(_ct_val, dict):
                _ct_val = next(iter(_ct_val.values()), 0)
            if True:  # apply to all skills regardless of current value
                e['cooltime'] = 0
                e['field_12'] = 0
                e['_cooltime'] = 0
                e.pop('_raw', None)
                self._skill_dirty_keys.add(e.get('key', 0))
                count += 1
        self._populate_skill_table()
        self._lbl_skill_status.setText(f"Zero Cooldown: {count} skills modified")
        QMessageBox.information(self, "Zero Cooldown",
            f"Set cooldown to 0 on {count} skills.")

    def _bulk_free_skills(self) -> None:
        if not self._bulk_ensure_loaded():
            return
        import skillinfo_parser as sip
        count = 0
        for e in self._skill_entries:
            # dmm_parser: 'use_resource_stat_list'; old parser: '_useResourceStatList'
            res_list = e.get('use_resource_stat_list', e.get('_useResourceStatList', []))
            if res_list:
                for res in res_list:
                    if isinstance(res, dict) and res.get('value', 0) != 0:
                        res['value'] = 0
                        count += 1
                        self._skill_dirty_keys.add(e.get('key', 0))
                e.pop('_raw', None)
        self._populate_skill_table()
        self._lbl_skill_status.setText(f"Free Skills: {count} resource costs zeroed")
        QMessageBox.information(self, "Free Skills",
            f"Zeroed {count} resource costs across all skills.\n\n"
            "")

    def _bulk_max_level(self) -> None:
        if not self._bulk_ensure_loaded():
            return
        count = 0
        for e in self._skill_entries:
            if e.get('_maxLevel', 0) != 30 or e.get('max_level', 0) != 30:
                e['_maxLevel'] = 30
                e['max_level'] = 30
                e.pop('_raw', None)
                self._skill_dirty_keys.add(e.get('key', 0))
                count += 1
        self._populate_skill_table()
        self._lbl_skill_status.setText(f"Max Level 30: {count} skills modified")
        QMessageBox.information(self, "Max Level 30",
            f"Set max level to 30 on {count} skills.")

    def _bulk_permanent_buffs(self) -> None:
        if not self._bulk_ensure_loaded():
            return
        count = 0
        for e in self._skill_entries:
            flag = e.get('_buffSustainFlag', 0)
            if flag != 1:
                e['_buffSustainFlag'] = 1
                e['buff_sustain_flag'] = 1
                e.pop('_raw', None)
                self._skill_dirty_keys.add(e.get('key', 0))
                count += 1
        self._populate_skill_table()
        self._lbl_skill_status.setText(f"Permanent Buffs: {count} skills set to sustain")
        QMessageBox.information(self, "Permanent Buffs",
            f"Set _buffSustainFlag=1 on {count} skills.\n\n"
            f"Food buffs, combat buffs, and other timed effects\n"
            f"should now persist permanently.\n\n"
            "")

    def _bulk_crowwing_to_rocket(self) -> None:
        """Test: full body swap between same-size skills across characters."""
        if not self._bulk_ensure_loaded():
            return
        import skillinfo_parser as sip

        by_name = {e['name']: e for e in self._skill_entries}

        # Swap entire entry bodies between same-size skill pairs
        # This swaps ALL data (buff levels, resource costs, everything)
        # while keeping the entry header (key, name) intact
        swaps = [
            ('Skill_Kliff_MpIce', 'Skill_Damian_JumpStep'),
            ('Skill_ElementalReinforce', 'Skill_Damian_ShieldThrow_II'),
            ('Skill_Nature', 'Skill_Damian_ElementalReinforce'),
        ]

        count = 0
        details = []
        for src_name, tgt_name in swaps:
            src = by_name.get(src_name)
            tgt = by_name.get(tgt_name)
            if not src or not tgt:
                continue

            src_bytes = sip.serialize_entry(src)
            tgt_bytes = sip.serialize_entry(tgt)
            if len(src_bytes) != len(tgt_bytes):
                continue

            # Swap all fields EXCEPT identity (key, name, name_len, name_bytes)
            save_keys = ('key', 'name', 'name_len', 'name_bytes')
            src_saved = {k: src[k] for k in save_keys}
            tgt_saved = {k: tgt[k] for k in save_keys}

            # Copy all tgt fields into src
            for k in list(tgt.keys()):
                if k not in save_keys:
                    src[k] = tgt[k]
            # Restore identity
            for k, v in src_saved.items():
                src[k] = v
            src.pop('_raw', None)

            count += 1
            details.append(f"{src_name} now has {tgt_name}'s data")

        self._populate_skill_table()
        detail_str = '\n'.join(details) if details else 'No swaps applied'
        self._lbl_skill_status.setText(f"Skill Swap: {count} pairs swapped")
        QMessageBox.information(self, "Skill Body Swap",
            f"Swapped full skill data between {count} pairs:\n\n"
            f"{detail_str}\n\n"
            "")

    def _bulk_unlock_all(self) -> None:
        if not self._bulk_ensure_loaded():
            return
        count = 0
        for e in self._skill_entries:
            char_list = e.get('_usableCharacterInfoList', [])
            if char_list:
                e['_usableCharacterInfoList'] = []
                e.pop('_raw', None)
                count += 1
        self._populate_skill_table()
        self._lbl_skill_status.setText(f"Unlock All: {count} skills unlocked for all characters")
        QMessageBox.information(self, "Unlock All",
            f"Cleared character restrictions on {count} skills.\n\n"
            f"All skills are now usable by all characters.\n"
            "")

    _STAMINA_HASH = 1000026
    _SPIRIT_HASH = 1000027

    def _on_regen_boost(self) -> None:
        """Multiply only stamina/spirit REGENERATION (positive d values) by the
        selected factor. Costs (negative d values) are left unchanged."""
        if not self._skill_loaded:
            self._on_skill_load()
        if not self._skill_loaded:
            return

        factor = self._regen_spin.value()

        try:
            import dmm_parser, copy
            dmm_items = dmm_parser.parse_table(
                'skill_info', self._skill_pabgb, self._skill_pabgh)
            vanilla_items = copy.deepcopy(dmm_items)
        except Exception as e:
            QMessageBox.critical(self, "Regen Boost",
                f"dmm_parser failed:\n{e}")
            return

        regen_count = 0
        dirty_keys: set = set()

        for it in dmm_items:
            hit = False
            for list_key in ('use_resource_stat_list', 'use_driver_resource_stat_list'):
                for r in (it.get(list_key) or []):
                    if not isinstance(r, dict):
                        continue
                    d = r.get('d', 0)
                    if isinstance(d, int) and d > 2**63:
                        d = d - 2**64
                    # Only boost POSITIVE values (restoration/regen)
                    # Negative values are costs — leave them alone
                    if d > 0:
                        r['d'] = int(d * factor)
                        regen_count += 1
                        hit = True
            if hit:
                dirty_keys.add(it.get('key', 0))

        new_pabgb = bytes(dmm_parser.serialize_table('skill_info', dmm_items))
        self._skill_pabgb = new_pabgb
        self._skill_entries = dmm_items
        self._skill_dirty_keys.update(dirty_keys)

        # Do NOT overwrite _skill_vanilla_entries — it must always reflect
        # the original game data so the export diff is cumulative across
        # multiple preset applications (stamina + regen, etc.)
        self._skill_loaded = True
        self._btn_skill_export.setEnabled(True)

        self._lbl_skill_status.setText(
            f"Regen Boost {factor}×: {regen_count} regen values boosted "
            f"across {len(dirty_keys)} skills.")

    def _on_stamina_preset(self, factor: float) -> None:
        """One-click stamina preset using dmm_parser for full field access.
        Zeros positive resource costs and stamina drain buffs.
        Preserves recovery (negative) values."""
        if not self._skill_loaded:
            self._on_skill_load()
        if not self._skill_loaded:
            return
        # filter_list = [10242,10243,10244,10245,10246,10247,10251,10253,10256,10257,10258,10259,10260,10262,10267,10268,10270,10273,10274,10278,10283,10284,10286,10292,45109,12341,12342,10300,10302,10303,10304,10305,10306,10310,10311,10312,10313,10314,77,10320,10323,10324,10325,10335,10339,10340,10341,10342,10343,10344,10345,10346,10347,10349,10350,10351,10352,10353,10354,10355,10356,10357,10378,10381,10382,10383,10384,10385,76002,10484,10485,60001,60007,60008,17008,17009,6802,60052,15004,15006,60065,15027,15028,15029,15031,15032,15033,15035,15045,15046,15048,15050,15051,15052,15053,13003,15062,15063,15064,13014,15070,15071,15072,15112,15155,15158,15159,15204,15206,15209,15210,15211,15212,15213,15214,15215,15216,52131,52133,52134,5101,5102,5105,5106,5107,5108,5109,5110,5111,1025,1034,1035,1038,1041,1052,1054,1057,11301,11302,11303,11304,11305,11306,1067,11308,1069,11309,1071,1072,1073,1074,1075,11307,1077,11310,11311,11312,1081,40011,40013,5201,5202,40020,40021,75113,1504,1515,20001,20002,20003,20005,20006,20007,20008,20009,20010,20011,20012,20013,20025,20026,20027,20035,20038,20041,20042,20043,20044,20045,20049,20050,18001,20052,20053,20054,20055,20056,18002,20058,20059,20060,20061,20062,20063,20064,20065,20066,20067,18013,18014,20070,20071,18021,20073,18022,20075,20076,20077,20088,20092,20093,20094,20095,20096,20098,20101,20102,20103,20104,20107,20108,20109,20110,20111,20112,18104,65216,12007,12009,12010,12016,12019,12020,12022,12026,12027,12028,12030,12031,12034,12036,12037,12038,12039,12040,12041,12042,12043,12044,12045,12046,12047,12048,12049,12050,12051,10004,10005,12052,12053,10008,12056,10010,10011,12057,12054,12055,12061,10016,10017,12060,10023,10025,10026,10027,10028,10030,10031,10032,10033,10034,10035,10041,10052,10053,10054,10055,10056,10057,10058,10059,10060,10062,10063,10064,10065,10066,10067,10068,10070,10071,10072,10074,10075,10076,10077,10078,10079,10080,10081,10082,10083,10085,10086,10091,10092,10093,10094,10095,10096,10098,10099,10110,10112,10115,10116,10118,10121,10122,10123,10124,10127,10130,10131,10132,10133,10134,10135,10136,10137,10138,10141,10142,10143,10144,10156,10160,10161,10163,10164,10165,10166,10167,10168,10169,10177,10180,10204,10205,10211,10213,10223,43001,10234,10235,10236,10237,10238,10239]
        # output = [skill for skill in self._skill_entries if skill['key'] in filter_list]

        # with open("data/fixing_stamina_preset.json", "w") as f:
        #     json.dump(output, f, indent=2)

        try:
            import dmm_parser#, copy
        #     dmm_items = dmm_parser.parse_table(
        #         'skill_info', self._skill_pabgb, self._skill_pabgh)
        #     vanilla_items = copy.deepcopy(dmm_items)
        except Exception as e:
            QMessageBox.critical(self, "Stamina Preset",
                f"dmm_parser failed:\n{e}")
            return

        res_count = 0
        buff_count = 0
        dirty_keys: set = set()

        for entry in self._skill_entries:
            hit = False
            if entry.get('_blob_fallback', False):
                continue

            for list_key in ('use_resource_stat_list', 'use_driver_resource_stat_list'):
                for r in (entry.get(list_key) or []):
                    if not isinstance(r, dict):
                        continue
                    d = r.get('d', 0)
                    if isinstance(d, int) and d > 2**63:
                        d = d - 2**64
                    # Only scale NEGATIVE values (stamina costs: roll, dash, fly,
                    # climb, swim, combat skills). Positive values are regen/restore
                    # and are handled independently by the Regen Boost button so
                    # both presets can be combined without cancelling each other.
                    if d < 0:
                        scaled = int(d * factor)
                        if scaled < 0:
                            scaled = scaled + 2**64
                        r['d'] = scaled
                        res_count += 1
                        hit = True

            for level in (entry.get('buff_level_list') or []):
                for buff in level:
                    var = buff.get('variant', {})
                    vtype = var.get('type', '')
                    body = var.get('body', {})
                    if body.get('f00') not in (self._STAMINA_HASH, self._SPIRIT_HASH):
                        continue

                    if vtype == 'VaryDataDefinedStatBuffData':
                        for fk in ('f01', 'f02'):
                            val = body.get(fk, 0)
                            if isinstance(val, int) and val > 2**63:
                                val = val - 2**64
                            if isinstance(val, (int, float)) and val < 0:
                                scaled_fk = int(val * factor)
                                if scaled_fk < 0:
                                    scaled_fk = scaled_fk + 2**64
                                body[fk] = scaled_fk
                                buff_count += 1
                                hit = True
                    elif vtype == 'BlockRegenerateStatBuffData':
                        body['f00'] = 0
                        buff_count += 1
                        hit = True
                    elif vtype == 'ChangeBuffLevelBuffData':
                        body['f01'] = 0
                        buff_count += 1
                        hit = True

            if hit:
                dirty_keys.add(entry.get('key', 0))

        new_pabgb = bytes(dmm_parser.serialize_table('skill_info', self._skill_entries))
        self._skill_pabgb = new_pabgb

        # # Keep dmm_parser items directly — do NOT re-parse with skillinfo_parser.
        # self._skill_entries = dmm_items
        self._skill_dirty_keys.update(dirty_keys)

        # # Generate _buff_data_raw byte-replace intents for entries where
        # # buff_level_list was modified. The typed apply path (dmmv3_skill)
        # # handles use_resource_stat_list, but buff_level_list is opaque to
        # # the typed path ("per-buff field edits aren't addressable yet" per
        # # DMM source). The dmmski byte-replace path handles _buff_data_raw
        # # intents — both paths run independently on the same export file.
        # # We detect buff-only changes by comparing full entry bytes against
        # # a version where only use_resource_stat_list was modified.
        # buff_raw_intents = []
        # for van_it, mod_it in zip(vanilla_items, dmm_items):
        #     try:
        #         van_bytes = bytes(dmm_parser.serialize_table('skill_info', [van_it]))
        #         mod_bytes = bytes(dmm_parser.serialize_table('skill_info', [mod_it]))
        #     except Exception:
        #         continue
        #     if van_bytes == mod_bytes:
        #         continue
        #     # Emit _buff_data_raw for every changed entry.
        #     # dmmski byte-replace is the only working apply path for skill.pabgb
        #     # (dmmv3_skill typed intents are silently ignored for pabgh-bounded
        #     # tables per DMM task #11 — confirmed against CrimsonWings mod which
        #     # uses _buff_data_raw exclusively and works correctly).
        #     name = mod_it.get('string_key', str(mod_it.get('key', '')))
        #     key  = mod_it.get('key')
        #     buff_raw_intents.append({
        #         'entry': name,
        #         'key':   key,
        #         'field': '_buff_data_raw',
        #         'old':   van_bytes.hex(),
        #         'new':   mod_bytes.hex(),
        #     })
        # self._skill_buff_raw_intents = buff_raw_intents
        # self._populate_skill_table()

        pct = f"{int(factor * 100)}%" if factor > 0 else "Infinite"
        total = res_count + buff_count
        self._lbl_skill_status.setText(
            f"Stamina {pct}: {res_count} costs + {buff_count} buff drains modified")
        QMessageBox.information(self, f"Stamina Preset: {pct}",
            f"Modified {total} stamina values via dmm_parser:\n"
            f"  {res_count} resource costs scaled to {pct}\n"
            f"    (includes roll, dash, fly, climb, swim, combat)\n"
            f"  {buff_count} buff-level drains scaled to {pct}\n\n"
            f"Export Field JSON v3 to save.")

    def _apply_skill_value_patches(self, path: str) -> None:
        """Apply a legacy skill JSON mod by patching values in-place.

        Instead of cross-version blob transfer, finds the original byte
        pattern in each entry's current _buff_data_raw and replaces it.
        No structural changes — same file size, safe roundtrip.
        """
        if not self._skill_loaded:
            QMessageBox.warning(self, "Not loaded", "Load SkillInfo first.")
            return

        try:
            with open(path, encoding='utf-8') as f:
                doc = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", f"Could not read JSON:\n{e}")
            return

        changes = []
        for p in doc.get('patches', []):
            changes.extend(p.get('changes', []))
        if not changes:
            QMessageBox.warning(self, "Import Failed", "No changes found.")
            return

        by_name = {e['name']: e for e in self._skill_entries}
        patched = 0
        skipped = 0
        missing_entries = set()
        missing_values = []

        for c in changes:
            name = c.get('entry', '')
            orig_hex = c.get('original', '')
            patch_hex = c.get('patched', '')
            if not name or not orig_hex or not patch_hex:
                skipped += 1
                continue
            e = by_name.get(name)
            if not e:
                missing_entries.add(name)
                skipped += 1
                continue

            orig_bytes = bytes.fromhex(orig_hex)
            patch_bytes = bytes.fromhex(patch_hex)

            # Search the full serialized entry, not just _buff_data_raw
            # (the new parser splits body into named fields, so the values
            # may be in _useResourceStatList, _buffLevelList, etc.)
            import skillinfo_parser as sip
            full = sip.serialize_entry(e)
            pos = full.find(orig_bytes)
            if pos >= 0:
                patched_full = bytearray(full)
                patched_full[pos:pos + len(orig_bytes)] = patch_bytes
                # Re-parse the patched entry to update all named fields
                idx = [(ek['key'], 0) for ek in [e]]
                try:
                    new_e = sip.parse_skill_entry(bytes(patched_full), 0, len(patched_full))
                    # Preserve key/name from original
                    new_e['key'] = e['key']
                    new_e['name'] = e['name']
                    new_e['name_len'] = e['name_len']
                    new_e['name_bytes'] = e.get('name_bytes', e['name'].encode('ascii'))
                    by_name[name] = new_e
                    # Update in the list
                    for i, se in enumerate(self._skill_entries):
                        if se['name'] == name:
                            self._skill_entries[i] = new_e
                            break
                    patched += 1
                except Exception:
                    # Fallback: patch _raw directly
                    e['_raw'] = bytes(patched_full)
                    e.pop('_buff_data_raw', None)
                    patched += 1
            else:
                missing_values.append(name)
                skipped += 1

        self._populate_skill_table()
        title = (doc.get('modinfo') or {}).get('title', os.path.basename(path))
        self._lbl_skill_status.setText(
            f"{title}: {patched} values patched, {skipped} skipped.")

        detail = f"Patched {patched}/{len(changes)} values in-place."

        QMessageBox.information(self, f"{title}", detail)

    def _on_skill_export_json(self) -> None:
        """Export current skill modifications as Format 3 field-name JSON."""
        if not self._skill_loaded:
            QMessageBox.warning(self, "Not loaded", "Load SkillInfo first.")
            return

        import skillinfo_parser as sip
        dirty_keys = getattr(self, '_skill_dirty_keys', set())
        intents = []
        for i, e in enumerate(self._skill_entries):
            if i >= len(self._skill_vanilla_entries):
                continue
            ekey = e.get('key', 0)
            # If dirty tracking is active, only process entries we know changed
            if dirty_keys and ekey not in dirty_keys:
                continue
            van = self._skill_vanilla_entries[i]
            # When loaded via dmm_parser, compare dicts directly
            if getattr(self, '_skill_dmm_loaded', False):
                if e == van:
                    log.warning(f"{ekey} marked as dirty but no entry changes were found")
                    continue
            else:
                if sip.serialize_entry(e) == sip.serialize_entry(van):
                    log.warning(f"{ekey} marked as dirty but no entry changes were found")
                    continue
            entry_intents = _diff_skill_entry(van, e)
            intents.extend(entry_intents)


        # A debug dump used to be written here, to the relative path
        # "data/fixing_stamina_preset.json". Relative means the working
        # directory: in the built EXE that folder usually does not exist, so
        # this button raised FileNotFoundError before it ever got to the save
        # dialog. Nothing reads the file, so it is gone.

        # Merge in _buff_data_raw byte-replace intents generated by the stamina
        # preset (dmmski path). These cover buff_level_list entries that the
        # typed dmmv3_skill path can't reach ("per-buff field edits aren't
        # addressable yet" per DMM source). Both dispatchers read the same file:
        # typed path picks up op="set" intents, byte-replace path picks up
        # field="_buff_data_raw" old/new hex intents — neither interferes.
        #
        # IMPORTANT: must use legacy "target"/"intents" format (not "targets"
        # array) so the dmmski byte-replace dispatcher sees the file. The
        # dispatcher reads json.get("target") at root level; "targets" array
        # is only read by the typed dmmv3_skill path.
        # buff_raw = getattr(self, '_skill_buff_raw_intents', [])
        # all_intents = intents + buff_raw

        if not intents:
            QMessageBox.information(self, "Export Field JSON",
                                    "No modifications to export.")
            return

        default_name = "skill_mod.field.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Skill Field JSON", default_name,
            "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            return

        # n_structured = len(intents)
        # n_buff_raw   = len(buff_raw)

        # # All skill.pabgb changes go as _buff_data_raw via dmmski dispatcher.
        # # dmmv3_skill typed intents are silently ignored for pabgh-bounded tables
        # # (DMM task #11 not yet implemented) — confirmed by CrimsonWings mod which
        # # uses _buff_data_raw exclusively. Structured intents are dropped from export.
        # raw_intents_only = [i for i in all_intents
        #                     if i.get('field') == '_buff_data_raw']

        doc = {
            'modinfo': {
                'title': 'Skill Mod',
                'version': '1.0',
                'author': 'CrimsonGameMods SkillTree',
                'description': f'{len(intents)} field-level intent(s)',
                'note': 'Format 3 — uses field names, survives game updates',
            },
            'format': 3,
            'format_minor': 1,
            # Root target/intents → dmmski dispatcher (_buff_data_raw only)
            # 'target': 'skill.pabgb',
            # 'intents': raw_intents_only,
            # targets array still included for forward compatibility
            'targets': [
                {
                    'file': 'skill.pabgb',
                    'intents': intents,
                }
            ],
        }

        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=2, ensure_ascii=False, default=str)
            self._lbl_skill_status.setText(
                f"Exported {len(intents)} intents to {os.path.basename(path)}"
                # + (f" ({n_structured} structured + {n_buff_raw} buff_raw)" if n_buff_raw else "")
                )
            QMessageBox.information(
                self, "Export Field JSON",
                f"Exported {len(intents)} intents\n"
                # f"  {n_structured} structured (use_resource_stat_list)\n"
                # + (f"  {n_buff_raw} _buff_data_raw (buff_level_list byte-replace)\n" if n_buff_raw else "")
                + f"File: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def _on_skill_export_legacy(self) -> None:
        """Export skill modifications as Format 2 hybrid JSON (entry + absolute offset)."""
        if not self._skill_loaded:
            QMessageBox.warning(self, "Not loaded", "Load SkillInfo first.")
            return

        import skillinfo_parser as sip

        van_pabgh = self._skill_pabgh
        van_pabgb = self._skill_pabgb
        van_index = sip.parse_skill_pabgh(van_pabgh)

        entry_offsets = {}
        for key, off in van_index:
            for ve in self._skill_vanilla_entries:
                if ve.get('key') == key:
                    entry_offsets[ve.get('name', '')] = off
                    break

        changes = []
        for i, e in enumerate(self._skill_entries):
            if i >= len(self._skill_vanilla_entries):
                continue
            van = self._skill_vanilla_entries[i]
            van_bytes = sip.serialize_entry(van)
            mod_bytes = sip.serialize_entry(e)
            if van_bytes == mod_bytes:
                continue
            entry_name = e.get('name', f'entry_{i}')
            entry_abs = entry_offsets.get(entry_name, 0)
            # Standard PABGB convention: entry body base = after key(4) +
            # name_len(4) + name_string(N). The null terminator is counted
            # as byte 0 of the body, not part of the header.
            name_len = e.get('name_len', len(entry_name))
            hdr_size = 4 + 4 + name_len
            body_base_abs = entry_abs + hdr_size
            j = hdr_size
            while j < min(len(van_bytes), len(mod_bytes)):
                if van_bytes[j] != mod_bytes[j]:
                    run_start = j
                    while j < min(len(van_bytes), len(mod_bytes)) and van_bytes[j] != mod_bytes[j]:
                        j += 1
                    rel = run_start - hdr_size
                    changes.append({
                        'entry': entry_name,
                        'rel_offset': rel,
                        'offset': body_base_abs + rel,
                        'original': van_bytes[run_start:j].hex(),
                        'patched': mod_bytes[run_start:j].hex(),
                    })
                else:
                    j += 1

        if not changes:
            QMessageBox.information(self, "Export Legacy JSON",
                                    "No modifications to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Legacy Skill JSON", "skill_mod.json",
            "JSON Files (*.json);;All Files (*)")
        if not path:
            return

        doc = {
            'modinfo': {
                'title': 'Skill Mod',
                'version': '1.0',
                'author': 'CrimsonGameMods SkillTree',
                'description': f'{len(changes)} byte patch(es)',
            },
            'format': 2,
            'patches': [{
                'game_file': 'gamedata/skill.pabgb',
                'source_group': '0008',
                'changes': changes,
            }],
        }

        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
            self._lbl_skill_status.setText(
                f"Exported {len(changes)} legacy patches to {os.path.basename(path)}")
            QMessageBox.information(
                self, "Export Legacy JSON",
                f"Exported {len(changes)} byte-level patches (hybrid format).\n\n"
                f"File: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def _on_skill_export_mod_folder(self) -> None:
        """Export patched skill.pabgb/pabgh as a mod folder with modinfo.json."""
        if not self._skill_loaded:
            QMessageBox.warning(self, "Not loaded", "Load SkillInfo first.")
            return

        if not self._has_skill_modifications():
            QMessageBox.information(self, "Export Mod",
                                    "No modifications to export.")
            return

        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Export Mod Folder",
            "Mod name:", text="Skill Mod")
        if not ok or not name.strip():
            return
        name = name.strip()

        import skillinfo_parser as sip
        new_pabgh, new_pabgb = sip.serialize_all(self._skill_entries)

        exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        folder = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
        out = os.path.join(exe_dir, "packs", folder)
        os.makedirs(out, exist_ok=True)
        files_dir = os.path.join(out, "files", "gamedata", "binary__", "client", "bin")
        os.makedirs(files_dir, exist_ok=True)

        with open(os.path.join(files_dir, "skill.pabgb"), "wb") as f:
            f.write(new_pabgb)
        with open(os.path.join(files_dir, "skill.pabgh"), "wb") as f:
            f.write(new_pabgh)

        with open(os.path.join(out, "modinfo.json"), "w", encoding="utf-8") as f:
            json.dump({
                "id": name.lower().replace(" ", "_"),
                "name": name,
                "version": "1.0.0",
                "game_version": "1.00.04",
                "author": "CrimsonGameMods",
                "description": f"Skill mod: {name} ({self._count_skill_modifications()} skills modified)",
            }, f, indent=2)

        mod_count = self._count_skill_modifications()
        self._lbl_skill_status.setText(f"Exported mod to packs/{folder}/")
        QMessageBox.information(self, "Exported",
            f"Mod written to:\n{out}\n\n"
            f"{mod_count} modified skill(s) included.")


# ── Module-level helpers ─────────────────────────────────────────────────

def _apply_one_skill_patch(patched: bytearray, vanilla: bytes,
                           change: dict) -> int:
    """Apply a single legacy JSON v2 patch to skill.pabgb. Returns 1 if applied."""
    ptype = change.get('type', 'replace')
    if ptype == 'replace':
        entry = change.get('entry')
        if entry and 'rel_offset' in change:
            name_bytes = entry.encode('ascii')
            search = struct.pack('<I', len(name_bytes)) + name_bytes + b'\x00'
            pos = vanilla.find(search)
            if pos < 0:
                return 0
            entry_start = pos - 4
            abs_off = entry_start + change['rel_offset']
        elif 'offset' in change:
            off_val = change['offset']
            abs_off = int(off_val, 16) if isinstance(off_val, str) else int(off_val)
        else:
            return 0
        patch_bytes = bytes.fromhex(change.get('patched', ''))
        orig_bytes = bytes.fromhex(change.get('original', ''))
        if not patch_bytes:
            return 0
        end = abs_off + max(len(orig_bytes), len(patch_bytes))
        if end > len(patched):
            return 0
        patched[abs_off:abs_off + len(orig_bytes)] = patch_bytes
        return 1
    elif ptype == 'insert':
        entry = change.get('entry')
        if entry and 'rel_offset' in change:
            name_bytes = entry.encode('ascii')
            search = struct.pack('<I', len(name_bytes)) + name_bytes + b'\x00'
            pos = vanilla.find(search)
            if pos < 0:
                return 0
            abs_off = (pos - 4) + change['rel_offset']
        elif 'offset' in change:
            off_val = change['offset']
            abs_off = int(off_val, 16) if isinstance(off_val, str) else int(off_val)
        else:
            return 0
        insert_bytes = bytes.fromhex(change.get('bytes', ''))
        if not insert_bytes:
            return 0
        patched[abs_off:abs_off] = insert_bytes
        return 1
    return 0


def _remap_resource_stat_list(items) -> list:
    """Convert a use_resource_stat_list from skillinfo_parser field names to
    dmm_parser field names so DMM can deserialize them correctly.

    skillinfo_parser  →  dmm_parser (ResourceStat in info.rs)
      stat_type       →  a           (u8)
      stat_hash       →  lookup_b    (u32)
      flag            →  c           (u8)
      value           →  d           (u64)  ← the stamina cost
      hash2           →  lookup_e    (u32)
      hash3           →  lookup_f    (u32)

    If the item already uses dmm_parser names (e.g. loaded via dmm_parser
    directly), it passes through unchanged.
    """
    _SP_TO_DMP = {
        'stat_type': 'a',
        'stat_hash': 'lookup_b',
        'flag':      'c',
        'value':     'd',
        'hash2':     'lookup_e',
        'hash3':     'lookup_f',
    }
    result = []
    for item in (items or []):
        if not isinstance(item, dict):
            result.append(item)
            continue
        # Already dmm_parser format if it has 'a' or 'lookup_b'
        if 'a' in item or 'lookup_b' in item:
            result.append(item)
        else:
            result.append({_SP_TO_DMP.get(k, k): v for k, v in item.items()})
    return result


def _diff_skill_entry(vanilla: dict, modified: dict) -> list[dict]:
    """Produce Format 3 field-level intents for one skill entry diff."""
    intents = []
    # dmm_parser uses 'string_key'; skillinfo_parser uses 'name'
    name = modified.get('name', modified.get('string_key', str(modified.get('key', '?'))))
    key = modified['key']

    # Fields to never export
    SKIP = {'key', 'string_key', 'is_blocked',
            'name_len', 'name_bytes', 'name', '_raw', '_pad_01',
            '_buffLevelCount', 'max_level', 'dev_skill_name', 'dev_skill_desc',
            'video_path_hash', 'buff_sustain_flag', 'skill_group_key_list',
            '_buff_data_raw', '_buff_raw_fallback', 'raw_bytes',
            '_cooltime', 'field_12',
            '_useDriverResourceStatList'
            # buff_level_list: DMM exposes this as base64 blob internally —
            # structured field intents (absent_flag/base/variant) can't be applied.
            # Also prevents spurious round-trip diffs from the dmm_parser re-parse.
            # 'buff_level_list',
            '_buffLevelList'
            }

    # camelCase → snake_case remap for old-parser fields that have canonical names
    FIELD_REMAP = {
        '_useResourceStatList': 'use_resource_stat_list',
        '_buffLevelList':       'buff_level_list',
    }

    # Build canonical→value lookup for vanilla to handle alias field names
    VAN_ALIASES = {
        'cooltime':              vanilla.get('cooltime', vanilla.get('field_12', vanilla.get('_cooltime', 0))),
        'use_resource_stat_list': vanilla.get('use_resource_stat_list', vanilla.get('_useResourceStatList', [])),
        'use_driver_resource_stat_list': vanilla.get('use_driver_resource_stat_list', vanilla.get('_useDriverResourceStatList', [])),
        'buff_level_list':       vanilla.get('buff_level_list', vanilla.get('_buffLevelList', [])),
    }

    for field in modified:
        if field in SKIP:
            continue
        # Skip ALL underscore-prefixed fields from skillinfo_parser that aren't
        # explicitly remapped — they are internal parser metadata, not game data.
        if field.startswith('_') and field not in FIELD_REMAP:
            continue
        # Remap field name to canonical
        export_field = FIELD_REMAP.get(field, field)
        # Get vanilla value — prefer alias-resolved value for known fields
        old_val = VAN_ALIASES.get(export_field, vanilla.get(field))
        new_val = modified.get(field)
        if old_val == new_val:
            continue
        if isinstance(new_val, bytes):
            intents.append({
                'entry': name, 'key': key, 'field': export_field, 'op': 'set',
                'new': new_val.hex(),
            })
        elif new_val is None:
            # None means the field was cleared/absent — skip, DMM can't apply None
            pass
        elif isinstance(new_val, (list, dict)):
            if export_field in ('buff_level_list', '_buffLevelList'):
                _diff_buff_levels(intents, name, key, old_val, new_val)
            elif export_field in ('use_resource_stat_list', 'use_driver_resource_stat_list'):
                # Remap sub-field names from skillinfo_parser to dmm_parser format
                # so DMM can deserialize ResourceStat objects correctly.
                remapped = _remap_resource_stat_list(new_val)
                intents.append({
                    'entry': name, 'key': key, 'field': export_field, 'op': 'set',
                    'new': remapped,
                })
            else:
                intents.append({
                    'entry': name, 'key': key, 'field': export_field, 'op': 'set',
                    'new': new_val,
                })
        else:
            intents.append({
                'entry': name, 'key': key, 'field': export_field, 'op': 'set',
                'new': new_val,
            })

    return intents


def _diff_buff_levels(intents: list, name: str, key: int,
                      old_levels, new_levels) -> None:
    """Diff _buffLevelList at the per-buff-data field level."""
    if old_levels is None or new_levels is None:
        # One side has no buff levels — if new is None, nothing to emit
        if new_levels is not None and old_levels != new_levels:
            intents.append({
                'entry': name, 'key': key,
                'field': 'buff_level_list', 'op': 'set',
                'new': new_levels,
            })
        return

    if len(old_levels) != len(new_levels):
        intents.append({
            'entry': name, 'key': key,
            'field': 'buff_level_list', 'op': 'set',
            'new': new_levels,
        })
        return

    for li, (old_lv, new_lv) in enumerate(zip(old_levels, new_levels)):
        if not isinstance(old_lv, dict) or not isinstance(new_lv, dict):
            if old_lv != new_lv:
                intents.append({
                    'entry': name, 'key': key,
                    'field': f'buff_level_list[{li}]', 'op': 'set',
                    'new': new_lv,
                })
            continue

        old_bd = old_lv.get('buff_data', [])
        new_bd = new_lv.get('buff_data', [])
        if len(old_bd) != len(new_bd):
            intents.append({
                'entry': name, 'key': key,
                'field': f'buff_level_list[{li}].buff_data', 'op': 'set',
                'new': new_bd,
            })
            continue

        for bi, (ob, nb) in enumerate(zip(old_bd, new_bd)):
            if not isinstance(ob, dict) or not isinstance(nb, dict):
                if ob != nb:
                    intents.append({
                        'entry': name, 'key': key,
                        'field': f'buff_level_list[{li}].buff_data[{bi}]',
                        'op': 'set', 'new': nb,
                    })
                continue
            for bf in nb:
                ov = ob.get(bf)
                nv = nb.get(bf)
                if ov == nv:
                    continue
                field_path = f'buff_level_list[{li}].buff_data[{bi}].{bf}'
                if isinstance(nv, bytes):
                    intents.append({
                        'entry': name, 'key': key,
                        'field': field_path, 'op': 'set',
                        'new': nv.hex(),
                    })
                else:
                    intents.append({
                        'entry': name, 'key': key,
                        'field': field_path, 'op': 'set',
                        'new': nv,
                    })
