from __future__ import annotations

import datetime
import json
import logging
from data_db import get_connection
import os
import struct
import sys

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDockWidget, QFileDialog, QFrame, QGroupBox,
    QHBoxLayout, QGridLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from models import SaveData, SaveItem, QuestState
from item_db import ItemNameDB
from item_packs import ItemPack, PackItem
from localization import tr
from gui.theme import COLORS, CATEGORY_COLORS, DARK_STYLESHEET

log = logging.getLogger(__name__)


class _FloatingTabWindow(QWidget):

    def __init__(self, widget: QWidget, title: str,
                 owner: "DetachableTabWidget", original_idx: int,
                 icon=None):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Window)
        self._owner = owner
        self._widget = widget
        self._original_idx = original_idx
        self._title = title
        self._icon = icon

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
        self.resize(1000, 700)

    def closeEvent(self, event):
        self._owner._reattach(self._widget, self._title, self._original_idx, self._icon)
        super().closeEvent(event)


class DetachableTabWidget(QTabWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._floating: dict = {}
        self.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabBar().customContextMenuRequested.connect(self._tab_bar_menu)

    def _tab_bar_menu(self, pos) -> None:
        idx = self.tabBar().tabAt(pos)
        if idx < 0:
            return
        menu = QMenu(self)
        detach_act = menu.addAction("Detach to floating window")
        if menu.exec(self.tabBar().mapToGlobal(pos)) == detach_act:
            self._detach(idx)

    def _detach(self, idx: int) -> None:
        widget = self.widget(idx)
        title = self.tabText(idx)
        icon = self.tabIcon(idx)
        self.removeTab(idx)
        win = _FloatingTabWindow(widget, title, self, idx, icon)
        self._floating[id(widget)] = win
        win.show()

    def _reattach(self, widget: QWidget, title: str, original_idx: int, icon=None) -> None:
        self._floating.pop(id(widget), None)
        idx = min(original_idx, self.count())
        if icon and not icon.isNull():
            self.insertTab(idx, widget, icon, title)
        else:
            self.insertTab(idx, widget, title)
        self.setCurrentIndex(idx)


class GiveItemDialog(QDialog):

    def __init__(self, name_db: ItemNameDB, items: List[SaveItem], parent=None, experimental: bool = False, icon_cache=None):
        super().__init__(parent)
        self.setWindowTitle("Give Item")
        self.setMinimumSize(700, 600)
        self._name_db = name_db
        self._icon_cache = icon_cache
        self._items = items
        self._read_only = ("Mercenary",) if experimental else ("Store", "Mercenary")
        self.target_key: int = 0
        self.target_count: int = 1
        self._donor_list: List[SaveItem] = []
        self.donor_item: Optional[SaveItem] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        step1 = QGroupBox("Step 1: What item do you want?")
        s1_layout = QVBoxLayout(step1)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._target_search = QLineEdit()
        self._target_search.setPlaceholderText("Type item name or key...")
        self._target_search.textChanged.connect(self._filter_targets)
        search_row.addWidget(self._target_search, 1)
        search_row.addWidget(QLabel("Count:"))
        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 999999)
        self._count_spin.setValue(1)
        search_row.addWidget(self._count_spin)
        s1_layout.addLayout(search_row)

        self._target_table = QTableWidget()
        self._target_table.setColumnCount(4)
        self._target_table.setHorizontalHeaderLabels(["", "Key", "Name", "Category"])
        self._target_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._target_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._target_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._target_table.setColumnWidth(0, ICON_SIZE + 16 if self._icon_cache else 0)
        self._target_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self._target_table.setColumnWidth(2, 220)
        self._target_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._target_table.setSortingEnabled(True)
        self._target_table.verticalHeader().setDefaultSectionSize(max(ICON_SIZE + 2, 22) if self._icon_cache else 22)
        self._target_table.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._target_table.selectionModel().selectionChanged.connect(self._on_target_selected)
        s1_layout.addWidget(self._target_table)
        layout.addWidget(step1)

        step2 = QGroupBox("Step 2: Pick a donor item to sacrifice (same category preferred)")
        s2_layout = QVBoxLayout(step2)

        self._donor_info = QLabel("Select a target item first.")
        self._donor_info.setStyleSheet(f"color: {COLORS['warning']}; padding: 4px;")
        s2_layout.addWidget(self._donor_info)

        self._donor_search = QLineEdit()
        self._donor_search.setPlaceholderText("Search donors by name, key, or category...")
        self._donor_search.textChanged.connect(self._filter_donors)
        s2_layout.addWidget(self._donor_search)

        self._donor_table = QTableWidget()
        self._donor_table.setColumnCount(6)
        self._donor_table.setHorizontalHeaderLabels(["", "Name", "Category", "Key", "Stack", "Slot"])
        self._donor_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._donor_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._donor_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._donor_table.setColumnWidth(0, ICON_SIZE + 16 if self._icon_cache else 0)
        self._donor_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self._donor_table.setColumnWidth(1, 200)
        self._donor_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._donor_table.setSortingEnabled(True)
        self._donor_table.verticalHeader().setDefaultSectionSize(max(ICON_SIZE + 2, 22) if self._icon_cache else 22)
        self._donor_table.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        s2_layout.addWidget(self._donor_table)
        layout.addWidget(step2)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._ok_btn = QPushButton("Give Item")
        self._ok_btn.setEnabled(False)
        self._ok_btn.setObjectName("accentBtn")
        self._ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(self._ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self._filter_targets("")

    def _filter_targets(self, text: str) -> None:
        table = self._target_table
        table.setSortingEnabled(False)

        if text.strip():
            results = self._name_db.search(text.strip())
        else:
            results = self._name_db.get_all_sorted()[:200]

        table.setRowCount(len(results))
        for row, info in enumerate(results):
            icon_item = QTableWidgetItem()
            if self._icon_cache:
                px = self._icon_cache.get_pixmap(info.item_key)
                if px:
                    icon_item.setIcon(QIcon(px))
            table.setItem(row, 0, icon_item)
            table.setItem(row, 1, QTableWidgetItem(str(info.item_key)))
            name_w = QTableWidgetItem(info.name)
            color = QColor(CATEGORY_COLORS.get(info.category, COLORS["text"]))
            name_w.setForeground(QBrush(color))
            table.setItem(row, 2, name_w)
            table.setItem(row, 3, QTableWidgetItem(info.category))
        table.setSortingEnabled(True)

    def _on_target_selected(self) -> None:
        rows = set(idx.row() for idx in self._target_table.selectedIndexes())
        if not rows:
            return
        row = min(rows)
        key_w = self._target_table.item(row, 1)
        cat_w = self._target_table.item(row, 3)
        if not key_w:
            return

        self.target_key = int(key_w.text())
        target_cat = cat_w.text() if cat_w else ""
        target_name = self._name_db.get_name(self.target_key)

        self._donor_info.setText(
            f"Target: {target_name} (key={self.target_key}, category={target_cat})\n"
            f"Pick a donor item below. Same-category donors shown first."
        )

        read_only = self._read_only
        self._donor_list = [it for it in self._items if it.source not in read_only]
        self._target_cat = target_cat

        def sort_key(it):
            cat = self._name_db.get_category(it.item_key)
            same_cat = 0 if cat == target_cat else 1
            return (same_cat, -it.stack_count)
        self._donor_list.sort(key=sort_key)

        self._donor_search.clear()
        self._populate_donor_table(self._donor_list)

        self._ok_btn.setEnabled(False)
        self._donor_table.selectionModel().selectionChanged.connect(self._on_donor_selected)

    def _filter_donors(self, text: str) -> None:
        search = text.lower().strip()
        if not search:
            self._populate_donor_table(self._donor_list)
            return
        filtered = [
            it for it in self._donor_list
            if search in self._name_db.get_name(it.item_key).lower()
            or search in str(it.item_key)
            or search in self._name_db.get_category(it.item_key).lower()
        ]
        self._populate_donor_table(filtered)

    def _populate_donor_table(self, donors) -> None:
        table = self._donor_table
        table.setSortingEnabled(False)
        table.setRowCount(len(donors))
        target_cat = getattr(self, '_target_cat', '')
        for row, it in enumerate(donors):
            icon_item = QTableWidgetItem()
            if self._icon_cache:
                px = self._icon_cache.get_pixmap(it.item_key)
                if px:
                    icon_item.setIcon(QIcon(px))
            table.setItem(row, 0, icon_item)
            name = self._name_db.get_name(it.item_key)
            cat = self._name_db.get_category(it.item_key)
            name_w = QTableWidgetItem(name)
            if cat == target_cat:
                name_w.setForeground(QBrush(QColor(COLORS["success"])))
            else:
                name_w.setForeground(QBrush(QColor(COLORS["text_dim"])))
            table.setItem(row, 1, name_w)
            table.setItem(row, 2, QTableWidgetItem(cat))
            table.setItem(row, 3, QTableWidgetItem(str(it.item_key)))
            table.setItem(row, 4, QTableWidgetItem(str(it.stack_count)))
            table.setItem(row, 5, QTableWidgetItem(str(it.slot_no)))
        table.setSortingEnabled(True)

    def _on_donor_selected(self) -> None:
        self._ok_btn.setEnabled(True)

    def _on_accept(self) -> None:
        rows = set(idx.row() for idx in self._donor_table.selectedIndexes())
        if not rows:
            QMessageBox.warning(self, "Give Item", "Select a donor item.")
            return
        row = min(rows)
        key_w = self._donor_table.item(row, 3)
        slot_w = self._donor_table.item(row, 5)
        if not key_w:
            return

        donor_key = int(key_w.text())
        donor_slot = int(slot_w.text()) if slot_w else -1

        read_only = self._read_only
        for it in self._items:
            if (it.item_key == donor_key and it.slot_no == donor_slot
                    and it.source not in read_only):
                self.donor_item = it
                break

        if not self.donor_item:
            QMessageBox.warning(self, "Give Item", "Could not resolve donor item.")
            return

        self.target_count = self._count_spin.value()
        self.accept()


_CATEGORY_TO_INV_KEY = {
    "Equipment": 1,
    "Material": 5,
    "Quest": 2,
    "Currency": 2,
    "Consumable": 8,
    "Ammo": 5,
    "Misc": 2,
}


class AddItemDialog(QDialog):

    def __init__(self, name_db: ItemNameDB, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Item (Template-Based)")
        self.setMinimumSize(700, 500)
        self._name_db = name_db
        self.selected_key: int = 0
        self.selected_count: int = 1
        self.selected_enchant: int = 0
        self.selected_category_key: int = 2

        try:
            from template_sync import load_local_master
            master = load_local_master()
            self._template_keys = set(int(k) for k in master.get('templates', {}).keys())
        except Exception:
            self._template_keys = set()

        self._item_limits = {}
        try:
            _db = get_connection()
            self._item_limits = {str(row['item_key']): json.loads(row['data']) for row in _db.execute("SELECT item_key, data FROM item_limits")}
        except Exception:
            pass

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        template_count = len(self._template_keys)
        limits_count = len(self._item_limits)
        status = QLabel(
            f"All {limits_count} game items shown. "
            f"{template_count} have verified templates (marked 'Yes'). "
            f"Others use clone-from-save ('Clone')."
        )
        status.setWordWrap(True)
        status.setStyleSheet(
            f"color: {COLORS['accent']}; background-color: rgba(79,195,247,0.08); "
            f"border: 1px solid {COLORS['accent']}; border-radius: 4px; padding: 6px;"
        )
        layout.addWidget(status)

        search_group = QGroupBox("Select Item")
        sg_layout = QVBoxLayout(search_group)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Type item name or key...")
        self._search.textChanged.connect(self._filter_items)
        search_row.addWidget(self._search, 1)
        sg_layout.addLayout(search_row)

        self._item_table = QTableWidget()
        self._item_table.setColumnCount(5)
        self._item_table.setHorizontalHeaderLabels(["Key", "Name", "Category", "Type", "Template"])
        self._item_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._item_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._item_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self._item_table.setColumnWidth(1, 220)
        self._item_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._item_table.setSortingEnabled(True)
        self._item_table.verticalHeader().setDefaultSectionSize(22)
        self._item_table.selectionModel().selectionChanged.connect(self._on_item_selected)
        sg_layout.addWidget(self._item_table)
        layout.addWidget(search_group)

        params_group = QGroupBox("Item Parameters")
        pg_layout = QGridLayout(params_group)

        pg_layout.addWidget(QLabel("Count:"), 0, 0)
        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 999999)
        self._count_spin.setValue(1)
        pg_layout.addWidget(self._count_spin, 0, 1)

        pg_layout.addWidget(QLabel("Enchant Level:"), 0, 2)
        self._enchant_spin = QSpinBox()
        self._enchant_spin.setRange(0, 10)
        self._enchant_spin.setValue(0)
        pg_layout.addWidget(self._enchant_spin, 0, 3)

        pg_layout.addWidget(QLabel("Inventory Category:"), 1, 0)
        self._cat_combo = QComboBox()
        self._cat_combo.addItems([
            "General (2)", "Equipment (1)", "Materials (5)",
            "Consumables (8)", "Quest (10)", "Housing (14)",
        ])
        self._cat_combo.setCurrentIndex(0)
        pg_layout.addWidget(self._cat_combo, 1, 1, 1, 3)

        self._selected_label = QLabel("No item selected.")
        self._selected_label.setStyleSheet(f"color: {COLORS['warning']}; padding: 4px;")
        pg_layout.addWidget(self._selected_label, 2, 0, 1, 4)

        layout.addWidget(params_group)

        info = QLabel(
            "This creates a REAL new item entry in the save file using PARC insertion.\n"
            "No donor item is consumed. If insertion fails, the editor will fall back\n"
            "to the Give Item (donor swap) method."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px; padding: 4px;"
        )
        layout.addWidget(info)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._ok_btn = QPushButton("Add Item")
        self._ok_btn.setEnabled(False)
        self._ok_btn.setObjectName("accentBtn")
        self._ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(self._ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self._filter_items("")

    def _filter_items(self, text: str) -> None:
        table = self._item_table
        table.setSortingEnabled(False)
        if text.strip():
            results = self._name_db.search(text.strip())
        else:
            results = self._name_db.get_all_sorted()
        if not text.strip():
            results = results[:300]
        table.setRowCount(len(results))
        for row, info in enumerate(results):
            table.setItem(row, 0, QTableWidgetItem(str(info.item_key)))
            name_w = QTableWidgetItem(info.name)
            color = QColor(CATEGORY_COLORS.get(info.category, COLORS["text"]))
            name_w.setForeground(QBrush(color))
            table.setItem(row, 1, name_w)
            table.setItem(row, 2, QTableWidgetItem(info.category))

            limits = self._item_limits.get(str(info.item_key), {})
            slot_type = limits.get('slotType', -1)
            if slot_type == 65535 or slot_type == -1:
                type_str = "Item"
            elif slot_type <= 3:
                type_str = "Weapon"
            elif slot_type <= 9:
                type_str = "Armor"
            else:
                type_str = "Equip"
            table.setItem(row, 3, QTableWidgetItem(type_str))

            has_template = info.item_key in self._template_keys
            tmpl_w = QTableWidgetItem("Yes" if has_template else "Clone")
            if has_template:
                tmpl_w.setForeground(QBrush(QColor(COLORS['success'])))
            else:
                tmpl_w.setForeground(QBrush(QColor(COLORS['warning'])))
            table.setItem(row, 4, tmpl_w)
        table.setSortingEnabled(True)

    def _on_item_selected(self) -> None:
        rows = set(idx.row() for idx in self._item_table.selectedIndexes())
        if not rows:
            return
        row = min(rows)
        key_w = self._item_table.item(row, 0)
        cat_w = self._item_table.item(row, 2)
        if not key_w:
            return
        self.selected_key = int(key_w.text())
        name = self._name_db.get_name(self.selected_key)
        cat = cat_w.text() if cat_w else "Misc"

        limits = self._item_limits.get(str(self.selected_key), {})
        stack_limit = limits.get('stackLimit', 999999)
        slot_type = limits.get('slotType', 65535)
        is_equipment = slot_type != 65535
        can_enchant = limits.get('canEnchant', 0)

        if stack_limit > 0:
            self._count_spin.setMaximum(stack_limit)
            self._count_spin.setValue(min(self._count_spin.value(), stack_limit))

        type_str = "Equipment" if is_equipment else "Consumable/Material"
        limit_str = f"Max stack: {stack_limit}" if stack_limit > 0 else "Virtual currency"
        enchant_str = "Can enchant" if can_enchant else "No enchant"

        self._selected_label.setText(
            f"Selected: {name} (key={self.selected_key})\n"
            f"Type: {type_str} | {limit_str} | {enchant_str} | Category: {cat}"
        )
        self._selected_label.setStyleSheet(f"color: {COLORS['success']}; padding: 4px;")
        self._ok_btn.setEnabled(True)

        inv_key = _CATEGORY_TO_INV_KEY.get(cat, 2)
        cat_map = {2: 0, 1: 1, 5: 2, 8: 3, 10: 4, 14: 5}
        idx = cat_map.get(inv_key, 0)
        self._cat_combo.setCurrentIndex(idx)

    def _on_accept(self) -> None:
        if self.selected_key == 0:
            QMessageBox.warning(self, "Add Item", "Select an item first.")
            return
        self.selected_count = self._count_spin.value()
        self.selected_enchant = self._enchant_spin.value()
        cat_text = self._cat_combo.currentText()
        import re
        m = re.search(r"\((\d+)\)", cat_text)
        self.selected_category_key = int(m.group(1)) if m else 2
        self.accept()


def _write_quest_state(blob, entry: dict, new_state: int) -> None:
    off = entry['state_offset']
    sz = entry.get('state_size', 4)
    if sz == 1:
        low = new_state & 0xFF
        struct.pack_into('<B', blob, off, low)
    elif sz == 2:
        struct.pack_into('<H', blob, off, new_state & 0xFFFF)
    else:
        struct.pack_into('<I', blob, off, new_state)
    entry['state'] = new_state


class QuestEditorWindow(QDialog):

    QUEST_STATE_NAMES = {
        QuestState.AVAILABLE:        "Available",
        QuestState.AVAILABLE_PLUS:   "Available (variant)",
        QuestState.IN_PROGRESS:      "In Progress",
        QuestState.LOCKED:           "Locked",
        QuestState.IN_PROGRESS_PLUS: "In Progress (advanced)",
        QuestState.COMPLETED:        "Completed",
        QuestState.SIDE_CONTENT:     "Side Content",
        QuestState.FULLY_COMPLETED:  "Fully Completed",
        0x01: "Locked",
        0x02: "Available",
        0x03: "Available (variant)",
        0x04: "Unknown (0x04)",
        0x05: "In Progress / Done",
    }

    def __init__(self, save_data, save_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quest Editor")
        self.setMinimumSize(900, 600)
        self.resize(1000, 700)
        self._save_data = save_data
        self._save_path = save_path
        self.dirty = False
        self._quest_entries = []
        self._mission_entries = []

        self._quest_names = {}
        self._mission_names = {}
        self._quest_chains = {}
        self._chain_entries = {}
        try:
            _db = get_connection()
            self._quest_names = {row['key']: row['name'] for row in _db.execute("SELECT key, name FROM quests")}
            self._mission_names = {row['key']: row['name'] for row in _db.execute("SELECT key, name FROM missions")}
        except Exception:
            pass
        for base in [os.path.dirname(os.path.abspath(__file__)), getattr(sys, '_MEIPASS', '')]:
            cp = os.path.join(base, 'quest_chains.json')
            if os.path.isfile(cp):
                try:
                    with open(cp, 'r') as f:
                        chain_data = json.load(f)
                        self._quest_chains = {int(k): v for k, v in chain_data.get('key_to_chain', {}).items()}
                        self._chain_entries = chain_data.get('chains', {})
                except Exception:
                    pass
                break

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        info = QLabel(f"Save: {os.path.basename(save_path)}")
        info.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold; padding: 4px;")
        layout.addWidget(info)

        top = QHBoxLayout()
        top.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search quest or mission name...")
        self._search.textChanged.connect(self._filter)
        top.addWidget(self._search, 1)

        top.addWidget(QLabel("State:"))
        self._state_filter = QComboBox()
        self._state_filter.addItems(["All", "In Progress", "Completed", "Available", "Locked"])
        self._state_filter.currentTextChanged.connect(self._filter)
        top.addWidget(self._state_filter)

        layout.addLayout(top)

        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(["Key", "Name", "State", "Status", "Completed", "Chain"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self._table.setColumnWidth(1, 200)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()

        advance_btn = QPushButton("Advance State")
        advance_btn.setObjectName("accentBtn")
        advance_btn.setToolTip(
            "Move quest to the next state (1→2→3→4→5).\n"
            "Safest way to progress quests — one step at a time.\n"
            "States: 1=Locked, 2=Available, 3→4=Unknown, 5=Completed"
        )
        advance_btn.clicked.connect(self._advance_state)
        btn_row.addWidget(advance_btn)

        complete_btn = QPushButton("Mark Completed")
        complete_btn.setToolTip("Jump directly to state 5 (Completed)")
        complete_btn.clicked.connect(self._mark_completed)
        btn_row.addWidget(complete_btn)

        reset_btn = QPushButton("Reset to In Progress")
        reset_btn.clicked.connect(self._reset_progress)
        btn_row.addWidget(reset_btn)

        reset_avail_btn = QPushButton("Reset to Available")
        reset_avail_btn.setToolTip("Reset quest to before you started it (Available state)")
        reset_avail_btn.clicked.connect(self._reset_available)
        btn_row.addWidget(reset_avail_btn)

        insert_btn = QPushButton("Add Quest as Completed (PARC Insert)")
        insert_btn.setToolTip(
            "Insert a quest that doesn't exist in your save yet as completed.\n"
            "Enter a quest key from the Quest Database tab."
        )
        insert_btn.clicked.connect(self._insert_quest_completed)
        btn_row.addWidget(insert_btn)

        batch_btn = QPushButton("Complete All Matching")
        batch_btn.setToolTip(
            "Mark ALL currently visible/filtered entries as completed.\n"
            "Use Search to filter first (e.g. 'Sanctum'), then click this\n"
            "to complete the entire chain at once."
        )
        batch_btn.clicked.connect(self._batch_complete_filtered)
        btn_row.addWidget(batch_btn)

        btn_row.addStretch()

        save_btn = QPushButton("Save File")
        save_btn.setObjectName("accentBtn")
        save_btn.setToolTip(f"Save changes to: {save_path}")
        save_btn.clicked.connect(self._save_file)
        btn_row.addWidget(save_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold;")
        layout.addWidget(self._status)

        warn = QLabel("WARNING: Changing quest states can have unpredictable effects. Use at your own risk.")
        warn.setStyleSheet(f"color: {COLORS['error']}; padding: 2px;")
        layout.addWidget(warn)

        self.setStyleSheet(DARK_STYLESHEET)

        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self._parse_quests)

    def _parse_quests(self) -> None:
        from PySide6.QtWidgets import QProgressDialog

        self._status.setText("Parsing quest data... please wait")
        self._table.setRowCount(0)
        QApplication.processEvents()

        try:
            _meipass = getattr(sys, '_MEIPASS', None)
            _mydir = os.path.dirname(os.path.abspath(__file__))
            for sub in ['Includes/desktopeditor', 'desktopeditor']:
                for base in [_mydir, _meipass] if _meipass else [_mydir]:
                    p = os.path.join(base, sub)
                    if os.path.isdir(p) and p not in sys.path:
                        sys.path.insert(0, p)
            import save_parser as sp

            raw = self._save_data.decompressed_blob
            result = sp.build_result_from_raw(bytes(raw), {'input_kind': 'raw_blob'})

            for obj in result['objects']:
                if obj.class_name != 'QuestSaveData':
                    continue
                for f in obj.fields:
                    if f.name == '_questStateList' and f.list_elements:
                        for elem in f.list_elements:
                            entry = {'key': 0, 'state': 0, 'state_offset': -1, 'state_size': 4,
                                     'has_completed': False, 'needs_parc_expand': False,
                                     'is_mission': False, 'mask_hex': ''}
                            has_completed = False
                            for cf in (elem.child_fields or []):
                                if cf.name == '_questKey' and cf.present:
                                    entry['key'] = struct.unpack_from('<I', raw, cf.start_offset)[0]
                                elif cf.name == '_state' and cf.present:
                                    sz = cf.end_offset - cf.start_offset
                                    entry['state_size'] = sz
                                    if sz == 1:
                                        entry['state'] = raw[cf.start_offset]
                                    elif sz == 2:
                                        entry['state'] = struct.unpack_from('<H', raw, cf.start_offset)[0]
                                    else:
                                        entry['state'] = struct.unpack_from('<I', raw, cf.start_offset)[0]
                                    entry['state_offset'] = cf.start_offset
                                elif cf.name == '_completedTime' and cf.present:
                                    has_completed = True
                                    entry['has_completed'] = True
                                    entry['completed_time'] = struct.unpack_from('<Q', raw, cf.start_offset)[0]
                                elif cf.name == '_branchedTime' and cf.present:
                                    entry['branched_time'] = struct.unpack_from('<Q', raw, cf.start_offset)[0]
                            entry['needs_parc_expand'] = not has_completed
                            entry['mask_hex'] = elem.child_mask_bytes.hex() if elem.child_mask_bytes else ''
                            entry['name'] = self._quest_names.get(entry['key'], f'Unknown_{entry["key"]}')
                            entry['state_name'] = self.QUEST_STATE_NAMES.get(entry['state'], f'0x{entry["state"]:02X}')
                            entry['state_raw'] = entry['state']
                            entry['display'] = entry['name']
                            chain = self._quest_chains.get(entry['key'])
                            entry['chain'] = chain
                            self._quest_entries.append(entry)

                    if f.name == '_missionStateList' and f.list_elements:
                        for elem in f.list_elements:
                            entry = {'key': 0, 'state': 0, 'state_offset': -1, 'state_size': 4,
                                     'has_completed': False, 'needs_parc_expand': False,
                                     'is_mission': True, 'mask_hex': ''}
                            has_branched = has_completed = False
                            for cf in (elem.child_fields or []):
                                if cf.name == '_key' and cf.present:
                                    entry['key'] = struct.unpack_from('<I', raw, cf.start_offset)[0]
                                elif cf.name == '_state' and cf.present:
                                    sz = cf.end_offset - cf.start_offset
                                    entry['state_size'] = sz
                                    if sz == 1:
                                        entry['state'] = raw[cf.start_offset]
                                    elif sz == 2:
                                        entry['state'] = struct.unpack_from('<H', raw, cf.start_offset)[0]
                                    else:
                                        entry['state'] = struct.unpack_from('<I', raw, cf.start_offset)[0]
                                    entry['state_offset'] = cf.start_offset
                                elif cf.name == '_completedTime' and cf.present:
                                    has_completed = True
                                    entry['has_completed'] = True
                                    entry['completed_time'] = struct.unpack_from('<Q', raw, cf.start_offset)[0]
                                elif cf.name == '_branchedTime' and cf.present:
                                    has_branched = True
                                    entry['branched_time'] = struct.unpack_from('<Q', raw, cf.start_offset)[0]
                            entry['needs_parc_expand'] = not has_completed
                            entry['mask_hex'] = elem.child_mask_bytes.hex() if elem.child_mask_bytes else ''
                            entry['name'] = self._mission_names.get(entry['key'], f'Mission_{entry["key"]}')
                            entry['state_name'] = self.QUEST_STATE_NAMES.get(entry['state'], f'0x{entry["state"]:02X}')
                            entry['state_raw'] = entry['state']
                            entry['display'] = entry['name']
                            chain = self._quest_chains.get(entry['key'])
                            entry['chain'] = chain
                            self._mission_entries.append(entry)
                break
        except Exception as e:
            log.exception("Unhandled exception")
            self._status.setText(f"Parse error: {e}")
            QMessageBox.critical(self, "Parse Error", f"Failed to parse quest data:\n{e}")

        if not self._quest_entries and not self._mission_entries:
            self._status.setText("No quest data found — try reloading the save")
        else:
            self._status.setText(f"Loaded {len(self._quest_entries)} quests, {len(self._mission_entries)} missions")

        self._filter()

    def _filter(self, _text=None) -> None:
        table = self._table
        table.setSortingEnabled(False)

        search = self._search.text().strip().lower()
        state_filt = self._state_filter.currentText()

        source = self._quest_entries + self._mission_entries

        filtered = []
        for e in source:
            if search and search not in e['name'].lower() and search not in str(e['key']):
                continue
            state_name = self.QUEST_STATE_NAMES.get(e['state'], f'Unknown (0x{e["state"]:04X})')
            if state_filt == "In Progress" and 'Progress' not in state_name:
                continue
            if state_filt == "Completed" and 'Completed' not in state_name:
                continue
            if state_filt == "Available" and 'Available' not in state_name:
                continue
            if state_filt == "Locked" and state_name != 'Locked':
                continue
            filtered.append(e)

        table.setRowCount(len(filtered))
        for row, e in enumerate(filtered):
            state_name = self.QUEST_STATE_NAMES.get(e['state'], f'Unknown (0x{e["state"]:04X})')

            key_item = QTableWidgetItem(str(e['key']))
            key_item.setData(Qt.UserRole, e)
            table.setItem(row, 0, key_item)

            name_item = QTableWidgetItem(e['name'])
            if 'Completed' in state_name:
                name_item.setForeground(QBrush(QColor(COLORS['success'])))
            elif 'Progress' in state_name:
                name_item.setForeground(QBrush(QColor(COLORS['accent'])))
            elif state_name == 'Locked':
                name_item.setForeground(QBrush(QColor(COLORS['text_dim'])))
            table.setItem(row, 1, name_item)

            table.setItem(row, 2, QTableWidgetItem(f'0x{e["state"]:04X}'))
            table.setItem(row, 3, QTableWidgetItem(state_name))
            table.setItem(row, 4, QTableWidgetItem("Yes" if e['has_completed'] else ""))

            chain = e.get('chain')
            if chain and isinstance(chain, list) and chain:
                c = chain[0]
                chain_text = f"{c.get('chain_name', '?')} ({c.get('chain_size', '?')} parts)"
                chain_item = QTableWidgetItem(chain_text)
                chain_item.setForeground(QBrush(QColor(COLORS['warning'])))
                chain_item.setToolTip(
                    f"This quest is part of a chain.\n"
                    f"Chain: {c.get('chain_name', '?')}\n"
                    f"Total sub-quests: {c.get('chain_size', '?')}\n\n"
                    f"Completing this quest alone may not advance the chain counter.\n"
                    f"The challenge progress counter is tracked separately."
                )
            else:
                chain_item = QTableWidgetItem("")
            table.setItem(row, 5, chain_item)

        table.setSortingEnabled(True)

        completed = sum(1 for e in source if e['state'] in (QuestState.COMPLETED, QuestState.FULLY_COMPLETED))
        in_prog = sum(1 for e in source if e['state'] in (QuestState.IN_PROGRESS, QuestState.IN_PROGRESS_PLUS))
        self._status.setText(
            f"{len(self._quest_entries)} quests + {len(self._mission_entries)} missions  |  "
            f"{in_prog} in progress  |  {completed} completed  |  "
            f"Showing {len(filtered)}"
        )

    STATE_NAMES_SHORT = {0: 'Default', 1: 'Locked', 2: 'Available', 3: 'State 3', 4: 'State 4', 5: 'Completed'}

    def _advance_state(self) -> None:
        entry = self._get_selected()
        if not entry:
            QMessageBox.information(self, "Quest Editor", "Select a quest or mission first.")
            return
        if entry['state_offset'] < 0:
            QMessageBox.warning(self, "Quest Editor", "State offset not found.")
            return

        cur = entry['state'] & 0xFF
        if cur >= 5:
            QMessageBox.information(self, "Quest Editor",
                f"'{entry['name']}' is already at state {cur} (Completed).\nCannot advance further.")
            return

        nxt = cur + 1
        cur_name = self.STATE_NAMES_SHORT.get(cur, f'State {cur}')
        nxt_name = self.STATE_NAMES_SHORT.get(nxt, f'State {nxt}')

        chain = entry.get('chain')
        chain_text = ""
        if chain and isinstance(chain, list) and chain:
            c = chain[0]
            chain_progress = self._get_chain_info(entry['key'])
            progress = chain_progress.get('progress', '?/?') if chain_progress else '?/?'
            chain_text = f"\n\nChain: {c.get('chain_name', '?')} ({progress} completed)"

        reply = QMessageBox.question(
            self, "Advance State",
            f"Advance '{entry['name']}'?\n\n"
            f"{cur_name} (state {cur}) → {nxt_name} (state {nxt}){chain_text}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        blob = self._save_data.decompressed_blob
        _write_quest_state(blob, entry, nxt)
        self.dirty = True
        self._filter()
        self._status.setText(f"'{entry['name']}' advanced: {cur_name} → {nxt_name} (unsaved)")

    def _get_selected(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self._table.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def _mark_completed(self) -> None:
        entry = self._get_selected()
        if not entry:
            QMessageBox.information(self, "Quest Editor", "Select a quest or mission first.")
            return
        if entry['state_offset'] < 0:
            QMessageBox.warning(self, "Quest Editor", "State offset not found.")
            return

        state_name = self.QUEST_STATE_NAMES.get(entry['state'], f'0x{entry["state"]:04X}')

        chain = entry.get('chain')
        chain_info = ""
        if chain and isinstance(chain, list) and chain:
            c = chain[0]
            chain_progress = self._get_chain_info(entry['key'])
            progress = chain_progress.get('progress', '?/?') if chain_progress else '?/?'
            chain_info = (
                f"\n\nThis quest is part of a challenge chain:\n"
                f"Chain: {c.get('chain_name', '?')} ({progress} completed)\n\n"
                f"The challenge counter updates automatically based on\n"
                f"how many sub-quests have state=5 (completed)."
            )

        reply = QMessageBox.question(
            self, "Mark Completed",
            f"Set '{entry['name']}' to Completed?\n\nCurrent state: {state_name}{chain_info}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        blob = self._save_data.decompressed_blob


        _write_quest_state(blob, entry, QuestState.FULLY_COMPLETED)
        self.dirty = True
        self._filter()
        self._status.setText(f"'{entry['name']}' -> Completed (unsaved)")

    def _reset_progress(self) -> None:
        entry = self._get_selected()
        if not entry:
            QMessageBox.information(self, "Quest Editor", "Select a quest or mission first.")
            return
        if entry['state_offset'] < 0:
            return

        blob = self._save_data.decompressed_blob
        _write_quest_state(blob, entry, 0x0905)
        self.dirty = True
        self._filter()
        self._status.setText(f"'{entry['name']}' -> In Progress (unsaved)")

    def _reset_available(self) -> None:
        entry = self._get_selected()
        if not entry:
            QMessageBox.information(self, "Quest Editor", "Select a quest or mission first.")
            return
        if entry['state_offset'] < 0:
            return

        state_name = self.QUEST_STATE_NAMES.get(entry['state'], f'0x{entry["state"]:04X}')
        reply = QMessageBox.question(
            self, "Reset to Available",
            f"Reset '{entry['name']}' to Available (not started)?\n\nCurrent state: {state_name}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        blob = self._save_data.decompressed_blob
        _write_quest_state(blob, entry, 0x0902)
        self.dirty = True
        self._filter()
        self._status.setText(f"'{entry['name']}' -> Available (unsaved)")


    def _get_chain_info(self, key: int) -> dict:
        chain = self._quest_chains.get(key)
        if not chain or not isinstance(chain, list) or not chain:
            return {}

        c = chain[0]
        chain_id = str(c.get('chain_id', ''))
        chain_entry = self._chain_entries.get(chain_id, {})
        siblings = chain_entry.get('sub_quest_keys', [])

        completed = []
        all_entries = self._quest_entries + self._mission_entries
        for sib_key in siblings:
            for e in all_entries:
                if e['key'] == sib_key and e.get('has_completed'):
                    completed.append(sib_key)
                    break

        return {
            'chain_name': c.get('chain_name', '?'),
            'chain_size': c.get('chain_size', 0),
            'chain_id': chain_id,
            'siblings': siblings,
            'completed_siblings': completed,
            'progress': f"{len(completed)}/{len(siblings)}",
        }

    def _batch_complete_filtered(self) -> None:
        table = self._table
        row_count = table.rowCount()
        if row_count == 0:
            QMessageBox.information(self, "No Entries", "No entries visible. Use Search to filter first.")
            return

        entries_to_complete = []
        for row in range(row_count):
            item_widget = table.item(row, 0)
            if not item_widget:
                continue
            entry = item_widget.data(Qt.UserRole)
            if not entry or entry.get('state_offset', -1) < 0:
                continue
            if entry.get('state') not in (QuestState.FULLY_COMPLETED, QuestState.COMPLETED):
                entries_to_complete.append(entry)

        if not entries_to_complete:
            QMessageBox.information(self, "Nothing to Do",
                "All visible entries are already completed or have no valid state.")
            return

        search_text = self._search.text().strip()
        names = [e['name'][:50] for e in entries_to_complete[:10]]
        more = f"\n... and {len(entries_to_complete) - 10} more" if len(entries_to_complete) > 10 else ""

        reply = QMessageBox.question(
            self, "Complete All Matching",
            f"Mark {len(entries_to_complete)} entries as COMPLETED?\n"
            f"(Search filter: '{search_text}')\n\n"
            + "\n".join(f"  - {n}" for n in names)
            + more
            + "\n\nThis will set all matching quest/mission states to completed.\n"
            + "Save and reload in-game after.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        blob = self._save_data.decompressed_blob
        count = 0
        for entry in entries_to_complete:
            _write_quest_state(blob, entry, QuestState.FULLY_COMPLETED)
            count += 1

        self.dirty = True
        self._filter()
        self._status.setText(f"Completed {count} entries matching '{search_text}' (unsaved)")

    def _insert_quest_completed(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        key, ok = QInputDialog.getInt(
            self, "Add Quest as Completed",
            "Enter the quest key to insert as completed.\n"
            "Find keys in the Quest Database tab.\n\n"
            "Example: 1000212 = Shattered Ties (Dragon unlock)",
            1000212, 1, 9999999,
        )
        if not ok:
            return

        name = self._quest_names.get(key, self._mission_names.get(key, f'Unknown_{key}'))

        reply = QMessageBox.question(
            self, "Insert Quest",
            f"Insert quest '{name}' (key={key}) as COMPLETED?\n\n"
            f"This uses PARC insertion to add a new quest entry.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            from parc_inserter3 import insert_quest_completed
            blob = bytearray(self._save_data.decompressed_blob)
            ok_ins, new_blob, msg = insert_quest_completed(blob, key)
            if ok_ins:
                self._save_data.decompressed_blob = bytearray(new_blob)
                self._save_data.parse_cache = None
                self.dirty = True
                self._status.setText(f"Inserted: {name} — {msg}")
                self._quest_entries = []
                self._mission_entries = []
                self._parse_quests()
            else:
                self._status.setText(f"Insert failed: {msg}")
                QMessageBox.warning(self, "Insert Failed", msg)
        except Exception as e:
            log.exception("Unhandled exception")
            QMessageBox.critical(self, "Insert Error", str(e))

    def _save_file(self) -> None:
        reply = QMessageBox.question(
            self, "Save Quest Changes",
            "PLEASE MAKE SURE YOU HAVE A BACKUP OF YOUR SAVE.\n"
            "Quest state changes are experimental.\n\n"
            f"Save to: {self._save_path}\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            from save_crypto import write_save_file
            write_save_file(self._save_path, bytes(self._save_data.decompressed_blob),
                           self._save_data.raw_header)
            self._status.setText(f"Saved to {os.path.basename(self._save_path)}")
            QMessageBox.information(self, "Saved", f"Quest changes saved to:\n{self._save_path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))


class DescriptionSearchDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search by Description")
        self.setMinimumSize(800, 550)
        self.selected_key: int = 0
        self.selected_type: str = ""
        self.selected_name: str = ""
        self._entries = []

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        info = QLabel(
            "Search ALL buffs, passives, stats, and game descriptions by keyword.\n"
            "Type 'imbue fire', 'damage to machines', 'stamina', 'immunity', etc.")
        info.setWordWrap(True)
        layout.addWidget(info)

        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Type keywords to search descriptions...")
        self._search.textChanged.connect(self._filter)
        self._search.returnPressed.connect(self._on_accept)
        search_row.addWidget(self._search, 1)

        self._count = QLabel("")
        self._count.setStyleSheet(f"color: {COLORS['text_dim']};")
        search_row.addWidget(self._count)
        layout.addLayout(search_row)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Type", "Key", "Name", "Description"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.setColumnWidth(0, 60)
        self._table.setColumnWidth(1, 70)
        self._table.setColumnWidth(2, 200)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.doubleClicked.connect(self._on_accept)
        layout.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        copy_btn = QPushButton("Copy Key")
        copy_btn.clicked.connect(self._copy_key)
        btn_row.addWidget(copy_btn)
        ok_btn = QPushButton("Select")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("Close")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._load_data()

    def _load_data(self):
        base = os.path.dirname(os.path.abspath(__file__))

        try:
            _db = get_connection()
            for row in _db.execute("SELECT buff_key, description FROM buff_descriptions"):
                desc = row['description']
                if desc:
                    self._entries.append({
                        "type": "buff",
                        "key": row['buff_key'],
                        "name": desc,
                        "desc": desc,
                        "search": desc.lower(),
                    })
        except Exception:
            pass

        loc_path = os.path.join(base, "localizationstring_eng_items.tsv")
        if os.path.isfile(loc_path):
            try:
                with open(loc_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if "[Effect]" not in line:
                            continue
                        parts = line.strip().split(";", 1)
                        if len(parts) < 2:
                            continue
                        desc = parts[1].replace("<br/>", " ").replace("<br>", " ")
                        idx = desc.find("[Effect]")
                        effect = desc[idx:].strip()
                        if len(effect) > 10:
                            self._entries.append({
                                "type": "effect",
                                "key": 0,
                                "name": effect.split(":")[0].replace("[Effect] ", "").strip() if ":" in effect else effect[:40],
                                "desc": effect,
                                "search": effect.lower(),
                            })
            except Exception:
                pass

        if os.path.isfile(loc_path):
            try:
                with open(loc_path, "r", encoding="utf-8") as f:
                    for line in f:
                        parts = line.strip().split(";", 1)
                        if len(parts) < 2:
                            continue
                        desc = parts[1].strip()
                        if "(imbue " in desc and len(desc) < 80:
                            self._entries.append({
                                "type": "imbue",
                                "key": 0,
                                "name": desc,
                                "desc": desc,
                                "search": desc.lower(),
                            })
            except Exception:
                pass

    def _filter(self):
        query = self._search.text().strip().lower()
        if len(query) < 2:
            self._table.setRowCount(0)
            self._count.setText(f"{len(self._entries)} total entries")
            return

        words = query.split()
        matches = [e for e in self._entries if all(w in e["search"] for w in words)]

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(matches))
        for row, e in enumerate(matches):
            self._table.setItem(row, 0, QTableWidgetItem(e["type"]))
            key_item = QTableWidgetItem()
            key_item.setData(Qt.DisplayRole, e["key"])
            self._table.setItem(row, 1, key_item)
            self._table.setItem(row, 2, QTableWidgetItem(e["name"]))
            self._table.setItem(row, 3, QTableWidgetItem(e["desc"]))
        self._table.setSortingEnabled(True)
        self._count.setText(f"{len(matches)} results")

    def _get_selected(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return {
            "type": self._table.item(row, 0).text(),
            "key": int(self._table.item(row, 1).data(Qt.DisplayRole)),
            "name": self._table.item(row, 2).text(),
        }

    def _on_accept(self):
        sel = self._get_selected()
        if sel:
            self.selected_key = sel["key"]
            self.selected_type = sel["type"]
            self.selected_name = sel["name"]
            self.accept()

    def _copy_key(self):
        sel = self._get_selected()
        if sel and sel["key"]:
            QApplication.clipboard().setText(str(sel["key"]))


class ItemSearchDialog(QDialog):

    def __init__(self, name_db: ItemNameDB, title: str = "Search Items",
                 prompt: str = "Type an item name to search:", parent=None,
                 category_filter: str = "", template_only: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(600, 450)
        self._name_db = name_db
        self._category_filter = category_filter.lower()
        self._template_keys: set = set()
        self._template_only = template_only
        self.selected_key: int = 0
        self.selected_name: str = ""

        if template_only:
            self._load_template_keys()

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        lbl = QLabel(prompt)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Type item name or key...")
        self._search.textChanged.connect(self._filter)
        search_row.addWidget(self._search, 1)

        self._template_cb = QCheckBox("Template items only")
        self._template_cb.setToolTip("Only show items that have a community template (correct binary format)")
        self._template_cb.setChecked(template_only)
        self._template_cb.stateChanged.connect(self._on_template_toggle)
        search_row.addWidget(self._template_cb)
        layout.addLayout(search_row)

        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["Key", "Name", "Category"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self._table.setColumnWidth(1, 200)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {COLORS['text_dim']};")
        layout.addWidget(self._count_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._ok_btn = QPushButton("Select")
        self._ok_btn.setObjectName("accentBtn")
        self._ok_btn.setEnabled(False)
        self._ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(self._ok_btn)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        layout.addLayout(btn_row)

        self._table.selectionModel().selectionChanged.connect(self._on_sel)
        self._filter("")

    def _load_template_keys(self) -> None:
        try:
            _db = get_connection()
            self._template_keys.update(
                row['item_key'] for row in _db.execute("SELECT item_key FROM item_templates")
            )
        except Exception:
            pass

    def _on_template_toggle(self, state: int) -> None:
        self._template_only = bool(state)
        if self._template_only and not self._template_keys:
            self._load_template_keys()
        self._filter(self._search.text())

    def _filter(self, text: str) -> None:
        self._table.setSortingEnabled(False)
        results = self._name_db.search(text.strip()) if text.strip() else self._name_db.get_all_sorted()
        if self._category_filter:
            results = [r for r in results if r.category.lower() == self._category_filter]
        if self._template_only and self._template_keys:
            results = [r for r in results if r.item_key in self._template_keys]
        if not text.strip():
            results = results[:500]
        self._table.setRowCount(len(results))
        for row, info in enumerate(results):
            self._table.setItem(row, 0, QTableWidgetItem(str(info.item_key)))
            name_w = QTableWidgetItem(info.name)
            color = QColor(CATEGORY_COLORS.get(info.category, COLORS["text"]))
            name_w.setForeground(QBrush(color))
            self._table.setItem(row, 1, name_w)
            self._table.setItem(row, 2, QTableWidgetItem(info.category))
        self._table.setSortingEnabled(True)
        tmpl_note = " (template items)" if self._template_only else ""
        self._count_label.setText(f"{len(results)} items{tmpl_note}")

    def _on_sel(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        self._ok_btn.setEnabled(len(rows) > 0)

    def _on_double_click(self) -> None:
        self._on_accept()

    def _on_accept(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        key_item = self._table.item(row, 0)
        name_item = self._table.item(row, 1)
        if key_item:
            self.selected_key = int(key_item.text())
            self.selected_name = name_item.text() if name_item else ""
            self.accept()


class ApplyPackDialog(QDialog):

    def __init__(self, pack: ItemPack, name_db: ItemNameDB, items: List[SaveItem], parent=None, experimental: bool = False):
        super().__init__(parent)
        self.setWindowTitle(f"Apply Pack: {pack.name}")
        self.setMinimumSize(800, 500)
        self._name_db = name_db
        self._items = items
        self._pack = pack
        self._read_only = ("Mercenary",) if experimental else ("Store", "Mercenary")

        self._item_limits = {}
        try:
            _db = get_connection()
            self._item_limits = {str(row['item_key']): json.loads(row['data']) for row in _db.execute("SELECT item_key, data FROM item_limits")}
        except Exception:
            pass
        self.mappings: List[tuple] = []

        layout = QVBoxLayout(self)

        info = QLabel(
            f"Pack: {pack.name} by {pack.author}\n"
            f"{pack.description}\n\n"
            f"For each pack item, select a donor from your inventory to replace."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._map_table = QTableWidget()
        self._map_table.setColumnCount(6)
        self._map_table.setHorizontalHeaderLabels([
            "Apply", "Pack Item", "Count", "Enchant", "Donor (click to pick)", "Donor Key"
        ])
        self._map_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._map_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._map_table.setColumnWidth(0, 40)
        self._map_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self._map_table.setColumnWidth(1, 180)
        self._map_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self._map_table.setColumnWidth(4, 180)
        self._map_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._map_table.verticalHeader().setDefaultSectionSize(28)
        self._map_table.setRowCount(len(pack.items))

        self._donors: List[Optional[SaveItem]] = [None] * len(pack.items)

        for row, pi in enumerate(pack.items):
            check_item = QTableWidgetItem()
            check_item.setCheckState(Qt.Checked)
            self._map_table.setItem(row, 0, check_item)

            name = pi.name or name_db.get_name(pi.item_key)
            self._map_table.setItem(row, 1, QTableWidgetItem(f"{name} (key={pi.item_key})"))
            self._map_table.setItem(row, 2, QTableWidgetItem(str(pi.count)))
            enc_text = f"+{pi.enchant}" if pi.enchant >= 0 else "-"
            self._map_table.setItem(row, 3, QTableWidgetItem(enc_text))
            donor_w = QTableWidgetItem("(click row, then 'Pick Donor')")
            donor_w.setForeground(QBrush(QColor(COLORS["text_dim"])))
            self._map_table.setItem(row, 4, donor_w)
            self._map_table.setItem(row, 5, QTableWidgetItem(""))

        layout.addWidget(self._map_table)

        btn_row = QHBoxLayout()
        pick_btn = QPushButton("Pick Donor for Selected")
        pick_btn.clicked.connect(self._pick_donor)
        btn_row.addWidget(pick_btn)

        auto_btn = QPushButton("Auto-Pick Donors (same category)")
        auto_btn.setToolTip("Automatically assign donor items by matching category")
        auto_btn.clicked.connect(self._auto_pick)
        btn_row.addWidget(auto_btn)

        stack_btn = QPushButton("Pick Donor from Item Stack")
        stack_btn.setToolTip("Pick one stacked item — fills ALL donor slots from that stack")
        stack_btn.setObjectName("accentBtn")
        stack_btn.clicked.connect(self._pick_from_stack)
        btn_row.addWidget(stack_btn)

        btn_row.addStretch()

        apply_btn = QPushButton("Apply All Checked")
        apply_btn.setObjectName("accentBtn")
        apply_btn.setToolTip("Apply only the items with checkmarks. Unchecked items are skipped.")
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _pick_donor(self) -> None:
        rows = set(idx.row() for idx in self._map_table.selectedIndexes())
        if not rows:
            QMessageBox.information(self, "Pick Donor", "Select a row first.")
            return
        row = min(rows)
        pi = self._pack.items[row]
        target_cat = pi.category or self._name_db.get_category(pi.item_key)

        read_only = self._read_only
        used_offsets = {d.offset for d in self._donors if d is not None}
        available = [it for it in self._items if it.source not in read_only and it.offset not in used_offsets]

        def sort_key(it):
            cat = self._name_db.get_category(it.item_key)
            return (0 if cat == target_cat else 1, -it.stack_count)
        available.sort(key=sort_key)

        if not available:
            QMessageBox.warning(self, "No Donors", "No available donor items in inventory.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Pick donor for: {pi.name or self._name_db.get_name(pi.item_key)}")
        dlg.setMinimumSize(500, 400)
        dl = QVBoxLayout(dlg)
        dl.addWidget(QLabel(f"Target category: {target_cat}  |  Green = same category"))

        filter_row = QHBoxLayout()
        donor_search = QLineEdit()
        donor_search.setPlaceholderText("Search donors...")
        filter_row.addWidget(donor_search, 1)

        vendor_only_cb = QCheckBox("Vendor Repurchase Only")
        vendor_only_cb.setToolTip("Only show items sold to vendors (safest for swapping)")
        filter_row.addWidget(vendor_only_cb)
        dl.addLayout(filter_row)

        donor_list = QListWidget()
        donor_texts = []
        donor_sources = []
        for it in available:
            name = self._name_db.get_name(it.item_key)
            cat = self._name_db.get_category(it.item_key)
            src = it.source
            is_vendor = src not in ("Equipment", "Inventory", "Mercenary")
            src_label = f"  [{src}]" if is_vendor else ""
            text = f"{name}  |  key={it.item_key}  stk={it.stack_count}  slot={it.slot_no}  [{cat}]{src_label}"
            lw = QListWidgetItem(text)
            if cat == target_cat:
                lw.setForeground(QBrush(QColor(COLORS["success"])))
            if is_vendor:
                lw.setForeground(QBrush(QColor(COLORS["accent"])))
            donor_list.addItem(lw)
            donor_texts.append(text.lower())
            donor_sources.append(is_vendor)

        def _filter_donor_list(*_args):
            s = donor_search.text().lower().strip()
            vendor_only = vendor_only_cb.isChecked()
            for i in range(donor_list.count()):
                hidden = False
                if s and s not in donor_texts[i]:
                    hidden = True
                if vendor_only and not donor_sources[i]:
                    hidden = True
                donor_list.item(i).setHidden(hidden)

        donor_search.textChanged.connect(_filter_donor_list)
        vendor_only_cb.toggled.connect(_filter_donor_list)
        dl.addWidget(donor_list)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        dl.addWidget(bb)

        if dlg.exec() != QDialog.Accepted:
            return
        sel = donor_list.currentRow()
        if sel < 0:
            return

        donor = available[sel]
        self._donors[row] = donor
        donor_name = self._name_db.get_name(donor.item_key)
        w = QTableWidgetItem(f"{donor_name} (stk={donor.stack_count}, no={donor.item_no})")
        w.setForeground(QBrush(QColor(COLORS["success"])))
        self._map_table.setItem(row, 4, w)
        self._map_table.setItem(row, 5, QTableWidgetItem(str(donor.item_key)))

    def _auto_pick(self) -> None:
        read_only = self._read_only
        used_offsets = set()

        for row, pi in enumerate(self._pack.items):
            if self._donors[row] is not None:
                used_offsets.add(self._donors[row].offset)

        pack_is_equipment = any(
            (pi.enchant >= 0 or
             self._name_db.get_category(pi.item_key) in ("Equipment", "Weapon", "Armor", "Shield"))
            for pi in self._pack.items
        )

        for row, pi in enumerate(self._pack.items):
            if self._donors[row] is not None:
                continue

            target_limits = self._item_limits.get(str(pi.item_key), {})
            target_slot = target_limits.get('slotType', -1)
            target_is_real_equip = target_slot not in (-1, 65535)

            available = [
                it for it in self._items
                if it.source not in read_only and it.offset not in used_offsets
            ]

            best = None
            best_score = (-10, -10, -10)
            for it in available:
                cat = self._name_db.get_category(it.item_key)

                donor_limits = self._item_limits.get(str(it.item_key), {})
                donor_slot = donor_limits.get('slotType', -1)
                donor_is_real_equip = donor_slot not in (-1, 65535)

                if target_is_real_equip:
                    if donor_is_real_equip:
                        type_score = 3
                    else:
                        type_score = -5
                        continue
                else:
                    if not donor_is_real_equip:
                        type_score = 2
                    else:
                        type_score = -5
                        continue

                same_cat = 2 if cat == (pi.category or self._name_db.get_category(pi.item_key)) else 0
                score = (type_score, same_cat, it.stack_count)
                if score > best_score:
                    best_score = score
                    best = it

            if best:
                self._donors[row] = best
                used_offsets.add(best.offset)
                donor_name = self._name_db.get_name(best.item_key)
                cat = self._name_db.get_category(best.item_key)
                match_quality = "success" if best.has_enchant or best.is_equipment else "warning"
                w = QTableWidgetItem(f"{donor_name} (stk={best.stack_count}, no={best.item_no}) [{cat}]")
                w.setForeground(QBrush(QColor(COLORS[match_quality])))
                self._map_table.setItem(row, 4, w)
                self._map_table.setItem(row, 5, QTableWidgetItem(str(best.item_key)))
            else:
                target_type = "equipment" if target_is_real_equip else "non-equipment (material/dye/insect)"
                w = QTableWidgetItem(f"(no suitable {target_type} donors!)")
                w.setForeground(QBrush(QColor(COLORS["error"])))
                self._map_table.setItem(row, 4, w)

    def _pick_from_stack(self) -> None:
        read_only = self._read_only
        needed = sum(1 for d in self._donors if d is None)
        if needed == 0:
            QMessageBox.information(self, "Stack Donor", "All donors already assigned.")
            return

        from collections import Counter
        key_counts = Counter()
        key_items: dict = {}
        for it in self._items:
            if it.source in read_only:
                continue
            key_counts[it.item_key] += 1
            if it.item_key not in key_items:
                key_items[it.item_key] = []
            key_items[it.item_key].append(it)

        stacked = []
        for key, count in key_counts.items():
            if count >= 2:
                name = self._name_db.get_name(key)
                stacked.append((key, name, count, key_items[key]))

        if not stacked:
            QMessageBox.warning(
                self, "No Stacked Items",
                "No items with multiple copies found.\n\n"
                "Dupe some items first in-game (e.g., 30 Kite Shields),\n"
                "save, then load that save here."
            )
            return

        stacked.sort(key=lambda x: -x[2])

        dlg = QDialog(self)
        dlg.setWindowTitle("Pick Donor from Item Stack")
        dlg.setMinimumSize(500, 400)
        dl = QVBoxLayout(dlg)
        dl.addWidget(QLabel(
            f"Need {needed} donors. Pick a stacked item to fill all slots.\n"
            f"Items shown below have multiple copies in your inventory."
        ))

        stack_search = QLineEdit()
        stack_search.setPlaceholderText("Search stacked items...")
        dl.addWidget(stack_search)

        donor_list = QListWidget()
        stack_texts = []
        for key, name, count, items_list in stacked:
            has_enc = any(it.has_enchant for it in items_list)
            equip_tag = " [Equipment]" if has_enc else ""
            text = f"{name}  x{count}  (key={key}){equip_tag}"
            lw = QListWidgetItem(text)
            if count >= needed:
                lw.setForeground(QBrush(QColor(COLORS["success"])))
            else:
                lw.setForeground(QBrush(QColor(COLORS["warning"])))
            donor_list.addItem(lw)
            stack_texts.append(text.lower())

        def _filter_stack_list(text):
            s = text.lower().strip()
            for i in range(donor_list.count()):
                donor_list.item(i).setHidden(s != "" and s not in stack_texts[i])

        stack_search.textChanged.connect(_filter_stack_list)
        dl.addWidget(donor_list)

        info = QLabel(f"Green = enough copies for all {needed} slots")
        info.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
        dl.addWidget(info)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        dl.addWidget(bb)

        if dlg.exec() != QDialog.Accepted:
            return
        sel = donor_list.currentRow()
        if sel < 0:
            return

        key, name, count, items_list = stacked[sel]

        used_offsets = {d.offset for d in self._donors if d is not None}

        available = [it for it in items_list if it.offset not in used_offsets]
        filled = 0
        for row in range(len(self._pack.items)):
            if self._donors[row] is not None:
                continue
            if not available:
                break
            donor = available.pop(0)
            self._donors[row] = donor
            used_offsets.add(donor.offset)
            w = QTableWidgetItem(f"{name} (no={donor.item_no}, slot={donor.slot_no})")
            w.setForeground(QBrush(QColor(COLORS["success"])))
            self._map_table.setItem(row, 4, w)
            self._map_table.setItem(row, 5, QTableWidgetItem(str(donor.item_key)))
            filled += 1

        remaining = sum(1 for d in self._donors if d is None)
        if remaining > 0:
            QMessageBox.warning(
                self, "Not Enough",
                f"Filled {filled} slots but still need {remaining} more donors.\n"
                f"You had {count} copies of {name}, {len(items_list)} available."
            )
        else:
            self._ok_btn.setEnabled(True)
            QMessageBox.information(
                self, "Donors Assigned",
                f"Filled all {filled} donor slots with {name}."
            )

    def _on_apply(self) -> None:
        self.mappings = []
        missing_checked = []
        for i in range(len(self._pack.items)):
            check_item = self._map_table.item(i, 0)
            is_checked = check_item and check_item.checkState() == Qt.Checked
            if not is_checked:
                continue
            if self._donors[i] is None:
                missing_checked.append(self._pack.items[i].name or str(self._pack.items[i].item_key))
                continue
            self.mappings.append((self._pack.items[i], self._donors[i]))

        if missing_checked:
            QMessageBox.warning(
                self, "Missing Donors",
                f"{len(missing_checked)} checked items still need donors:\n"
                + "\n".join(missing_checked[:5])
                + ("\n..." if len(missing_checked) > 5 else "")
                + "\n\nUncheck them or assign donors."
            )
            return

        if not self.mappings:
            QMessageBox.warning(self, "Nothing Selected", "No items checked for apply.")
            return

        self.accept()


class CreatePackDialog(QDialog):

    def __init__(self, name_db: ItemNameDB, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Item Pack")
        self.setMinimumSize(800, 600)
        self._name_db = name_db
        self.pack: Optional[ItemPack] = None

        layout = QVBoxLayout(self)

        meta = QGroupBox("Pack Info")
        mg = QGridLayout(meta)
        mg.addWidget(QLabel("Name:"), 0, 0)
        self._pack_name = QLineEdit()
        self._pack_name.setPlaceholderText("e.g. Endgame Weapon Set")
        mg.addWidget(self._pack_name, 0, 1)
        mg.addWidget(QLabel("Author:"), 0, 2)
        self._pack_author = QLineEdit()
        self._pack_author.setPlaceholderText("Your name")
        mg.addWidget(self._pack_author, 0, 3)
        mg.addWidget(QLabel("Description:"), 1, 0)
        self._pack_desc = QLineEdit()
        self._pack_desc.setPlaceholderText("What's in this pack?")
        mg.addWidget(self._pack_desc, 1, 1, 1, 3)
        layout.addWidget(meta)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Search Item Database:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Type to search...")
        self._search.textChanged.connect(self._filter_items)
        ll.addWidget(self._search)

        self._db_table = QTableWidget()
        self._db_table.setColumnCount(3)
        self._db_table.setHorizontalHeaderLabels(["Key", "Name", "Category"])
        self._db_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._db_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._db_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self._db_table.setColumnWidth(1, 200)
        self._db_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._db_table.setSortingEnabled(True)
        self._db_table.verticalHeader().setDefaultSectionSize(22)
        ll.addWidget(self._db_table)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Count:"))
        self._add_count = QSpinBox()
        self._add_count.setRange(1, 999999)
        self._add_count.setValue(1)
        add_row.addWidget(self._add_count)
        add_row.addWidget(QLabel("Enchant:"))
        self._add_enchant = QSpinBox()
        self._add_enchant.setRange(-1, 10)
        self._add_enchant.setValue(-1)
        self._add_enchant.setSpecialValueText("None")
        add_row.addWidget(self._add_enchant)
        add_btn = QPushButton("Add to Pack >>")
        add_btn.setObjectName("accentBtn")
        add_btn.clicked.connect(self._add_to_pack)
        add_row.addWidget(add_btn)
        ll.addLayout(add_row)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Pack Contents:"))

        self._pack_table = QTableWidget()
        self._pack_table.setColumnCount(4)
        self._pack_table.setHorizontalHeaderLabels(["Name", "Key", "Count", "Enchant"])
        self._pack_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._pack_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._pack_table.setColumnWidth(0, 200)
        self._pack_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pack_table.verticalHeader().setDefaultSectionSize(22)
        rl.addWidget(self._pack_table)

        rm_btn = QPushButton("Remove Selected")
        rm_btn.clicked.connect(self._remove_from_pack)
        rl.addWidget(rm_btn)
        splitter.addWidget(right)

        splitter.setSizes([450, 350])
        layout.addWidget(splitter, 1)

        bb = QHBoxLayout()
        bb.addStretch()
        save_btn = QPushButton("Save Pack")
        save_btn.setObjectName("accentBtn")
        save_btn.clicked.connect(self._on_save)
        bb.addWidget(save_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        bb.addWidget(cancel_btn)
        layout.addLayout(bb)

        self._pack_items: List[PackItem] = []
        self._filter_items("")

    def _filter_items(self, text: str) -> None:
        table = self._db_table
        table.setSortingEnabled(False)
        items = self._name_db.search(text) if text.strip() else self._name_db.get_all_sorted()[:200]
        table.setRowCount(len(items))
        for row, info in enumerate(items):
            table.setItem(row, 0, QTableWidgetItem(str(info.item_key)))
            name_w = QTableWidgetItem(info.name)
            color = QColor(CATEGORY_COLORS.get(info.category, COLORS["text"]))
            name_w.setForeground(QBrush(color))
            table.setItem(row, 1, name_w)
            table.setItem(row, 2, QTableWidgetItem(info.category))
        table.setSortingEnabled(True)

    def _add_to_pack(self) -> None:
        rows = set(idx.row() for idx in self._db_table.selectedIndexes())
        count = self._add_count.value()
        enchant = self._add_enchant.value()

        for row in sorted(rows):
            key_w = self._db_table.item(row, 0)
            if not key_w:
                continue
            key = int(key_w.text())
            name = self._name_db.get_name(key)
            cat = self._name_db.get_category(key)
            self._pack_items.append(PackItem(
                item_key=key, name=name, count=count,
                enchant=enchant, category=cat,
            ))

        self._refresh_pack_table()

    def _remove_from_pack(self) -> None:
        rows = sorted(set(idx.row() for idx in self._pack_table.selectedIndexes()), reverse=True)
        for row in rows:
            if 0 <= row < len(self._pack_items):
                self._pack_items.pop(row)
        self._refresh_pack_table()

    def _refresh_pack_table(self) -> None:
        table = self._pack_table
        table.setRowCount(len(self._pack_items))
        for row, pi in enumerate(self._pack_items):
            table.setItem(row, 0, QTableWidgetItem(pi.name))
            table.setItem(row, 1, QTableWidgetItem(str(pi.item_key)))
            table.setItem(row, 2, QTableWidgetItem(str(pi.count)))
            enc_text = f"+{pi.enchant}" if pi.enchant >= 0 else "-"
            table.setItem(row, 3, QTableWidgetItem(enc_text))

    def _on_save(self) -> None:
        name = self._pack_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Create Pack", "Enter a pack name.")
            return
        if not self._pack_items:
            QMessageBox.warning(self, "Create Pack", "Add at least one item.")
            return

        import datetime
        self.pack = ItemPack(
            name=name,
            author=self._pack_author.text().strip() or "Anonymous",
            description=self._pack_desc.text().strip(),
            version=1,
            created=datetime.datetime.now().strftime("%Y-%m-%d"),
            items=list(self._pack_items),
        )
        self.accept()
