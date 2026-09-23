"""Quest Mods tab — unified editor for quest/mission/stage pabgb tables.

Sub-tabs:
- Quests  (questinfo.pabgb, 35 fields)
- Missions (missioninfo.pabgb, 40 fields)
- Stages  (stageinfo.pabgb, 96 fields fully typed)

All use dmm_parser for 100% round-trip. Shared overlay group for deployment.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import tempfile
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QMessageBox, QApplication, QFileDialog, QAbstractItemView, QInputDialog,
)
from PySide6.QtGui import QBrush, QColor

from gui.theme import COLORS, button_css

log = logging.getLogger(__name__)

INTERNAL_DIR = "gamedata/binary__/client/bin"

QUEST_CATEGORIES = {
    0: "Side/Generic", 1: "Tutorial", 2: "Challenge",
    5: "Faction", 10: "Region", 12: "Region Story", 13: "Main Story",
}
PLAYER_KEYS = {1: "Kliff", 4: "Damiane", 6: "Oongka"}
ALL_PLAYER_KEYS = sorted(PLAYER_KEYS.keys())

# Table configs: (pabgb_stem, dmm_table_name, display columns)
TABLE_CONFIGS = {
    "quest": ("questinfo", "quest_info", [
        ("Key", "key"), ("Name", "string_key"), ("Category", "_cat_str"),
        ("Type", "quest_type"), ("Players", "_player_str"),
        ("Missions", "_mission_count"), ("Stages", "_stage_count"),
        ("Repeatable", "is_repeatable"), ("Blocked", "is_blocked"),
    ]),
    "mission": ("missioninfo", "mission_info", [
        ("Key", "key"), ("Name", "string_key"), ("Parent Quest", "parent_quest"),
        ("Sub Missions", "_sub_count"), ("Stages", "_stage_count"),
        ("Start Players", "_player_str"), ("Blocked", "is_blocked"),
    ]),
    "stage": ("stageinfo", "stage_info", [
        ("Key", "key"), ("Name", "string_key"),
        ("Quest Type", "quest_type"), ("Category", "stage_category"),
        ("Start Players", "_player_str"), ("Forbidden", "_forbidden_str"),
        ("Parent Quest", "parent_quest"), ("Owner Mission", "owner_mission_info"),
        ("Blocked", "is_blocked"),
    ]),
}


def _safe_len(v):
    if isinstance(v, list):
        return len(v)
    return 0


def _player_str(players):
    if not players:
        return "(any)"
    return ", ".join(PLAYER_KEYS.get(p, str(p)) for p in players)


class _SubTableEditor(QWidget):
    """Reusable sub-tab for editing one pabgb table."""

    status_message = Signal(str)

    def __init__(self, table_key: str, config: dict, parent=None):
        super().__init__(parent)
        self._table_key = table_key
        self._config = config
        self._stem, self._dmm_name, self._columns = TABLE_CONFIGS[table_key]
        self._items: list[dict] = []
        self._vanilla_items: list[dict] = []
        self._pabgh: bytes = b""
        self._dirty = False
        self._updating = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        top = QHBoxLayout()
        extract_btn = QPushButton("Extract")
        extract_btn.clicked.connect(self._extract)
        top.addWidget(extract_btn)

        top.addWidget(QLabel(f"{self._stem}.pabgb"))
        top.addStretch()

        if self._table_key == "quest":
            self._filter = QComboBox()
            self._filter.addItem("All", None)
            self._filter.addItem("Main Story (13)", 13)
            self._filter.addItem("Has Character Restriction", "restricted")
            self._filter.addItem("Side (0)", 0)
            self._filter.setFixedWidth(200)
            self._filter.currentIndexChanged.connect(self._populate)
            top.addWidget(self._filter)

        if self._table_key == "mission":
            self._filter = QComboBox()
            self._filter.addItem("All", None)
            self._filter.addItem("Has start_player_list", "restricted")
            self._filter.setFixedWidth(200)
            self._filter.currentIndexChanged.connect(self._populate)
            top.addWidget(self._filter)

        self._count_label = QLabel("")
        top.addWidget(self._count_label)
        layout.addLayout(top)

        # Automation row
        if self._table_key == "quest":
            auto = QHBoxLayout()
            btn = QPushButton("Unlock All Characters")
            btn.setStyleSheet(button_css("neutral") + " font-weight: bold;")
            btn.setToolTip("Patch start_player_list on all restricted quests to [Kliff, Damiane, Oongka]")
            btn.clicked.connect(self._unlock_all_characters)
            auto.addWidget(btn)

            btn2 = QPushButton("Make All Repeatable")
            btn2.setStyleSheet(button_css("success") + " font-weight: bold;")
            btn2.clicked.connect(self._make_all_repeatable)
            auto.addWidget(btn2)
            auto.addStretch()
            layout.addLayout(auto)

        if self._table_key == "mission":
            auto = QHBoxLayout()
            btn = QPushButton("Unlock All Mission Characters")
            btn.setStyleSheet(button_css("neutral") + " font-weight: bold;")
            btn.setToolTip("Patch start_player_list on all missions to [Kliff, Damiane, Oongka]")
            btn.clicked.connect(self._unlock_all_characters)
            auto.addWidget(btn)
            auto.addStretch()
            layout.addLayout(auto)

        if self._table_key == "stage":
            self._filter = QComboBox()
            self._filter.addItem("All", None)
            self._filter.addItem("Has Character Restriction", "restricted")
            self._filter.setFixedWidth(200)
            self._filter.currentIndexChanged.connect(self._populate)
            top.addWidget(self._filter)

            auto = QHBoxLayout()
            btn = QPushButton("Unlock All Stage Characters")
            btn.setStyleSheet(button_css("neutral") + " font-weight: bold;")
            btn.setToolTip("Clear forbidden lists, set start_player_list to all 3, clear hide_mercenary on all 70 restricted stages")
            btn.clicked.connect(self._unlock_all_stage_characters)
            auto.addWidget(btn)
            auto.addStretch()
            layout.addLayout(auto)

        self._table = QTableWidget()
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels([c[0] for c in self._columns])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        if self._table_key in ("quest", "mission", "stage"):
            self._table.cellDoubleClicked.connect(self._on_cell_double_click)
        layout.addWidget(self._table, 1)

    def _extract(self):
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "No Game Path", "Set the game install path first.")
            return
        self.status_message.emit(f"Extracting {self._stem}...")
        QApplication.processEvents()
        try:
            import crimson_rs, dmm_parser
            pabgb = bytes(crimson_rs.extract_file(game, "0008", INTERNAL_DIR, f"{self._stem}.pabgb"))
            pabgh = bytes(crimson_rs.extract_file(game, "0008", INTERNAL_DIR, f"{self._stem}.pabgh"))
            self._pabgh = pabgh
            self._items = dmm_parser.parse_table(self._dmm_name, pabgb, pabgh)
            self._vanilla_items = copy.deepcopy(self._items)
            self._dirty = False
            self._populate()
            self.status_message.emit(f"Loaded {len(self._items)} entries from {self._stem}.pabgb")
        except Exception as e:
            log.exception(f"{self._stem} extract failed")
            QMessageBox.critical(self, "Extract Failed", str(e))

    def _enrich(self, it: dict) -> dict:
        if self._table_key == "quest":
            cat = it.get("quest_category", 0)
            it["_cat_str"] = QUEST_CATEGORIES.get(cat, str(cat))
            it["_player_str"] = _player_str(it.get("start_player_list", []))
            it["_mission_count"] = _safe_len(it.get("mission_list"))
            it["_stage_count"] = _safe_len(it.get("stage_list"))
        elif self._table_key == "mission":
            it["_sub_count"] = _safe_len(it.get("sub_mission_list"))
            it["_stage_count"] = _safe_len(it.get("mission_stage_list") or it.get("execute_stage_list"))
            it["_player_str"] = _player_str(it.get("start_player_list", []))
        elif self._table_key == "stage":
            it["_player_str"] = _player_str(it.get("start_player_list", []))
            it["_forbidden_str"] = _player_str(it.get("forbidden_character_list", []))
        return it

    def _populate(self):
        self._updating = True
        self._table.setSortingEnabled(False)
        filt = getattr(self, '_filter', None)
        filt_val = filt.currentData() if filt else None

        rows = []
        for it in self._items:
            self._enrich(it)
            if filt_val == "restricted":
                if self._table_key == "stage":
                    if not (it.get("start_player_list") or it.get("forbidden_character_list")
                            or it.get("hide_mercenary_group_info_list")):
                        continue
                elif not it.get("start_player_list"):
                    continue
            elif filt_val is not None and it.get("quest_category") != filt_val:
                continue
            rows.append(it)

        self._item_by_key = {it.get("key", 0): it for it in self._items}
        self._table.setRowCount(len(rows))

        for row, it in enumerate(rows):
            for col, (_, field) in enumerate(self._columns):
                val = it.get(field, "")
                text = str(val) if not isinstance(val, list) else str(len(val))
                item = QTableWidgetItem(text)

                if col == 0:
                    item.setData(Qt.UserRole, int(it.get("key", 0)))
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                if field == "_cat_str" and it.get("quest_category") == 13:
                    item.setForeground(QBrush(QColor(COLORS["accent"])))
                if field == "_player_str" and it.get("start_player_list"):
                    item.setForeground(QBrush(QColor("#FF8800")))
                if field == "_forbidden_str" and it.get("forbidden_character_list"):
                    item.setForeground(QBrush(QColor("#FF4444")))

                editable_fields = {"is_repeatable", "is_blocked", "quest_type"}
                if field not in editable_fields:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)

                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)
        self._table.resizeColumnsToContents()
        self._count_label.setText(f"({len(rows)}/{len(self._items)})")
        self._updating = False

    def _on_cell_double_click(self, row, col):
        field = self._columns[col][1] if col < len(self._columns) else ""
        item0 = self._table.item(row, 0)
        if not item0:
            return
        key_val = item0.data(Qt.UserRole)
        quest = self._item_by_key.get(key_val)
        if not quest:
            return

        if field in ("_player_str",):
            current = quest.get("start_player_list", [])
            current_str = ", ".join(str(p) for p in current) if current else ""
            text, ok = QInputDialog.getText(
                self, "Edit start_player_list",
                f"Entry: {quest.get('string_key', '?')}\n\n"
                f"Character keys (comma-separated):\n"
                f"  1=Kliff, 4=Damiane, 6=Oongka\n"
                f"  Empty = no restriction\n\n"
                f"Current: [{current_str}]",
                text=current_str)
            if not ok:
                return
            new_list = [int(x.strip()) for x in text.split(",") if x.strip().isdigit()] if text.strip() else []
            quest["start_player_list"] = new_list
            self._dirty = True
            self._populate()

        elif field == "_forbidden_str":
            current = quest.get("forbidden_character_list", [])
            current_str = ", ".join(str(p) for p in current) if current else ""
            text, ok = QInputDialog.getText(
                self, "Edit forbidden_character_list",
                f"Entry: {quest.get('string_key', '?')}\n\n"
                f"Character keys (comma-separated):\n"
                f"  1=Kliff, 4=Damiane, 6=Oongka\n"
                f"  Empty = no restriction\n\n"
                f"Current: [{current_str}]",
                text=current_str)
            if not ok:
                return
            new_list = [int(x.strip()) for x in text.split(",") if x.strip().isdigit()] if text.strip() else []
            quest["forbidden_character_list"] = new_list
            self._dirty = True
            self._populate()

        elif field in ("is_repeatable", "is_blocked"):
            current = quest.get(field, 0)
            quest[field] = 0 if current else 1
            self._dirty = True
            self._populate()

    def _unlock_all_characters(self):
        if not self._items:
            QMessageBox.warning(self, "No Data", "Extract first.")
            return
        count = 0
        for it in self._items:
            players = it.get("start_player_list", [])
            if players and sorted(players) != ALL_PLAYER_KEYS:
                it["start_player_list"] = list(ALL_PLAYER_KEYS)
                count += 1
        self._dirty = True
        self._populate()
        QMessageBox.information(self, "Unlock Characters",
            f"Patched {count} entries to [Kliff, Damiane, Oongka].\n"
            f"Click Apply to Game to deploy.")

    def _make_all_repeatable(self):
        if not self._items:
            return
        count = sum(1 for it in self._items if not it.get("is_repeatable"))
        for it in self._items:
            it["is_repeatable"] = 1
        self._dirty = True
        self._populate()
        QMessageBox.information(self, "Repeatable", f"Set {count} quests to repeatable.")

    def _unlock_all_stage_characters(self):
        if not self._items:
            QMessageBox.warning(self, "No Data", "Extract first.")
            return
        patched = 0
        for it in self._items:
            changed = False
            players = it.get("start_player_list", [])
            if players and sorted(players) != ALL_PLAYER_KEYS:
                it["start_player_list"] = list(ALL_PLAYER_KEYS)
                changed = True
            if it.get("forbidden_character_list"):
                it["forbidden_character_list"] = []
                changed = True
            if it.get("hide_mercenary_group_info_list"):
                it["hide_mercenary_group_info_list"] = []
                changed = True
            if changed:
                patched += 1
        self._dirty = True
        self._populate()
        QMessageBox.information(self, "Unlock Stage Characters",
            f"Patched {patched} stages:\n"
            f"  - start_player_list → [Kliff, Damiane, Oongka]\n"
            f"  - forbidden_character_list → cleared\n"
            f"  - hide_mercenary_group_info_list → cleared\n\n"
            f"Click Apply to Game to deploy.")

    def get_modified_data(self) -> tuple[str, bytes, bytes] | None:
        if not self._dirty or not self._items:
            return None
        try:
            import dmm_parser
            pabgb = bytes(dmm_parser.serialize_table(self._dmm_name, self._items))
            return self._stem, pabgb, self._pabgh
        except Exception:
            return None

    def get_diff_intents(self) -> list[dict]:
        if not self._items or not self._vanilla_items:
            return []
        van_by_key = {it["key"]: it for it in self._vanilla_items}
        intents = []
        for it in self._items:
            k = it["key"]
            van = van_by_key.get(k)
            if not van:
                continue
            sk = it.get("string_key", "")
            for field in it:
                if field.startswith("_") or field in ("key", "string_key", "_blob_b64", "_blob_fallback", "_tail_b64"):
                    continue
                if it[field] != van.get(field):
                    intents.append({
                        "entry": sk, "key": k,
                        "field": field, "op": "set", "new": it[field],
                    })
        return intents


class QuestModsTab(QWidget):
    """Top-level Quest Mods tab with sub-tabs for Quest/Mission/Stage."""

    status_message = Signal(str)
    config_save_requested = Signal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._build_ui()

    def set_game_path(self, path: str):
        self._config["game_install_path"] = path

    @property
    def _overlay_group(self) -> str:
        return f"{self._overlay_spin.value():04d}"

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # Top bar: shared Apply/Restore/Export/Overlay
        top = QHBoxLayout()

        apply_btn = QPushButton("Apply to Game")
        apply_btn.setStyleSheet(
            f"background-color: {COLORS['accent']}; color: white; font-weight: bold;")
        apply_btn.clicked.connect(self._apply_to_game)
        top.addWidget(apply_btn)

        top.addWidget(QLabel("Overlay:"))
        self._overlay_spin = QSpinBox()
        self._overlay_spin.setRange(1, 9999)
        self._overlay_spin.setValue(self._config.get("quest_overlay_dir", 63))
        self._overlay_spin.setFixedWidth(70)
        self._overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"quest_overlay_dir": int(v)}))
        top.addWidget(self._overlay_spin)

        restore_btn = QPushButton("Restore")
        restore_btn.clicked.connect(self._restore)
        top.addWidget(restore_btn)

        unlock_all_btn = QPushButton("Unlock All Characters (one-click)")
        unlock_all_btn.setStyleSheet(
            button_css("neutral") + " font-weight: bold;")
        unlock_all_btn.setToolTip(
            "Extracts all 3 tables, patches character restrictions, and deploys in one click.\n"
            "Quests: 72 restricted -> all 3 characters\n"
            "Missions: 2 restricted -> all 3 characters\n"
            "Stages: 70 restricted -> all 3 characters + clear forbidden lists")
        unlock_all_btn.clicked.connect(self._unlock_everything_oneclick)
        top.addWidget(unlock_all_btn)

        top.addStretch()

        export_btn = QPushButton("Export Field JSON v3")
        export_btn.setStyleSheet(button_css("primary") + " font-weight: bold;")
        export_btn.clicked.connect(self._export_field_json)
        top.addWidget(export_btn)

        import_btn = QPushButton("Import Field JSON v3")
        import_btn.clicked.connect(self._import_field_json)
        top.addWidget(import_btn)

        root.addLayout(top)

        # Sub-tabs
        self._sub_tabs = QTabWidget()
        self._sub_tabs.setTabPosition(QTabWidget.South)

        self._quest_editor = _SubTableEditor("quest", self._config)
        self._quest_editor.status_message.connect(self.status_message)
        self._sub_tabs.addTab(self._quest_editor, "Quests (935)")

        self._mission_editor = _SubTableEditor("mission", self._config)
        self._mission_editor.status_message.connect(self.status_message)
        self._sub_tabs.addTab(self._mission_editor, "Missions (6506)")

        self._stage_editor = _SubTableEditor("stage", self._config)
        self._stage_editor.status_message.connect(self.status_message)
        self._sub_tabs.addTab(self._stage_editor, "Stages (50789)")

        root.addWidget(self._sub_tabs, 1)

    def _apply_to_game(self):
        game = self._config.get("game_install_path", "")
        if not game:
            QMessageBox.warning(self, "Apply", "Set game path first.")
            return

        modified = []
        for editor in (self._quest_editor, self._mission_editor, self._stage_editor):
            data = editor.get_modified_data()
            if data:
                modified.append(data)

        if not modified:
            QMessageBox.information(self, "Apply", "No modifications to deploy.")
            return

        names = ", ".join(m[0] for m in modified)
        groups = [self._QUEST_OVERLAY_GROUPS.get(m[0], "0063") for m in modified]
        detail = "\n".join(f"  {m[0]} -> {g}/" for m, g in zip(modified, groups))
        reply = QMessageBox.question(
            self, "Apply Quest Mods",
            f"Deploy {len(modified)} modified table(s)?\n{detail}\n\n"
            f"Restart the game after applying.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        try:
            import crimson_rs

            for (stem, pabgb, pabgh), grp in zip(modified, groups):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    group_dir = os.path.join(tmp_dir, grp)
                    builder = crimson_rs.PackGroupBuilder(
                        group_dir, crimson_rs.Compression.NONE,
                        crimson_rs.Crypto.NONE)
                    builder.add_file(INTERNAL_DIR, f"{stem}.pabgb", pabgb)
                    builder.add_file(INTERNAL_DIR, f"{stem}.pabgh", pabgh)
                    pamt_bytes = bytes(builder.finish())
                    pamt_checksum = crimson_rs.parse_pamt_bytes(
                        pamt_bytes)["checksum"]

                    game_overlay = os.path.join(game, grp)
                    os.makedirs(game_overlay, exist_ok=True)
                    for fn in os.listdir(group_dir):
                        shutil.copy2(os.path.join(group_dir, fn),
                                     os.path.join(game_overlay, fn))

                papgt_path = os.path.join(game, "meta", "0.papgt")
                if os.path.isfile(papgt_path):
                    papgt = crimson_rs.parse_papgt_file(papgt_path)
                    papgt["entries"] = [e for e in papgt["entries"]
                                        if e.get("group_name") != grp]
                    papgt = crimson_rs.add_papgt_entry(
                        papgt, grp, pamt_checksum, 0, 16383)
                    crimson_rs.write_papgt_file(papgt, papgt_path)

            self.status_message.emit(f"Deployed {names}")
            QMessageBox.information(self, "Applied",
                f"Quest mods deployed:\n{detail}\n\nRestart the game.")
        except Exception as e:
            log.exception("Quest apply failed")
            QMessageBox.critical(self, "Apply Failed", str(e))

    def _restore(self):
        game = self._config.get("game_install_path", "")
        if not game:
            return
        grp = self._overlay_group
        grp_dir = os.path.join(game, grp)
        if os.path.isdir(grp_dir):
            reply = QMessageBox.question(
                self, "Restore",
                f"Remove {grp}/ overlay and restore vanilla?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            try:
                shutil.rmtree(grp_dir)
                self.status_message.emit(f"Removed {grp}/ overlay")
            except Exception as e:
                QMessageBox.critical(self, "Restore Failed", str(e))
        else:
            self.status_message.emit(f"No {grp}/ overlay found")

    _QUEST_OVERLAY_GROUPS = {
        "questinfo": "0063",
        "missioninfo": "0064",
        "stageinfo": "0066",
    }

    def _unlock_everything_oneclick(self):
        game = self._config.get("game_install_path", "")
        if not game or not os.path.isdir(game):
            QMessageBox.warning(self, "Unlock All", "Set the game install path first.")
            return

        reply = QMessageBox.question(
            self, "Unlock All Characters",
            "This will extract, patch, and deploy all 3 tables:\n\n"
            "  questinfo   -> 0063/  (72 quests)\n"
            "  missioninfo -> 0064/  (2 missions)\n"
            "  stageinfo   -> 0066/  (70 stages)\n\n"
            "Each table gets its own overlay group.\n"
            "Restart the game after deploying.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        try:
            import crimson_rs, dmm_parser, copy

            deployed_groups = []

            for editor in (self._quest_editor, self._mission_editor, self._stage_editor):
                grp = self._QUEST_OVERLAY_GROUPS.get(editor._stem, "0063")
                self.status_message.emit(f"Extracting {editor._stem}...")
                QApplication.processEvents()

                pabgb = bytes(crimson_rs.extract_file(
                    game, "0008", INTERNAL_DIR, f"{editor._stem}.pabgb"))
                pabgh = bytes(crimson_rs.extract_file(
                    game, "0008", INTERNAL_DIR, f"{editor._stem}.pabgh"))
                editor._pabgh = pabgh
                editor._items = dmm_parser.parse_table(editor._dmm_name, pabgb, pabgh)
                editor._vanilla_items = copy.deepcopy(editor._items)

                patched = 0
                for it in editor._items:
                    changed = False
                    players = it.get("start_player_list", [])
                    if players and sorted(players) != ALL_PLAYER_KEYS:
                        it["start_player_list"] = list(ALL_PLAYER_KEYS)
                        changed = True
                    if it.get("forbidden_character_list"):
                        it["forbidden_character_list"] = []
                        changed = True
                    if it.get("hide_mercenary_group_info_list"):
                        it["hide_mercenary_group_info_list"] = []
                        changed = True
                    if changed:
                        patched += 1

                if not patched:
                    self.status_message.emit(f"{editor._stem}: no restrictions found")
                    continue

                editor._dirty = True
                out_pabgb = bytes(dmm_parser.serialize_table(
                    editor._dmm_name, editor._items))

                self.status_message.emit(
                    f"Deploying {editor._stem} to {grp}/ ({patched} patched)...")
                QApplication.processEvents()

                with tempfile.TemporaryDirectory() as tmp_dir:
                    group_dir = os.path.join(tmp_dir, grp)
                    builder = crimson_rs.PackGroupBuilder(
                        group_dir, crimson_rs.Compression.NONE,
                        crimson_rs.Crypto.NONE)
                    builder.add_file(INTERNAL_DIR, f"{editor._stem}.pabgb", out_pabgb)
                    builder.add_file(INTERNAL_DIR, f"{editor._stem}.pabgh", pabgh)
                    pamt_bytes = bytes(builder.finish())
                    pamt_checksum = crimson_rs.parse_pamt_bytes(
                        pamt_bytes)["checksum"]

                    game_overlay = os.path.join(game, grp)
                    os.makedirs(game_overlay, exist_ok=True)
                    for fn in os.listdir(group_dir):
                        shutil.copy2(os.path.join(group_dir, fn),
                                     os.path.join(game_overlay, fn))

                papgt_path = os.path.join(game, "meta", "0.papgt")
                if os.path.isfile(papgt_path):
                    papgt = crimson_rs.parse_papgt_file(papgt_path)
                    papgt["entries"] = [e for e in papgt["entries"]
                                        if e.get("group_name") != grp]
                    papgt = crimson_rs.add_papgt_entry(
                        papgt, grp, pamt_checksum, 0, 16383)
                    crimson_rs.write_papgt_file(papgt, papgt_path)

                deployed_groups.append(f"{editor._stem} -> {grp}/ ({patched})")

            for editor in (self._quest_editor, self._mission_editor, self._stage_editor):
                if editor._items:
                    editor._populate()

            summary = "\n".join(f"  {d}" for d in deployed_groups)
            self.status_message.emit(f"Deployed {len(deployed_groups)} tables")
            QMessageBox.information(self, "Unlock All Characters",
                f"Deployed to separate overlay groups:\n{summary}\n\n"
                f"Restart the game to apply.")

        except Exception as e:
            log.exception("Unlock all failed")
            QMessageBox.critical(self, "Unlock Failed", str(e))

    def _export_field_json(self):
        all_intents = {}
        for editor in (self._quest_editor, self._mission_editor, self._stage_editor):
            intents = editor.get_diff_intents()
            if intents:
                all_intents[f"{editor._stem}.pabgb"] = intents

        if not all_intents:
            QMessageBox.information(self, "Export", "No changes to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Field JSON", "QuestMod.field.json",
            "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            return

        total = sum(len(v) for v in all_intents.values())
        doc = {
            "modinfo": {
                "title": "Quest Mod",
                "version": "1.0",
                "author": "CrimsonGameMods Quest Editor",
                "description": f"{total} intent(s) across {len(all_intents)} table(s)",
            },
            "format": 3,
            "format_minor": 1,
            "targets": [
                {"file": fname, "intents": intents}
                for fname, intents in all_intents.items()
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False, default=str)
        self.status_message.emit(f"Exported {total} intents to {os.path.basename(path)}")
        QMessageBox.information(self, "Export", f"Exported {total} intents.\nFile: {path}")

    def _import_field_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Field JSON", "",
            "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)

        stem_to_editor = {
            e._stem: e for e in (self._quest_editor, self._mission_editor, self._stage_editor)
        }

        targets = doc.get("targets", [])
        if not targets and doc.get("intents"):
            targets = [{"file": doc.get("target", ""), "intents": doc["intents"]}]

        total_applied = 0
        for t in targets:
            fname = t.get("file", "")
            stem = fname.replace(".pabgb", "").replace("_info", "info")
            editor = stem_to_editor.get(stem)
            if not editor or not editor._items:
                continue
            by_key = {it["key"]: it for it in editor._items}
            by_name = {it.get("string_key", ""): it for it in editor._items}
            for intent in t.get("intents", []):
                target = by_key.get(intent.get("key")) or by_name.get(intent.get("entry"))
                if target and intent.get("op") == "set" and intent.get("field") in target:
                    target[intent["field"]] = intent["new"]
                    total_applied += 1
            editor._dirty = True
            editor._populate()

        self.status_message.emit(f"Imported {total_applied} intents")
        QMessageBox.information(self, "Import", f"Applied {total_applied} intent(s).")

    def get_staged_files(self) -> dict[str, bytes]:
        result = {}
        for editor in (self._quest_editor, self._mission_editor, self._stage_editor):
            data = editor.get_modified_data()
            if data:
                stem, pabgb, pabgh = data
                result[f"{stem}.pabgb"] = pabgb
                result[f"{stem}.pabgh"] = pabgh
        return result
