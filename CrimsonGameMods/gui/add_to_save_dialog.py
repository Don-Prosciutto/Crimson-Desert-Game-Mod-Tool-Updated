"""Add Custom Item to Save File dialog.

Invoked from the Item Creator dialog after a custom item has been
deployed to the game (iteminfo overlay). Lets the user pick a save
slot via the same save-slot discovery used by the main Save Browser,
browse their inventory and vendor-repurchase lists (with icons),
and swap an existing item's key to the custom item's key (e.g. 999001).
Game then reads the custom item's stats via the custom iteminfo entry.

Doesn't touch the game's iteminfo.pabgb. Modifies only the user's
save.save, writing a .backup sidecar first.
"""
from __future__ import annotations

import datetime
import logging
import os
import shutil
from typing import List, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from gui.theme import button_css

log = logging.getLogger(__name__)

ICON_COL_PX = 28


class AddCustomItemToSaveDialog(QDialog):
    """Modal dialog: pick save slot → browse inventory + repurchase → swap key."""

    def __init__(
        self,
        custom_key: int,
        custom_name: str,
        name_db,
        icon_cache,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Add '{custom_name}' to Save File")
        self.resize(960, 680)

        self._custom_key = int(custom_key)
        self._custom_name = custom_name
        self._name_db = name_db
        self._icon_cache = icon_cache

        self._slot_records: List[dict] = []
        self._save_path: str = ""
        self._save_data = None
        self._repurch_items: List = []

        self._build_ui()
        self._refresh_slots()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QLabel(
            f"<b>Custom item:</b> {self._custom_name}  "
            f"<b>(key {self._custom_key})</b><br>"
            f"Pick a save slot, then pick a vendor (sold/repurchase) item — "
            f"its key gets swapped to your custom item."
        )
        header.setWordWrap(True)
        header.setStyleSheet(
            "background-color: rgba(0,105,92,0.12); padding: 8px; "
            "border: 1px solid rgba(0,105,92,0.5); border-radius: 4px;"
        )
        layout.addWidget(header)

        # Save slot picker row — reuses find_save_files() from main_window
        # so we see exactly what the Save Browser sees. Auto-loads on
        # selection change.
        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Save slot:"))
        self._slot_combo = QComboBox()
        self._slot_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._slot_combo.setMinimumWidth(520)
        self._slot_combo.currentIndexChanged.connect(self._on_slot_changed)
        picker_row.addWidget(self._slot_combo, 1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Rescan AppData for save slots")
        refresh_btn.clicked.connect(self._refresh_slots)
        picker_row.addWidget(refresh_btn)

        browse_btn = QPushButton("Browse…")
        browse_btn.setToolTip("Pick a save.save file manually (e.g. a backup copy)")
        browse_btn.clicked.connect(self._on_browse)
        picker_row.addWidget(browse_btn)
        layout.addLayout(picker_row)

        # Repurchase / Sold items table. Inventory swaps were removed 2026-04-21
        # -- the in-save apply_item_swap path works for vendor-sold records but
        # the same swap against a live inventory record did not produce the
        # expected in-game result. Only Repurchase is exposed here.
        self._rep_label = QLabel("Repurchase / Sold Items (0)")
        self._rep_label.setStyleSheet("font-weight: bold; padding: 4px 2px;")
        layout.addWidget(self._rep_label)
        self._rep_table = self._make_table()
        layout.addWidget(self._rep_table, 1)

        # Filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("name, key, category…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._filter_edit, 1)
        layout.addLayout(filter_row)

        # Bottom row: status + swap + close
        bottom_row = QHBoxLayout()
        self._status = QLabel("Pick a save slot to begin.")
        self._status.setStyleSheet("color: #888; padding: 2px;")
        bottom_row.addWidget(self._status, 1)

        swap_btn = QPushButton(f"↻ Swap Selected → Key {self._custom_key}")
        swap_btn.setStyleSheet(
            button_css("danger") + " font-weight: bold; "
            "padding: 8px 14px;")
        swap_btn.setToolTip(
            "Pick a vendor item above, then click to change its key\n"
            "to your custom item's key. Save is backed up first.")
        swap_btn.clicked.connect(self._on_swap)
        bottom_row.addWidget(swap_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        bottom_row.addWidget(close_btn)
        layout.addLayout(bottom_row)

    def _make_table(self) -> QTableWidget:
        t = QTableWidget()
        t.setColumnCount(5)
        t.setHorizontalHeaderLabels(["Name", "Key", "Category", "Qty", "Source"])
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setSelectionMode(QTableWidget.SingleSelection)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setStretchLastSection(True)
        t.setIconSize(QSize(ICON_COL_PX, ICON_COL_PX))
        t.setColumnWidth(0, 320)
        t.setColumnWidth(1, 80)
        t.setColumnWidth(2, 140)
        t.setColumnWidth(3, 70)
        return t

    # ------------------------------------------------------------------
    def _refresh_slots(self) -> None:
        """Repopulate the combobox from find_save_files()."""
        try:
            from gui.main_window import find_save_files
            self._slot_records = find_save_files()
        except Exception as e:
            log.warning("find_save_files failed: %s", e)
            self._slot_records = []

        self._slot_combo.blockSignals(True)
        self._slot_combo.clear()
        if not self._slot_records:
            self._slot_combo.addItem(
                "(no save slots found — use Browse… to pick manually)")
            self._slot_combo.setEnabled(False)
        else:
            self._slot_combo.setEnabled(True)
            for rec in self._slot_records:
                self._slot_combo.addItem(rec["display"])
        self._slot_combo.setCurrentIndex(-1)  # don't auto-load until user picks
        self._slot_combo.blockSignals(False)

        if self._slot_records:
            self._status.setText(
                f"{len(self._slot_records)} save slot(s) found — pick one to load.")
        else:
            self._status.setText(
                "No save slots auto-detected. Use Browse… to pick a save.save.")

    def _on_slot_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._slot_records):
            return
        self._save_path = self._slot_records[idx]["path"]
        self._load_save()

    def _on_browse(self) -> None:
        start = os.path.dirname(self._save_path) if self._save_path else \
            os.path.expandvars(r"%LOCALAPPDATA%\Pearl Abyss\CD\save")
        if not os.path.isdir(start):
            start = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick save.save", start,
            "Save file (save.save);;All files (*.*)")
        if path:
            self._save_path = path
            # Deselect the combo so the user knows they're on a manual pick
            self._slot_combo.blockSignals(True)
            self._slot_combo.setCurrentIndex(-1)
            self._slot_combo.blockSignals(False)
            self._load_save()

    # ------------------------------------------------------------------
    def _load_save(self) -> None:
        if not self._save_path or not os.path.isfile(self._save_path):
            QMessageBox.warning(self, "Load Save", "No valid save file selected.")
            return

        self._status.setText(f"Loading {os.path.basename(self._save_path)}…")

        try:
            from save_crypto import load_save_file
            self._save_data = load_save_file(self._save_path)
        except Exception as e:
            log.exception("Load save failed")
            QMessageBox.critical(self, "Load Save", f"Failed to load:\n{e}")
            self._save_data = None
            self._status.setText("Load failed.")
            return

        # Repurchase via a headless RepurchaseTab (reuses its PARC store
        # parser without refactoring the tab). RepurchaseTab.load() needs an
        # items list -- scan_items_parc provides it and is only used here to
        # satisfy that contract; its results aren't displayed.
        self._repurch_items = []
        try:
            from item_scanner import scan_items_parc
            inv, _note = scan_items_parc(self._save_data.decompressed_blob)
        except Exception:
            inv = []
        try:
            from gui.tabs.items import RepurchaseTab
            shim = RepurchaseTab(
                name_db=self._name_db,
                icon_cache=self._icon_cache,
                icons_enabled=False,
            )
            shim.load(self._save_data, inv)
            self._repurch_items = list(shim.scan_repurchase_items())
            shim.deleteLater()
        except Exception as e:
            log.warning("Repurchase scan failed: %s", e)

        self._populate_tables()
        self._status.setText(
            f"✓ Loaded {os.path.basename(self._save_path)} — "
            f"{len(self._repurch_items)} repurchase items."
        )

    # ------------------------------------------------------------------
    def _populate_tables(self) -> None:
        self._fill_table(self._rep_table, self._repurch_items, is_repurch=True)
        self._rep_label.setText(f"Repurchase / Sold Items ({len(self._repurch_items)})")
        self._apply_filter()

    def _fill_table(self, table: QTableWidget, items: List, *, is_repurch: bool) -> None:
        table.setRowCount(len(items))
        for row, it in enumerate(items):
            name = getattr(it, "name", None) or self._name_db.get_name(it.item_key)
            cat = getattr(it, "category", None) or self._name_db.get_category(it.item_key)
            qty = getattr(it, "stack_count", 0) or 0
            src = getattr(it, "source", "") or ("Vendor" if is_repurch else "Inventory")

            name_item = QTableWidgetItem(str(name))
            # Icon — same API the Items tab uses.
            try:
                px = self._icon_cache.get_pixmap(it.item_key)
                if px is not None:
                    from PySide6.QtGui import QIcon
                    name_item.setIcon(QIcon(px))
            except Exception:
                pass
            table.setItem(row, 0, name_item)
            table.setItem(row, 1, QTableWidgetItem(str(it.item_key)))
            table.setItem(row, 2, QTableWidgetItem(str(cat)))
            table.setItem(row, 3, QTableWidgetItem(str(qty)))
            table.setItem(row, 4, QTableWidgetItem(str(src)))

    def _apply_filter(self) -> None:
        needle = self._filter_edit.text().lower().strip()
        table = self._rep_table
        for row in range(table.rowCount()):
            if not needle:
                table.setRowHidden(row, False)
                continue
            hit = False
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item and needle in item.text().lower():
                    hit = True
                    break
            table.setRowHidden(row, not hit)

    # ------------------------------------------------------------------
    def _selected(self) -> Optional[object]:
        rows = {idx.row() for idx in self._rep_table.selectedIndexes()}
        if not rows:
            return None
        row = min(rows)
        if row >= len(self._repurch_items):
            return None
        return self._repurch_items[row]

    def _on_swap(self) -> None:
        if self._save_data is None:
            QMessageBox.warning(self, "Swap", "Load a save slot first.")
            return

        target = self._selected()
        if target is None:
            QMessageBox.warning(
                self, "Swap",
                "Pick a vendor item in the Repurchase list first.")
            return

        old_key = target.item_key
        old_name = getattr(target, "name", None) or self._name_db.get_name(old_key)

        reply = QMessageBox.question(
            self, "Confirm Swap",
            f"Replace this vendor item's key with your custom item key?\n\n"
            f"  Target: {old_name} (key {old_key})\n"
            f"  Becomes: {self._custom_name} (key {self._custom_key})\n\n"
            f"A backup will be written to\n  {self._save_path}.backup\n"
            f"before the save is modified.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        try:
            shutil.copy2(self._save_path, self._save_path + ".backup")
        except Exception as e:
            QMessageBox.critical(
                self, "Backup Failed",
                f"Could not create backup before writing:\n{e}\n\n"
                f"Aborting to protect your save.")
            return

        try:
            from item_scanner import apply_item_swap
            blob = bytearray(self._save_data.decompressed_blob)
            patches = apply_item_swap(blob, target, self._custom_key)
            if not patches:
                QMessageBox.information(
                    self, "No-op",
                    "Target item already has this key — nothing to do.")
                return
            self._save_data.decompressed_blob = bytes(blob)
        except Exception as e:
            log.exception("Key swap failed")
            QMessageBox.critical(self, "Swap Failed", str(e))
            return

        # Write save — original_header is required, otherwise bytes 0x08-0x11
        # zero out and the game rejects the save.
        try:
            from save_crypto import write_save_file
            write_save_file(
                self._save_path,
                self._save_data.decompressed_blob,
                original_header=self._save_data.raw_header,
            )
        except Exception as e:
            log.exception("Write save failed")
            QMessageBox.critical(
                self, "Write Failed",
                f"Failed to write save:\n{e}\n\n"
                f"Your backup at {self._save_path}.backup is intact.")
            return

        self._status.setText(
            f"✓ Swapped {old_name} (key {old_key}) → custom key {self._custom_key}. "
            f"Save written, backup at .backup.")
        QMessageBox.information(
            self, "Swap Complete",
            f"Success. In-game, the {old_name} slot now shows as:\n"
            f"  {self._custom_name}\n\n"
            f"If the item doesn't appear immediately, exit to title and reload "
            f"your save. If something looks wrong, restore from "
            f"{os.path.basename(self._save_path)}.backup.")
        self.accept()
