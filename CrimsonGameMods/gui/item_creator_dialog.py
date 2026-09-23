"""Visual item creator dialog — clone existing items with ALL fields editable.

Exposes every combat-relevant field: stats (per enchant level), passive skills,
equip buffs, gimmick info, sockets, sharpness, tier, dye, durability, and more.
"""
from __future__ import annotations

import logging
import struct
import copy
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextBrowser, QVBoxLayout, QWidget,
)
from gui.theme import button_css

log = logging.getLogger(__name__)

STAT_NAMES = {
    1000000: "Max HP", 1000001: "Fatal", 1000002: "Attack",
    1000003: "Defense", 1000004: "Accuracy", 1000005: "Base Attack",
    1000006: "Critical Damage", 1000007: "Critical Rate",
    1000008: "Incoming Dmg Rate", 1000009: "Incoming Dmg Reduction",
    1000010: "Attack Speed", 1000011: "Movement Speed",
    1000012: "Climb Speed", 1000013: "Swim Speed",
    1000016: "Fire Resist", 1000017: "Ice Resist",
    1000018: "Lightning Resist", 1000026: "Stamina Regen",
    1000027: "MP Regen", 1000031: "Hit Rate",
    1000035: "Max Damage Rate", 1000036: "Pressure",
    1000037: "Stamina Cost Reduction", 1000043: "Guard PV Rate",
    1000046: "MP Cost Reduction", 1000047: "Money Drop Rate",
    1000049: "Equip Drop Rate", 1000050: "DPV Rate",
}

TIER_NAMES = {0: "", 1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic", 5: "Legendary"}
TIER_COLORS = {0: "#AAA", 1: "#AAA", 2: "#4FC3F7", 3: "#81C784", 4: "#CE93D8", 5: "#FFB74D"}


class ItemCreatorDialog(QDialog):

    def __init__(self, rust_items: list, name_db, icon_cache,
                 game_path: str = "",
                 passive_skill_names: Optional[dict] = None,
                 equip_buff_names: Optional[dict] = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Custom Item")
        self.setMinimumSize(1100, 750)
        self.setToolTip(
            "Custom Item Creator\n\n"
            "Clone existing items with custom stats, skills, buffs, and more.\n"
            "Deploy directly to game or swap into a vendor's shop.\n\n"
            "Item cloning system based on research by Benreuveni\n"
            "(github.com/Benreuveni/crimson-desert-add-item)\n"
            "Echo key patching + paloc ID formula contributed by Benreuveni."
        )

        self._rust_items = rust_items
        self._name_db = name_db
        self._icon_cache = icon_cache
        self._game_path = game_path
        self._passive_skill_names = passive_skill_names or {}
        self._equip_buff_names = equip_buff_names or {}
        self._items_by_key = {it.get('key', 0): it for it in rust_items if it.get('key', 0) > 0}
        self._selected_donor: Optional[dict] = None
        self._working_copy: Optional[dict] = None  # deep copy for editing

        # Output
        self.created_key: int = 0
        self.created_item_bytes: bytes = b''
        self.created_name: str = ''
        self.created_desc: str = ''
        self.created_donor_key: int = 0
        self.finish_mode: str = ''  # 'new' | 'swap' | 'export_single'
        self.swap_store_key: int = 0  # which store to swap into
        self.swap_replace_item_key: int = 0  # which store item to replace

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── LEFT: donor + editor ──
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 4, 4, 4)

        # Donor search
        donor_grp = QGroupBox("1. Pick Donor Item")
        dl = QVBoxLayout(donor_grp)
        sr = QHBoxLayout()
        sr.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Type item name...")
        self._search.textChanged.connect(self._refresh_donor_list)
        sr.addWidget(self._search, 1)
        dl.addLayout(sr)

        self._donor_table = QTableWidget()
        self._donor_table.setColumnCount(4)
        self._donor_table.setHorizontalHeaderLabels(["", "Key", "Name", "Tier"])
        self._donor_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._donor_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._donor_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._donor_table.setIconSize(QSize(32, 32))
        hh = self._donor_table.horizontalHeader()
        hh.setSectionResizeMode(2, hh.ResizeMode.Stretch)
        self._donor_table.setColumnWidth(0, 36)
        self._donor_table.setColumnWidth(1, 70)
        self._donor_table.verticalHeader().setDefaultSectionSize(36)
        self._donor_table.selectionModel().selectionChanged.connect(self._on_donor_selected)
        dl.addWidget(self._donor_table, 1)
        ll.addWidget(donor_grp, 1)

        # Editor tabs
        self._editor_tabs = QTabWidget()

        # Tab: Identity
        self._identity_tab = QWidget()
        ifl = QFormLayout(self._identity_tab)
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Display name in-game")
        self._name_input.textChanged.connect(self._update_preview)
        ifl.addRow("Display Name:", self._name_input)
        self._desc_input = QLineEdit()
        self._desc_input.setPlaceholderText("Description (optional)")
        ifl.addRow("Description:", self._desc_input)
        kr = QHBoxLayout()
        self._key_spin = QSpinBox()
        self._key_spin.setRange(999001, 99999999)
        self._key_spin.setValue(999001)
        self._key_spin.valueChanged.connect(self._validate_key)
        self._key_label = QLabel("Available")
        self._key_label.setStyleSheet("color:#81C784;font-weight:bold;")
        kr.addWidget(self._key_spin)
        kr.addWidget(self._key_label)
        kr.addStretch()
        ifl.addRow("Item Key:", kr)
        self._tier_combo = QComboBox()
        for t, n in TIER_NAMES.items():
            if n:
                self._tier_combo.addItem(n, t)
        self._tier_combo.currentIndexChanged.connect(self._update_preview)
        ifl.addRow("Tier:", self._tier_combo)
        self._endurance_spin = QSpinBox()
        self._endurance_spin.setRange(0, 65535)
        self._endurance_spin.setValue(65535)
        ifl.addRow("Max Endurance:", self._endurance_spin)
        self._stack_spin = QSpinBox()
        self._stack_spin.setRange(1, 999999)
        self._stack_spin.setValue(1)
        ifl.addRow("Max Stack:", self._stack_spin)
        self._dyeable_cb = QCheckBox("Dyeable")
        self._grime_cb = QCheckBox("Editable Grime")
        dye_row = QHBoxLayout()
        dye_row.addWidget(self._dyeable_cb)
        dye_row.addWidget(self._grime_cb)
        dye_row.addStretch()
        ifl.addRow("Appearance:", dye_row)
        self._editor_tabs.addTab(self._identity_tab, "Identity")

        # Tab: Stats (per enchant level)
        self._stats_tab = QWidget()
        stl = QVBoxLayout(self._stats_tab)
        er = QHBoxLayout()
        er.addWidget(QLabel("Enchant Level:"))
        self._enchant_level_combo = QComboBox()
        self._enchant_level_combo.currentIndexChanged.connect(self._load_enchant_stats)
        er.addWidget(self._enchant_level_combo)
        self._apply_all_levels_cb = QCheckBox("Apply changes to ALL levels")
        er.addWidget(self._apply_all_levels_cb)
        er.addStretch()
        stl.addLayout(er)
        self._stats_scroll = QScrollArea()
        self._stats_scroll.setWidgetResizable(True)
        self._stats_container = QWidget()
        self._stats_form = QFormLayout(self._stats_container)
        self._stats_scroll.setWidget(self._stats_container)
        stl.addWidget(self._stats_scroll, 1)
        self._stat_spinners: dict[int, QSpinBox] = {}
        self._rate_spinners: dict[int, QSpinBox] = {}
        self._regen_spinners: dict[int, QSpinBox] = {}
        self._editor_tabs.addTab(self._stats_tab, "Stats")

        # Tab: Passive Skills
        self._skills_tab = QWidget()
        skl = QVBoxLayout(self._skills_tab)
        self._skills_table = QTableWidget()
        self._skills_table.setColumnCount(3)
        self._skills_table.setHorizontalHeaderLabels(["Skill ID", "Name", "Level"])
        self._skills_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._skills_table.setColumnWidth(0, 80)
        self._skills_table.setColumnWidth(2, 60)
        skl.addWidget(self._skills_table, 1)
        skbr = QHBoxLayout()
        skbr.addWidget(QLabel("Add:"))
        self._skill_search = QComboBox()
        self._skill_search.setEditable(True)
        self._skill_search.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._skill_search.setMinimumWidth(300)
        self._skill_search.lineEdit().setPlaceholderText("Search skill by name...")
        # Populate with known skills
        for sk in sorted(self._passive_skill_names.keys()):
            name = self._passive_skill_names[sk]
            self._skill_search.addItem(f"{name} ({sk})", sk)
        self._skill_search.setCurrentIndex(-1)
        skbr.addWidget(self._skill_search, 1)
        self._skill_level_spin = QSpinBox()
        self._skill_level_spin.setRange(1, 99)
        self._skill_level_spin.setValue(1)
        self._skill_level_spin.setFixedWidth(50)
        skbr.addWidget(QLabel("Lv:"))
        skbr.addWidget(self._skill_level_spin)
        self._add_skill_btn = QPushButton("+ Add")
        self._add_skill_btn.clicked.connect(self._add_skill_row)
        skbr.addWidget(self._add_skill_btn)
        self._remove_skill_btn = QPushButton("- Remove")
        self._remove_skill_btn.clicked.connect(self._remove_skill_row)
        skbr.addWidget(self._remove_skill_btn)
        skl.addLayout(skbr)
        self._editor_tabs.addTab(self._skills_tab, "Passive Skills")

        # Tab: Buffs (per enchant level)
        self._buffs_tab = QWidget()
        bfl = QVBoxLayout(self._buffs_tab)
        bfl.addWidget(QLabel("Buffs are per enchant level (uses same level selector as Stats tab)"))
        self._buffs_table = QTableWidget()
        self._buffs_table.setColumnCount(3)
        self._buffs_table.setHorizontalHeaderLabels(["Buff ID", "Name", "Level"])
        self._buffs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._buffs_table.setColumnWidth(0, 80)
        self._buffs_table.setColumnWidth(2, 60)
        bfl.addWidget(self._buffs_table, 1)
        bbr = QHBoxLayout()
        bbr.addWidget(QLabel("Add:"))
        self._buff_search = QComboBox()
        self._buff_search.setEditable(True)
        self._buff_search.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._buff_search.setMinimumWidth(300)
        self._buff_search.lineEdit().setPlaceholderText("Search buff by name...")
        for bk in sorted(self._equip_buff_names.keys()):
            name = self._equip_buff_names[bk]
            self._buff_search.addItem(f"{name} ({bk})", bk)
        self._buff_search.setCurrentIndex(-1)
        bbr.addWidget(self._buff_search, 1)
        self._buff_level_spin = QSpinBox()
        self._buff_level_spin.setRange(0, 99)
        self._buff_level_spin.setValue(1)
        self._buff_level_spin.setFixedWidth(50)
        bbr.addWidget(QLabel("Lv:"))
        bbr.addWidget(self._buff_level_spin)
        self._add_buff_btn = QPushButton("+ Add")
        self._add_buff_btn.clicked.connect(self._add_buff_row)
        bbr.addWidget(self._add_buff_btn)
        self._remove_buff_btn = QPushButton("- Remove")
        self._remove_buff_btn.clicked.connect(self._remove_buff_row)
        bbr.addWidget(self._remove_buff_btn)
        bfl.addLayout(bbr)
        self._editor_tabs.addTab(self._buffs_tab, "Buffs")

        # Tab: Gimmick / Sockets
        self._gimmick_tab = QWidget()
        gl = QFormLayout(self._gimmick_tab)
        self._gimmick_spin = QSpinBox()
        self._gimmick_spin.setRange(0, 999999999)
        gl.addRow("Gimmick Info:", self._gimmick_spin)
        self._socket_count_spin = QSpinBox()
        self._socket_count_spin.setRange(0, 5)
        gl.addRow("Socket Count:", self._socket_count_spin)
        self._socket_valid_spin = QSpinBox()
        self._socket_valid_spin.setRange(0, 5)
        gl.addRow("Socket Valid:", self._socket_valid_spin)
        self._drop_enchant_spin = QSpinBox()
        self._drop_enchant_spin.setRange(0, 10)
        gl.addRow("Drop Enchant Level:", self._drop_enchant_spin)
        self._sharpness_spin = QSpinBox()
        self._sharpness_spin.setRange(0, 20)
        gl.addRow("Max Sharpness:", self._sharpness_spin)
        gl.addRow("", QLabel("Docking/socket bone attachment is copied from donor"))
        self._editor_tabs.addTab(self._gimmick_tab, "Gimmick / Sockets")

        # Tab: Raw Fields (catch-all for advanced users)
        self._raw_tab = QWidget()
        rl = QVBoxLayout(self._raw_tab)
        rl.addWidget(QLabel("All 105 fields from donor (read-only view, edit above)"))
        self._raw_table = QTableWidget()
        self._raw_table.setColumnCount(3)
        self._raw_table.setHorizontalHeaderLabels(["Field", "Type", "Value"])
        self._raw_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._raw_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._raw_table.setColumnWidth(0, 250)
        self._raw_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        rl.addWidget(self._raw_table, 1)
        self._editor_tabs.addTab(self._raw_tab, "Raw Fields")

        ll.addWidget(self._editor_tabs, 1)
        splitter.addWidget(left)

        # ── RIGHT: Live preview ──
        right = QWidget()
        rl2 = QVBoxLayout(right)
        rl2.setContentsMargins(4, 4, 4, 4)
        rl2.addWidget(QLabel("Live Preview:"))
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setFixedHeight(100)
        rl2.addWidget(self._icon_label)
        self._preview = QTextBrowser()
        self._preview.setOpenExternalLinks(False)
        self._preview.setStyleSheet("background-color:#0d0d1a;border:1px solid #3a3a5c;border-radius:6px;")
        rl2.addWidget(self._preview, 1)
        splitter.addWidget(right)
        splitter.setSizes([650, 350])
        root.addWidget(splitter, 1)

        # Bottom — two deploy modes
        bottom = QHBoxLayout()
        bottom.addStretch()

        self._dropset_btn = QPushButton("Deliver via Money Bag")
        self._dropset_btn.setStyleSheet(
            button_css("primary") + " font-weight:bold;"
            "font-size:14px;padding:10px 24px;")
        self._dropset_btn.setToolTip(
            "Add this item to the Copper Money Bag drop table.\n"
            "Open any copper money pouch in your inventory to receive it.\n\n"
            "No save editing required — works purely through game data.\n"
            "Uses dropsetinfo overlay (default group 0036).")
        self._dropset_btn.setEnabled(False)
        self._dropset_btn.clicked.connect(lambda: self._on_finish('dropset'))
        bottom.addWidget(self._dropset_btn)

        self._stage_btn = QPushButton("Stage Item")
        self._stage_btn.setStyleSheet(
            button_css("primary") + " font-weight:bold;"
            "font-size:14px;padding:10px 24px;")
        self._stage_btn.setToolTip(
            "Stage this item into the ItemBuffs edit session.\n"
            "The item's stats are applied to the donor key in memory.\n"
            "Use 'Apply to Game' in ItemBuffs to deploy alongside\n"
            "all your other edits (sockets, buffs, UP, abyss, etc.).\n\n"
            "This is the safest option — nothing gets clobbered.")
        self._stage_btn.setEnabled(False)
        self._stage_btn.clicked.connect(lambda: self._on_finish('stage'))
        bottom.addWidget(self._stage_btn)

        self._export_single_btn = QPushButton("Export as Single-Item Mod")
        self._export_single_btn.setStyleSheet(
            button_css("success") + " font-weight:bold;"
            "font-size:14px;padding:10px 24px;")
        self._export_single_btn.setToolTip(
            "Export a clean standalone folder mod containing ONLY this item.\n"
            "Built against vanilla iteminfo (not your current modded state),\n"
            "so the mod is shareable and doesn't include your other edits.\n\n"
            "Output folder can be imported by any mod loader (JMM, CDUMM)\n"
            "or re-imported back into this tool via Import Mod.")
        self._export_single_btn.setEnabled(False)
        self._export_single_btn.clicked.connect(lambda: self._on_finish('export_single'))
        bottom.addWidget(self._export_single_btn)

        # Separator
        bottom.addWidget(QLabel("  |  "))

        save_cfg_btn = QPushButton("Save Config")
        save_cfg_btn.setToolTip("Save this item configuration to a JSON file for later")
        save_cfg_btn.clicked.connect(self._save_config)
        bottom.addWidget(save_cfg_btn)

        load_cfg_btn = QPushButton("Load Config")
        load_cfg_btn.setToolTip("Load a previously saved item configuration")
        load_cfg_btn.clicked.connect(self._load_config)
        bottom.addWidget(load_cfg_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)
        root.addLayout(bottom)

        credit = QLabel("Item cloning by Benreuveni (github.com/Benreuveni/crimson-desert-add-item)")
        credit.setStyleSheet("color:#666688;font-size:10px;")
        credit.setAlignment(Qt.AlignmentFlag.AlignRight)
        root.addWidget(credit)

        self._validate_key()
        self._refresh_donor_list()

    # ── Donor list ────────────────────────────────────────────────────

    def _refresh_donor_list(self) -> None:
        text = self._search.text().strip().lower()
        self._donor_table.setSortingEnabled(False)
        matches = []
        for it in self._rust_items:
            if not it.get('equip_type_info'):
                continue
            k = it.get('key', 0)
            if k <= 0:
                continue
            name = self._name_db.get_name(k)
            skey = it.get('string_key', '')
            if text and text not in name.lower() and text not in skey.lower():
                continue
            matches.append((k, name, it))
            if len(matches) >= 200:
                break

        self._donor_table.setRowCount(len(matches))
        for row, (k, name, it) in enumerate(matches):
            icon_item = QTableWidgetItem()
            if self._icon_cache:
                px = self._icon_cache.get_pixmap(k)
                if px and not px.isNull():
                    icon_item.setIcon(px.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))
            self._donor_table.setItem(row, 0, icon_item)
            ki = QTableWidgetItem(str(k))
            ki.setData(Qt.ItemDataRole.UserRole, k)
            self._donor_table.setItem(row, 1, ki)
            self._donor_table.setItem(row, 2, QTableWidgetItem(name))
            tier = it.get('item_tier', 0)
            self._donor_table.setItem(row, 3, QTableWidgetItem(TIER_NAMES.get(tier, "")))
        self._donor_table.setSortingEnabled(True)

    def _on_donor_selected(self) -> None:
        rows = set(idx.row() for idx in self._donor_table.selectedIndexes())
        if not rows:
            return
        row = min(rows)
        ki = self._donor_table.item(row, 1)
        if not ki:
            return
        dk = ki.data(Qt.ItemDataRole.UserRole)
        self._selected_donor = self._items_by_key.get(dk)
        if not self._selected_donor:
            return

        # Deep copy for editing
        import json
        self._working_copy = json.loads(json.dumps(self._selected_donor))

        donor_name = self._name_db.get_name(dk)
        if not self._name_input.text():
            self._name_input.setText(f"Custom {donor_name}")

        # Icon
        if self._icon_cache:
            px = self._icon_cache.get_pixmap(dk)
            if px and not px.isNull():
                self._icon_label.setPixmap(px.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))

        self._load_identity()
        self._load_enchant_levels()
        self._load_skills()
        self._load_gimmick()
        self._load_raw_fields()
        self._update_preview()
        self._stage_btn.setEnabled(True)
        self._export_single_btn.setEnabled(True)
        self._dropset_btn.setEnabled(True)

    # ── Identity tab ──────────────────────────────────────────────────

    def _load_identity(self) -> None:
        it = self._working_copy
        tier = it.get('item_tier', 0)
        idx = self._tier_combo.findData(tier)
        if idx >= 0:
            self._tier_combo.setCurrentIndex(idx)
        self._endurance_spin.setValue(it.get('max_endurance', 65535))
        self._stack_spin.setValue(it.get('max_stack_count', 1))
        self._dyeable_cb.setChecked(bool(it.get('is_dyeable', 0)))
        self._grime_cb.setChecked(bool(it.get('is_editable_grime', 0)))

    # ── Stats tab ─────────────────────────────────────────────────────

    def _load_enchant_levels(self) -> None:
        self._enchant_level_combo.blockSignals(True)
        self._enchant_level_combo.clear()
        edl = self._working_copy.get('enchant_data_list', [])
        for i in range(len(edl)):
            self._enchant_level_combo.addItem(f"+{i}", i)
        self._enchant_level_combo.blockSignals(False)
        if edl:
            self._load_enchant_stats(0)

    def _load_enchant_stats(self, idx: int = -1) -> None:
        if idx < 0:
            idx = self._enchant_level_combo.currentData() or 0
        while self._stats_form.rowCount() > 0:
            self._stats_form.removeRow(0)
        self._stat_spinners.clear()
        self._rate_spinners.clear()
        self._regen_spinners.clear()

        edl = self._working_copy.get('enchant_data_list', [])
        if idx >= len(edl):
            return
        sd = edl[idx].get('enchant_stat_data', {})

        # Flat stats
        for s in sd.get('stat_list_static', []):
            sid = s['stat']
            name = STAT_NAMES.get(sid, f"Stat {sid}")
            spin = QSpinBox()
            spin.setRange(-999999999, 999999999)
            spin.setValue(s['change_mb'])
            spin.setSingleStep(1000)
            spin.valueChanged.connect(self._update_preview)
            self._stat_spinners[sid] = spin
            disp = s['change_mb'] / 1000
            hint = QLabel(f"(= {disp:,.0f})")
            hint.setStyleSheet("color:#888;")
            r = QHBoxLayout()
            r.addWidget(spin, 1)
            r.addWidget(hint)
            self._stats_form.addRow(f"{name}:", r)

        # Rate stats
        for s in sd.get('stat_list_static_level', []):
            sid = s['stat']
            name = STAT_NAMES.get(sid, f"Rate {sid}")
            spin = QSpinBox()
            spin.setRange(0, 15)
            spin.setValue(s['change_mb'])
            spin.valueChanged.connect(self._update_preview)
            self._rate_spinners[sid] = spin
            self._stats_form.addRow(f"{name} (Lv):", spin)

        # Regen stats
        for s in sd.get('regen_stat_list', []):
            sid = s['stat']
            name = STAT_NAMES.get(sid, f"Regen {sid}")
            spin = QSpinBox()
            spin.setRange(-999999999, 999999999)
            spin.setValue(s['change_mb'])
            spin.setSingleStep(1000)
            spin.valueChanged.connect(self._update_preview)
            self._regen_spinners[sid] = spin
            self._stats_form.addRow(f"{name} (regen):", spin)

        # Load buffs for this enchant level
        self._load_buffs(idx)

    # ── Skills tab ────────────────────────────────────────────────────

    def _load_skills(self) -> None:
        skills = self._working_copy.get('equip_passive_skill_list', [])
        self._skills_table.setRowCount(len(skills))
        for row, s in enumerate(skills):
            sid = s['skill']
            si = QTableWidgetItem(str(sid))
            si.setFlags(si.flags() | Qt.ItemFlag.ItemIsEditable)
            self._skills_table.setItem(row, 0, si)
            name = self._passive_skill_names.get(sid, f"Skill {sid}")
            ni = QTableWidgetItem(name)
            ni.setFlags(ni.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._skills_table.setItem(row, 1, ni)
            li = QTableWidgetItem(str(s['level']))
            li.setFlags(li.flags() | Qt.ItemFlag.ItemIsEditable)
            self._skills_table.setItem(row, 2, li)

    def _add_skill_row(self) -> None:
        idx = self._skill_search.currentIndex()
        if idx < 0:
            QMessageBox.information(self, "Add Skill", "Select a skill from the dropdown first.")
            return
        sid = self._skill_search.currentData()
        name = self._passive_skill_names.get(sid, f"Skill {sid}")
        level = self._skill_level_spin.value()
        r = self._skills_table.rowCount()
        self._skills_table.setRowCount(r + 1)
        si = QTableWidgetItem(str(sid))
        si.setFlags(si.flags() | Qt.ItemFlag.ItemIsEditable)
        self._skills_table.setItem(r, 0, si)
        ni = QTableWidgetItem(name)
        ni.setFlags(ni.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._skills_table.setItem(r, 1, ni)
        li = QTableWidgetItem(str(level))
        li.setFlags(li.flags() | Qt.ItemFlag.ItemIsEditable)
        self._skills_table.setItem(r, 2, li)

    def _remove_skill_row(self) -> None:
        rows = set(idx.row() for idx in self._skills_table.selectedIndexes())
        for r in sorted(rows, reverse=True):
            self._skills_table.removeRow(r)

    # ── Buffs tab ─────────────────────────────────────────────────────

    def _load_buffs(self, enchant_idx: int) -> None:
        edl = self._working_copy.get('enchant_data_list', [])
        if enchant_idx >= len(edl):
            self._buffs_table.setRowCount(0)
            return
        buffs = edl[enchant_idx].get('equip_buffs', [])
        self._buffs_table.setRowCount(len(buffs))
        for row, b in enumerate(buffs):
            bid = b['buff']
            bi = QTableWidgetItem(str(bid))
            bi.setFlags(bi.flags() | Qt.ItemFlag.ItemIsEditable)
            self._buffs_table.setItem(row, 0, bi)
            name = self._equip_buff_names.get(bid, f"Buff {bid}")
            ni = QTableWidgetItem(name)
            ni.setFlags(ni.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._buffs_table.setItem(row, 1, ni)
            li = QTableWidgetItem(str(b['level']))
            li.setFlags(li.flags() | Qt.ItemFlag.ItemIsEditable)
            self._buffs_table.setItem(row, 2, li)

    def _add_buff_row(self) -> None:
        idx = self._buff_search.currentIndex()
        if idx < 0:
            QMessageBox.information(self, "Add Buff", "Select a buff from the dropdown first.")
            return
        bid = self._buff_search.currentData()
        name = self._equip_buff_names.get(bid, f"Buff {bid}")
        level = self._buff_level_spin.value()
        r = self._buffs_table.rowCount()
        self._buffs_table.setRowCount(r + 1)
        bi = QTableWidgetItem(str(bid))
        bi.setFlags(bi.flags() | Qt.ItemFlag.ItemIsEditable)
        self._buffs_table.setItem(r, 0, bi)
        ni = QTableWidgetItem(name)
        ni.setFlags(ni.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._buffs_table.setItem(r, 1, ni)
        li = QTableWidgetItem(str(level))
        li.setFlags(li.flags() | Qt.ItemFlag.ItemIsEditable)
        self._buffs_table.setItem(r, 2, li)

    def _remove_buff_row(self) -> None:
        rows = set(idx.row() for idx in self._buffs_table.selectedIndexes())
        for r in sorted(rows, reverse=True):
            self._buffs_table.removeRow(r)

    # ── Gimmick tab ───────────────────────────────────────────────────

    def _load_gimmick(self) -> None:
        it = self._working_copy
        self._gimmick_spin.setValue(it.get('gimmick_info', 0) or 0)
        dd = it.get('drop_default_data', {}) or {}
        sockets = dd.get('add_socket_material_item_list', []) or []
        self._socket_count_spin.setValue(len(sockets))
        self._socket_valid_spin.setValue(dd.get('socket_valid_count', 0) or 0)
        self._drop_enchant_spin.setValue(dd.get('drop_enchant_level', 0) or 0)
        sharp = it.get('sharpness_data', {}) or {}
        self._sharpness_spin.setValue(sharp.get('max_sharpness', 0) or 0)

    # ── Raw fields tab ────────────────────────────────────────────────

    def _load_raw_fields(self) -> None:
        it = self._working_copy
        fields = sorted(it.keys())
        self._raw_table.setRowCount(len(fields))
        for row, k in enumerate(fields):
            v = it[k]
            self._raw_table.setItem(row, 0, QTableWidgetItem(k))
            t = type(v).__name__
            if isinstance(v, list):
                t = f"list[{len(v)}]"
            elif isinstance(v, dict):
                t = f"dict[{len(v)}]"
            self._raw_table.setItem(row, 1, QTableWidgetItem(t))
            vs = str(v)
            if len(vs) > 100:
                vs = vs[:100] + "..."
            self._raw_table.setItem(row, 2, QTableWidgetItem(vs))

    # ── Preview ───────────────────────────────────────────────────────

    def _update_preview(self) -> None:
        if not self._working_copy:
            self._preview.setHtml("<p style='color:#666;'>Select a donor item</p>")
            return

        name = self._name_input.text() or "Unnamed"
        tier = self._tier_combo.currentData() or 0
        tc = TIER_COLORS.get(tier, "#AAA")
        tn = TIER_NAMES.get(tier, "")
        key = self._key_spin.value()
        dk = self._working_copy.get('key', 0)
        donor_name = self._name_db.get_name(dk)

        html = f"""<div style="background:#1a1a2e;border:2px solid #3a3a5c;border-radius:8px;
                    padding:16px;font-family:'Segoe UI',Arial;">
            <div style="font-size:18px;font-weight:bold;color:{tc};">{name}</div>
            <div style="font-size:12px;color:#8888aa;margin-bottom:4px;">
                {tn+' | ' if tn else ''}Key: {key}</div>
            <div style="font-size:11px;color:#666688;margin-bottom:8px;">
                Cloned from: {donor_name}</div>
            <hr style="border:1px solid #3a3a5c;margin:4px 0;">"""

        # Stats
        for sid, spin in self._stat_spinners.items():
            sn = STAT_NAMES.get(sid, f"Stat {sid}")
            v = spin.value() / 1000
            ds = f"{v:,.0f}" if v == int(v) else f"{v:,.1f}"
            html += f'<div style="font-size:14px;color:#e0e0e0;padding:1px 0;">' \
                    f'<span style="color:#FFB74D;">\u2b50</span> {sn} ' \
                    f'<span style="float:right;font-weight:bold;">{ds}</span></div>'

        for sid, spin in self._rate_spinners.items():
            sn = STAT_NAMES.get(sid, f"Rate {sid}")
            html += f'<div style="font-size:14px;color:#e0e0e0;padding:1px 0;">' \
                    f'<span style="color:#81C784;">\u26a1</span> {sn} ' \
                    f'<span style="float:right;color:#81C784;">Lv {spin.value()}</span></div>'

        for sid, spin in self._regen_spinners.items():
            sn = STAT_NAMES.get(sid, f"Regen {sid}")
            v = spin.value() / 1000
            html += f'<div style="font-size:14px;color:#e0e0e0;padding:1px 0;">' \
                    f'<span style="color:#4FC3F7;">\u267b\ufe0f</span> {sn} ' \
                    f'<span style="float:right;color:#4FC3F7;">{v:,.0f}</span></div>'

        # Skills
        skills = self._working_copy.get('equip_passive_skill_list', [])
        if skills:
            html += '<hr style="border:1px solid #3a3a5c;margin:4px 0;">'
            for s in skills:
                html += f'<div style="font-size:13px;color:#66BB6A;padding:1px 0;">' \
                        f'\u2618 Skill {s["skill"]} Lv {s["level"]}</div>'

        # Gimmick
        gi = self._working_copy.get('gimmick_info', 0)
        if gi:
            html += f'<div style="font-size:12px;color:#CE93D8;padding:1px 0;">' \
                    f'Gimmick: {gi}</div>'

        # Sharpness
        sharp = (self._working_copy.get('sharpness_data') or {}).get('max_sharpness', 0)
        if sharp:
            html += f'<div style="font-size:13px;color:#FFB74D;padding:1px 0;">' \
                    f'\u2728 Refinement: {"\u2588" * sharp}</div>'

        html += "</div>"
        self._preview.setHtml(html)

    # ── Key validation ────────────────────────────────────────────────

    # ── Save / Load config ──────────────────────────────────────────

    def _save_config(self) -> None:
        if not self._working_copy:
            QMessageBox.warning(self, "Save Config", "Select a donor item first.")
            return

        import json
        from PySide6.QtWidgets import QFileDialog

        edited = self._collect_edits()
        config = {
            'version': 1,
            'donor_key': self._selected_donor.get('key', 0),
            'donor_name': self._selected_donor.get('string_key', ''),
            'custom_name': self._name_input.text().strip(),
            'custom_desc': self._desc_input.text().strip(),
            'custom_key': self._key_spin.value(),
            'item_tier': edited.get('item_tier', 0),
            'max_endurance': edited.get('max_endurance', 65535),
            'max_stack_count': edited.get('max_stack_count', 1),
            'is_dyeable': edited.get('is_dyeable', 0),
            'is_editable_grime': edited.get('is_editable_grime', 0),
            'enchant_data_list': edited.get('enchant_data_list', []),
            'equip_passive_skill_list': edited.get('equip_passive_skill_list', []),
            'gimmick_info': edited.get('gimmick_info', 0),
            'sharpness_max': (edited.get('sharpness_data') or {}).get('max_sharpness', 0),
        }

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Item Config", f"{config['custom_name'] or 'custom_item'}.json",
            "JSON Files (*.json)")
        if not path:
            return

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        QMessageBox.information(self, "Saved", f"Config saved to:\n{path}")

    def _load_config(self) -> None:
        import json
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "Load Item Config", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Load Failed", str(e))
            return

        # Find and select the donor item
        donor_key = config.get('donor_key', 0)
        if donor_key and donor_key in self._items_by_key:
            # Select donor in the table
            for row in range(self._donor_table.rowCount()):
                ki = self._donor_table.item(row, 1)
                if ki and ki.data(Qt.ItemDataRole.UserRole) == donor_key:
                    self._donor_table.selectRow(row)
                    break
            else:
                # Donor not in current filtered list — search for it
                self._search.setText(config.get('donor_name', ''))
                QApplication.processEvents()
                for row in range(self._donor_table.rowCount()):
                    ki = self._donor_table.item(row, 1)
                    if ki and ki.data(Qt.ItemDataRole.UserRole) == donor_key:
                        self._donor_table.selectRow(row)
                        break
        else:
            QMessageBox.warning(self, "Load Config",
                                f"Donor item key {donor_key} not found in game data.\n"
                                f"Select a donor manually, then load again.")
            return

        # Wait for donor selection to process
        QApplication.processEvents()

        if not self._working_copy:
            QMessageBox.warning(self, "Load Config", "Donor selection failed.")
            return

        # Apply config values
        self._name_input.setText(config.get('custom_name', ''))
        self._desc_input.setText(config.get('custom_desc', ''))
        self._key_spin.setValue(config.get('custom_key', 999001))

        idx = self._tier_combo.findData(config.get('item_tier', 0))
        if idx >= 0:
            self._tier_combo.setCurrentIndex(idx)

        self._endurance_spin.setValue(config.get('max_endurance', 65535))
        self._stack_spin.setValue(config.get('max_stack_count', 1))
        self._dyeable_cb.setChecked(bool(config.get('is_dyeable', 0)))
        self._grime_cb.setChecked(bool(config.get('is_editable_grime', 0)))
        self._gimmick_spin.setValue(config.get('gimmick_info', 0))
        self._sharpness_spin.setValue(config.get('sharpness_max', 0))

        # Apply enchant data
        cfg_edl = config.get('enchant_data_list', [])
        wc_edl = self._working_copy.get('enchant_data_list', [])
        for i, cfg_ed in enumerate(cfg_edl):
            if i >= len(wc_edl):
                break
            wc_edl[i] = cfg_ed

        # Apply skills
        cfg_skills = config.get('equip_passive_skill_list', [])
        self._working_copy['equip_passive_skill_list'] = cfg_skills

        # Reload UI from working copy
        self._load_enchant_levels()
        self._load_skills()
        self._load_gimmick()
        self._update_preview()

        QMessageBox.information(self, "Loaded",
                                f"Config loaded: {config.get('custom_name', '?')}")

    def _validate_key(self) -> None:
        k = self._key_spin.value()
        if k in self._items_by_key:
            self._key_label.setText("TAKEN")
            self._key_label.setStyleSheet("color:#FF4444;font-weight:bold;")
        else:
            self._key_label.setText("Available")
            self._key_label.setStyleSheet("color:#81C784;font-weight:bold;")

    # ── Create ────────────────────────────────────────────────────────

    def _collect_edits(self) -> dict:
        """Apply all UI edits back to the working copy."""
        it = self._working_copy

        # Identity
        it['item_tier'] = self._tier_combo.currentData() or 0
        it['max_endurance'] = self._endurance_spin.value()
        it['max_stack_count'] = self._stack_spin.value()
        it['is_dyeable'] = 1 if self._dyeable_cb.isChecked() else 0
        it['is_editable_grime'] = 1 if self._grime_cb.isChecked() else 0

        # Stats — apply spinners to current (or all) enchant levels
        apply_all = self._apply_all_levels_cb.isChecked()
        edl = it.get('enchant_data_list', [])
        levels = range(len(edl)) if apply_all else [self._enchant_level_combo.currentData() or 0]

        for lvl in levels:
            if lvl >= len(edl):
                continue
            sd = edl[lvl].get('enchant_stat_data', {})
            for s in sd.get('stat_list_static', []):
                spin = self._stat_spinners.get(s['stat'])
                if spin:
                    s['change_mb'] = spin.value()
            for s in sd.get('stat_list_static_level', []):
                spin = self._rate_spinners.get(s['stat'])
                if spin:
                    s['change_mb'] = spin.value()
            for s in sd.get('regen_stat_list', []):
                spin = self._regen_spinners.get(s['stat'])
                if spin:
                    s['change_mb'] = spin.value()

            # Buffs (col 0=ID, col 1=Name(display), col 2=Level)
            buffs = []
            for row in range(self._buffs_table.rowCount()):
                bi = self._buffs_table.item(row, 0)
                li = self._buffs_table.item(row, 2)
                if bi and li:
                    try:
                        buffs.append({'buff': int(bi.text()), 'level': int(li.text())})
                    except ValueError:
                        pass
            edl[lvl]['equip_buffs'] = buffs

        # Skills (col 0=ID, col 1=Name(display), col 2=Level)
        skills = []
        for row in range(self._skills_table.rowCount()):
            si = self._skills_table.item(row, 0)
            li = self._skills_table.item(row, 2)
            if si and li:
                try:
                    skills.append({'skill': int(si.text()), 'level': int(li.text())})
                except ValueError:
                    pass
        it['equip_passive_skill_list'] = skills

        # Gimmick
        it['gimmick_info'] = self._gimmick_spin.value()
        sharp = it.get('sharpness_data') or {}
        sharp['max_sharpness'] = self._sharpness_spin.value()
        it['sharpness_data'] = sharp

        return it

    def _on_finish(self, mode: str) -> None:
        if not self._working_copy:
            QMessageBox.warning(self, "Error", "Select a donor item first.")
            return

        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Enter a display name.")
            return

        donor_key = self._selected_donor.get('key', 0)

        if mode == 'stage':
            self.created_key = donor_key
            self.finish_mode = 'stage'
        elif mode == 'dropset':
            self.created_key = donor_key
            self.finish_mode = 'dropset'
        elif mode == 'export_single':
            # Same key-selection flow as 'new' but will be written as a
            # standalone shareable folder mod, not installed to the live game.
            key = self._key_spin.value()
            if key in self._items_by_key:
                QMessageBox.warning(self, "Error", f"Key {key} already exists.")
                return
            self.created_key = key
            self.finish_mode = 'export_single'
        else:
            # New Item — use custom key
            key = self._key_spin.value()
            if key in self._items_by_key:
                QMessageBox.warning(self, "Error", f"Key {key} already exists.")
                return
            self.created_key = key
            self.finish_mode = 'new'

        # Collect all edits
        edited = self._collect_edits()

        try:
            import crimson_rs
            modified_bytes = crimson_rs.serialize_iteminfo([edited])

            if mode in ('new', 'export_single'):
                from item_creator import clone_item_bytes
                internal = 'Custom_' + ''.join(
                    c if c.isalnum() else '_' for c in name)[:40]
                final = clone_item_bytes(modified_bytes, donor_key,
                                         self.created_key, internal)
            else:
                # Swap mode — keep the donor key, just modified stats
                final = modified_bytes

            self.created_item_bytes = final
            self.created_name = name
            self.created_desc = self._desc_input.text().strip()
            self.created_donor_key = donor_key
            self.accept()

        except Exception as e:
            log.exception("Item creation failed")
            QMessageBox.critical(self, "Failed", str(e))

    def _pick_vendor_swap(self) -> tuple[int, int]:
        """Dialog to pick which vendor and which item to replace."""
        try:
            import crimson_rs
            from storeinfo_parser import StoreinfoParser
            gp = self._game_path or r'C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert'
            dp = 'gamedata/binary__/client/bin'
            gb = bytes(crimson_rs.extract_file(gp, '0008', dp, 'storeinfo.pabgb'))
            gh = bytes(crimson_rs.extract_file(gp, '0008', dp, 'storeinfo.pabgh'))
            sp = StoreinfoParser()
            sp.load_from_bytes(gh, gb)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load stores: {e}")
            return 0, 0

        # Build vendor picker dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Pick Vendor + Item to Replace")
        dlg.setMinimumSize(700, 500)
        dl = QVBoxLayout(dlg)

        dl.addWidget(QLabel(
            "Pick a vendor store, then select which item to REPLACE\n"
            "with your custom item. The replaced item will become your creation."))

        # Store selector
        sr = QHBoxLayout()
        sr.addWidget(QLabel("Store:"))
        store_combo = QComboBox()
        stores_with_items = [s for s in sp.stores if s.items and s.is_standard]
        stores_with_items.sort(key=lambda s: s.name)
        for s in stores_with_items:
            store_combo.addItem(f"{s.name} ({len(s.items)} items)", s.key)
        sr.addWidget(store_combo, 1)
        dl.addLayout(sr)

        # Items table
        items_table = QTableWidget()
        items_table.setColumnCount(3)
        items_table.setHorizontalHeaderLabels(["Key", "Name", "Price"])
        items_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        items_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        items_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        items_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        dl.addWidget(items_table, 1)

        def refresh_items():
            sk = store_combo.currentData()
            store = sp.get_store_by_key(sk)
            if not store:
                items_table.setRowCount(0)
                return
            items_table.setRowCount(len(store.items))
            for row, it in enumerate(store.items):
                items_table.setItem(row, 0, QTableWidgetItem(str(it.item_key)))
                n = self._name_db.get_name(it.item_key)
                items_table.setItem(row, 1, QTableWidgetItem(n))
                items_table.setItem(row, 2, QTableWidgetItem(str(it.buy_price)))

        store_combo.currentIndexChanged.connect(lambda: refresh_items())
        refresh_items()

        from PySide6.QtWidgets import QDialogButtonBox
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        dl.addWidget(bb)

        if dlg.exec() != QDialog.Accepted:
            return 0, 0

        store_key = store_combo.currentData()
        rows = set(idx.row() for idx in items_table.selectedIndexes())
        if not rows:
            QMessageBox.warning(self, "Error", "Select an item to replace.")
            return 0, 0

        row = min(rows)
        ki = items_table.item(row, 0)
        replace_key = int(ki.text()) if ki else 0
        replace_name = items_table.item(row, 1).text() if items_table.item(row, 1) else "?"

        reply = QMessageBox.question(
            self, "Confirm Swap",
            f"Replace '{replace_name}' (key={replace_key})\n"
            f"in {store_combo.currentText()}\n"
            f"with your custom item?\n\n"
            f"The original item's stats will be overwritten.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return 0, 0

        return store_key, replace_key
