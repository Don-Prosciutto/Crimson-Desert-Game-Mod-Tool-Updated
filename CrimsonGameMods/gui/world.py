from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import struct
import sys
from typing import Callable, List, Optional

from data_db import get_connection

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QDialog, QFileDialog, QFrame, QGroupBox,
    QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QDoubleSpinBox, QSplitter,
    QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)
from gui.theme import COLORS, CATEGORY_COLORS, button_css
from gui.dialogs import ItemSearchDialog
from icon_cache import ICON_SIZE
from gui.utils import make_scope_label, make_help_btn
from i18n import tr

log = logging.getLogger(__name__)


def _is_admin() -> bool:
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


class GameDataTab(QWidget):

    status_message = Signal(str)

    def __init__(self, game_path_fn=None, show_guide_fn=None, parent=None):
        super().__init__(parent)
        self._game_path: str = ""
        self._game_path_fn = game_path_fn
        self._show_guide_fn = show_guide_fn
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._game_path = path

    def set_experimental_mode(self, enabled: bool) -> None:
        if hasattr(self, '_dev_export_btn_gd'):
            self._dev_export_btn_gd.setVisible(bool(enabled))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(make_scope_label("game"))

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel(tr("File:")))
        self._gd_file_combo = QComboBox()
        self._gd_file_combo.setMinimumWidth(250)
        from gamedata_editor import GameDataEditor
        for name, desc in GameDataEditor.KNOWN_FILES.items():
            self._gd_file_combo.addItem(f"{name} — {desc}", name)
        top_row.addWidget(self._gd_file_combo, 1)

        gd_load_btn = QPushButton(tr("Load"))
        gd_load_btn.setObjectName("accentBtn")
        gd_load_btn.clicked.connect(self._gd_load)
        top_row.addWidget(gd_load_btn)

        self._gd_status = QLabel("")
        self._gd_status.setStyleSheet(f"color: {COLORS['accent']}; padding: 4px;")
        top_row.addWidget(self._gd_status, 1)

        top_row.addWidget(make_help_btn("gamedata", self._show_guide_fn))
        layout.addLayout(top_row)

        splitter = QSplitter(Qt.Horizontal)

        left = QFrame()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(tr("Search:")))
        self._gd_search = QLineEdit()
        self._gd_search.setPlaceholderText(tr("Filter by name or key..."))
        self._gd_search.textChanged.connect(self._gd_filter)
        search_row.addWidget(self._gd_search, 1)
        left_layout.addLayout(search_row)

        self._gd_record_table = QTableWidget()
        self._gd_record_table.setColumnCount(4)
        self._gd_record_table.setHorizontalHeaderLabels(["#", "Key", "Name", "Size"])
        self._gd_record_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._gd_record_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._gd_record_table.setSelectionMode(QAbstractItemView.SingleSelection)
        gh = self._gd_record_table.horizontalHeader()
        gh.setSectionResizeMode(0, QHeaderView.Interactive)
        self._gd_record_table.setColumnWidth(0, 40)
        gh.setSectionResizeMode(1, QHeaderView.Interactive)
        self._gd_record_table.setColumnWidth(1, 80)
        gh.setSectionResizeMode(2, QHeaderView.Interactive)
        self._gd_record_table.setColumnWidth(2, 200)
        gh.setSectionResizeMode(3, QHeaderView.Interactive)
        self._gd_record_table.setColumnWidth(3, 60)
        self._gd_record_table.verticalHeader().setDefaultSectionSize(22)
        self._gd_record_table.selectionModel().selectionChanged.connect(self._gd_record_selected)
        left_layout.addWidget(self._gd_record_table)

        self._gd_record_count = QLabel("")
        self._gd_record_count.setStyleSheet(f"color: {COLORS['text_dim']};")
        left_layout.addWidget(self._gd_record_count)
        splitter.addWidget(left)

        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._gd_record_label = QLabel(tr("Select a record to view"))
        self._gd_record_label.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold; padding: 4px;")
        right_layout.addWidget(self._gd_record_label)

        self._gd_hex_view = QTextEdit()
        self._gd_hex_view.setReadOnly(True)
        self._gd_hex_view.setFont(QFont("Consolas", 11))
        self._gd_hex_view.setStyleSheet(
            f"background-color: {COLORS['input_bg']}; color: {COLORS['text']}; "
            f"border: 1px solid {COLORS['border']};"
        )
        right_layout.addWidget(self._gd_hex_view, 1)

        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel(tr("Offset:")))
        self._gd_edit_offset = QLineEdit()
        self._gd_edit_offset.setPlaceholderText(tr("0x00"))
        self._gd_edit_offset.setFixedWidth(80)
        edit_row.addWidget(self._gd_edit_offset)

        edit_row.addWidget(QLabel(tr("Bytes (hex):")))
        self._gd_edit_bytes = QLineEdit()
        self._gd_edit_bytes.setPlaceholderText(tr("FF FF FF FF"))
        self._gd_edit_bytes.setMinimumWidth(150)
        edit_row.addWidget(self._gd_edit_bytes, 1)

        gd_patch_btn = QPushButton(tr("Patch Bytes"))
        gd_patch_btn.clicked.connect(self._gd_patch_bytes)
        edit_row.addWidget(gd_patch_btn)
        right_layout.addLayout(edit_row)

        apply_row = QHBoxLayout()
        gd_apply_btn = QPushButton(tr("Apply to Game"))
        gd_apply_btn.setObjectName("accentBtn")
        gd_apply_btn.setToolTip(tr("Write changes to original game PAZ file (in-place)"))
        gd_apply_btn.clicked.connect(self._gd_apply)
        apply_row.addWidget(gd_apply_btn)

        gd_restore_btn = QPushButton(tr("Restore"))
        gd_restore_btn.setToolTip(tr("Restore from .sebak backup"))
        gd_restore_btn.clicked.connect(self._gd_restore)
        apply_row.addWidget(gd_restore_btn)

        gd_export_btn = QPushButton(tr("Export Record"))
        gd_export_btn.setToolTip(tr("ADVANCED — Export selected record as hex/binary"))
        gd_export_btn.clicked.connect(self._gd_export_record)
        gd_export_btn.setVisible(False)
        apply_row.addWidget(gd_export_btn)
        self._dev_export_btn_gd = gd_export_btn

        apply_row.addStretch()
        right_layout.addLayout(apply_row)

        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel(tr("Quick:")))

        gd_boost_drops = QPushButton(tr("5x Drop Rates"))
        gd_boost_drops.setToolTip(tr("Multiply ALL drop rates in this file by 5x (dropsetinfo only)"))
        gd_boost_drops.clicked.connect(lambda: self._gd_batch_multiply_rates(5))
        batch_row.addWidget(gd_boost_drops)

        gd_max_drops = QPushButton(tr("Max Drop Rates"))
        gd_max_drops.setToolTip(tr("Set all drop rates to 100% (dropsetinfo only)"))
        gd_max_drops.clicked.connect(lambda: self._gd_batch_multiply_rates(0))
        batch_row.addWidget(gd_max_drops)

        gd_zero_cooldowns = QPushButton(tr("Zero Cooldowns"))
        gd_zero_cooldowns.setToolTip(tr("Set all cooldown timers to 0 (skill only)"))
        gd_zero_cooldowns.clicked.connect(self._gd_batch_zero_cooldowns)
        batch_row.addWidget(gd_zero_cooldowns)

        batch_row.addStretch()
        right_layout.addLayout(batch_row)

        splitter.addWidget(right)
        splitter.setSizes([350, 500])
        layout.addWidget(splitter, 1)

        self._gd_editor = None
        self._gd_current_file = None


    def _gd_load(self) -> None:
        game_path = self._game_path.strip() if hasattr(self, '_paz_game_path') else ""
        if not game_path:
            QMessageBox.warning(self, tr("No Game Path"), tr("Set the game install path using the Browse button at the top."))
            return

        file_name = self._gd_file_combo.currentData()
        if not file_name:
            return

        self._gd_status.setText(f"Loading {file_name}...")
        QApplication.processEvents()

        try:
            from gamedata_editor import GameDataEditor
            if not self._gd_editor:
                self._gd_editor = GameDataEditor(game_path)
                self._gd_editor.load_item_names()

            pf = self._gd_editor.extract_file(file_name)
            if pf:
                self._gd_current_file = file_name
                self._gd_status.setText(
                    f"{file_name}: {len(pf.records)} records, {len(pf.body_bytes):,} bytes"
                )
                self._gd_populate_records()
            else:
                self._gd_status.setText(f"Failed to load {file_name}")
        except Exception as e:
            self._gd_status.setText(f"Error: {e}")
            log.exception("Unhandled exception")

    def _gd_populate_records(self, filter_text: str = "") -> None:
        if not self._gd_editor or not self._gd_current_file:
            return
        records = self._gd_editor.search_records(self._gd_current_file, filter_text)

        table = self._gd_record_table
        table.setSortingEnabled(False)
        table.setRowCount(len(records))
        for row, rec in enumerate(records):
            idx_w = QTableWidgetItem()
            idx_w.setData(Qt.DisplayRole, rec.index)
            idx_w.setData(Qt.UserRole, rec.index)
            table.setItem(row, 0, idx_w)

            key_w = QTableWidgetItem()
            key_w.setData(Qt.DisplayRole, rec.key)
            table.setItem(row, 1, key_w)

            display_name = self._gd_editor.resolve_record_display_name(self._gd_current_file, rec)
            name_w = QTableWidgetItem(display_name)
            if not rec.name:
                name_w.setForeground(QBrush(QColor(COLORS['text_dim'])))
            name_w.setToolTip(rec.name)
            table.setItem(row, 2, name_w)

            size_w = QTableWidgetItem()
            size_w.setData(Qt.DisplayRole, rec.size)
            table.setItem(row, 3, size_w)

        table.setSortingEnabled(True)
        self._gd_record_count.setText(f"{len(records)} records")

    def _gd_filter(self, text: str) -> None:
        self._gd_populate_records(text)

    def _gd_record_selected(self, *_args) -> None:
        if not self._gd_editor or not self._gd_current_file:
            return
        rows = self._gd_record_table.selectionModel().selectedRows()
        if not rows:
            return
        rec_idx = self._gd_record_table.item(rows[0].row(), 0).data(Qt.UserRole)
        pf = self._gd_editor.get_file(self._gd_current_file)
        if not pf or rec_idx >= len(pf.records):
            return
        rec = pf.records[rec_idx]
        self._gd_record_label.setText(
            f"{rec.name or '(unnamed)'}  |  Key: {rec.key}  |  "
            f"Offset: 0x{rec.offset:X}  |  Size: {rec.size} bytes"
        )

        display_parts = []

        try:
            from pabgb_field_parsers import get_parser
            parser_fn = get_parser(self._gd_current_file)
            if parser_fn:
                item_keys = set(self._gd_editor._name_lookup.keys()) if self._gd_editor._name_lookup else set()
                if 'known_item_keys' in parser_fn.__code__.co_varnames:
                    parsed_fields = parser_fn(pf.body_bytes, rec.offset, rec.size, item_keys)
                else:
                    parsed_fields = parser_fn(pf.body_bytes, rec.offset, rec.size)

                if parsed_fields:
                    display_parts.append(f"=== PARSED FIELDS ({len(parsed_fields)}) ===")
                    display_parts.append(f"{'Offset':<10s} {'Type':<10s} {'Category':<12s} {'Name':<20s} {'Value':<20s} Display")
                    display_parts.append("-" * 90)
                    by_cat = {}
                    for pf_field in parsed_fields:
                        by_cat.setdefault(pf_field.category, []).append(pf_field)
                    for cat, cat_fields in by_cat.items():
                        display_parts.append(f"\n  [{cat}]")
                        for pf_field in cat_fields[:20]:
                            val_str = str(pf_field.value)
                            if len(val_str) > 18:
                                val_str = val_str[:15] + "..."
                            name = self._gd_editor.get_item_name(pf_field.value) if pf_field.field_type == 'item_key' else ''
                            disp = name if name else pf_field.display
                            display_parts.append(
                                f"  0x{pf_field.offset:06X}  {pf_field.field_type:<10s} {pf_field.category:<12s} "
                                f"{pf_field.name:<20s} {val_str:<20s} {disp}"
                            )
                        if len(cat_fields) > 20:
                            display_parts.append(f"  ... +{len(cat_fields)-20} more")
                    display_parts.append("")
        except Exception as e:
            display_parts.append(f"Parser error: {e}")

        hex_dump = self._gd_editor.get_record_hex(self._gd_current_file, rec_idx, max_bytes=2048)
        display_parts.append("=== HEX DUMP ===")
        display_parts.append(hex_dump)

        self._gd_hex_view.setPlainText('\n'.join(display_parts))
        self._gd_edit_offset.setText(f"0x{rec.offset:X}")

    def _gd_patch_bytes(self) -> None:
        if not self._gd_editor or not self._gd_current_file:
            return
        try:
            off_text = self._gd_edit_offset.text().strip()
            offset = int(off_text, 16) if off_text.startswith('0x') else int(off_text)
            hex_text = self._gd_edit_bytes.text().strip().replace(' ', '')
            new_bytes = bytes.fromhex(hex_text)
        except (ValueError, TypeError) as e:
            QMessageBox.warning(self, tr("Invalid Input"), f"Bad offset or hex: {e}")
            return

        ok = self._gd_editor.patch_bytes(self._gd_current_file, offset, new_bytes)
        if ok:
            self._gd_status.setText(f"Patched {len(new_bytes)} bytes at 0x{offset:X}")
            self._gd_record_selected()
        else:
            QMessageBox.warning(self, tr("Patch Failed"), tr("Offset out of range."))

    def _gd_apply(self) -> None:
        if not self._gd_editor or not self._gd_current_file:
            QMessageBox.warning(self, tr("Game Data"), tr("Load a file first."))
            return
        if not _is_admin():
            QMessageBox.warning(self, tr("Admin Required"),
                tr("Run as administrator to write game files."))
            return

        reply = QMessageBox.question(
            self, tr("Apply Game Data Changes"),
            f"Write modified {self._gd_current_file}.pabgb to the game?\n\n"
            f"This patches the original PAZ file in-place.\n"
            f"A backup (.sebak) is created automatically.\n\n"
            f"RESTART THE GAME for changes to take effect.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        ok, msg = self._gd_editor.apply_to_game(self._gd_current_file)
        if ok:
            self._gd_status.setText(f"Applied: {self._gd_current_file}")
            QMessageBox.information(self, tr("Applied"),
                f"{msg}\n\nRESTART THE GAME for changes to take effect.")
        else:
            self._gd_status.setText(f"Failed: {msg}")
            QMessageBox.critical(self, tr("Failed"), msg)

    def _gd_restore(self) -> None:
        if not self._gd_editor or not self._gd_current_file:
            return
        reply = QMessageBox.question(
            self, tr("Restore Game Data"),
            f"Restore {self._gd_current_file} from backup?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        ok, msg = self._gd_editor.restore_file(self._gd_current_file)
        self._gd_status.setText(msg)
        QMessageBox.information(self, tr("Restore"), msg)

    def _gd_export_record(self) -> None:
        if not self._gd_editor or not self._gd_current_file:
            return
        rows = self._gd_record_table.selectionModel().selectedRows()
        if not rows:
            return
        rec_idx = self._gd_record_table.item(rows[0].row(), 0).data(Qt.UserRole)
        pf = self._gd_editor.get_file(self._gd_current_file)
        if not pf or rec_idx >= len(pf.records):
            return
        rec = pf.records[rec_idx]
        raw = bytes(pf.body_bytes[rec.offset:rec.offset + rec.size])
        safe_name = (rec.name or str(rec.key)).replace(' ', '_').replace('/', '_')
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Record",
            f"{self._gd_current_file}_{safe_name}.bin",
            "Binary Files (*.bin);;All Files (*)")
        if path:
            with open(path, 'wb') as f:
                f.write(raw)
            self._gd_status.setText(f"Exported {len(raw)} bytes to {os.path.basename(path)}")

    def _gd_batch_multiply_rates(self, multiplier: int) -> None:
        if not self._gd_editor or self._gd_current_file != 'dropsetinfo':
            QMessageBox.information(self, tr("Drop Rates"), tr("Load dropsetinfo first."))
            return

        pf = self._gd_editor.get_file('dropsetinfo')
        if not pf:
            return

        label = "100% (max)" if multiplier == 0 else f"{multiplier}x"
        reply = QMessageBox.question(
            self, tr("Batch Drop Rate Edit"),
            f"Set ALL drop rates to {label} across {len(pf.records)} drop sets?\n\n"
            f"This modifies rate-like u32 values (100-100000 range, ×100 basis).\n"
            f"Click 'Apply to Game' afterward to write changes.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        from pabgb_field_parsers import _scan_rates
        changed = 0
        for rec in pf.records:
            rates = _scan_rates(pf.body_bytes, rec.offset, rec.offset + rec.size)
            for rate_field in rates:
                old_val = rate_field.value
                if multiplier == 0:
                    new_val = 10000
                else:
                    new_val = min(old_val * multiplier, 10000)
                if new_val != old_val:
                    struct.pack_into('<I', pf.body_bytes, rate_field.offset, new_val)
                    changed += 1

        self._gd_status.setText(f"Modified {changed} rate values to {label}")
        self._gd_record_selected()

    def _gd_batch_zero_cooldowns(self) -> None:
        if not self._gd_editor or self._gd_current_file != 'skill':
            QMessageBox.information(self, tr("Cooldowns"), tr("Load skill data first."))
            return

        pf = self._gd_editor.get_file('skill')
        if not pf:
            return

        reply = QMessageBox.question(
            self, tr("Zero Cooldowns"),
            f"Set all cooldown timers to 100ms across {len(pf.records)} skills?\n\n"
            f"This modifies u32 values in the 500-120000 range (millisecond timers).\n"
            f"Click 'Apply to Game' afterward to write changes.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        changed = 0
        for rec in pf.records:
            end = rec.offset + rec.size
            for off in range(rec.offset, min(end - 3, len(pf.body_bytes) - 3), 4):
                v = struct.unpack_from('<I', pf.body_bytes, off)[0]
                if 500 <= v <= 120000 and v % 100 == 0:
                    struct.pack_into('<I', pf.body_bytes, off, 100)
                    changed += 1

        self._gd_status.setText(f"Zeroed {changed} cooldown values")
        self._gd_record_selected()


class StoreEditorTab(QWidget):

    status_message = Signal(str)
    config_save_requested = Signal()
    paz_refresh_requested = Signal()

    def __init__(
        self,
        name_db,
        icon_cache,
        config: dict,
        rebuild_papgt_fn: Optional[Callable] = None,
        show_guide_fn=None,
        parent=None,
    ):
        super().__init__(parent)
        self._name_db = name_db
        self._icon_cache = icon_cache
        self._config = config
        self._rebuild_papgt_fn = rebuild_papgt_fn
        self._show_guide_fn = show_guide_fn
        self._game_path: str = ""
        self._icons_enabled: bool = False
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._game_path = path

    def set_experimental_mode(self, enabled: bool) -> None:
        if hasattr(self, '_dev_export_btn_store'):
            self._dev_export_btn_store.setVisible(bool(enabled))

    def set_icons_enabled(self, enabled: bool) -> None:
        self._icons_enabled = enabled

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(make_scope_label("game"))

        info = QLabel(
            "Edit vendor inventories — swap items, change purchase limits, "
            "then Export JSON to use with CD JSON Mod Manager. "
            "Compatible with community JSON patch format (Pldada/CDUMM)."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['accent']}; padding: 8px; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"background-color: rgba(218,168,80,0.08);"
        )
        layout.addWidget(info)

        top_row = QHBoxLayout()
        store_extract_btn = QPushButton(tr("Load Store Data"))
        store_extract_btn.setObjectName("accentBtn")
        store_extract_btn.setToolTip(tr("Extract storeinfo.pabgb from the game PAZ archive"))
        store_extract_btn.clicked.connect(self._store_extract)
        top_row.addWidget(store_extract_btn)

        import_json_btn = QPushButton(tr("Import JSON Patch"))
        import_json_btn.setToolTip(tr("Import a Pldada-format JSON vendor patch file"))
        import_json_btn.clicked.connect(self._store_import_json)
        top_row.addWidget(import_json_btn)

        export_json_btn = QPushButton(tr("Export JSON Patch"))
        export_json_btn.setToolTip(tr("ADVANCED — UNSUPPORTED. Export changes as JSON patch."))
        export_json_btn.clicked.connect(self._store_export_json)
        export_json_btn.setVisible(False)
        top_row.addWidget(export_json_btn)
        self._dev_export_btn_store = export_json_btn

        top_row.addWidget(QLabel(tr("Overlay:")))
        self._store_overlay_spin = QSpinBox()
        self._store_overlay_spin.setRange(1, 9999)
        self._store_overlay_spin.setValue(self._config.get("store_overlay_dir", 60))
        self._store_overlay_spin.setFixedWidth(70)
        self._store_overlay_spin.setToolTip(
            "PAZ group folder used when applying stores to game.\n"
            "Default: 0060. Change if another mod already occupies 0060."
        )
        self._store_overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"store_overlay_dir": v}) or self.config_save_requested.emit()
        )
        top_row.addWidget(self._store_overlay_spin)

        self._store_status = QLabel("")
        self._store_status.setStyleSheet(f"color: {COLORS['accent']}; padding: 4px;")
        top_row.addWidget(self._store_status, 1)

        self._store_changes_label = QLabel("")
        self._store_changes_label.setStyleSheet(f"color: {COLORS['warning']}; font-weight: bold; padding: 4px;")
        top_row.addWidget(self._store_changes_label)
        top_row.addWidget(make_help_btn("stores", self._show_guide_fn))
        layout.addLayout(top_row)

        splitter = QSplitter(Qt.Horizontal)

        store_frame = QFrame()
        store_vlayout = QVBoxLayout(store_frame)
        store_vlayout.setContentsMargins(0, 0, 0, 0)

        store_search_row = QHBoxLayout()
        store_search_row.addWidget(QLabel(tr("Search:")))
        self._store_search = QLineEdit()
        self._store_search.setPlaceholderText(tr("Filter stores..."))
        self._store_search.textChanged.connect(self._store_filter)
        store_search_row.addWidget(self._store_search, 1)
        store_vlayout.addLayout(store_search_row)

        self._store_list = QTableWidget()
        self._store_list.setColumnCount(4)
        self._store_list.setHorizontalHeaderLabels(["Key", "Store Name", "Items", "Type"])
        self._store_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._store_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._store_list.setSelectionMode(QAbstractItemView.SingleSelection)
        sh = self._store_list.horizontalHeader()
        sh.setSectionResizeMode(0, QHeaderView.Interactive)
        self._store_list.setColumnWidth(0, 80)
        sh.setSectionResizeMode(1, QHeaderView.Interactive)
        self._store_list.setColumnWidth(1, 200)
        sh.setSectionResizeMode(2, QHeaderView.Interactive)
        self._store_list.setColumnWidth(2, 60)
        sh.setSectionResizeMode(3, QHeaderView.Interactive)
        self._store_list.setColumnWidth(3, 80)
        self._store_list.verticalHeader().setDefaultSectionSize(24)
        self._store_list.selectionModel().selectionChanged.connect(self._store_selected)
        store_vlayout.addWidget(self._store_list)
        splitter.addWidget(store_frame)

        items_frame = QFrame()
        items_vlayout = QVBoxLayout(items_frame)
        items_vlayout.setContentsMargins(0, 0, 0, 0)
        items_vlayout.addWidget(QLabel(tr("Items in Store:")))

        self._store_items_table = QTableWidget()
        self._store_items_table.setColumnCount(7)
        self._store_items_table.setHorizontalHeaderLabels([
            "", "Key", "Item Name", "Category", "Limit", "Buy Price", "Sell Price"
        ])
        self._store_items_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self._store_items_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._store_items_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._store_items_table.itemChanged.connect(self._store_cell_changed)
        self._store_items_table.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        ih = self._store_items_table.horizontalHeader()
        ih.setSectionResizeMode(0, QHeaderView.Fixed)
        icon_col_w = ICON_SIZE + 16 if self._icons_enabled else 0
        self._store_items_table.setColumnWidth(0, icon_col_w)
        ih.setMinimumSectionSize(icon_col_w if self._icons_enabled else 20)
        ih.setSectionResizeMode(1, QHeaderView.Fixed)
        self._store_items_table.setColumnWidth(1, 70)
        ih.setSectionResizeMode(2, QHeaderView.Interactive)
        self._store_items_table.setColumnWidth(2, 200)
        ih.setSectionResizeMode(3, QHeaderView.Interactive)
        self._store_items_table.setColumnWidth(3, 100)
        ih.setSectionResizeMode(4, QHeaderView.Interactive)
        self._store_items_table.setColumnWidth(4, 60)
        ih.setSectionResizeMode(5, QHeaderView.Interactive)
        self._store_items_table.setColumnWidth(5, 80)
        ih.setSectionResizeMode(6, QHeaderView.Interactive)
        self._store_items_table.setColumnWidth(6, 80)
        row_h = max(ICON_SIZE + 6, 28) if self._icons_enabled else 24
        self._store_items_table.verticalHeader().setDefaultSectionSize(row_h)
        items_vlayout.addWidget(self._store_items_table)

        edit_row = QHBoxLayout()
        swap_btn = QPushButton(tr("Swap Selected"))
        swap_btn.setObjectName("accentBtn")
        swap_btn.setToolTip(tr("Replace selected item(s) with a different item from the database"))
        swap_btn.clicked.connect(self._store_swap_item)
        edit_row.addWidget(swap_btn)

        edit_row.addWidget(QLabel(tr("Set Limit:")))
        self._store_limit_spin = QSpinBox()
        self._store_limit_spin.setRange(0, 99999)
        self._store_limit_spin.setValue(999)
        self._store_limit_spin.setFixedWidth(80)
        edit_row.addWidget(self._store_limit_spin)

        set_limit_btn = QPushButton(tr("Apply Limit"))
        set_limit_btn.setToolTip(tr("Set purchase limit for selected item(s)"))
        set_limit_btn.clicked.connect(self._store_set_limit)
        edit_row.addWidget(set_limit_btn)

        set_all_limit_btn = QPushButton(tr("Set ALL Limits"))
        set_all_limit_btn.setToolTip(tr("Set purchase limit for ALL items in this store"))
        set_all_limit_btn.clicked.connect(self._store_set_all_limits)
        edit_row.addWidget(set_all_limit_btn)

        edit_row.addStretch()
        items_vlayout.addLayout(edit_row)


        splitter.addWidget(items_frame)
        splitter.setSizes([300, 500])
        layout.addWidget(splitter, 1)

        self._store_parser = None
        self._store_modified = False
        self._store_change_count = 0
        self._store_original_body = None
        self._store_original_header = None


    def _store_extract(self) -> None:
        game_path = self._game_path.strip()
        if not game_path:
            QMessageBox.warning(self, tr("No Game Path"), tr("Set the game install path using the Browse button at the top."))
            return

        self._store_status.setText(tr("Loading storeinfo..."))
        QApplication.processEvents()

        try:
            from store_editor import StoreInfoParser as _OldParser
            old_parser = _OldParser(game_path)
            ok = old_parser.extract()
            if not ok:
                self._store_status.setText(tr("Failed to extract storeinfo from PAZ"))
                return

            from storeinfo_parser import StoreinfoParser
            self._store_parser_v2 = StoreinfoParser()
            self._store_parser_v2.load_from_bytes(old_parser._header_data, bytes(old_parser._body_data))
            self._store_parser_v2.load_names()
            self._store_parser = old_parser
            self._store_original_body = bytes(old_parser._body_data)
            self._store_original_header = bytes(old_parser._header_data)
            self._store_status.setText(self._store_parser_v2.get_summary())
            self._store_populate_list()
            self._store_modified = False
            self._store_change_count = 0
            self._store_changes_label.setText("")
        except Exception as e:
            log.error("Store extract failed: %s", e)
            log.exception("Unhandled exception")
            self._store_status.setText(f"Failed: {e}")

    def _store_update_change_count(self, delta: int = 1) -> None:
        self._store_change_count += delta
        self._store_modified = self._store_change_count > 0
        if self._store_change_count > 0:
            self._store_changes_label.setText(f"{self._store_change_count} change(s)")
        else:
            self._store_changes_label.setText("")

    def _store_populate_list(self, filter_text: str = "") -> None:
        if not hasattr(self, '_store_parser_v2') or not self._store_parser_v2:
            return

        if not hasattr(self, '_store_display_names'):
            self._store_display_names = {}
            try:
                _db = get_connection()
                self._store_display_names = {
                    row['store_id']: row['name']
                    for row in _db.execute("SELECT store_id, name FROM stores")
                }
            except Exception:
                pass

        q = filter_text.lower().strip()
        stores = self._store_parser_v2.stores
        if q:
            stores = [s for s in stores
                      if q in s.name.lower()
                      or q in str(s.key)
                      or q in self._store_display_names.get(str(s.key), "").lower()]

        table = self._store_list
        table.setSortingEnabled(False)
        table.setRowCount(len(stores))
        for row, store in enumerate(stores):
            key_item = QTableWidgetItem()
            key_item.setData(Qt.DisplayRole, store.key)
            key_item.setData(Qt.UserRole, store.key)
            table.setItem(row, 0, key_item)

            display = self._store_display_names.get(str(store.key), "")
            if not display:
                display = store.name.replace("Store_", "").replace("_", " ")
            name_item = QTableWidgetItem(display)
            name_item.setToolTip(store.name)
            table.setItem(row, 1, name_item)

            count_item = QTableWidgetItem()
            count_item.setData(Qt.DisplayRole, len(store.items))
            if store.items:
                count_item.setForeground(QBrush(QColor(COLORS['success'])))
            table.setItem(row, 2, count_item)

            fmt = "Standard" if store.is_standard else "Special"
            fmt_item = QTableWidgetItem(fmt)
            if not store.is_standard:
                fmt_item.setForeground(QBrush(QColor(COLORS['text_dim'])))
            table.setItem(row, 3, fmt_item)
        table.setSortingEnabled(True)

    def _store_filter(self, text: str) -> None:
        self._store_populate_list(text)

    def _store_get_selected_store(self):
        if not hasattr(self, '_store_parser_v2') or not self._store_parser_v2:
            return None
        rows = self._store_list.selectionModel().selectedRows()
        if not rows:
            return None
        key_item = self._store_list.item(rows[0].row(), 0)
        if not key_item:
            return None
        return self._store_parser_v2.get_store_by_key(key_item.data(Qt.UserRole))

    def _store_selected(self, *_args) -> None:
        store = self._store_get_selected_store()
        if not store:
            return

        table = self._store_items_table
        self._store_suppress_cell_edit = True
        table.setSortingEnabled(False)
        table.setRowCount(len(store.items))

        non_editable_flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        editable_flags = non_editable_flags | Qt.ItemIsEditable

        for row, item in enumerate(store.items):
            icon_item = QTableWidgetItem()
            if self._icons_enabled:
                px = self._icon_cache.get_pixmap(item.item_key)
                if px:
                    icon_item.setIcon(QIcon(px))
            icon_item.setFlags(non_editable_flags)
            table.setItem(row, 0, icon_item)

            key_cell = QTableWidgetItem()
            key_cell.setData(Qt.DisplayRole, item.item_key)
            key_cell.setData(Qt.UserRole, row)
            key_cell.setFlags(non_editable_flags)
            table.setItem(row, 1, key_cell)

            name = self._store_parser_v2.get_item_name(item.item_key)
            cat = self._name_db.get_category(item.item_key) if hasattr(self, '_name_db') else ""
            color = QColor(CATEGORY_COLORS.get(cat, COLORS["text"]))
            name_w = QTableWidgetItem(name)
            name_w.setForeground(QBrush(color))
            name_w.setFlags(non_editable_flags)
            table.setItem(row, 2, name_w)

            cat_w = QTableWidgetItem(cat)
            cat_w.setForeground(QBrush(color))
            cat_w.setFlags(non_editable_flags)
            table.setItem(row, 3, cat_w)

            limit_w = QTableWidgetItem()
            limit_w.setData(Qt.DisplayRole, item.trade_flags)
            if item.trade_flags >= 999:
                limit_w.setForeground(QBrush(QColor(COLORS['success'])))
            limit_w.setFlags(editable_flags)
            limit_w.setToolTip("Double-click to edit purchase limit")
            table.setItem(row, 4, limit_w)

            buy_w = QTableWidgetItem()
            buy_w.setData(Qt.DisplayRole, item.buy_price)
            buy_w.setFlags(editable_flags)
            buy_w.setToolTip("Double-click to edit buy price")
            table.setItem(row, 5, buy_w)

            sell_w = QTableWidgetItem()
            sell_w.setData(Qt.DisplayRole, item.sell_price)
            sell_w.setFlags(editable_flags)
            sell_w.setToolTip("Double-click to edit sell price")
            table.setItem(row, 6, sell_w)

        table.setSortingEnabled(True)
        self._store_suppress_cell_edit = False

    def _store_cell_changed(self, cell) -> None:
        if getattr(self, '_store_suppress_cell_edit', False):
            return
        col = cell.column()
        if col not in (4, 5, 6):
            return
        if not hasattr(self, '_store_parser_v2') or not self._store_parser_v2:
            return

        store = self._store_get_selected_store()
        if not store or not store.is_standard:
            return

        row = cell.row()
        if row >= len(store.items):
            return
        item = store.items[row]

        raw = cell.data(Qt.DisplayRole)
        try:
            new_val = int(raw)
            if new_val < 0:
                raise ValueError
        except (TypeError, ValueError):
            self._store_suppress_cell_edit = True
            orig = {4: item.trade_flags, 5: item.buy_price, 6: item.sell_price}[col]
            cell.setData(Qt.DisplayRole, orig)
            self._store_suppress_cell_edit = False
            return

        body = self._store_parser_v2._body_data
        if col == 4:
            if new_val > 0xFFFFFFFF:
                new_val = 0xFFFFFFFF
            struct.pack_into('<I', body, item.offset + 0x12, new_val)
            item.trade_flags = new_val
            if new_val >= 999:
                cell.setForeground(QBrush(QColor(COLORS['success'])))
            else:
                cell.setForeground(QBrush(QColor(COLORS['text'])))
        elif col == 5:
            if new_val > 0xFFFFFFFFFFFFFFFF:
                new_val = 0xFFFFFFFFFFFFFFFF
            struct.pack_into('<Q', body, item.offset + 0x02, new_val)
            item.buy_price = new_val
        elif col == 6:
            if new_val > 0xFFFFFFFFFFFFFFFF:
                new_val = 0xFFFFFFFFFFFFFFFF
            struct.pack_into('<Q', body, item.offset + 0x0A, new_val)
            item.sell_price = new_val

        self._store_parser._body_data = bytearray(self._store_parser_v2.get_body_bytes())
        self._store_update_change_count(1)
        col_name = {4: 'limit', 5: 'buy price', 6: 'sell price'}[col]
        self._store_status.setText(
            f"Set {col_name}={new_val} on {self._store_parser_v2.get_item_name(item.item_key)}"
        )

    def _store_get_selected_items(self):
        rows = set(idx.row() for idx in self._store_items_table.selectedIndexes())
        return sorted(rows)

    def _store_swap_item(self) -> None:
        if not hasattr(self, '_store_parser_v2') or not self._store_parser_v2:
            QMessageBox.warning(self, tr("Stores"), tr("Load store data first."))
            return

        store = self._store_get_selected_store()
        if not store or not store.is_standard:
            QMessageBox.warning(self, tr("Swap"), tr("Select a standard-format store first."))
            return

        sel_rows = self._store_get_selected_items()
        if not sel_rows:
            QMessageBox.information(self, tr("No Selection"), tr("Select item(s) to swap."))
            return

        dlg = ItemSearchDialog(
            self._name_db,
            title="Swap Vendor Item",
            prompt=f"Select the item to replace {len(sel_rows)} vendor item(s) with:",
            parent=self,
        ) if hasattr(self, '_name_db') else None

        if dlg is None:
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(self, "Swap Item", "Enter item key or name:")
            if not ok or not text.strip():
                return
            try:
                new_key = int(text.strip())
            except ValueError:
                q = text.strip().lower()
                new_key = 0
                for k, n in self._store_parser_v2._name_lookup.items():
                    if q in n.lower():
                        new_key = k
                        break
            if not new_key:
                QMessageBox.warning(self, tr("Not Found"), tr("Item not found."))
                return
        else:
            if dlg.exec() != QDialog.Accepted or dlg.selected_key == 0:
                return
            new_key = dlg.selected_key

        new_name = self._store_parser_v2.get_item_name(new_key)

        swapped = 0
        for row in sel_rows:
            if row < len(store.items):
                item = store.items[row]
                ok = self._store_parser_v2.swap_item(store.key, item.item_key, new_key)
                if ok:
                    swapped += 1
                    self._store_update_change_count()

        if swapped:
            self._store_parser._body_data = bytearray(self._store_parser_v2.get_body_bytes())
            self._store_status.setText(f"Swapped {swapped} item(s) to {new_name}")
            self._store_selected()
        else:
            QMessageBox.warning(self, tr("Swap Failed"), tr("Could not swap any items."))

    def _store_add_item(self) -> None:
        if not hasattr(self, '_store_parser_v2') or not self._store_parser_v2:
            QMessageBox.warning(self, tr("Stores"), tr("Load store data first."))
            return

        store = self._store_get_selected_store()
        if not store or not store.is_standard:
            QMessageBox.warning(self, tr("Add"), tr("Select a standard-format store."))
            return

        sel_rows = self._store_get_selected_items()
        if not sel_rows:
            QMessageBox.information(self, tr("No Selection"),
                tr("Select an existing item to use as template (donor)."))
            return

        donor = store.items[sel_rows[0]]

        dlg = ItemSearchDialog(
            self._name_db,
            title="Add Item to Store",
            prompt=f"Select the item to add (cloned from {self._store_parser_v2.get_item_name(donor.item_key)}):",
            parent=self,
        ) if hasattr(self, '_name_db') else None

        if dlg is None:
            return
        if dlg.exec() != QDialog.Accepted or dlg.selected_key == 0:
            return

        new_key = dlg.selected_key
        new_name = self._store_parser_v2.get_item_name(new_key)

        ok = self._store_parser_v2.add_item(store.key, donor.item_key, new_key)
        if ok:
            self._store_parser._body_data = bytearray(self._store_parser_v2.get_body_bytes())
            self._store_parser._header_data = self._store_parser_v2.get_header_bytes()
            self._store_update_change_count()
            self._store_status.setText(f"Added {new_name} to store")
            self._store_selected()
        else:
            QMessageBox.warning(self, tr("Add Failed"), tr("Could not add item."))

    def _store_set_limit(self) -> None:
        if not hasattr(self, '_store_parser_v2') or not self._store_parser_v2:
            return
        store = self._store_get_selected_store()
        if not store or not store.is_standard:
            return

        sel_rows = self._store_get_selected_items()
        if not sel_rows:
            QMessageBox.information(self, tr("Set Limit"), tr("Select item(s) first."))
            return

        new_limit = self._store_limit_spin.value()
        body = self._store_parser_v2._body_data
        changed = 0
        for row in sel_rows:
            if row < len(store.items):
                item = store.items[row]
                struct.pack_into('<I', body, item.offset + 0x12, new_limit)
                item.trade_flags = new_limit
                changed += 1

        if changed:
            self._store_parser._body_data = bytearray(self._store_parser_v2.get_body_bytes())
            self._store_update_change_count(changed)
            self._store_status.setText(f"Set limit={new_limit} on {changed} item(s)")
            self._store_selected()

    def _store_set_all_limits(self) -> None:
        store = self._store_get_selected_store()
        if not store or not store.is_standard or not store.items:
            QMessageBox.information(self, tr("Set All Limits"), tr("Select a standard store with items first."))
            return

        new_limit = self._store_limit_spin.value()
        reply = QMessageBox.question(
            self, tr("Set All Limits"),
            f"Set purchase limit to {new_limit} for ALL {len(store.items)} items in {store.name}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        body = self._store_parser_v2._body_data
        for item in store.items:
            struct.pack_into('<I', body, item.offset + 0x12, new_limit)
            item.trade_flags = new_limit

        self._store_parser._body_data = bytearray(self._store_parser_v2.get_body_bytes())
        self._store_update_change_count(len(store.items))
        self._store_status.setText(f"Set limit={new_limit} on all {len(store.items)} items")
        self._store_selected()

    def _store_import_json(self) -> None:
        if not hasattr(self, '_store_parser_v2') or not self._store_parser_v2:
            QMessageBox.warning(self, tr("Import"), tr("Load store data first."))
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Import JSON Vendor Patch", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                patch_data = json.load(f)

            body = self._store_parser_v2._body_data
            applied = 0
            skipped = 0

            for patch_group in patch_data.get('patches', []):
                if 'storeinfo.pabgb' not in patch_group.get('game_file', ''):
                    continue
                for change in patch_group.get('changes', []):
                    offset = change['offset']
                    original = bytes.fromhex(change['original'])
                    patched = bytes.fromhex(change['patched'])

                    if offset + len(original) > len(body):
                        skipped += 1
                        continue

                    current = bytes(body[offset:offset + len(original)])
                    if current == original:
                        body[offset:offset + len(patched)] = patched
                        applied += 1
                    elif current == patched:
                        skipped += 1
                    else:
                        skipped += 1
                        log.warning(tr("Patch mismatch at offset %d: expected %s, got %s"),
                                    offset, original.hex(), current.hex())

            self._store_parser_v2._parse_all_stores()
            self._store_parser._body_data = bytearray(self._store_parser_v2.get_body_bytes())
            self._store_update_change_count(applied)
            self._store_populate_list(self._store_search.text())
            self._store_selected()

            mod_name = patch_data.get('name', os.path.basename(path))
            self._store_status.setText(f"Imported '{mod_name}': {applied} patches applied, {skipped} skipped")
            QMessageBox.information(self, tr("Import Complete"),
                f"Mod: {mod_name}\n"
                f"Author: {patch_data.get('author', 'Unknown')}\n\n"
                f"Applied: {applied} patches\n"
                f"Skipped: {skipped} (already applied or mismatch)")

        except Exception as e:
            QMessageBox.critical(self, tr("Import Error"), str(e))


    def _store_label_for_offset(self, offset: int) -> str:
        parser = self._store_parser_v2
        for store in parser.stores:
            if not store.is_standard or not store.items:
                continue
            items_start = store.after_name + 51
            items_end = items_start + store.item_count * 105
            if not (items_start <= offset < items_end):
                continue
            item_idx = (offset - items_start) // 105
            item_rel = (offset - items_start) % 105
            if item_idx >= len(store.items):
                break
            item = store.items[item_idx]
            item_name = parser.get_item_name(item.item_key)
            if item_rel == 0x12:
                return f"{store.name} - {item_name} (Limit)"
            elif item_rel == 0x22:
                return f"{store.name} - {item_name} (ItemID)"
            elif item_rel == 0x5D:
                return f"{store.name} - {item_name} (ItemID)"
            else:
                return f"{store.name} - {item_name} (+0x{item_rel:02X})"
        return f"Offset 0x{offset:X}"

    def _store_build_changes(self, original: bytes, current: bytes) -> list:
        changes = []
        i = 0
        while i < len(current):
            if current[i] != original[i]:
                start = i
                while i < len(current) and current[i] != original[i]:
                    i += 1
                changes.append({
                    "offset": start,
                    "label": self._store_label_for_offset(start),
                    "original": original[start:i].hex(),
                    "patched": current[start:i].hex(),
                })
            else:
                i += 1
        return changes


    def _store_export_json(self) -> None:
        if not hasattr(self, '_store_parser_v2') or not self._store_parser_v2:
            QMessageBox.warning(self, tr("Export"), tr("Load store data first."))
            return
        if not self._store_original_body:
            QMessageBox.warning(self, tr("Export"), tr("No original data to diff against."))
            return

        current = self._store_parser_v2.get_body_bytes()
        original = self._store_original_body

        if len(current) != len(original):
            QMessageBox.warning(self, tr("Export"),
                "File size changed (items were added/removed). "
                "JSON export only supports in-place edits (swaps + limits).")
            return

        changes = self._store_build_changes(original, current)
        if not changes:
            QMessageBox.information(self, tr("Export"), tr("No changes to export."))
            return

        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Export JSON Patch",
                                        "Patch name:", text="My Vendor Mod")
        if not ok or not name.strip():
            return
        name = name.strip()

        path, _ = QFileDialog.getSaveFileName(
            self, "Export JSON Vendor Patch", f"{name}.json", "JSON Files (*.json)")
        if not path:
            return

        patch_json = {
            "name": name,
            "version": "1.0",
            "description": f"{len(changes)} vendor changes",
            "author": "CrimsonSaveEditor",
            "patches": [{
                "game_file": "gamedata/storeinfo.pabgb",
                "changes": changes,
            }]
        }

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(patch_json, f, indent=2)

        self._store_status.setText(f"Exported {len(changes)} patches to {os.path.basename(path)}")
        QMessageBox.information(self, tr("Exported"),
            f"Saved {len(changes)} patches to:\n{path}\n\n"
            f"Compatible with NoSEModLoad / JSON Mod Manager.\n"
            f"Share this file — others drop it into NoSEModLoad/Json/.")

    def _store_apply(self) -> None:
        if not self._store_parser:
            QMessageBox.warning(self, tr("Stores"), tr("Load store data first."))
            return

        if not self._store_modified:
            QMessageBox.information(self, tr("No Changes"), tr("No modifications to apply."))
            return

        game_path = self._store_parser.game_path
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.critical(self, tr("Invalid Game Path"),
                f"Game path not found:\n{game_path}\n\n"
                "Set the correct path using the Browse button at the top.")
            return

        if not _is_admin():
            QMessageBox.warning(self, tr("Admin Required"),
                "Writing to game files requires administrator privileges.\n\n"
                "Right-click the exe → Run as administrator")
            return

        if hasattr(self, '_store_parser_v2') and self._store_parser_v2:
            body_data = bytes(self._store_parser_v2.get_body_bytes())
            header_data = self._store_parser_v2.get_header_bytes()
        else:
            body_data = bytes(self._store_parser._body_data)
            header_data = self._store_original_header or self._store_parser._header_data

        store_dir = f"{self._store_overlay_spin.value():04d}"
        reply = QMessageBox.question(
            self, tr("Apply Store Changes"),
            f"Pack modified storeinfo into {store_dir}/ override directory?\n\n"
            f"Data: pabgb={len(body_data):,} bytes, pabgh={len(header_data):,} bytes\n\n"
            f"Uses pack_mod pipeline (same as ItemBuffs tab).\n"
            f"Original 0008/0.paz is NOT modified.\n"
            f"To undo: click Restore Original.\n\n"
            f"The game must be restarted for changes to take effect.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._store_status.setText(tr("Packing with pack_mod..."))
        QApplication.processEvents()

        try:
            import crimson_rs.pack_mod
            import shutil
            import tempfile


            with tempfile.TemporaryDirectory() as tmp_dir:
                mod_dir = os.path.join(tmp_dir, "gamedata")
                os.makedirs(mod_dir, exist_ok=True)
                with open(os.path.join(mod_dir, "storeinfo.pabgb"), "wb") as f:
                    f.write(body_data)
                with open(os.path.join(mod_dir, "storeinfo.pabgh"), "wb") as f:
                    f.write(header_data)

                out_dir = os.path.join(tmp_dir, "output")
                os.makedirs(out_dir, exist_ok=True)

                crimson_rs.pack_mod.pack_mod(
                    game_dir=game_path,
                    mod_folder=tmp_dir,
                    output_dir=out_dir,
                    group_name=store_dir,
                )

                papgt_path = os.path.join(game_path, "meta", "0.papgt")
                papgt_backup = papgt_path + ".store_sebak"
                if os.path.isfile(papgt_path) and not os.path.isfile(papgt_backup):
                    shutil.copy2(papgt_path, papgt_backup)

                game_mod = os.path.join(game_path, store_dir)
                if os.path.isdir(game_mod):
                    shutil.rmtree(game_mod)
                os.makedirs(game_mod, exist_ok=True)

                shutil.copy2(
                    os.path.join(out_dir, store_dir, "0.paz"),
                    os.path.join(game_mod, "0.paz"),
                )
                shutil.copy2(
                    os.path.join(out_dir, store_dir, "0.pamt"),
                    os.path.join(game_mod, "0.pamt"),
                )
                shutil.copy2(
                    os.path.join(out_dir, "meta", "0.papgt"),
                    papgt_path,
                )

                with open(os.path.join(game_mod, ".se_storemod"), "w") as mf:
                    mf.write("Created by CrimsonSaveEditor Stores tab\n")

            paz_size = os.path.getsize(os.path.join(game_mod, "0.paz"))

            papgt_verify = ""
            try:
                import crimson_rs as _crs
                papgt_check = _crs.parse_papgt_file(papgt_path)
                overlay_entries = [e['group_name'] for e in papgt_check['entries'] if int(e['group_name']) >= 36]
                papgt_verify = f"\nPAPGT overlays: {', '.join(overlay_entries)}" if overlay_entries else ""
                if papgt_check['entries'][0]['group_name'] != store_dir:
                    papgt_verify += f"\n⚠ WARNING: {store_dir} is not at the front of PAPGT!"
            except Exception:
                pass

            self._store_modified = False
            self._store_change_count = 0
            self._store_changes_label.setText("")
            self._store_status.setText(f"Success: packed to {store_dir}/ ({paz_size:,} bytes)")

            try:
                from shared_state import record_overlay
                record_overlay(game_path, store_dir, "Store edits",
                               ["storeinfo.pabgb", "storeinfo.pabgh"])
            except Exception:
                pass

            QMessageBox.information(self, tr("Applied Successfully"),
                f"Packed to {store_dir}/ via pack_mod ({paz_size:,} bytes)\n"
                f"Original 0008/0.paz untouched{papgt_verify}\n\n"
                f"Restart the game for changes to take effect.\n"
                f"To undo: click 'Restore Original'.")
            self.paz_refresh_requested.emit()

        except Exception as ex:
            log.exception("Unhandled exception")
            self._store_status.setText(f"Failed: {ex}")
            QMessageBox.critical(self, tr("Apply Failed"),
                f"{ex}\n\n"
                f"Make sure you're running as administrator\n"
                f"and crimson_rs is available.")

    def _store_restore(self) -> None:
        game_path = self._game_path.strip()
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.warning(self, tr("Restore"), tr("Set a valid game path first."))
            return

        if not _is_admin():
            QMessageBox.warning(self, tr("Admin Required"),
                "Restoring game files requires administrator privileges.\n\n"
                "Right-click → Run as administrator")
            return

        import shutil

        store_dir = f"{self._store_overlay_spin.value():04d}"
        game_mod = os.path.join(game_path, store_dir)
        has_mod_dir = os.path.isdir(game_mod)

        if not has_mod_dir:
            QMessageBox.information(self, tr("Nothing to Restore"),
                f"No store override ({store_dir}/) found.\n\n"
                "If your game is broken, use Steam:\n"
                "  Right-click game → Properties → Installed Files\n"
                "  → Verify integrity of game files")
            return

        parts = [
            f"Delete {store_dir}/ override directory",
            f"Remove {store_dir} from PAPGT (preserves other overlays)",
        ]

        reply = QMessageBox.question(
            self, tr("Restore Original"),
            '\n'.join(parts) + "\n\nProceed?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        messages = []

        msg = self._rebuild_papgt_fn(game_path, store_dir)
        messages.append(msg)

        try:
            shutil.rmtree(game_mod)
            messages.append(f"Removed {store_dir}/ override directory")
            try:
                from overlay_coordinator import post_restore
                post_restore(game_path, store_dir)
            except Exception:
                pass
        except Exception as e:
            messages.append(f"Failed to remove {store_dir}/: {e}")

        sebak = os.path.join(game_path, "meta", "0.papgt.store_sebak")
        if os.path.isfile(sebak):
            try:
                os.remove(sebak)
            except Exception:
                pass

        self._store_modified = False
        self._store_change_count = 0
        self._store_changes_label.setText("")

        full_msg = '\n'.join(messages) + "\n\nRestart the game for changes to take effect."
        self._store_status.setText(tr("Restored"))
        QMessageBox.information(self, tr("Restored"), full_msg)
        self.paz_refresh_requested.emit()


class SpawnTab(QWidget):

    status_message = Signal(str)

    def __init__(self, config: dict, show_guide_fn=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._show_guide_fn = show_guide_fn
        self._build_ui()

    def set_experimental_mode(self, enabled: bool) -> None:
        if hasattr(self, '_dev_export_btn_spawn'):
            self._dev_export_btn_spawn.setVisible(bool(enabled))

    def get_staged_files(self) -> dict:
        """Return modified spawn pabgb buffers for Stacker Pull All Edits.

        Mirrors the FieldEditTab pattern: compare current buffer against
        vanilla original; include a file only when they differ.
        """
        result = {}
        _PAIRS = [
            ('terrainregionautospawninfo.pabgb', '_spawn_data',         '_spawn_original'),
            ('spawningpoolautospawninfo.pabgb',  '_spawn_life_data',    '_spawn_life_original'),
            ('factionnode.pabgb',               '_spawn_fnode_ops_data', '_spawn_fnode_ops_original'),
            ('factionnodespawninfo.pabgb',       '_spawn_node_data',    '_spawn_node_original'),
        ]
        for fname, data_attr, orig_attr in _PAIRS:
            data = getattr(self, data_attr, None)
            orig = getattr(self, orig_attr, None)
            if data is not None and orig is not None and bytes(data) != bytes(orig):
                result[fname] = bytes(data)
        return result

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(make_scope_label("game"))

        header = QHBoxLayout()
        header.setSpacing(4)

        load_btn = QPushButton(tr("Load Spawn Data"))
        load_btn.setObjectName("accentBtn")
        load_btn.setToolTip(tr("Extract spawn tables from game PAZ files"))
        load_btn.clicked.connect(self._spawn_extract)
        header.addWidget(load_btn)

        header.addWidget(QLabel("Mod#:"))
        self._spawn_overlay_spin = QSpinBox()
        self._spawn_overlay_spin.setRange(1, 9999)
        self._spawn_overlay_spin.setValue(self._config.get("spawn_overlay_dir", 37))
        self._spawn_overlay_spin.setFixedWidth(70)
        self._spawn_overlay_spin.setToolTip(
            "Overlay folder number for spawn mods.\n"
            "Each tab should use a different number to avoid conflicts.\n"
            "Default: 0037")
        self._spawn_overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"spawn_overlay_dir": int(v)}))
        header.addWidget(self._spawn_overlay_spin)

        apply_btn = QPushButton(tr("Apply to Game"))
        apply_btn.setStyleSheet(button_css("success") + " font-weight: bold;")
        apply_btn.setToolTip(tr("Deploy modified spawn data directly to the game (requires restart)"))
        apply_btn.clicked.connect(self._spawn_apply)
        header.addWidget(apply_btn)

        spawn_field_json_btn = QPushButton(tr("Export Field JSON v3"))
        spawn_field_json_btn.setStyleSheet(
            button_css("primary") + " font-weight: bold;")
        spawn_field_json_btn.setToolTip(
            "Export all SpawnEdit changes as Format 3.1 field JSON.\n"
            "Compatible with DMM 1.3.3+ multi-target format.")
        spawn_field_json_btn.clicked.connect(self._spawn_export_field_json_v3)
        header.addWidget(spawn_field_json_btn)

        spawn_export_btn = QPushButton(tr("Export Mod"))
        spawn_export_btn.setToolTip(tr("ADVANCED — UNSUPPORTED. Export as CDUMM-compatible mod."))
        spawn_export_btn.clicked.connect(self._spawn_export_cdumm)
        spawn_export_btn.setVisible(False)
        header.addWidget(spawn_export_btn)
        self._dev_export_btn_spawn = spawn_export_btn

        restore_btn = QPushButton(tr("Restore Vanilla"))
        restore_btn.setToolTip(tr("Remove spawn mod and restore original game data"))
        restore_btn.clicked.connect(self._spawn_restore)
        header.addWidget(restore_btn)

        reset_btn = QPushButton(tr("Reset Edits"))
        reset_btn.setToolTip(tr("Undo all changes (reset to last loaded data)"))
        reset_btn.clicked.connect(self._spawn_reset)
        header.addWidget(reset_btn)

        help_btn = QPushButton("?")
        help_btn.setFixedSize(24, 24)
        help_btn.setStyleSheet(
            f"font-weight: bold; font-size: 12px; border-radius: 12px; "
            f"background-color: {COLORS['accent']}; color: white;")
        help_btn.clicked.connect(self._spawn_show_help)
        header.addWidget(help_btn)

        self._spawn_status = QLabel("")
        self._spawn_status.setStyleSheet(f"color: {COLORS['accent']};")
        header.addWidget(self._spawn_status, 1)
        layout.addLayout(header)

        simple_group = QGroupBox(tr("Spawn Density"))
        simple_layout = QVBoxLayout(simple_group)
        simple_layout.setContentsMargins(6, 8, 6, 6)
        simple_layout.setSpacing(4)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(QLabel(tr("Multiplier:")))
        self._spawn_multiplier = QSpinBox()
        self._spawn_multiplier.setRange(1, 99999)
        self._spawn_multiplier.setValue(2)
        self._spawn_multiplier.setFixedWidth(60)
        self._spawn_multiplier.setToolTip(tr("Multiply spawn density by this value (2 = double, 3 = triple)"))
        row1.addWidget(self._spawn_multiplier)

        increase_all_btn = QPushButton(tr("Increase ALL Spawns"))
        increase_all_btn.setStyleSheet(button_css("success") + " font-weight: bold; padding: 6px 12px;")
        increase_all_btn.setToolTip(
            "Increase enemy/animal spawn density.\n"
            "Camp enemies: MaxOp/MinOp/Sub-slots x multiplier\n"
            "Open-world: remove caps, loosen spacing, enable duplicates")
        increase_all_btn.clicked.connect(self._spawn_increase_all_smart)
        row1.addWidget(increase_all_btn)

        increase_life_btn = QPushButton(tr("Increase ALL Life"))
        increase_life_btn.setStyleSheet(button_css("primary") + " font-weight: bold; padding: 6px 12px;")
        increase_life_btn.setToolTip(
            "Increase ambient wildlife: fireflies, birds, bats, insects,\n"
            "animals near crops, butterflies, crows, swamp creatures.\n"
            "Makes the world feel more alive between enemy camps.\n"
            "Modifies spawningpoolautospawninfo.pabgb (140 entries).")
        increase_life_btn.clicked.connect(self._spawn_increase_life)
        row1.addWidget(increase_life_btn)

        halve_btn = QPushButton(tr("Halve Respawn Timers"))
        halve_btn.setToolTip(tr("Make enemies and animals respawn twice as fast"))
        halve_btn.clicked.connect(self._spawn_halve_timers)
        row1.addWidget(halve_btn)

        row1.addStretch()
        self._spawn_changes_label = QLabel("")
        self._spawn_changes_label.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold;")
        row1.addWidget(self._spawn_changes_label)
        simple_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(4)
        row2.addWidget(QLabel(tr("Individual:")))

        mult_camp_btn = QPushButton(tr("x Camp Max"))
        mult_camp_btn.setToolTip(tr("Multiply only camp MaxOp (max enemies per camp, cap 255)"))
        mult_camp_btn.clicked.connect(self._spawn_multiply_all)
        row2.addWidget(mult_camp_btn)

        mult_minop_btn = QPushButton(tr("x Camp Min"))
        mult_minop_btn.setToolTip(tr("Multiply only camp MinOp (min enemies always present, cap 255)"))
        mult_minop_btn.clicked.connect(self._spawn_multiply_all_minop)
        row2.addWidget(mult_minop_btn)

        mult_rate_btn = QPushButton(tr("x World Rates"))
        mult_rate_btn.setToolTip(tr("Multiply open-world spawn rates (50 verified offsets from parse tree)"))
        mult_rate_btn.clicked.connect(self._spawn_multiply_rates)
        row2.addWidget(mult_rate_btn)

        mult_sub_btn = QPushButton(tr("x Sub-Slots"))
        mult_sub_btn.setToolTip(tr("Multiply only per-slot operator counts in camp schedules"))
        mult_sub_btn.clicked.connect(self._spawn_multiply_sub_slots)
        row2.addWidget(mult_sub_btn)

        halve_sub_btn = QPushButton(tr("Halve Sub Times"))
        halve_sub_btn.setToolTip(tr("Halve sub-schedule time values"))
        halve_sub_btn.clicked.connect(self._spawn_halve_sub_times)
        row2.addWidget(halve_sub_btn)

        row2.addStretch()
        simple_layout.addLayout(row2)

        layout.addWidget(simple_group)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)

        filter_row.addWidget(QLabel(tr("View:")))
        self._spawn_source_combo = QComboBox()
        self._spawn_source_combo.addItem("All Sources", None)
        self._spawn_source_combo.addItem("Terrain (Animals/Enemies)", "terrain")
        self._spawn_source_combo.addItem("Camp Enemies (MaxOp/MinOp)", "fnode_ops")
        self._spawn_source_combo.addItem("Open-World Rates", "rate")
        self._spawn_source_combo.setFixedWidth(200)
        self._spawn_source_combo.currentIndexChanged.connect(self._spawn_filter)
        filter_row.addWidget(self._spawn_source_combo)

        filter_row.addWidget(QLabel(tr("Region:")))
        self._spawn_region_combo = QComboBox()
        self._spawn_region_combo.setFixedWidth(220)
        self._spawn_region_combo.currentIndexChanged.connect(self._spawn_filter)
        filter_row.addWidget(self._spawn_region_combo)

        filter_row.addWidget(QLabel(tr("Search:")))
        self._spawn_search = QLineEdit()
        self._spawn_search.setPlaceholderText(tr("Filter by name..."))
        self._spawn_search.textChanged.connect(self._spawn_filter)
        filter_row.addWidget(self._spawn_search, 1)
        layout.addLayout(filter_row)

        self._spawn_table = QTableWidget()
        self._spawn_table.setColumnCount(10)
        self._spawn_table.setHorizontalHeaderLabels([
            "Source", "Region", "Region Name", "Char Key", "Char Name",
            "Count/MaxOp", "MinOp", "Sub-Slots", "Workers", "Timer (ms)",
        ])
        self._spawn_table.horizontalHeader().setStretchLastSection(True)
        self._spawn_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._spawn_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self._spawn_table.setAlternatingRowColors(True)
        self._spawn_table.verticalHeader().setVisible(False)
        self._spawn_table.verticalHeader().setDefaultSectionSize(20)
        self._spawn_table.cellChanged.connect(self._spawn_cell_changed)
        self._spawn_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._spawn_table.customContextMenuRequested.connect(self._spawn_context_menu)
        layout.addWidget(self._spawn_table, 1)

        self._spawn_data = None
        self._spawn_original = None
        self._spawn_schema = None
        self._spawn_elements = []
        self._spawn_modified = False
        self._spawn_editing = False
        self._spawn_life_data = None
        self._spawn_life_original = None
        self._spawn_life_schema = None
        self._spawn_fnode_ops_data = None
        self._spawn_fnode_ops_original = None
        self._spawn_fnode_ops_schema = None


    def _spawn_show_help(self):
        QMessageBox.information(self, tr("Spawn Editor Help"),
            "SPAWN EDITOR\n\n"
            "Controls enemy, animal, fish, bird, and NPC spawn density.\n\n"
            "STEP 1: Click 'Load Spawn Data'\n"
            "STEP 2: Use Quick Actions to modify spawns\n"
            "STEP 3: Click 'Apply to Game' (restart game to see changes)\n\n"
            "QUICK ACTIONS:\n"
            "  x Camp MaxOp — Max enemies per camp (cap: 255)\n"
            "  x Camp MinOp — Min enemies always present\n"
            "  x Sub-Slots — Per-slot counts in camp schedules\n"
            "  x Open-World Rates — ALL spawn rates: enemies, wildlife,\n"
            "    fish, birds, town NPCs (965 values across 126 regions)\n"
            "  Halve Timers — Faster respawns\n\n"
            "FILTERS:\n"
            "  View: Switch between terrain spawns and camp data\n"
            "  Region: Filter by specific area\n"
            "  Search: Filter by name\n\n"
            "NOTES:\n"
            "  - Camp MaxOp/MinOp cap at 255 (u8 game limit)\n"
            "  - Open-World Rates are floats, no hard cap\n"
            "  - Start with 2x-3x multiplier and test\n"
            "  - 'Restore Vanilla' removes all spawn mods")

    def _spawn_extract(self):
        game_path = self._config.get("game_install_path", "")
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.warning(self, tr("Game Path"),
                tr("Set the game install path first (top of the window)."))
            return

        self._spawn_status.setText(tr("Extracting spawn data..."))
        QApplication.processEvents()

        try:
            import crimson_rs

            dir_path = "gamedata/binary__/client/bin"
            body = crimson_rs.extract_file(game_path, "0008", dir_path,
                                           "terrainregionautospawninfo.pabgb")
            schema = crimson_rs.extract_file(game_path, "0008", dir_path,
                                              "terrainregionautospawninfo.pabgh")

            self._spawn_data = bytearray(body)
            self._spawn_original = bytes(body)
            self._spawn_schema = bytes(schema)
            self._spawn_modified = False
            self._spawn_changes_label.setText("")

            import struct as _st
            _c16 = _st.unpack_from('<H', self._spawn_schema, 0)[0]
            if 2 + _c16 * 8 == len(self._spawn_schema):
                count = _c16
                _idx_off = 2
            else:
                count = _st.unpack_from('<I', self._spawn_schema, 0)[0]
                _idx_off = 4
            idx = {}
            for i in range(count):
                _pos = _idx_off + i * 8
                if _pos + 8 > len(self._spawn_schema):
                    break
                k = _st.unpack_from('<I', self._spawn_schema, _pos)[0]
                o = _st.unpack_from('<I', self._spawn_schema, _pos + 4)[0]
                idx[k] = o

            sorted_offs = sorted(set(idx.values())) + [len(self._spawn_data)]

            MARKER = b'\x0A\x36\xC1\xE0'
            elements = []

            for region_key, entry_off in sorted(idx.items(), key=lambda x: x[1]):
                ni = sorted_offs.index(entry_off) + 1
                entry_end = sorted_offs[ni]
                raw = self._spawn_data[entry_off:entry_end]

                if len(raw) < 8:
                    continue
                name_len = _st.unpack_from('<I', raw, 4)[0]
                region_name = raw[8:8 + name_len].decode('utf-8', errors='replace').rstrip('\x00')

                positions = []
                search_start = 0
                while True:
                    pos = raw.find(MARKER, search_start)
                    if pos < 0:
                        break
                    positions.append(pos)
                    search_start = pos + 4

                for mi in range(len(positions) - 1):
                    m_off = positions[mi]
                    next_off = positions[mi + 1]
                    elem_size = next_off - m_off

                    if elem_size != 81:
                        continue

                    abs_marker = entry_off + m_off
                    timer_ms = _st.unpack_from('<I', self._spawn_data, abs_marker + 0x23)[0]
                    char_key = _st.unpack_from('<I', self._spawn_data, abs_marker + 0x2F)[0]
                    spawn_count = _st.unpack_from('<I', self._spawn_data, abs_marker + 0x3B)[0]

                    elements.append({
                        'region_key': region_key,
                        'region_name': region_name,
                        'char_key': char_key,
                        'spawn_count': spawn_count,
                        'timer_ms': timer_ms,
                        'count_offset': abs_marker + 0x3B,
                        'timer_offset': abs_marker + 0x23,
                        'source': 'terrain',
                    })

            self._spawn_elements = elements

            self._spawn_char_names = {}
            try:
                import crimson_rs
                char_data = crimson_rs.extract_file(
                    game_path, "0008", dir_path, "characterinfo.pabgh")
                char_body = crimson_rs.extract_file(
                    game_path, "0008", dir_path, "characterinfo.pabgb")
                _c16 = _st.unpack_from('<H', char_data, 0)[0]
                if 2 + _c16 * 8 == len(char_data):
                    char_count = _c16
                    _idx_start = 2
                else:
                    char_count = _st.unpack_from('<I', char_data, 0)[0]
                    _idx_start = 4
                char_offsets = {}
                for ci in range(char_count):
                    _pos = _idx_start + ci * 8
                    if _pos + 8 > len(char_data):
                        break
                    ck = _st.unpack_from('<I', char_data, _pos)[0]
                    co = _st.unpack_from('<I', char_data, _pos + 4)[0]
                    char_offsets[ck] = co
                for ck, co in char_offsets.items():
                    if co + 8 > len(char_body):
                        continue
                    nlen = _st.unpack_from('<I', char_body, co + 4)[0]
                    if nlen > 200 or co + 8 + nlen > len(char_body):
                        continue
                    raw_name = char_body[co + 8:co + 8 + nlen]
                    name = raw_name.decode('utf-8', errors='replace').rstrip('\x00')
                    clean = name
                    parts = clean.rsplit('_', 1)
                    if len(parts) == 2 and parts[1].isdigit():
                        clean = parts[0]
                    self._spawn_char_names[ck] = clean.replace('_', ' ')
                log.info("Loaded %d character names", len(self._spawn_char_names))
            except Exception as _ce:
                log.warning(tr("Could not load character names: %s"), _ce)

            try:
                from terrain_spawn_parser import get_verified_rate_offsets
                verified_rates = get_verified_rate_offsets(bytes(self._spawn_data), self._spawn_schema)
                for off, val, rname in verified_rates:
                    elements.append({
                        'region_key': 0,
                        'region_name': rname,
                        'char_key': 0,
                        'spawn_count': val,
                        'timer_ms': -1,
                        'count_offset': off,
                        'timer_offset': -1,
                        'source': 'rate',
                        'rate_value': val,
                    })
                log.info("Loaded %d verified open-world spawn rates", len(verified_rates))
            except Exception as _re:
                log.exception("Unhandled exception")
                log.warning(tr("Could not load spawn rates: %s"), _re)

            try:
                fnode_body = crimson_rs.extract_file(
                    game_path, "0008", dir_path, "factionnode.pabgb")
                fnode_gh = crimson_rs.extract_file(
                    game_path, "0008", dir_path, "factionnode.pabgh")

                self._spawn_fnode_ops_data = bytearray(fnode_body)
                self._spawn_fnode_ops_original = bytes(fnode_body)
                self._spawn_fnode_ops_schema = bytes(fnode_gh)

                import tempfile as _tf2
                with _tf2.NamedTemporaryFile(suffix='.pabgb', delete=False) as _fb:
                    _fb.write(self._spawn_fnode_ops_data)
                    _fb_path = _fb.name
                with _tf2.NamedTemporaryFile(suffix='.pabgh', delete=False) as _fg:
                    _fg.write(self._spawn_fnode_ops_schema)
                    _fg_path = _fg.name
                try:
                    from factionnode_operator_parser import parse_operator_counts
                    fnode_results, _fn_fails = parse_operator_counts(_fb_path, _fg_path)
                finally:
                    os.unlink(_fb_path)
                    os.unlink(_fg_path)

                fnode_ops_count = 0
                for entry in fnode_results:
                    for si, sched in enumerate(entry.get('schedules', [])):
                        node_name = entry.get('name', '').replace('Node_', '').replace('_', ' ')
                        sched_label = f"{node_name} [sched {si}]" if len(entry.get('schedules', [])) > 1 else node_name
                        elements.append({
                            'region_key': entry.get('key', 0),
                            'region_name': sched_label,
                            'char_key': 0,
                            'spawn_count': sched['max_operator_count'],
                            'timer_ms': sched.get('period_time', 0),
                            'count_offset': sched['max_operator_offset'],
                            'timer_offset': -1,
                            'source': 'fnode_ops',
                            'min_op': sched.get('min_operator_count', -1),
                            'min_op_offset': sched.get('min_operator_offset', -1),
                            'sub_elements': sched.get('sub_elements', []),
                            'worker_count': entry.get('worker_count', -1),
                            'worker_count_offset': entry.get('worker_count_offset', -1),
                        })
                        fnode_ops_count += 1

                log.info("Loaded %d factionnode operator schedules (maxOp)", fnode_ops_count)


            except Exception as _foe:
                log.exception("Unhandled exception")
                log.warning(tr("Could not load factionnode operator data: %s"), _foe)

            self._spawn_elements = elements

            self._spawn_region_combo.blockSignals(True)
            self._spawn_region_combo.clear()
            self._spawn_region_combo.addItem("All Regions", None)
            seen_regions = {}
            for el in elements:
                rk = el['region_key']
                if rk not in seen_regions:
                    seen_regions[rk] = el['region_name']
            for rk in sorted(seen_regions.keys()):
                self._spawn_region_combo.addItem(
                    f"{rk} — {seen_regions[rk]}", rk)
            self._spawn_region_combo.blockSignals(False)

            self._spawn_filter()
            self._spawn_status.setText(
                f"Loaded {len(elements)} spawn definitions across {len(seen_regions)} regions")

        except Exception as e:
            log.exception("Unhandled exception")
            self._spawn_status.setText(f"Error: {e}")
            QMessageBox.critical(self, tr("Extract Failed"), str(e))

    def _spawn_filter(self):
        if not self._spawn_elements:
            return

        self._spawn_editing = True
        region_filter = self._spawn_region_combo.currentData()
        source_filter = self._spawn_source_combo.currentData()
        search = self._spawn_search.text().strip().lower()

        filtered = []
        for el in self._spawn_elements:
            if source_filter and el.get('source', 'terrain') != source_filter:
                continue
            if region_filter is not None and el['region_key'] != region_filter:
                continue
            if search:
                char_name = self._spawn_char_names.get(el['char_key'], '').lower()
                if (search not in str(el['char_key']) and
                    search not in el['region_name'].lower() and
                    search not in str(el['region_key']) and
                    search not in char_name):
                    continue
            filtered.append(el)

        self._spawn_table.setRowCount(len(filtered))
        for row, el in enumerate(filtered):
            src = el.get('source', 'terrain')
            is_terrain = src == 'terrain'
            is_fnode = src == 'fnode'

            src_labels = {'terrain': 'Animal', 'fnode_ops': 'Camp', 'rate': 'SpawnRate'}
            src_label = src_labels.get(src, src)
            item = QTableWidgetItem(src_label)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            is_fnode_ops = src == 'fnode_ops'
            is_rate = src == 'rate'
            if is_rate:
                item.setForeground(QColor(80, 160, 255))
            elif is_fnode_ops:
                item.setForeground(QColor(180, 130, 100))
            item.setData(Qt.UserRole, el)
            self._spawn_table.setItem(row, 0, item)

            item = QTableWidgetItem(str(el['region_key']))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._spawn_table.setItem(row, 1, item)

            item = QTableWidgetItem(el['region_name'])
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._spawn_table.setItem(row, 2, item)

            item = QTableWidgetItem(str(el['char_key']))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._spawn_table.setItem(row, 3, item)

            char_name = self._spawn_char_names.get(el['char_key'], f"Char_{el['char_key']}")
            item = QTableWidgetItem(char_name)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._spawn_table.setItem(row, 4, item)

            if is_rate:
                rate_val = el.get('rate_value', el.get('spawn_count', 1.0))
                item = QTableWidgetItem(f"{rate_val:.2f}")
                orig_rate = struct.unpack_from('<f', self._spawn_original, el['count_offset'])[0]
                if abs(rate_val - orig_rate) > 0.001:
                    item.setBackground(QColor(20, 40, 80))
                item.setToolTip(f"Spawn rate (vanilla: {orig_rate:.2f})")
            elif is_terrain:
                item = QTableWidgetItem(str(el['spawn_count']))
                orig = struct.unpack_from('<I', self._spawn_original, el['count_offset'])[0]
                if el['spawn_count'] != orig:
                    item.setBackground(QColor(60, 40, 20))
            elif is_fnode_ops:
                item = QTableWidgetItem(str(el['spawn_count']))
                orig_fo = self._spawn_fnode_ops_original[el['count_offset']]
                if el['spawn_count'] != orig_fo:
                    item.setBackground(QColor(60, 30, 10))
            else:
                item = QTableWidgetItem("?")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setForeground(QColor(150, 150, 150))
            self._spawn_table.setItem(row, 5, item)

            if is_fnode_ops:
                min_op = el.get('min_op', -1)
                item = QTableWidgetItem(str(min_op))
                min_op_off = el.get('min_op_offset', -1)
                if min_op_off >= 0:
                    orig_mo = struct.unpack_from('<I', self._spawn_fnode_ops_original, min_op_off)[0]
                    if min_op != orig_mo:
                        item.setBackground(QColor(60, 30, 10))
            else:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setForeground(QColor(150, 150, 150))
            self._spawn_table.setItem(row, 6, item)

            if is_fnode_ops:
                sub_elems = el.get('sub_elements', [])
                parts = []
                changed = False
                for se in sub_elems:
                    c = se['count']
                    parts.append(str(c))
                    off = se.get('count_offset', -1)
                    if off >= 0 and hasattr(self, '_spawn_fnode_ops_original') and self._spawn_fnode_ops_original:
                        orig_c = self._spawn_fnode_ops_original[off]
                        if c != orig_c:
                            changed = True
                display = ' / '.join(parts)
                item = QTableWidgetItem(display)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if changed:
                    item.setBackground(QColor(80, 20, 40))
                item.setToolTip(
                    f"Per-slot operator counts (vanilla typically 12/15/0)\n"
                    f"Use 'Multiply Sub-Slot Counts' button to change")
            else:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._spawn_table.setItem(row, 7, item)

            if is_fnode_ops:
                wc = el.get('worker_count', -1)
                item = QTableWidgetItem(str(wc) if wc >= 0 else "?")
                wc_off = el.get('worker_count_offset', -1)
                if wc_off >= 0 and hasattr(self, '_spawn_fnode_ops_original') and self._spawn_fnode_ops_original:
                    orig_wc = self._spawn_fnode_ops_original[wc_off]
                    if wc != orig_wc:
                        item.setBackground(QColor(40, 50, 30))
            else:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._spawn_table.setItem(row, 8, item)

            if is_terrain:
                item = QTableWidgetItem(str(el['timer_ms']))
                orig_t = struct.unpack_from('<I', self._spawn_original, el['timer_offset'])[0]
                if el['timer_ms'] != orig_t:
                    item.setBackground(QColor(60, 40, 20))
            else:
                item = QTableWidgetItem("?")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setForeground(QColor(150, 150, 150))
            self._spawn_table.setItem(row, 9, item)

        self._spawn_table.resizeColumnsToContents()
        self._spawn_editing = False

    def _spawn_cell_changed(self, row, col):
        if self._spawn_editing or not self._spawn_elements:
            return
        if col not in (5, 6, 8, 9):
            return

        item0 = self._spawn_table.item(row, 0)
        if not item0:
            return
        el = item0.data(Qt.UserRole)
        if not el:
            return
        src = el.get('source', '')
        if src not in ('terrain', 'fnode_ops', 'rate'):
            return

        if src == 'rate' and col == 5:
            try:
                new_val = float(cell.text())
            except ValueError:
                return
            new_val = max(0.01, min(new_val, 20.0))
            off = el.get('count_offset', -1)
            if off >= 0:
                struct.pack_into('<f', self._spawn_data, off, new_val)
                el['spawn_count'] = new_val
                el['rate_value'] = new_val
                self._spawn_modified = True
                self._spawn_update_changes()
            return

        cell = self._spawn_table.item(row, col)
        if not cell:
            return

        if src == 'fnode_ops' and col == 8:
            try:
                new_val = int(cell.text())
            except ValueError:
                return
            new_val = max(0, min(new_val, 255))
            wc_off = el.get('worker_count_offset', -1)
            if wc_off >= 0:
                self._spawn_fnode_ops_data[wc_off] = new_val
                el['worker_count'] = new_val
                for other in self._spawn_elements:
                    if other.get('source') == 'fnode_ops' and other.get('region_key') == el.get('region_key'):
                        other['worker_count'] = new_val
                self._spawn_modified = True
                self._spawn_update_changes()
            return

        if src == 'fnode_info' and col == 5:
            try:
                new_val = float(cell.text())
            except ValueError:
                return
            if new_val < 0:
                new_val = 0.0
            struct.pack_into('<f', self._spawn_fnode_ops_data, el['count_offset'], new_val)
            el['spawn_count'] = round(new_val, 2)
            self._spawn_modified = True
            self._spawn_update_changes()
            return

        if src == 'fnode_ops' and col == 5:
            try:
                new_val = int(cell.text())
            except ValueError:
                return
            new_val = max(1, min(new_val, 255))
            self._spawn_fnode_ops_data[el['count_offset']] = new_val
            el['spawn_count'] = new_val
            self._spawn_modified = True
            self._spawn_update_changes()
            return

        if src == 'fnode_ops' and col == 6:
            try:
                new_val = int(cell.text())
            except ValueError:
                return
            new_val = max(0, min(new_val, 255))
            min_off = el.get('min_op_offset', -1)
            if min_off >= 0:
                self._spawn_fnode_ops_data[min_off] = new_val
                el['min_op'] = new_val
                self._spawn_modified = True
                self._spawn_update_changes()
            return

        if src == 'fnode' and col == 5:
            try:
                new_val = float(cell.text())
            except ValueError:
                return
            if new_val < 0:
                new_val = 0.0
            struct.pack_into('<f', self._spawn_node_data, el['count_offset'], new_val)
            el['spawn_count'] = round(new_val, 2)
            self._spawn_modified = True
            self._spawn_update_changes()
            return

        try:
            new_val = int(cell.text())
        except ValueError:
            return

        if new_val < 0:
            new_val = 0
        if col == 5 and new_val > 100:
            new_val = 100

        if col == 5:
            struct.pack_into('<I', self._spawn_data, el['count_offset'], new_val)
            el['spawn_count'] = new_val
        elif col == 9:
            struct.pack_into('<I', self._spawn_data, el['timer_offset'], new_val)
            el['timer_ms'] = new_val

        self._spawn_modified = True
        self._spawn_update_changes()

    def _spawn_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu, QInputDialog
        rows = self._spawn_table.selectionModel().selectedRows()
        if not rows:
            return

        menu = QMenu(self)
        set_count_act = menu.addAction(f"Set Spawn Count/Radius for {len(rows)} selected")
        set_timer_act = menu.addAction(f"Set Timer (ms) for {len(rows)} selected")
        menu.addSeparator()
        multiply_act = menu.addAction(f"Multiply selected by...")

        action = menu.exec(self._spawn_table.viewport().mapToGlobal(pos))
        if not action:
            return

        if action == set_count_act:
            val, ok = QInputDialog.getDouble(
                self, "Set Spawn Count / Radius",
                f"New value for {len(rows)} selected rows:\n"
                "(Terrain: integer spawn count, FNode: float radius)",
                5.0, 0.0, 10000.0, 2)
            if not ok:
                return
            changed = 0
            for idx in rows:
                item0 = self._spawn_table.item(idx.row(), 0)
                if not item0:
                    continue
                el = item0.data(Qt.UserRole)
                if not el or el.get('count_offset', -1) < 0:
                    continue
                src = el.get('source', '')
                if src == 'terrain':
                    iv = min(int(val), 100)
                    struct.pack_into('<I', self._spawn_data, el['count_offset'], iv)
                    el['spawn_count'] = iv
                    changed += 1
                elif src == 'fnode':
                    struct.pack_into('<f', self._spawn_node_data, el['count_offset'], val)
                    el['spawn_count'] = round(val, 2)
                    changed += 1
                elif src == 'fnode_ops':
                    iv = max(1, min(int(val), 255))
                    self._spawn_fnode_ops_data[el['count_offset']] = iv
                    el['spawn_count'] = iv
                    changed += 1
                elif src == 'fnode_info':
                    struct.pack_into('<f', self._spawn_fnode_ops_data, el['count_offset'], val)
                    el['spawn_count'] = round(val, 2)
                    changed += 1
            if changed:
                self._spawn_modified = True
                self._spawn_filter()
                self._spawn_update_changes()
                self._spawn_status.setText(f"Set {changed} entries to {val}")

        elif action == set_timer_act:
            val, ok = QInputDialog.getInt(
                self, "Set Timer (ms)",
                f"New respawn timer for {len(rows)} selected rows (ms):",
                5000, 50, 600000)
            if not ok:
                return
            changed = 0
            for idx in rows:
                item0 = self._spawn_table.item(idx.row(), 0)
                if not item0:
                    continue
                el = item0.data(Qt.UserRole)
                if not el or el.get('source') != 'terrain' or el.get('timer_offset', -1) < 0:
                    continue
                struct.pack_into('<I', self._spawn_data, el['timer_offset'], val)
                el['timer_ms'] = val
                changed += 1
            if changed:
                self._spawn_modified = True
                self._spawn_filter()
                self._spawn_update_changes()
                self._spawn_status.setText(f"Set {changed} timers to {val}ms")

        elif action == multiply_act:
            val, ok = QInputDialog.getDouble(
                self, "Multiply Selected",
                f"Multiply {len(rows)} selected values by:", 2.0, 0.1, 100.0, 2)
            if not ok:
                return
            changed = 0
            for idx in rows:
                item0 = self._spawn_table.item(idx.row(), 0)
                if not item0:
                    continue
                el = item0.data(Qt.UserRole)
                if not el or el.get('count_offset', -1) < 0:
                    continue
                src = el.get('source', '')
                if src == 'terrain':
                    new_val = min(int(el['spawn_count'] * val), 100)
                    struct.pack_into('<I', self._spawn_data, el['count_offset'], new_val)
                    el['spawn_count'] = new_val
                    changed += 1
                elif src == 'fnode':
                    new_val = round(el['spawn_count'] * val, 2)
                    struct.pack_into('<f', self._spawn_node_data, el['count_offset'], new_val)
                    el['spawn_count'] = new_val
                    changed += 1
                elif src == 'fnode_ops':
                    new_val = max(1, min(int(el['spawn_count'] * val), 255))
                    self._spawn_fnode_ops_data[el['count_offset']] = new_val
                    el['spawn_count'] = new_val
                    changed += 1
                elif src == 'fnode_info':
                    new_val = round(el['spawn_count'] * val, 2)
                    struct.pack_into('<f', self._spawn_fnode_ops_data, el['count_offset'], new_val)
                    el['spawn_count'] = new_val
                    changed += 1
            if changed:
                self._spawn_modified = True
                self._spawn_filter()
                self._spawn_update_changes()
                self._spawn_status.setText(f"Multiplied {changed} entries by {val}x")

    def _spawn_update_changes(self):
        if not self._spawn_original or not self._spawn_data:
            return
        changes = 0
        for el in self._spawn_elements:
            src = el.get('source', '')
            if src == 'terrain' and el['count_offset'] >= 0:
                orig_c = struct.unpack_from('<I', self._spawn_original, el['count_offset'])[0]
                orig_t = struct.unpack_from('<I', self._spawn_original, el['timer_offset'])[0]
                if el['spawn_count'] != orig_c or el['timer_ms'] != orig_t:
                    changes += 1
            elif src == 'fnode' and el['count_offset'] >= 0 and hasattr(self, '_spawn_node_original'):
                orig_f = struct.unpack_from('<f', self._spawn_node_original, el['count_offset'])[0]
                if abs(el['spawn_count'] - orig_f) > 0.01:
                    changes += 1
            elif src == 'fnode_ops' and el['count_offset'] >= 0 and hasattr(self, '_spawn_fnode_ops_original'):
                orig_fo = self._spawn_fnode_ops_original[el['count_offset']]
                if el['spawn_count'] != orig_fo:
                    changes += 1
                min_off = el.get('min_op_offset', -1)
                if min_off >= 0:
                    orig_mo = self._spawn_fnode_ops_original[min_off]
                    if el.get('min_op', -1) != orig_mo:
                        changes += 1
            elif src == 'fnode_info' and el['count_offset'] >= 0 and hasattr(self, '_spawn_fnode_ops_original'):
                orig_fi = struct.unpack_from('<f', self._spawn_fnode_ops_original, el['count_offset'])[0]
                if abs(el['spawn_count'] - round(orig_fi, 2)) > 0.01:
                    changes += 1
        self._spawn_changes_label.setText(f"{changes} change(s)" if changes else "")

    def _spawn_multiply_all(self):
        if not self._spawn_data or not self._spawn_elements:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        mult = self._spawn_multiplier.value()
        source_filter = self._spawn_source_combo.currentData()
        count = 0
        for el in self._spawn_elements:
            src = el.get('source', '')
            if source_filter and src != source_filter:
                continue
            if src == 'terrain' and el['count_offset'] >= 0:
                old = el['spawn_count']
                new_val = min(old * mult, 100)
                if new_val != old:
                    struct.pack_into('<I', self._spawn_data, el['count_offset'], new_val)
                    el['spawn_count'] = new_val
                    count += 1
            elif src == 'fnode' and el['count_offset'] >= 0:
                old = el['spawn_count']
                new_val = round(old * mult, 2)
                if new_val != old:
                    struct.pack_into('<f', self._spawn_node_data, el['count_offset'], new_val)
                    el['spawn_count'] = new_val
                    count += 1
            elif src == 'fnode_ops' and el['count_offset'] >= 0:
                old = el['spawn_count']
                new_val = max(1, min(int(old * mult), 255))
                if new_val != old:
                    self._spawn_fnode_ops_data[el['count_offset']] = new_val
                    el['spawn_count'] = new_val
                    count += 1
            elif src == 'fnode_info' and el['count_offset'] >= 0:
                old = el['spawn_count']
                new_val = round(old * mult, 2)
                if new_val != old:
                    struct.pack_into('<f', self._spawn_fnode_ops_data, el['count_offset'], new_val)
                    el['spawn_count'] = new_val
                    count += 1

        self._spawn_modified = True
        self._spawn_filter()
        self._spawn_update_changes()
        filter_label = source_filter or "all sources"
        self._spawn_status.setText(f"Multiplied {count} spawn values by {mult}x ({filter_label})")

    def _spawn_multiply_sub_slots(self):
        if not hasattr(self, '_spawn_fnode_ops_data') or not self._spawn_fnode_ops_data:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        mult = self._spawn_multiplier.value()
        count_changed = 0
        dormant_filled = 0

        for el in self._spawn_elements:
            if el.get('source') != 'fnode_ops':
                continue
            sub_elems = el.get('sub_elements', [])
            if not sub_elems:
                continue

            active_counts = [se['count'] for se in sub_elems if 1 <= se['count'] <= 20]
            fill_value = min(active_counts) if active_counts else 0

            for se in sub_elems:
                off = se.get('count_offset', -1)
                if off < 0:
                    continue
                old = se['count']
                if old > 20:
                    continue
                if old == 0 and fill_value > 0:
                    new_val = min(fill_value * mult, 255)
                    self._spawn_fnode_ops_data[off] = new_val
                    se['count'] = new_val
                    dormant_filled += 1
                    count_changed += 1
                elif old > 0:
                    new_val = min(old * mult, 255)
                    self._spawn_fnode_ops_data[off] = new_val
                    se['count'] = new_val
                    count_changed += 1

        self._spawn_modified = True
        self._spawn_filter()
        self._spawn_update_changes()
        self._spawn_status.setText(
            f"Multiplied {count_changed} sub-slot counts by {mult}x "
            f"({dormant_filled} dormant slots filled)")

    def _spawn_halve_sub_times(self):
        if not hasattr(self, '_spawn_fnode_ops_data') or not self._spawn_fnode_ops_data:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        count = 0
        for el in self._spawn_elements:
            if el.get('source') != 'fnode_ops':
                continue
            for se in el.get('sub_elements', []):
                off = se.get('time_offset', -1)
                if off < 0:
                    continue
                old = se['time']
                new_val = max(old // 2, 10)
                if new_val != old:
                    struct.pack_into('<I', self._spawn_fnode_ops_data, off, new_val)
                    se['time'] = new_val
                    count += 1

        self._spawn_modified = True
        self._spawn_filter()
        self._spawn_update_changes()
        self._spawn_status.setText(f"Halved {count} sub-slot time values")

    def _spawn_multiply_all_minop(self):
        if not hasattr(self, '_spawn_fnode_ops_data') or not self._spawn_fnode_ops_data:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        mult = self._spawn_multiplier.value()
        count = 0
        for el in self._spawn_elements:
            if el.get('source') != 'fnode_ops':
                continue
            min_off = el.get('min_op_offset', -1)
            if min_off < 0:
                continue
            old = el.get('min_op', 0)
            new_val = max(1, min(int(old * mult), 255))
            if new_val != old:
                self._spawn_fnode_ops_data[min_off] = new_val
                el['min_op'] = new_val
                count += 1

        self._spawn_modified = True
        self._spawn_filter()
        self._spawn_update_changes()
        self._spawn_status.setText(f"Multiplied {count} MinOp values by {mult}x")

    def _spawn_increase_all_smart(self):
        if not self._spawn_data:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        mult = self._spawn_multiplier.value()
        results = []

        if hasattr(self, '_spawn_fnode_ops_data') and self._spawn_fnode_ops_data:
            camp_max = 0
            for el in self._spawn_elements:
                if el.get('source') != 'fnode_ops': continue
                off = el.get('count_offset', -1)
                if off < 0: continue
                old = el.get('spawn_count', 0)
                new_val = max(1, min(int(old * mult), 255))
                if new_val != old:
                    self._spawn_fnode_ops_data[off] = new_val
                    el['spawn_count'] = new_val
                    camp_max += 1
            if camp_max: results.append(f"{camp_max} camp MaxOp x{mult}")

            camp_min = 0
            for el in self._spawn_elements:
                if el.get('source') != 'fnode_ops': continue
                min_off = el.get('min_op_offset', -1)
                if min_off < 0: continue
                old = el.get('min_op', 0)
                new_val = max(1, min(int(old * mult), 255))
                if new_val != old:
                    self._spawn_fnode_ops_data[min_off] = new_val
                    el['min_op'] = new_val
                    camp_min += 1
            if camp_min: results.append(f"{camp_min} camp MinOp x{mult}")

            sub_count = 0
            for el in self._spawn_elements:
                if el.get('source') != 'fnode_ops': continue
                sub_offsets = el.get('sub_slot_offsets', [])
                sub_values = el.get('sub_slot_values', [])
                for i, (soff, sval) in enumerate(zip(sub_offsets, sub_values)):
                    if soff < 0 or sval == 0: continue
                    new_val = max(1, min(int(sval * mult), 255))
                    if new_val != sval:
                        self._spawn_fnode_ops_data[soff] = new_val
                        sub_values[i] = new_val
                        sub_count += 1
            if sub_count: results.append(f"{sub_count} sub-slots x{mult}")

        if self._spawn_data and self._spawn_schema:
            try:
                from terrain_spawn_parser import parse_all_from_bytes
                entries, _, _ = parse_all_from_bytes(bytes(self._spawn_data), self._spawn_schema)

                limit_c = mps_c = dup_c = safety_c = dist_c = 0
                for e in entries:
                    if not e.get('parse_complete'): continue
                    for t in e.get('targets', []):
                        sl_off = t.get('spawn_limit_offset', -1)
                        if sl_off > 0:
                            raw = struct.unpack_from('<I', self._spawn_data, sl_off)[0]
                            if raw == 1:
                                struct.pack_into('<I', self._spawn_data, sl_off, 0)
                                limit_c += 1

                            mps_off = sl_off + 4
                            raw2 = struct.unpack_from('<I', self._spawn_data, mps_off)[0]
                            if raw2 == 1:
                                struct.pack_into('<I', self._spawn_data, mps_off, 0)
                                mps_c += 1

                            dist_off = sl_off + 16
                            dist_f = struct.unpack_from('<f', self._spawn_data, dist_off)[0]
                            if 10.0 < dist_f < 10000.0:
                                struct.pack_into('<f', self._spawn_data, dist_off, min(dist_f * 2, 2000.0))
                                dist_c += 1

                            safe_off = sl_off + 20
                            safe_f = struct.unpack_from('<f', self._spawn_data, safe_off)[0]
                            if safe_f > 20.0:
                                struct.pack_into('<f', self._spawn_data, safe_off, safe_f / 2)
                                safety_c += 1

                        for p in t.get('parties', []):
                            rate_off = p.get('spawn_rate_offset', -1)
                            if rate_off > 0:
                                dup_off = rate_off + 24
                                if dup_off < len(self._spawn_data) and self._spawn_data[dup_off] == 0:
                                    self._spawn_data[dup_off] = 1
                                    dup_c += 1

                if limit_c: results.append(f"{limit_c} spawn caps removed")
                if mps_c: results.append(f"{mps_c} spawn spacing loosened")
                if dist_c: results.append(f"{dist_c} spawn distance x2")
                if safety_c: results.append(f"{safety_c} safety dist halved")
                if dup_c: results.append(f"{dup_c} duplicates enabled")
            except Exception as _te:
                log.warning(tr("Terrain spawn modification failed: %s"), _te)
                log.exception("Unhandled exception")

        self._spawn_modified = True
        self._spawn_filter()
        self._spawn_update_changes()

        if results:
            summary = "\n  ".join(results)
            self._spawn_status.setText(f"Applied: {', '.join(results)}")
            QMessageBox.information(self, tr("Spawn Density Increased"),
                f"Applied all spawn density increases:\n  {summary}")
        else:
            self._spawn_status.setText(tr("No changes made (data not loaded?)"))

    def _spawn_increase_life(self):
        game_path = self._config.get("game_install_path", "")
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.warning(self, tr("Game Path"), tr("Set the game install path first."))
            return

        self._spawn_status.setText(tr("Loading ambient life data..."))
        QApplication.processEvents()

        try:
            import crimson_rs
            dir_path = "gamedata/binary__/client/bin"

            life_body = crimson_rs.extract_file(
                game_path, "0008", dir_path, "spawningpoolautospawninfo.pabgb")
            life_gh = crimson_rs.extract_file(
                game_path, "0008", dir_path, "spawningpoolautospawninfo.pabgh")

            self._spawn_life_data = bytearray(life_body)
            self._spawn_life_original = bytes(life_body)
            self._spawn_life_schema = bytes(life_gh)

            from terrain_spawn_parser import parse_spawningpool_all
            entries, failures = parse_spawningpool_all(
                bytes(self._spawn_life_data), self._spawn_life_schema)

            parsed = sum(1 for e in entries if e.get('parse_complete'))
            log.info("Parsed %d/%d spawning pool entries (%d failures)",
                     parsed, len(entries), failures)

            limit_c = mps_c = dup_c = safety_c = dist_c = 0
            for e in entries:
                if not e.get('parse_complete'):
                    continue
                for t in e.get('targets', []):
                    sl_off = t.get('spawn_limit_offset', -1)
                    if sl_off > 0:
                        raw = struct.unpack_from('<I', self._spawn_life_data, sl_off)[0]
                        if raw == 1:
                            struct.pack_into('<I', self._spawn_life_data, sl_off, 0)
                            limit_c += 1

                        mps_off = sl_off + 4
                        raw2 = struct.unpack_from('<I', self._spawn_life_data, mps_off)[0]
                        if raw2 == 1:
                            struct.pack_into('<I', self._spawn_life_data, mps_off, 0)
                            mps_c += 1

                        dist_off = sl_off + 16
                        if dist_off + 4 <= len(self._spawn_life_data):
                            dist_f = struct.unpack_from('<f', self._spawn_life_data, dist_off)[0]
                            if 10.0 < dist_f < 10000.0:
                                struct.pack_into('<f', self._spawn_life_data, dist_off,
                                                 min(dist_f * 2, 2000.0))
                                dist_c += 1

                        safe_off = sl_off + 20
                        if safe_off + 4 <= len(self._spawn_life_data):
                            safe_f = struct.unpack_from('<f', self._spawn_life_data, safe_off)[0]
                            if safe_f > 5.0:
                                struct.pack_into('<f', self._spawn_life_data, safe_off, safe_f / 2)
                                safety_c += 1

                    for p in t.get('parties', []):
                        rate_off = p.get('spawn_rate_offset', -1)
                        if rate_off > 0:
                            dup_off = rate_off + 24
                            if dup_off < len(self._spawn_life_data) and self._spawn_life_data[dup_off] == 0:
                                self._spawn_life_data[dup_off] = 1
                                dup_c += 1

            entries2, fails2 = parse_spawningpool_all(
                bytes(self._spawn_life_data), self._spawn_life_schema)
            parsed2 = sum(1 for e in entries2 if e.get('parse_complete'))

            self._spawn_modified = True
            results = []
            if limit_c: results.append(f"{limit_c} caps removed")
            if mps_c: results.append(f"{mps_c} spacing loosened")
            if dist_c: results.append(f"{dist_c} distances x2")
            if safety_c: results.append(f"{safety_c} safety halved")
            if dup_c: results.append(f"{dup_c} duplicates enabled")

            summary = ", ".join(results) if results else "no changes"
            self._spawn_status.setText(
                f"Ambient life: {parsed2}/{len(entries2)} pools modified ({summary})")

            QMessageBox.information(self, tr("Ambient Life Increased"),
                f"Modified {parsed} spawning pools (fireflies, birds, bats, insects, etc.):\n\n"
                f"  {chr(10).join(results)}\n\n"
                f"Verification: {parsed2}/{len(entries2)} still parse OK.\n"
                f"Click 'Apply to Game' to deploy.")

        except Exception as e:
            log.exception("Unhandled exception")
            self._spawn_status.setText(f"Error: {e}")
            QMessageBox.critical(self, tr("Error"), f"Failed to load ambient life data:\n{e}")

    def _spawn_multiply_rates(self):
        if not self._spawn_data or not self._spawn_schema:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        mult = self._spawn_multiplier.value()
        try:
            from terrain_spawn_parser import multiply_spawn_rates
            count = multiply_spawn_rates(self._spawn_data, self._spawn_schema, mult)
            self._spawn_modified = True
            self._spawn_update_changes()
            self._spawn_status.setText(f"Multiplied {count} verified spawn rates by {mult}x (parse-tree safe)")
        except Exception as e:
            log.exception("Unhandled exception")
            QMessageBox.critical(self, tr("SpawnEdit"), f"Failed to multiply rates: {e}")

    def _spawn_halve_timers(self):
        if not self._spawn_data or not self._spawn_elements:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        count = 0
        for el in self._spawn_elements:
            if el.get('source') != 'terrain' or el['timer_offset'] < 0:
                continue
            old = el['timer_ms']
            new_val = max(old // 2, 50)
            if new_val != old:
                struct.pack_into('<I', self._spawn_data, el['timer_offset'], new_val)
                el['timer_ms'] = new_val
                count += 1

        self._spawn_modified = True
        self._spawn_filter()
        self._spawn_update_changes()
        self._spawn_status.setText(f"Halved {count} respawn timers")

    def _spawn_reset(self):
        if not self._spawn_original:
            return
        self._spawn_data = bytearray(self._spawn_original)
        if hasattr(self, '_spawn_node_original') and self._spawn_node_original:
            self._spawn_node_data = bytearray(self._spawn_node_original)
        if hasattr(self, '_spawn_fnode_ops_original') and self._spawn_fnode_ops_original:
            self._spawn_fnode_ops_data = bytearray(self._spawn_fnode_ops_original)
        for el in self._spawn_elements:
            src = el.get('source', '')
            if src == 'terrain' and el['count_offset'] >= 0:
                el['spawn_count'] = struct.unpack_from('<I', self._spawn_data, el['count_offset'])[0]
                el['timer_ms'] = struct.unpack_from('<I', self._spawn_data, el['timer_offset'])[0]
            elif src == 'fnode' and el['count_offset'] >= 0 and hasattr(self, '_spawn_node_data'):
                el['spawn_count'] = round(struct.unpack_from('<f', self._spawn_node_data, el['count_offset'])[0], 2)
            elif src == 'fnode_ops' and el['count_offset'] >= 0 and hasattr(self, '_spawn_fnode_ops_data'):
                el['spawn_count'] = self._spawn_fnode_ops_data[el['count_offset']]
                min_off = el.get('min_op_offset', -1)
                if min_off >= 0:
                    el['min_op'] = self._spawn_fnode_ops_data[min_off]
                wc_off = el.get('worker_count_offset', -1)
                if wc_off >= 0:
                    el['worker_count'] = self._spawn_fnode_ops_data[wc_off]
                for se in el.get('sub_elements', []):
                    if se.get('count_offset', -1) >= 0:
                        se['count'] = self._spawn_fnode_ops_data[se['count_offset']]
                    if se.get('time_offset', -1) >= 0:
                        se['time'] = struct.unpack_from('<I', self._spawn_fnode_ops_data, se['time_offset'])[0]
            elif src == 'fnode_info' and el['count_offset'] >= 0 and hasattr(self, '_spawn_fnode_ops_data'):
                el['spawn_count'] = round(struct.unpack_from('<f', self._spawn_fnode_ops_data, el['count_offset'])[0], 2)
        self._spawn_modified = False
        self._spawn_changes_label.setText("")
        self._spawn_filter()
        self._spawn_status.setText(tr("Reset to vanilla values"))

    def _spawn_export_cdumm(self):
        if not self._spawn_data or not self._spawn_modified:
            QMessageBox.information(self, tr("SpawnEdit"), tr("No modifications to export."))
            return

        from PySide6.QtWidgets import QInputDialog, QFileDialog
        name, ok = QInputDialog.getText(self, "Export Spawn Mod",
                                        "Mod name:", text="Spawn Density Boost")
        if not ok or not name.strip():
            return
        name = name.strip()

        exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        default_dir = os.path.join(exe_dir, "packs")
        os.makedirs(default_dir, exist_ok=True)
        folder_name = "".join(c if (c.isalnum() or c in "-_ ") else "_" for c in name)
        save_dir = QFileDialog.getExistingDirectory(
            self, f"Choose folder for '{folder_name}' mod", default_dir)
        if not save_dir:
            return
        out_path = os.path.join(save_dir, folder_name)

        self._spawn_status.setText(tr("Packing with pack_mod..."))
        QApplication.processEvents()

        try:
            import crimson_rs
            import crimson_rs.pack_mod
            import tempfile
            import shutil

            game_path = self._config.get("game_install_path", "")

            if os.path.isdir(out_path):
                shutil.rmtree(out_path)
            os.makedirs(out_path, exist_ok=True)

            with tempfile.TemporaryDirectory() as tmp_dir:
                mod_dir = os.path.join(tmp_dir, "gamedata", "binary__", "client", "bin")
                os.makedirs(mod_dir, exist_ok=True)
                with open(os.path.join(mod_dir, "terrainregionautospawninfo.pabgb"), "wb") as f:
                    f.write(self._spawn_data)
                if hasattr(self, '_spawn_node_data') and self._spawn_node_data:
                    with open(os.path.join(mod_dir, "factionnodespawninfo.pabgb"), "wb") as f:
                        f.write(self._spawn_node_data)
                if hasattr(self, '_spawn_fnode_ops_data') and self._spawn_fnode_ops_data:
                    with open(os.path.join(mod_dir, "factionnode.pabgb"), "wb") as f:
                        f.write(self._spawn_fnode_ops_data)
                if hasattr(self, '_spawn_life_data') and self._spawn_life_data:
                    with open(os.path.join(mod_dir, "spawningpoolautospawninfo.pabgb"), "wb") as f:
                        f.write(self._spawn_life_data)

                pack_out = os.path.join(tmp_dir, "output")
                os.makedirs(pack_out, exist_ok=True)

                mod_group = f"{self._spawn_overlay_spin.value():04d}"
                crimson_rs.pack_mod.pack_mod(
                    game_dir=game_path,
                    mod_folder=tmp_dir,
                    output_dir=pack_out,
                    group_name=mod_group,
                )

                paz_dst = os.path.join(out_path, mod_group)
                os.makedirs(paz_dst, exist_ok=True)
                shutil.copy2(os.path.join(pack_out, mod_group, "0.paz"),
                             os.path.join(paz_dst, "0.paz"))
                shutil.copy2(os.path.join(pack_out, mod_group, "0.pamt"),
                             os.path.join(paz_dst, "0.pamt"))

                meta_dst = os.path.join(out_path, "meta")
                os.makedirs(meta_dst, exist_ok=True)
                shutil.copy2(os.path.join(pack_out, "meta", "0.papgt"),
                             os.path.join(meta_dst, "0.papgt"))

            modinfo = {
                "id": name.lower().replace(" ", "_"),
                "name": name,
                "version": "1.0.0",
                "game_version": "1.00.03",
                "author": "CrimsonSaveEditor",
                "description": f"Spawn density mod: {name}",
            }
            with open(os.path.join(out_path, "modinfo.json"), "w", encoding="utf-8") as f:
                json.dump(modinfo, f, indent=2)

            paz_size = os.path.getsize(os.path.join(paz_dst, "0.paz"))
            self._spawn_status.setText(f"Exported to {folder_name}/")
            QMessageBox.information(self, tr("Spawn Mod Exported"),
                f"Mod exported to:\n{out_path}\n\n"
                f"Contents:\n"
                f"  {mod_group}/0.paz ({paz_size:,} bytes)\n"
                f"  {mod_group}/0.pamt\n"
                f"  meta/0.papgt\n"
                f"  modinfo.json\n\n"
                f"Import into CDUMM or copy to game directory.")

        except Exception as e:
            log.exception("Unhandled exception")
            self._spawn_status.setText(f"Export failed: {e}")
            QMessageBox.critical(self, tr("Export Failed"), str(e))

    def _spawn_export_field_json_v3(self) -> None:
        """Export SpawnEdit modifications as Format 3.1 multi-target field JSON."""
        try:
            import struct as _st

            if not self._spawn_data or not self._spawn_original:
                QMessageBox.information(self, tr("Export Field JSON v3"),
                    tr("No spawn data loaded. Extract spawn data first."))
                return

            def _diff_table(cur_buf, van_buf, file_label):
                """Byte-diff two buffers, return list of 4-byte intents."""
                intents = []
                j = 0
                cur_bytes = bytes(cur_buf)
                van_bytes = bytes(van_buf)
                while j < min(len(cur_bytes), len(van_bytes)) - 3:
                    if cur_bytes[j:j+4] != van_bytes[j:j+4]:
                        intents.append({
                            'entry': f'offset_{j}',
                            'key': j,
                            'field': 'raw_bytes',
                            'op': 'set',
                            'new': cur_bytes[j:j+4].hex().upper(),
                            '_offset': j,
                            '_original': van_bytes[j:j+4].hex().upper(),
                        })
                        j += 4
                    else:
                        j += 1
                return intents

            targets = []

            # terrainregionautospawninfo — annotate with region/char names where known
            ter_intents = _diff_table(self._spawn_data, self._spawn_original, 'terrain')
            # Enrich with names from element map
            off_map = {}
            for elem in getattr(self, '_spawn_elements', []):
                region = elem.get('region_name', f"Region_{elem.get('region_key','?')}")
                char_key = elem.get('char_key', 0)
                rkey = elem.get('region_key', 0)
                label = f"{region}_char{char_key}"
                for fname, okey in [('spawn_count','count_offset'),
                                     ('timer_ms','timer_offset'),
                                     ('max_operator_count','max_operator_offset')]:
                    off = elem.get(okey, -1)
                    if off >= 0:
                        off_map[off] = (label, fname, rkey)
            for intent in ter_intents:
                off = intent['_offset']
                if off in off_map:
                    label, fname, rkey = off_map[off]
                    intent['entry'] = label
                    intent['field'] = fname
                    intent['key'] = rkey
            if ter_intents:
                targets.append({'file': 'terrainregionautospawninfo.pabgb',
                                'intents': ter_intents})

            # other tables
            for cur_attr, van_attr, fname in [
                ('_spawn_life_data',      '_spawn_life_original',      'spawningpoolautospawninfo.pabgb'),
                ('_spawn_node_data',      '_spawn_node_original',      'factionnodespawninfo.pabgb'),
                ('_spawn_fnode_ops_data', '_spawn_fnode_ops_original', 'factionnode.pabgb'),
            ]:
                cur = getattr(self, cur_attr, None)
                van = getattr(self, van_attr, None)
                if cur and van:
                    its = _diff_table(cur, van, fname)
                    if its:
                        targets.append({'file': fname, 'intents': its})

            if not targets:
                QMessageBox.information(self, tr("Export Field JSON v3"),
                    tr("No differences found. Make changes using the spawn editor first."))
                return

            total = sum(len(t['intents']) for t in targets)
            summary = ', '.join(f"{len(t['intents'])} {t['file'].split('.')[0]}"
                                for t in targets)

            path, _ = QFileDialog.getSaveFileName(
                self, tr("Export Field JSON v3"), "SpawnEdit.field.json",
                "Field JSON (*.field.json *.json);;All Files (*)")
            if not path:
                return

            doc = {
                'modinfo': {
                    'title': 'SpawnEdit Mod',
                    'version': '1.0',
                    'author': 'CrimsonGameMods SpawnEdit',
                    'description': (f'{total} spawn intent(s) across '
                                    f'{len(targets)} target(s) — {summary}'),
                    'note': ('Field JSON v3.1 (multi-target) — byte-level spawn patches. '
                             'Each intent includes _offset and _original for verification. '
                             'Named entries where region/character mapping is known.'),
                },
                'format': 3,
                'format_minor': 1,
                'targets': targets,
            }

            with open(path, 'w', encoding='utf-8') as _f:
                json.dump(doc, _f, indent=2, ensure_ascii=False)

            self._spawn_status.setText(
                f"Exported {total} spawn intents to {os.path.basename(path)}")
            QMessageBox.information(self, tr("Export Field JSON v3"),
                f"Exported {total} spawn intents across {len(targets)} targets:\n"
                + "\n".join(f"  • {t['file']}: {len(t['intents'])} intents"
                             for t in targets)
                + f"\n\nFile: {path}")

        except Exception as _err:
            import traceback as _tb
            QMessageBox.critical(self, tr("Export Field JSON v3 — Error"),
                f"An error occurred:\n{_err}\n\n{_tb.format_exc()}")

    def _spawn_apply(self):

        if not self._spawn_data or not self._spawn_modified:
            QMessageBox.information(self, tr("SpawnEdit"), tr("No modifications to apply."))
            return

        game_path = self._config.get("game_install_path", "")
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.critical(self, tr("Game Path"), tr("Game install path not set."))
            return

        mod_group = f"{self._spawn_overlay_spin.value():04d}"
        reply = QMessageBox.question(
            self, tr("Apply Spawn Changes"),
            f"Deploy modified spawn data to the game?\n\n"
            f"Creates {mod_group}/ overlay. Restart game to take effect.\n"
            f"Original files are NOT modified. Use Restore to undo.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self._spawn_status.setText(tr("Packing with pack_mod..."))
        QApplication.processEvents()

        try:
            import crimson_rs.pack_mod
            import shutil
            import tempfile
            from pathlib import Path

            gp = Path(game_path)

            with tempfile.TemporaryDirectory() as tmp_dir:
                mod_dir = os.path.join(tmp_dir, "gamedata", "binary__", "client", "bin")
                os.makedirs(mod_dir, exist_ok=True)
                with open(os.path.join(mod_dir, "terrainregionautospawninfo.pabgb"), "wb") as f:
                    f.write(self._spawn_data)
                if hasattr(self, '_spawn_node_data') and self._spawn_node_data:
                    with open(os.path.join(mod_dir, "factionnodespawninfo.pabgb"), "wb") as f:
                        f.write(self._spawn_node_data)
                if hasattr(self, '_spawn_fnode_ops_data') and self._spawn_fnode_ops_data:
                    with open(os.path.join(mod_dir, "factionnode.pabgb"), "wb") as f:
                        f.write(self._spawn_fnode_ops_data)
                if hasattr(self, '_spawn_life_data') and self._spawn_life_data:
                    with open(os.path.join(mod_dir, "spawningpoolautospawninfo.pabgb"), "wb") as f:
                        f.write(self._spawn_life_data)

                pack_out = os.path.join(tmp_dir, "output")
                os.makedirs(pack_out, exist_ok=True)

                crimson_rs.pack_mod.pack_mod(
                    game_dir=game_path,
                    mod_folder=tmp_dir,
                    output_dir=pack_out,
                    group_name=mod_group,
                )

                papgt_path = gp / "meta" / "0.papgt"
                backup_path = papgt_path.with_suffix(".papgt.spawn_bak")
                if papgt_path.exists() and not backup_path.exists():
                    shutil.copy2(papgt_path, backup_path)

                dest = gp / mod_group
                dest.mkdir(exist_ok=True)
                shutil.copyfile(
                    os.path.join(pack_out, mod_group, "0.paz"), dest / "0.paz")
                shutil.copyfile(
                    os.path.join(pack_out, mod_group, "0.pamt"), dest / "0.pamt")
                shutil.copyfile(
                    os.path.join(pack_out, "meta", "0.papgt"), papgt_path)

            self._spawn_status.setText(f"Applied to {mod_group}/")
            QMessageBox.information(self, tr("Applied"),
                f"Spawn mod deployed to {mod_group}/.\n"
                f"Restart the game for changes to take effect.")

        except Exception as e:
            log.exception("Unhandled exception")
            self._spawn_status.setText(f"Apply failed: {e}")
            QMessageBox.critical(self, tr("Apply Failed"), str(e))

    def _spawn_restore(self):
        game_path = self._config.get("game_install_path", "")
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.warning(self, tr("Game Path"), tr("Game path not set."))
            return

        mod_group = f"{self._spawn_overlay_spin.value():04d}"
        game_mod = os.path.join(game_path, mod_group)
        if not os.path.isdir(game_mod):
            QMessageBox.information(self, tr("Restore"), f"No {mod_group}/ overlay found.")
            return

        reply = QMessageBox.question(
            self, tr("Restore Vanilla Spawns"),
            f"Remove {mod_group}/ overlay and restore vanilla spawn data?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        try:
            import shutil
            msg = self._rebuild_papgt_fn(game_path, mod_group)
            shutil.rmtree(game_mod)
            self._spawn_status.setText(tr("Restored vanilla spawns"))
            QMessageBox.information(self, tr("Restored"),
                f"Removed {mod_group}/ overlay.\n{msg}\n"
                f"Restart the game for changes to take effect.")
        except Exception as e:
            QMessageBox.critical(self, tr("Restore Failed"), str(e))


class PrecisionItemDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QDoubleSpinBox(parent)
        editor.setDecimals(4)
        editor.setRange(0.0000, 100.0000)
        return editor

    def displayText(self, value, locale):
        try:
            return f"{float(value):.4f}"
        except (ValueError, TypeError):
            return str(value)


class DropsetTab(QWidget):

    status_message = Signal(str)

    def __init__(
        self,
        name_db,
        icon_cache,
        config: dict,
        rebuild_papgt_fn: Optional[Callable] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._name_db = name_db
        self._icon_cache = icon_cache
        self._config = config
        self._rebuild_papgt_fn = rebuild_papgt_fn
        self._build_ui()

    def set_experimental_mode(self, enabled: bool) -> None:
        if hasattr(self, '_dev_export_btn_drop'):
            self._dev_export_btn_drop.setVisible(bool(enabled))

    def get_staged_files(self) -> dict:
        """Return modified dropsetinfo pabgb/pabgh for Stacker Pull All Edits."""
        if not getattr(self, '_dropset_modified', False):
            return {}
        editor = getattr(self, '_dropset_editor', None)
        if editor is None:
            return {}
        # Flush any pending cell edits before snapshotting
        try:
            self._dropset_flush_dirty()
        except Exception:
            pass
        result = {}
        body = getattr(editor, 'body_bytes', None)
        header = getattr(editor, 'header_bytes', None)
        orig_body = getattr(self, '_dropset_original_body', None)
        orig_header = getattr(self, '_dropset_original_header', None)
        if body is not None and orig_body is not None and bytes(body) != bytes(orig_body):
            result['dropsetinfo.pabgb'] = bytes(body)
        if header is not None and orig_header is not None and bytes(header) != bytes(orig_header):
            result['dropsetinfo.pabgh'] = bytes(header)
        # Always include body if modified flag is set and body exists (header may be unchanged)
        if result == {} and body is not None and getattr(self, '_dropset_modified', False):
            if body is not None:
                result['dropsetinfo.pabgb'] = bytes(body)
            if header is not None:
                result['dropsetinfo.pabgh'] = bytes(header)
        return result

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(make_scope_label("game"))

        info = QLabel(
            "Edit drop tables — boost chest loot rates, swap trash items for enchant scrolls, "
            "add new drops, adjust quantities. Export as JSON mod or apply directly."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['accent']}; padding: 8px; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"background-color: rgba(218,168,80,0.08);"
        )
        layout.addWidget(info)

        top_row = QHBoxLayout()
        load_btn = QPushButton(tr("Load DropSets"))
        load_btn.setObjectName("accentBtn")
        load_btn.setToolTip(tr("Extract dropsetinfo from the game PAZ archive"))
        load_btn.clicked.connect(self._dropset_extract)
        top_row.addWidget(load_btn)

        drop_export_btn = QPushButton(tr("Export as Mod"))
        drop_export_btn.setToolTip(
            "ADVANCED — UNSUPPORTED. Contact mod loader dev for help.\n\n"
            "Export as standalone PAZ overlay mod.")
        drop_export_btn.clicked.connect(self._dropset_export_mod)
        drop_export_btn.setVisible(False)
        top_row.addWidget(drop_export_btn)
        self._dev_export_btn_drop = drop_export_btn

        apply_btn = QPushButton(tr("Apply to Game"))
        apply_btn.setObjectName("accentBtn")
        apply_btn.setToolTip(
            "Deploy modified drop tables directly to the game.\n"
            "Creates an overlay group (default 0036/). Restart game to take effect.")
        apply_btn.clicked.connect(self._dropset_apply)
        top_row.addWidget(apply_btn)

        # Overlay group number — user-configurable so they can avoid
        # colliding with whichever slot another mod owns.
        top_row.addWidget(QLabel(tr("Overlay:")))
        self._dropset_overlay_spin = QSpinBox()
        self._dropset_overlay_spin.setRange(1, 9999)
        self._dropset_overlay_spin.setValue(
            self._config.get("dropset_overlay_dir", 36))
        self._dropset_overlay_spin.setFixedWidth(70)
        self._dropset_overlay_spin.setToolTip(
            "Overlay group number (0036 = default). Change if another mod\n"
            "already uses this slot. Apply to Game writes to <game>/NNNN/;\n"
            "Restore removes the same NNNN/.")
        self._dropset_overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"dropset_overlay_dir": int(v)}))
        top_row.addWidget(self._dropset_overlay_spin)

        restore_btn = QPushButton(tr("Restore"))
        restore_btn.setToolTip(tr("Remove drop table mod and restore vanilla"))
        restore_btn.clicked.connect(self._dropset_restore)
        top_row.addWidget(restore_btn)

        export_field_btn = QPushButton("Export Field JSON")
        export_field_btn.setStyleSheet(button_css("success") + " font-weight: bold;")
        export_field_btn.setToolTip(
            "Export edits as Format 3 field-name JSON.\n"
            "Uses field names — survives game updates.")
        export_field_btn.clicked.connect(self._dropset_export_field_json)
        top_row.addWidget(export_field_btn)

        import_field_btn = QPushButton("Import Field JSON")
        import_field_btn.setToolTip(
            "Import a Format 3 field-name JSON and apply its intents\n"
            "to the currently loaded vanilla data.")
        import_field_btn.clicked.connect(self._dropset_import_field_json)
        top_row.addWidget(import_field_btn)

        self._dropset_status = QLabel("")
        self._dropset_status.setStyleSheet(f"color: {COLORS['accent']}; padding: 4px;")
        top_row.addWidget(self._dropset_status, 1)

        self._dropset_changes_label = QLabel("")
        self._dropset_changes_label.setStyleSheet(
            f"color: {COLORS['warning']}; font-weight: bold; padding: 4px;")
        top_row.addWidget(self._dropset_changes_label)
        layout.addLayout(top_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(tr("Category:")))
        self._dropset_cat_combo = QComboBox()
        self._dropset_cat_combo.addItem("All")
        self._dropset_cat_combo.setFixedWidth(140)
        self._dropset_cat_combo.currentTextChanged.connect(self._dropset_filter)
        filter_row.addWidget(self._dropset_cat_combo)

        self._dropset_search = QLineEdit()
        self._dropset_search.setPlaceholderText(tr("Search drop sets..."))
        self._dropset_search.textChanged.connect(self._dropset_filter)
        filter_row.addWidget(self._dropset_search, 1)

        self._dropset_show_unnamed = QCheckBox(tr("Show unnamed (10K+)"))
        self._dropset_show_unnamed.setChecked(False)
        self._dropset_show_unnamed.toggled.connect(self._dropset_filter)
        filter_row.addWidget(self._dropset_show_unnamed)
        layout.addLayout(filter_row)

        splitter = QSplitter(Qt.Horizontal)

        left_frame = QFrame()
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self._dropset_list = QTableWidget()
        self._dropset_list.setColumnCount(4)
        self._dropset_list.setHorizontalHeaderLabels(["Key", "Name", "Items", "Category"])
        self._dropset_list.setEditTriggers(QTableWidget.NoEditTriggers)
        self._dropset_list.setSelectionBehavior(QTableWidget.SelectRows)
        self._dropset_list.setSelectionMode(QTableWidget.SingleSelection)
        self._dropset_list.setSortingEnabled(True)
        self._dropset_list.horizontalHeader().setStretchLastSection(True)
        self._dropset_list.setColumnWidth(0, 70)
        self._dropset_list.setColumnWidth(1, 220)
        self._dropset_list.setColumnWidth(2, 50)
        self._dropset_list.itemSelectionChanged.connect(self._dropset_selected)
        left_layout.addWidget(self._dropset_list)
        splitter.addWidget(left_frame)

        right_frame = QFrame()
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._dropset_set_label = QLabel(tr("Select a drop set"))
        self._dropset_set_label.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold; padding: 4px;")
        right_layout.addWidget(self._dropset_set_label)

        self._dropset_items = QTableWidget()
        self._dropset_items.setColumnCount(8)
        self._dropset_items.setHorizontalHeaderLabels(
            ["Icon", "#", "Item Key", "Item Name", "Category", "Rate %", "Qty Min", "Qty Max"])
        self._dropset_items.setSelectionBehavior(QTableWidget.SelectRows)
        self._dropset_items.setSelectionMode(QTableWidget.ExtendedSelection)
        self._dropset_items.setSortingEnabled(False)
        self._dropset_items.horizontalHeader().setStretchLastSection(False)
        self._dropset_items.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._dropset_show_icons = False
        self._dropset_items.setColumnWidth(0, 0)
        self._dropset_items.setColumnWidth(1, 30)
        self._dropset_items.setColumnWidth(2, 80)
        self._dropset_items.setColumnWidth(3, 180)
        self._dropset_items.setColumnWidth(4, 100)
        self._dropset_items.setColumnWidth(5, 75)
        self._dropset_items.setColumnWidth(6, 80)
        self._dropset_items.setColumnWidth(7, 80)
        self._dropset_items.cellChanged.connect(self._dropset_cell_edited)
        self._dropset_items.setItemDelegateForColumn(5, PrecisionItemDelegate(self._dropset_items))
        right_layout.addWidget(self._dropset_items)

        edit_row = QHBoxLayout()

        add_key_input = QLineEdit()
        add_key_input.setPlaceholderText(tr("Item key"))
        add_key_input.setFixedWidth(90)
        self._dropset_add_key = add_key_input
        edit_row.addWidget(add_key_input)

        add_btn = QPushButton(tr("+Add"))
        add_btn.setToolTip(tr("Add a new item to this drop set"))
        add_btn.clicked.connect(self._dropset_add_item)
        edit_row.addWidget(add_btn)

        remove_btn = QPushButton(tr("Remove"))
        remove_btn.setToolTip(tr("Remove selected items from this drop set"))
        remove_btn.clicked.connect(self._dropset_remove_item)
        edit_row.addWidget(remove_btn)

        swap_btn = QPushButton(tr("Swap"))
        swap_btn.setToolTip(tr("Replace selected item with a new item key"))
        swap_btn.clicked.connect(self._dropset_swap_item)
        edit_row.addWidget(swap_btn)

        icons_btn = QPushButton(tr("Icons"))
        icons_btn.setCheckable(True)
        icons_btn.setToolTip(tr("Toggle item icons in the drop items table"))
        icons_btn.clicked.connect(self._dropset_toggle_icons)
        edit_row.addWidget(icons_btn)

        edit_row.addStretch()

        edit_row.addWidget(QLabel(tr("All Rates:")))
        self._dropset_bulk_rate = QDoubleSpinBox()
        self._dropset_bulk_rate.setDecimals(4)
        self._dropset_bulk_rate.setRange(0.0000, 100.0000)
        self._dropset_bulk_rate.setValue(100.0000)
        self._dropset_bulk_rate.setSuffix("%")
        self._dropset_bulk_rate.setMinimumWidth(85)
        edit_row.addWidget(self._dropset_bulk_rate)
        bulk_rate_btn = QPushButton(tr("Set"))
        bulk_rate_btn.clicked.connect(self._dropset_bulk_set_rate)
        edit_row.addWidget(bulk_rate_btn)

        edit_row.addWidget(QLabel(tr("All Qty:")))
        self._dropset_bulk_qty = QSpinBox()
        self._dropset_bulk_qty.setRange(1, 9999)
        self._dropset_bulk_qty.setValue(10)
        self._dropset_bulk_qty.setMinimumWidth(80)
        edit_row.addWidget(self._dropset_bulk_qty)
        bulk_qty_btn = QPushButton(tr("Set"))
        bulk_qty_btn.clicked.connect(self._dropset_bulk_set_qty)
        edit_row.addWidget(bulk_qty_btn)

        right_layout.addLayout(edit_row)
        splitter.addWidget(right_frame)
        splitter.setSizes([350, 550])
        layout.addWidget(splitter, 1)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel(tr("Preset:")))
        self._dropset_preset_combo = QComboBox()
        self._dropset_preset_combo.addItems(["Loot Bonanza", "Generous"])
        self._dropset_preset_combo.setFixedWidth(160)
        preset_row.addWidget(self._dropset_preset_combo)

        apply_preset_btn = QPushButton(tr("Apply to Chest Tiers"))
        apply_preset_btn.setObjectName("accentBtn")
        apply_preset_btn.setToolTip(
            tr("Apply the selected preset to all 4 chest tier drop sets (Tier 1-4)"))
        apply_preset_btn.clicked.connect(self._dropset_apply_preset)
        preset_row.addWidget(apply_preset_btn)

        apply_sel_btn = QPushButton(tr("Apply to Selected"))
        apply_sel_btn.setToolTip(tr("Apply rate/qty boost to the currently selected drop set"))
        apply_sel_btn.clicked.connect(self._dropset_apply_to_selected)
        preset_row.addWidget(apply_sel_btn)

        preset_row.addStretch()

        preset_row.addWidget(QLabel(tr("Global Loot:")))
        for mult, label in [(5, "5x"), (10, "10x"), (50, "50x"), (100, "100x")]:
            btn = QPushButton(label)
            btn.setToolTip(
                f"Set ALL named drop sets to 100% rate, x{mult} quantity.\n"
                f"Affects all {679} named sets (chests, factions, monsters, etc.)")
            btn.clicked.connect(lambda checked, m=mult: self._dropset_global_boost(m))
            preset_row.addWidget(btn)

        layout.addLayout(preset_row)

        config_row = QHBoxLayout()

        save_cfg_btn = QPushButton(tr("Save Config"))
        save_cfg_btn.setToolTip(tr("Save current drop table edits as a reusable JSON config"))
        save_cfg_btn.clicked.connect(self._dropset_save_config)
        config_row.addWidget(save_cfg_btn)

        load_cfg_btn = QPushButton(tr("Load Config"))
        load_cfg_btn.setToolTip(tr("Load a previously saved drop table config"))
        load_cfg_btn.clicked.connect(self._dropset_load_config)
        config_row.addWidget(load_cfg_btn)

        config_row.addWidget(QLabel("  "))

        config_row.addWidget(QLabel(tr("Pack:")))
        self._dropset_pack_combo = QComboBox()
        self._dropset_pack_combo.setFixedWidth(180)
        self._dropset_pack_combo.setToolTip(tr("Select a drop item pack to add to the selected set"))
        config_row.addWidget(self._dropset_pack_combo)

        add_pack_btn = QPushButton(tr("Add Pack to Selected"))
        add_pack_btn.setToolTip(tr("Append all items from the selected pack to the current drop set"))
        add_pack_btn.clicked.connect(self._dropset_add_pack)
        config_row.addWidget(add_pack_btn)

        config_row.addStretch()
        layout.addLayout(config_row)

        credit = QLabel(tr("credit: Potter420 (dropsetinfo RE, pycrimson, crimson-rs)"))
        credit.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 2px;")
        layout.addWidget(credit)

        self._dropset_editor = None
        self._dropset_modified = False
        self._dropset_change_count = 0
        self._dropset_original_body = None
        self._dropset_original_header = None
        self._dropset_current_key = None
        self._dropset_summaries = []
        self._dropset_editing = False
        self._dropset_dirty_keys = set()


    def _dropset_extract(self):
        game_path = self._config.get("game_install_path", "")
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.warning(self, tr("Game Path"),
                tr("Set the game install path first (top of the window)."))
            return

        self._dropset_status.setText(tr("Extracting dropsetinfo..."))
        QApplication.processEvents()

        try:
            import crimson_rs

            dir_path = "gamedata/binary__/client/bin"
            body_data = crimson_rs.extract_file(game_path, "0008", dir_path, "dropsetinfo.pabgb")
            header_data = crimson_rs.extract_file(game_path, "0008", dir_path, "dropsetinfo.pabgh")

            from dropset_editor import DropsetEditor
            editor = DropsetEditor()
            editor.header_bytes = bytes(header_data)
            editor.body_bytes = bytearray(body_data)

            import struct
            editor.record_count = struct.unpack_from("<H", editor.header_bytes, 0)[0]
            editor.records = []
            for i in range(editor.record_count):
                off = 2 + i * 8
                key, offset = struct.unpack_from("<II", editor.header_bytes, off)
                editor.records.append((key, offset))

            editor.load_item_names()

            self._dropset_editor = editor
            self._dropset_original_body = bytes(body_data)
            self._dropset_original_header = bytes(header_data)
            self._dropset_modified = False
            self._dropset_change_count = 0
            self._dropset_changes_label.setText("")

            cats = editor.get_categories(named_only=True)
            self._dropset_cat_combo.blockSignals(True)
            self._dropset_cat_combo.clear()
            self._dropset_cat_combo.addItem("All")
            for c in cats:
                self._dropset_cat_combo.addItem(c)
            self._dropset_cat_combo.blockSignals(False)

            self._dropset_filter()
            self._dropset_scan_packs()
            self._dropset_status.setText(
                f"Loaded {editor.record_count:,} drop sets")
        except Exception as e:
            log.exception("Unhandled exception")
            self._dropset_status.setText(f"Error: {e}")
            QMessageBox.critical(self, tr("Extract Failed"), str(e))

    def _dropset_filter(self):
        if not self._dropset_editor:
            return

        named_only = not self._dropset_show_unnamed.isChecked()
        summaries = self._dropset_editor.get_all_sets_summary(named_only=named_only)
        self._dropset_summaries = summaries

        cat = self._dropset_cat_combo.currentText()
        search = self._dropset_search.text().strip().lower()

        filtered = summaries
        if cat and cat != "All":
            filtered = [s for s in filtered if s["category"] == cat]
        if search:
            filtered = [s for s in filtered
                        if search in s["name"].lower() or search in str(s["key"])]

        self._dropset_list.setSortingEnabled(False)
        self._dropset_list.setRowCount(len(filtered))
        for row, s in enumerate(filtered):
            key_item = QTableWidgetItem()
            key_item.setData(Qt.DisplayRole, s["key"])
            self._dropset_list.setItem(row, 0, key_item)
            self._dropset_list.setItem(row, 1, QTableWidgetItem(s["name"] or f"(key {s['key']})"))
            count_item = QTableWidgetItem()
            count_item.setData(Qt.DisplayRole, s["drop_count"])
            self._dropset_list.setItem(row, 2, count_item)
            self._dropset_list.setItem(row, 3, QTableWidgetItem(s["category"]))
        self._dropset_list.setSortingEnabled(True)

    def _dropset_selected(self):
        if not self._dropset_editor:
            return
        rows = self._dropset_list.selectionModel().selectedRows()
        if not rows:
            return

        row = rows[0].row()
        key_item = self._dropset_list.item(row, 0)
        if not key_item:
            return
        key = int(key_item.data(Qt.DisplayRole))
        self._dropset_current_key = key

        ds = self._dropset_editor.parse_dropset(key)
        if not ds:
            self._dropset_set_label.setText(f"Failed to parse key {key}")
            return

        name = ds.name or f"(key {key})"
        self._dropset_set_label.setText(f"{name}  —  {len(ds.drops)} items")
        self._dropset_refresh_items(ds)

    def _dropset_refresh_items(self, ds=None):
        if ds is None:
            if self._dropset_current_key is None:
                return
            ds = self._dropset_editor.parse_dropset(self._dropset_current_key)
            if not ds:
                return

        self._dropset_editing = True
        show_icons = self._dropset_show_icons
        if show_icons:
            self._dropset_items.verticalHeader().setDefaultSectionSize(ICON_SIZE + 4)
        else:
            self._dropset_items.verticalHeader().setDefaultSectionSize(22)

        self._dropset_items.setRowCount(len(ds.drops))
        for row, d in enumerate(ds.drops):
            item_name = self._dropset_editor.get_item_name(d.item_key)
            item_cat = ""

            icon_item = QTableWidgetItem()
            icon_item.setFlags(icon_item.flags() & ~Qt.ItemIsEditable)
            if show_icons and hasattr(self, '_icon_cache') and self._icon_cache:
                px = self._icon_cache.get_pixmap(d.item_key)
                if px and not px.isNull():
                    icon_item.setIcon(QIcon(px.scaled(
                        ICON_SIZE, ICON_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self._dropset_items.setItem(row, 0, icon_item)

            idx_item = QTableWidgetItem()
            idx_item.setData(Qt.DisplayRole, row)
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
            self._dropset_items.setItem(row, 1, idx_item)

            key_item = QTableWidgetItem()
            key_item.setData(Qt.DisplayRole, d.item_key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
            self._dropset_items.setItem(row, 2, key_item)

            name_item = QTableWidgetItem(item_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self._dropset_items.setItem(row, 3, name_item)

            cat_item = QTableWidgetItem(item_cat)
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemIsEditable)
            self._dropset_items.setItem(row, 4, cat_item)

            rate_pct = d.rates / 10000
            rate_item = QTableWidgetItem()
            rate_item.setData(Qt.DisplayRole, round(rate_pct, 2))
            self._dropset_items.setItem(row, 5, rate_item)

            qmin_item = QTableWidgetItem()
            qmin_item.setData(Qt.DisplayRole, d.max_amt)
            self._dropset_items.setItem(row, 6, qmin_item)

            qmax_item = QTableWidgetItem()
            qmax_item.setData(Qt.DisplayRole, d.min_amt)
            self._dropset_items.setItem(row, 7, qmax_item)

        self._dropset_editing = False

    def _dropset_toggle_icons(self, checked):
        self._dropset_show_icons = checked
        if checked:
            self._dropset_items.setColumnWidth(0, ICON_SIZE + 16)
            self._dropset_items.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        else:
            self._dropset_items.setColumnWidth(0, 0)
        self._dropset_refresh_items()

    def _dropset_cell_edited(self, row, col):
        if self._dropset_editing or not self._dropset_editor:
            return
        if self._dropset_current_key is None:
            return
        if col < 5:
            return

        ds = self._dropset_editor.parse_dropset(self._dropset_current_key)
        if not ds or row >= len(ds.drops):
            return

        item = self._dropset_items.item(row, col)
        if not item:
            return
        try:
            val = float(item.data(Qt.DisplayRole))
        except (TypeError, ValueError):
            return

        drop = ds.drops[row]
        if col == 5:
            drop.rates = int(val * 10000)
            drop.rates_100 = int(val)
        elif col == 6:
            drop.max_amt = int(val)
        elif col == 7:
            drop.min_amt = int(val)

        self._dropset_mark_modified()

    def _dropset_flush_dirty(self):
        if not self._dropset_editor or not self._dropset_dirty_keys:
            return
        modified = []
        for key in self._dropset_dirty_keys:
            ds = self._dropset_editor._parsed_sets.get(key)
            if ds:
                modified.append(ds)
        if modified:
            self._dropset_editor.apply_modifications(modified)
        self._dropset_dirty_keys.clear()

    def _dropset_mark_modified(self, key=None):
        self._dropset_modified = True
        self._dropset_change_count += 1
        if key is not None:
            self._dropset_dirty_keys.add(key)
        elif self._dropset_current_key is not None:
            self._dropset_dirty_keys.add(self._dropset_current_key)
        self._dropset_changes_label.setText(f"{self._dropset_change_count} change(s)")

    def _dropset_add_item(self):
        if not self._dropset_editor or self._dropset_current_key is None:
            return

        ds = self._dropset_editor.parse_dropset(self._dropset_current_key)
        if not ds:
            return

        item_key = None
        if hasattr(self, '_name_db') and self._name_db:
            dlg = ItemSearchDialog(
                self._name_db,
                title="Add Drop Item",
                prompt="Search for an item to add to this drop set:",
                parent=self)
            if dlg.exec() == QDialog.Accepted and dlg.selected_key:
                item_key = dlg.selected_key
        else:
            key_text = self._dropset_add_key.text().strip()
            try:
                item_key = int(key_text)
            except ValueError:
                QMessageBox.warning(self, tr("Invalid Key"), tr("Enter a numeric item key."))
                return

        if item_key is None:
            return

        self._dropset_editor.add_item(ds, item_key, rate=1_000_000, min_qty=1, max_qty=1)
        self._dropset_mark_modified()
        self._dropset_refresh_items(ds)
        self._dropset_add_key.clear()

    def _dropset_remove_item(self):
        if not self._dropset_editor or self._dropset_current_key is None:
            return
        rows = sorted(set(idx.row() for idx in self._dropset_items.selectedIndexes()), reverse=True)
        if not rows:
            return

        ds = self._dropset_editor.parse_dropset(self._dropset_current_key)
        if not ds:
            return

        for row in rows:
            if row < len(ds.drops):
                ds.drops.pop(row)

        self._dropset_mark_modified()
        self._dropset_refresh_items(ds)

    def _dropset_swap_item(self):
        if not self._dropset_editor or self._dropset_current_key is None:
            return
        rows = self._dropset_items.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, tr("Swap"), tr("Select an item row first."))
            return
        row = rows[0].row()

        ds = self._dropset_editor.parse_dropset(self._dropset_current_key)
        if not ds or row >= len(ds.drops):
            return

        old_key = ds.drops[row].item_key
        old_name = self._dropset_editor.get_item_name(old_key)

        new_key = None
        if hasattr(self, '_name_db') and self._name_db:
            dlg = ItemSearchDialog(
                self._name_db,
                title="Swap Drop Item",
                prompt=f"Replace '{old_name}' ({old_key}) with:",
                parent=self)
            if dlg.exec() == QDialog.Accepted and dlg.selected_key:
                new_key = dlg.selected_key
        else:
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(
                self, "Swap Item", f"Replace {old_name} ({old_key}) with item key:")
            if ok and text.strip():
                try:
                    new_key = int(text.strip())
                except ValueError:
                    QMessageBox.warning(self, tr("Invalid"), tr("Enter a numeric item key."))
                    return

        if new_key is None:
            return

        self._dropset_editor.swap_item(ds, old_key, new_key)
        self._dropset_mark_modified()
        self._dropset_refresh_items(ds)

    def _dropset_bulk_set_rate(self):
        if not self._dropset_editor or self._dropset_current_key is None:
            return
        ds = self._dropset_editor.parse_dropset(self._dropset_current_key)
        if not ds:
            return

        pct = self._dropset_bulk_rate.value()
        rate = pct * 10000
        self._dropset_editor.boost_rates(ds, rate=rate)
        self._dropset_mark_modified()
        self._dropset_refresh_items(ds)
        name = ds.name or f"key={ds.key}"
        self._dropset_status.setText(f"Set all rates to {pct}% in {name}")

    def _dropset_bulk_set_qty(self):
        if not self._dropset_editor or self._dropset_current_key is None:
            return
        ds = self._dropset_editor.parse_dropset(self._dropset_current_key)
        if not ds:
            return

        qty = self._dropset_bulk_qty.value()
        self._dropset_editor.boost_quantities(ds, min_qty=qty, max_qty=qty)
        self._dropset_mark_modified()
        self._dropset_refresh_items(ds)
        name = ds.name or f"key={ds.key}"
        self._dropset_status.setText(f"Set all qty to x{qty} in {name}")

    def _dropset_apply_preset(self):
        if not self._dropset_editor:
            QMessageBox.warning(self, tr("DropSets"), tr("Load drop set data first."))
            return

        from dropset_editor import apply_loot_bonanza, apply_generous

        preset = self._dropset_preset_combo.currentText()
        reply = QMessageBox.question(
            self, tr("Apply Preset"),
            f"Apply '{preset}' to all 4 chest tier drop sets?\n\n"
            "This will modify Tier 1-4 chest drops.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        try:
            self._dropset_flush_dirty()

            if preset == "Loot Bonanza":
                modified = apply_loot_bonanza(self._dropset_editor)
            elif preset == "Generous":
                modified = apply_generous(self._dropset_editor)
            else:
                return

            self._dropset_editor.apply_modifications(modified)
            for ds in modified:
                self._dropset_mark_modified(key=ds.key)
            self._dropset_filter()

            if self._dropset_current_key is not None:
                self._dropset_refresh_items()

            names = ", ".join(ds.name or f"key={ds.key}" for ds in modified)
            self._dropset_status.setText(f"Applied '{preset}' to {len(modified)} sets")
            QMessageBox.information(self, tr("Preset Applied"),
                f"'{preset}' applied to:\n{names}\n\n"
                f"Use 'Export as Mod' to save, or 'Apply to Game' to deploy.")
        except Exception as e:
            log.exception("Unhandled exception")
            QMessageBox.critical(self, tr("Preset Failed"), str(e))

    def _dropset_global_boost(self, multiplier: int):
        if not self._dropset_editor:
            QMessageBox.warning(self, tr("DropSets"), tr("Load drop set data first."))
            return

        summaries = self._dropset_editor.get_all_sets_summary(named_only=True)
        count = len(summaries)

        reply = QMessageBox.question(
            self, f"Global {multiplier}x Loot",
            f"Set ALL {count} named drop sets to:\n"
            f"  - 100% drop rate on every item\n"
            f"  - x{multiplier} quantity on every item\n\n"
            f"This affects chests, factions, monsters, quests — everything.\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self._dropset_status.setText(f"Applying {multiplier}x to {count} sets...")
        QApplication.processEvents()

        modified = []
        for s in summaries:
            ds = self._dropset_editor.parse_dropset(s["key"])
            if not ds:
                continue
            self._dropset_editor.boost_rates(ds, rate=1_000_000)
            for drop in ds.drops:
                base_min = max(drop.max_amt, 1)
                base_max = max(drop.min_amt, 1)
                drop.max_amt = min(base_min * multiplier, 999999)
                drop.min_amt = min(base_max * multiplier, 999999)
            modified.append(ds)
            self._dropset_dirty_keys.add(s["key"])

        self._dropset_modified = True
        self._dropset_change_count += count
        self._dropset_changes_label.setText(f"{self._dropset_change_count} change(s)")

        if self._dropset_current_key is not None:
            self._dropset_refresh_items()

        self._dropset_status.setText(
            f"Applied {multiplier}x to {len(modified)} drop sets — 100% rates, x{multiplier} qty")
        QMessageBox.information(self, tr("Global Boost Applied"),
            f"Modified {len(modified)} drop sets:\n"
            f"  - All rates set to 100%\n"
            f"  - All quantities x{multiplier}\n\n"
            f"Use 'Export as Mod' to save.")

    def _dropset_apply_to_selected(self):
        if not self._dropset_editor or self._dropset_current_key is None:
            QMessageBox.information(self, tr("DropSets"), tr("Select a drop set first."))
            return

        ds = self._dropset_editor.parse_dropset(self._dropset_current_key)
        if not ds:
            return

        pct = self._dropset_bulk_rate.value()
        qty = self._dropset_bulk_qty.value()
        name = ds.name or f"key={ds.key}"
        self._dropset_editor.boost_rates(ds, rate=pct * 10000)
        self._dropset_editor.boost_quantities(ds, min_qty=qty, max_qty=qty)
        self._dropset_mark_modified()
        self._dropset_refresh_items(ds)
        self._dropset_status.setText(f"Boosted {name}: {pct}% rate, x{qty} qty")
        QMessageBox.information(self, tr("Applied"),
            f"Set all drops in '{name}' to {pct}% rate, x{qty} quantity.\n\n"
            f"Use 'Export as Mod' to save.")

    def _dropset_export_json(self):
        if not self._dropset_editor or not self._dropset_modified:
            QMessageBox.information(self, tr("No Changes"), tr("No modifications to export."))
            return

        self._dropset_flush_dirty()

        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Export DropSet JSON Patch", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            import json
            patch = {
                "type": "dropset_patch",
                "version": "1.0",
                "description": "DropSet modifications from CrimsonSaveEditor",
                "original_size": len(self._dropset_original_body),
                "modified_size": len(self._dropset_editor.body_bytes),
                "changes": [],
            }

            from dropset_editor import DropsetEditor
            orig = DropsetEditor()
            orig.header_bytes = self._dropset_original_header
            orig.body_bytes = bytearray(self._dropset_original_body)
            import struct
            orig.record_count = struct.unpack_from("<H", orig.header_bytes, 0)[0]
            orig.records = []
            for i in range(orig.record_count):
                off = 2 + i * 8
                key, offset = struct.unpack_from("<II", orig.header_bytes, off)
                orig.records.append((key, offset))

            for key, _ in self._dropset_editor.records:
                ds_new = self._dropset_editor.parse_dropset(key)
                ds_old = orig.parse_dropset(key)
                if not ds_new or not ds_old:
                    continue
                new_ser = self._dropset_editor._serialize_dropset(ds_new)
                old_ser = orig._serialize_dropset(ds_old)
                if new_ser != old_ser:
                    drops_data = []
                    for d in ds_new.drops:
                        drops_data.append({
                            "item_key": d.item_key,
                            "rate": d.rates,
                            "rate_pct": round(d.rates / 10000, 2),
                            "qty_min": d.max_amt,
                            "qty_max": d.min_amt,
                        })
                    patch["changes"].append({
                        "key": key,
                        "name": ds_new.name,
                        "drops": drops_data,
                    })

            with open(path, "w") as f:
                json.dump(patch, f, indent=2)

            self._dropset_status.setText(f"Exported {len(patch['changes'])} changes to {os.path.basename(path)}")
        except Exception as e:
            log.exception("Unhandled exception")
            QMessageBox.critical(self, tr("Export Failed"), str(e))

    def _dropset_export_mod(self):
        if not self._dropset_editor or not self._dropset_modified:
            QMessageBox.information(self, tr("No Changes"), tr("No modifications to export."))
            return

        self._dropset_flush_dirty()

        from PySide6.QtWidgets import QInputDialog, QFileDialog
        name, ok = QInputDialog.getText(
            self, "Mod Name", "Name for this drop table mod:",
            text="DropSet Loot Boost")
        if not ok or not name.strip():
            return
        name = name.strip()
        folder_name = name.replace(" ", "_")

        exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        default_dir = os.path.join(exe_dir, "packs")
        os.makedirs(default_dir, exist_ok=True)
        out_path = QFileDialog.getExistingDirectory(
            self, f"Choose folder to create '{folder_name}' mod in", default_dir)
        if not out_path:
            return
        out_path = os.path.join(out_path, folder_name)

        try:
            import shutil

            body_data = bytes(self._dropset_editor.body_bytes)
            header_data = self._dropset_editor.header_bytes

            if os.path.isdir(out_path):
                shutil.rmtree(out_path)

            files_dir = os.path.join(out_path, "files",
                                     "gamedata", "binary__", "client", "bin")
            os.makedirs(files_dir, exist_ok=True)
            with open(os.path.join(files_dir, "dropsetinfo.pabgb"), "wb") as f:
                f.write(body_data)
            with open(os.path.join(files_dir, "dropsetinfo.pabgh"), "wb") as f:
                f.write(header_data)

            modinfo = {
                "id": folder_name.lower(),
                "name": name,
                "version": "1.0.0",
                "game_version": "1.00.03",
                "author": "CrimsonSaveEditor",
                "description": f"DropSet mod: {name} — Modified drop tables for chests/loot",
            }
            with open(os.path.join(out_path, "modinfo.json"), "w", encoding="utf-8") as f:
                json.dump(modinfo, f, indent=2)

            gb_size = len(body_data)
            self._dropset_status.setText(
                f"Exported to {folder_name}/ ({gb_size:,} bytes)")
            QMessageBox.information(self, tr("Mod Exported"),
                f"Mod exported to:\n{out_path}\n\n"
                f"Contents:\n"
                f"  files/gamedata/binary__/client/bin/dropsetinfo.pabgb ({gb_size:,} bytes)\n"
                f"  modinfo.json\n\n"
                f"To install:\n"
                f"  Copy '{folder_name}' into your mod loader's mods/ directory")

        except Exception as e:
            log.exception("Unhandled exception")
            self._dropset_status.setText(f"Export failed: {e}")
            QMessageBox.critical(self, tr("Export Failed"), str(e))

    def _dropset_apply(self):
        if not self._dropset_editor or not self._dropset_modified:
            QMessageBox.information(self, tr("No Changes"), tr("No modifications to apply."))
            return

        self._dropset_flush_dirty()

        game_path = self._config.get("game_install_path", "")
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.critical(self, tr("Game Path"), tr("Game install path not set."))
            return

        body_data = bytes(self._dropset_editor.body_bytes)
        header_data = self._dropset_editor.header_bytes

        group_name = f"{self._dropset_overlay_spin.value():04d}"

        reply = QMessageBox.question(
            self, tr("Apply DropSet Changes"),
            f"Deploy modified drop tables to the game?\n\n"
            f"Data: pabgb ({len(body_data):,} bytes) + pabgh ({len(header_data):,} bytes)\n"
            f"Overlay: {group_name}/\n\n"
            f"Original game files are NOT modified.\n"
            f"To undo: click Restore.\n"
            f"Restart the game for changes to take effect.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self._dropset_status.setText(tr("Packing with pack_mod..."))
        QApplication.processEvents()

        try:
            import crimson_rs.pack_mod
            from crimson_rs import Compression
            import shutil
            import tempfile
            from pathlib import Path

            gp = Path(game_path)

            with tempfile.TemporaryDirectory() as tmp_dir:
                mod_dir = os.path.join(tmp_dir, "gamedata", "binary__", "client", "bin")
                os.makedirs(mod_dir, exist_ok=True)
                with open(os.path.join(mod_dir, "dropsetinfo.pabgb"), "wb") as f:
                    f.write(body_data)
                with open(os.path.join(mod_dir, "dropsetinfo.pabgh"), "wb") as f:
                    f.write(header_data)

                out_dir = os.path.join(tmp_dir, "output")
                os.makedirs(out_dir, exist_ok=True)

                crimson_rs.pack_mod.pack_mod(
                    game_dir=game_path,
                    mod_folder=tmp_dir,
                    output_dir=out_dir,
                    group_name=group_name,
                    compression=Compression.NONE,
                )

                papgt_path = gp / "meta" / "0.papgt"
                backup_path = papgt_path.with_suffix(".papgt.dropset_bak")
                if papgt_path.exists() and not backup_path.exists():
                    shutil.copy2(papgt_path, backup_path)

                dest = gp / group_name
                dest.mkdir(exist_ok=True)
                shutil.copyfile(
                    os.path.join(out_dir, group_name, "0.paz"), dest / "0.paz")
                shutil.copyfile(
                    os.path.join(out_dir, group_name, "0.pamt"), dest / "0.pamt")
                shutil.copyfile(
                    os.path.join(out_dir, "meta", "0.papgt"), papgt_path)

            paz_size = (dest / "0.paz").stat().st_size
            try:
                from shared_state import record_overlay
                record_overlay(str(gp), group_name, "DropSet edits",
                               ["dropsetinfo.pabgb", "dropsetinfo.pabgh"])
            except Exception:
                pass
            self._dropset_status.setText(f"Applied! {group_name}/ ({paz_size:,} bytes)")
            QMessageBox.information(self, tr("Success"),
                f"Deployed to {group_name}/ ({paz_size:,} bytes)\n"
                f"Restart the game for changes to take effect.\n\n"
                f"Note: If another mod also uses {group_name}/, they will conflict.\n"
                f"Use Restore to remove before applying other {group_name}/ mods.")

        except Exception as e:
            log.exception("Unhandled exception")
            self._dropset_status.setText(f"Error: {e}")
            QMessageBox.critical(self, tr("Apply Failed"), str(e))

    def _dropset_restore(self):
        game_path = self._config.get("game_install_path", "")
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.warning(self, tr("Game Path"), tr("Game install path not set."))
            return

        from pathlib import Path
        gp = Path(game_path)
        group_name = f"{self._dropset_overlay_spin.value():04d}"
        overlay = gp / group_name
        backup = gp / "meta" / "0.papgt.dropset_bak"

        if not overlay.is_dir():
            QMessageBox.information(self, tr("Nothing to Restore"),
                tr(f"No dropset mod found in {group_name}/"))
            return

        reply = QMessageBox.question(
            self, tr("Restore Original"),
            tr(f"Remove {group_name}/ overlay and restore PAPGT backup?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        try:
            import shutil
            messages = []

            if backup.exists():
                shutil.copyfile(backup, gp / "meta" / "0.papgt")
                backup.unlink()
                messages.append("Restored PAPGT from backup")
            else:
                msg = self._rebuild_papgt_fn(game_path, group_name)
                messages.append(msg)

            shutil.rmtree(overlay)
            messages.append(f"Removed {group_name}/")
            try:
                from overlay_coordinator import post_restore
                post_restore(game_path, group_name)
            except Exception:
                pass

            self._dropset_status.setText(tr("Restored"))
            QMessageBox.information(self, tr("Restored"),
                '\n'.join(messages) + "\n\nRestart the game for changes to take effect.")

        except Exception as e:
            log.exception("Unhandled exception")
            QMessageBox.critical(self, tr("Restore Failed"), str(e))


    def _dropset_save_config(self):
        if not self._dropset_editor or not self._dropset_modified:
            QMessageBox.information(self, tr("No Changes"), tr("No modifications to save."))
            return

        self._dropset_flush_dirty()

        from PySide6.QtWidgets import QInputDialog, QFileDialog
        name, ok = QInputDialog.getText(
            self, "Config Name", "Name for this config:", text="My Loot Config")
        if not ok or not name.strip():
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save DropSet Config", f"{name.strip().replace(' ', '_')}.json",
            "JSON Files (*.json)")
        if not path:
            return

        try:
            import struct
            from dropset_editor import DropsetEditor

            orig = DropsetEditor()
            orig.header_bytes = self._dropset_original_header
            orig.body_bytes = bytearray(self._dropset_original_body)
            orig.record_count = struct.unpack_from("<H", orig.header_bytes, 0)[0]
            orig.records = [(struct.unpack_from("<II", orig.header_bytes, 2+i*8))
                            for i in range(orig.record_count)]

            config = {
                "format": "crimson_dropset_config",
                "version": 1,
                "name": name.strip(),
                "description": f"{self._dropset_change_count} modification(s)",
                "author": "CrimsonSaveEditor",
                "created": __import__('datetime').date.today().isoformat(),
                "dropsets": {},
            }

            for key, _ in self._dropset_editor.records:
                ds_new = self._dropset_editor.parse_dropset(key)
                ds_old = orig.parse_dropset(key)
                if not ds_new or not ds_old:
                    continue
                new_ser = self._dropset_editor._serialize_dropset(ds_new)
                old_ser = orig._serialize_dropset(ds_old)
                if new_ser != old_ser:
                    drops = []
                    for d in ds_new.drops:
                        drops.append({
                            "item_key": d.item_key,
                            "rate_pct": round(d.rates / 10000, 2),
                            "qty_min": d.max_amt,
                            "qty_max": d.min_amt,
                        })
                    config["dropsets"][str(key)] = {
                        "name": ds_new.name,
                        "drops": drops,
                    }

            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)

            count = len(config["dropsets"])
            self._dropset_status.setText(f"Saved config: {count} drop set(s)")
            QMessageBox.information(self, tr("Config Saved"),
                f"Saved {count} modified drop set(s) to:\n{path}")

        except Exception as e:
            log.exception("Unhandled exception")
            QMessageBox.critical(self, tr("Save Failed"), str(e))

    def _dropset_load_config(self):
        if not self._dropset_editor:
            QMessageBox.warning(self, tr("DropSets"), tr("Load drop set data first."))
            return

        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Load DropSet Config", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                config = json.load(f)

            if config.get("format") != "crimson_dropset_config":
                QMessageBox.warning(self, tr("Invalid Format"),
                    "This doesn't look like a DropSet config file.\n"
                    f"Expected format: crimson_dropset_config")
                return

            dropsets = config.get("dropsets", {})
            if not dropsets:
                QMessageBox.information(self, tr("Empty"), tr("Config has no modifications."))
                return

            reply = QMessageBox.question(
                self, tr("Load Config"),
                f"Load '{config.get('name', 'config')}'?\n"
                f"Contains {len(dropsets)} modified drop set(s).\n\n"
                f"This will reset current edits and apply the config.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

            self._dropset_editor.body_bytes = bytearray(self._dropset_original_body)
            self._dropset_editor.header_bytes = self._dropset_original_header
            self._dropset_editor._parsed_sets.clear()

            applied = 0
            for key_str, entry in dropsets.items():
                key = int(key_str)
                ds = self._dropset_editor.parse_dropset(key)
                if not ds:
                    continue
                drops_cfg = entry.get("drops", [])
                for i, dcfg in enumerate(drops_cfg):
                    if i < len(ds.drops):
                        ds.drops[i].item_key = dcfg["item_key"]
                        ds.drops[i].item_key_dup = dcfg["item_key"]
                        ds.drops[i].rates = int(dcfg["rate_pct"] * 10000)
                        ds.drops[i].rates_100 = int(dcfg["rate_pct"])
                        ds.drops[i].max_amt = dcfg["qty_min"]
                        ds.drops[i].min_amt = dcfg["qty_max"]
                self._dropset_dirty_keys.add(key)
                applied += 1

            self._dropset_flush_dirty()
            self._dropset_modified = True
            self._dropset_change_count = applied
            self._dropset_changes_label.setText(f"{applied} change(s)")
            self._dropset_filter()
            if self._dropset_current_key:
                self._dropset_refresh_items()

            self._dropset_status.setText(
                f"Loaded config: {applied} drop set(s) from {os.path.basename(path)}")

        except Exception as e:
            log.exception("Unhandled exception")
            QMessageBox.critical(self, tr("Load Failed"), str(e))

    def _dropset_scan_packs(self):
        self._dropset_pack_combo.clear()
        self._dropset_packs = {}

        dirs = []
        if getattr(sys, "frozen", False):
            dirs.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "dropset_packs"))
        else:
            dirs.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0] or "."))
                                     if sys.argv and sys.argv[0] else os.getcwd(),
                                     "dropset_packs"))
        dirs.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dropset_packs"))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(os.path.join(meipass, "dropset_packs"))

        try:
            os.makedirs(dirs[0], exist_ok=True)
        except Exception:
            pass

        seen, uniq = set(), []
        for d in dirs:
            k = os.path.normcase(os.path.abspath(d)) if d else ""
            if k and k not in seen:
                seen.add(k); uniq.append(d)

        seen_files = set()
        for d in uniq:
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".json") or fn in seen_files:
                    continue
                seen_files.add(fn)
                try:
                    with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                        pack = json.load(f)
                    name = pack.get("name", fn)
                    items = pack.get("items", [])
                    self._dropset_packs[name] = pack
                    self._dropset_pack_combo.addItem(f"{name} ({len(items)} items)")
                except Exception:
                    pass

    def _dropset_add_pack(self):
        if not self._dropset_editor or self._dropset_current_key is None:
            QMessageBox.information(self, tr("DropSets"), tr("Select a drop set first."))
            return

        if not hasattr(self, '_dropset_packs') or not self._dropset_packs:
            self._dropset_scan_packs()
            if not self._dropset_packs:
                QMessageBox.information(self, tr("No Packs"),
                    tr("No drop packs found in dropset_packs/ directory."))
                return

        idx = self._dropset_pack_combo.currentIndex()
        pack_name = list(self._dropset_packs.keys())[idx] if idx >= 0 else None
        if not pack_name:
            return
        pack = self._dropset_packs[pack_name]
        items = pack.get("items", [])
        if not items:
            return

        ds = self._dropset_editor.parse_dropset(self._dropset_current_key)
        if not ds:
            return

        total_after = len(ds.drops) + len(items)
        if total_after > 48:
            reply = QMessageBox.warning(
                self, tr("Large Drop Set Warning"),
                f"Adding {len(items)} items would bring the total to {total_after} drops.\n\n"
                f"The game may not give all items from a single chest if\n"
                f"the total exceeds ~48 drops. Consider using fewer items\n"
                f"or splitting across multiple drop sets.\n\n"
                f"Continue anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return

        added = 0
        for item in items:
            rate = int(item.get("rate_pct", 100) * 10000)
            qty = item.get("qty", 1)
            self._dropset_editor.add_item(
                ds, item["item_key"], rate=rate, min_qty=qty, max_qty=qty)
            added += 1

        self._dropset_mark_modified()
        self._dropset_refresh_items(ds)
        self._dropset_status.setText(
            f"Added {added} items from '{pack_name}' to {ds.name or ds.key}")

    def _dropset_export_field_json(self) -> None:
        try:
            self._dropset_export_field_json_impl()
        except Exception as _ex:
            import traceback as _tb
            QMessageBox.critical(
                self, "Export Field JSON — Error",
                f"Error:\n{_ex}\n\n{_tb.format_exc()}")

    def _dropset_export_field_json_impl(self) -> None:
        if not self._dropset_editor:
            QMessageBox.warning(self, "Export", "Load DropSets first.")
            return
        if not self._dropset_modified:
            QMessageBox.information(self, "Export", "No modifications to export.")
            return

        # Snapshot _parsed_sets and dirty_keys BEFORE flush.
        # _dropset_flush_dirty -> apply_modifications may clear the cache.
        dirty_keys = set(self._dropset_dirty_keys)
        parsed     = getattr(self._dropset_editor, '_parsed_sets', {})
        modified_entries = {k: parsed[k] for k in dirty_keys
                            if k in parsed and parsed[k]}

        if not modified_entries:
            QMessageBox.warning(self, "Export Field JSON",
                f"No cached DropSet objects found.\n\n"
                f"Try: Load DropSets → apply preset → Export Field JSON "
                f"without clicking anything else in between.")
            return

        # Flush AFTER snapshot so body_bytes is ready for Apply to Game.
        self._dropset_flush_dirty()

        def _sd(drops):
            return [{'item_key':  getattr(d, 'item_key',  0),
                     'rates':     getattr(d, 'rates',     0),
                     'rates_100': getattr(d, 'rates_100', 0),
                     'min_amt':   getattr(d, 'min_amt',   0),
                     'max_amt':   getattr(d, 'max_amt',   0)}
                    for d in drops]

        intents = []
        for key, cur in modified_entries.items():
            name = getattr(cur, 'name', None) or str(key)
            drops = getattr(cur, 'drops', [])
            if drops:
                intents.append({'entry': name, 'key': key,
                                'field': 'drops', 'op': 'set', 'new': _sd(drops)})
            for f in ('drop_roll_count', 'drop_roll_type',
                      'drop_condition_string', 'is_blocked'):
                cv = getattr(cur, f, None)
                if cv is not None:
                    intents.append({'entry': name, 'key': key,
                                    'field': f, 'op': 'set', 'new': cv})

        if not intents:
            QMessageBox.information(self, "Export",
                "No drop data found in modified entries.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Field JSON", "DropSets.field.json",
            "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            return

        doc = {
            'modinfo': {
                'title':       'DropSets Mod',
                'version':     '1.0',
                'author':      'CrimsonGameMods DropSets',
                'description': (f'{len(intents)} field-level intent(s) '
                                f'from {len(modified_entries)} modified entries'),
                'note':        'Format 3 — field names, survives game updates',
            },
            'format':  3,
            'target':  'dropsetinfo.pabgb',
            'intents': intents,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f, indent=2, ensure_ascii=False, default=str)

        self._dropset_status.setText(
            f"Exported {len(intents)} intents "
            f"({len(modified_entries)} entries) "
            f"to {os.path.basename(path)}")
        QMessageBox.information(self, "Export Field JSON",
            f"Exported {len(intents)} field-level intents\n"
            f"from {len(modified_entries)} modified entries.\n\n"
            f"File: {path}")

    @staticmethod
    def _drop_differs(a, b) -> bool:
        return (a.item_key != b.item_key or a.rates != b.rates or
                a.rates_100 != b.rates_100 or
                a.min_amt != b.min_amt or a.max_amt != b.max_amt)

    def _dropset_import_field_json(self) -> None:
        if not hasattr(self, '_dropset_editor') or not self._dropset_editor:
            QMessageBox.warning(self, "Import", "Load DropSets first.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Import Field JSON", "",
            "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            return
        with open(path, 'r', encoding='utf-8') as f:
            doc = json.load(f)
        if doc.get('format') != 3 or not doc.get('intents'):
            QMessageBox.warning(self, "Import", "Not a valid Format 3 Field JSON file.")
            return

        sets_by_name = {}
        sets_by_key = {}
        for key, _ in self._dropset_editor.records:
            ds = self._dropset_editor.parse_dropset(key)
            if ds:
                sets_by_name[ds.name] = ds
                sets_by_key[ds.key] = ds

        applied = skipped = 0
        for intent in doc['intents']:
            target = sets_by_name.get(intent.get('entry')) or \
                     sets_by_key.get(intent.get('key'))
            if not target:
                skipped += 1
                continue
            field = intent.get('field', '')
            if intent.get('op') != 'set':
                skipped += 1
                continue
            if field in ('is_blocked', 'drop_roll_type', 'drop_roll_count'):
                setattr(target, field, intent['new'])
                applied += 1
            elif field == 'drops':
                from dropset_editor import ItemDrop
                new_drops = []
                for d in intent['new']:
                    drop = ItemDrop(
                        flag=1, item_key=d['item_key'],
                        rates=d.get('rates', 0),
                        rates_100=d.get('rates_100', 0),
                        min_amt=d.get('min_amt', 0),
                        max_amt=d.get('max_amt', 0),
                        item_key_dup=d['item_key'],
                    )
                    new_drops.append(drop)
                target.drops = new_drops
                applied += 1
            else:
                skipped += 1

        if applied:
            modified = {k: ds for k, ds in self._dropset_editor._parsed_sets.items()
                        if ds in sets_by_name.values() or ds in sets_by_key.values()}
            self._dropset_editor.apply_modifications(modified)
            self._dropset_mark_modified()

        self._dropset_status.setText(
            f"Imported {applied} intents, {skipped} skipped.")
        QMessageBox.information(self, "Import Field JSON",
            f"Applied {applied} intent(s), skipped {skipped}.\n\n"
            f"Click Apply to Game to deploy.")


class PabgbBrowserTab(QWidget):

    status_message = Signal(str)

    def __init__(self, game_path_fn=None, parent=None):
        super().__init__(parent)
        self._game_path_fn = game_path_fn
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        info = QLabel(
            "Browse any PABGB file inside the game's PAZ archives. "
            "Lists all records with name, key, and data size. Click a record to view its raw hex data."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['text_dim']}; padding: 6px; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px;"
        )
        layout.addWidget(info)

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel(tr("PABGB File:")))
        self._pabgb_file_combo = QComboBox()
        self._pabgb_file_combo.setMinimumWidth(200)
        file_row.addWidget(self._pabgb_file_combo, 1)

        scan_btn = QPushButton(tr("Scan PAZ"))
        scan_btn.setToolTip(tr("Scan PAMT index to list all PABGB files in the game"))
        scan_btn.clicked.connect(self._pabgb_scan_files)
        file_row.addWidget(scan_btn)

        load_btn = QPushButton(tr("Load File"))
        load_btn.setObjectName("accentBtn")
        load_btn.clicked.connect(self._pabgb_load_file)
        file_row.addWidget(load_btn)
        layout.addLayout(file_row)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(tr("Search Records:")))
        self._pabgb_search = QLineEdit()
        self._pabgb_search.setPlaceholderText(tr("Filter by name or key..."))
        self._pabgb_search.textChanged.connect(self._pabgb_filter_records)
        search_row.addWidget(self._pabgb_search, 1)

        self._pabgb_record_count = QLabel("")
        search_row.addWidget(self._pabgb_record_count)
        layout.addLayout(search_row)

        splitter = QSplitter(Qt.Horizontal)

        self._pabgb_record_table = QTableWidget()
        self._pabgb_record_table.setColumnCount(4)
        self._pabgb_record_table.setHorizontalHeaderLabels(["Key", "Name", "Data Size", "Offset"])
        self._pabgb_record_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._pabgb_record_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._pabgb_record_table.setSelectionMode(QAbstractItemView.SingleSelection)
        hdr = self._pabgb_record_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        self._pabgb_record_table.setColumnWidth(1, 200)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        self._pabgb_record_table.setColumnWidth(0, 90)
        self._pabgb_record_table.setColumnWidth(2, 80)
        self._pabgb_record_table.setColumnWidth(3, 80)
        self._pabgb_record_table.verticalHeader().setDefaultSectionSize(22)
        self._pabgb_record_table.selectionModel().selectionChanged.connect(self._pabgb_record_selected)
        splitter.addWidget(self._pabgb_record_table)

        hex_frame = QFrame()
        hex_layout = QVBoxLayout(hex_frame)
        hex_layout.setContentsMargins(0, 0, 0, 0)
        self._pabgb_hex_label = QLabel(tr("Select a record to view hex data"))
        self._pabgb_hex_label.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        hex_layout.addWidget(self._pabgb_hex_label)

        from PySide6.QtWidgets import QTextEdit
        self._pabgb_hex_view = QTextEdit()
        self._pabgb_hex_view.setReadOnly(True)
        self._pabgb_hex_view.setFont(QFont("Consolas", 9))
        self._pabgb_hex_view.setStyleSheet(
            f"background: {COLORS['bg']}; color: {COLORS['text']}; "
            f"border: 1px solid {COLORS['border']};"
        )
        hex_layout.addWidget(self._pabgb_hex_view)
        splitter.addWidget(hex_frame)

        splitter.setSizes([350, 500])
        layout.addWidget(splitter, 1)

        self._pabgb_status = QLabel(tr("Click 'Scan PAZ' to list PABGB files. Requires game path (set in GPatch or ItemBuffs tab)."))
        self._pabgb_status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        layout.addWidget(self._pabgb_status)


        self._pabgb_raw_data: Optional[bytes] = None
        self._pabgb_records: list = []

    def _pabgb_get_game_path(self) -> str:
        return self._game_path_fn() if callable(self._game_path_fn) else ""

    def _pabgb_scan_files(self) -> None:
        game_path = self._pabgb_get_game_path()
        if not game_path:
            QMessageBox.warning(self, tr("No Game Path"),
                                tr("Set the game install path in GPatch or ItemBuffs tab first."))
            return

        self._pabgb_status.setText(tr("Scanning PAMT index..."))
        QApplication.processEvents()

        try:
            import sys as _sys
            my_dir = os.path.dirname(os.path.abspath(__file__))
            for d in [os.path.join(my_dir, 'Includes', 'source'),
                       os.path.join(my_dir, 'Includes', 'BestCrypto')]:
                if os.path.isdir(d) and d not in _sys.path:
                    _sys.path.insert(0, d)
            from paz_parse import parse_pamt

            pabgb_files = []
            for subdir in sorted(os.listdir(game_path)):
                pamt = os.path.join(game_path, subdir, "0.pamt")
                if not os.path.isfile(pamt):
                    continue
                try:
                    entries = parse_pamt(pamt, paz_dir=os.path.join(game_path, subdir))
                    for e in entries:
                        if e.path.lower().endswith('.pabgb'):
                            pabgb_files.append((subdir, e))
                except Exception:
                    continue

            self._pabgb_file_combo.clear()
            self._pabgb_entries = {}
            for subdir, e in pabgb_files:
                label = f"{subdir}/{os.path.basename(e.path)}  ({e.orig_size:,}B)"
                self._pabgb_file_combo.addItem(label)
                self._pabgb_entries[label] = e

            self._pabgb_status.setText(f"Found {len(pabgb_files)} PABGB files across {game_path}")
        except Exception as ex:
            self._pabgb_status.setText(f"Scan failed: {ex}")

    def _pabgb_load_file(self) -> None:
        label = self._pabgb_file_combo.currentText()
        if not label or not hasattr(self, '_pabgb_entries'):
            return

        entry = self._pabgb_entries.get(label)
        if not entry:
            return

        self._pabgb_status.setText(f"Loading {label}...")
        QApplication.processEvents()

        try:
            with open(entry.paz_file, 'rb') as f:
                f.seek(entry.offset)
                compressed = f.read(entry.comp_size)

            if entry.compressed:
                import lz4.block
                self._pabgb_raw_data = lz4.block.decompress(compressed, uncompressed_size=entry.orig_size)
            else:
                self._pabgb_raw_data = compressed

            data = self._pabgb_raw_data
            self._pabgb_records = []

            if len(data) < 4:
                self._pabgb_status.setText(tr("File too small"))
                return

            record_count = struct.unpack_from('<I', data, 0)[0]

            offset = 4
            while offset < len(data) - 8:
                if offset + 8 > len(data):
                    break
                key = struct.unpack_from('<I', data, offset)[0]
                name_len = struct.unpack_from('<I', data, offset + 4)[0]

                if name_len < 1 or name_len > 200:
                    offset += 1
                    continue

                name_end = offset + 8 + name_len
                if name_end >= len(data):
                    break

                candidate = data[offset + 8:name_end]
                if not all(32 <= b < 127 for b in candidate):
                    offset += 1
                    continue

                if data[name_end] != 0:
                    offset += 1
                    continue

                name = candidate.decode('ascii')

                if not name[0:1].isalpha():
                    offset += 1
                    continue

                data_start = name_end + 1

                self._pabgb_records.append((offset, key, name, data_start))
                offset = data_start
                continue

            records_with_end = []
            for i, (off, key, name, dstart) in enumerate(self._pabgb_records):
                if i + 1 < len(self._pabgb_records):
                    dend = self._pabgb_records[i + 1][0]
                else:
                    dend = len(data)
                records_with_end.append((off, key, name, dstart, dend))
            self._pabgb_records = records_with_end

            self._pabgb_filter_records("")
            self._pabgb_status.setText(
                f"Loaded {os.path.basename(entry.path)}: {len(self._pabgb_records)} records, "
                f"{len(data):,} bytes decompressed"
            )

        except Exception as ex:
            log.exception("Unhandled exception")
            self._pabgb_status.setText(f"Load failed: {ex}")

    def _pabgb_filter_records(self, text: str = None) -> None:
        if text is None:
            text = self._pabgb_search.text()
        q = text.lower().strip()

        table = self._pabgb_record_table
        table.setSortingEnabled(False)

        filtered = []
        for off, key, name, dstart, dend in self._pabgb_records:
            if q and q not in name.lower() and q not in str(key):
                continue
            filtered.append((off, key, name, dstart, dend))

        table.setRowCount(len(filtered))
        for row, (off, key, name, dstart, dend) in enumerate(filtered):
            table.setItem(row, 0, QTableWidgetItem(str(key)))
            name_cell = QTableWidgetItem(name)
            name_cell.setData(Qt.UserRole, (off, key, name, dstart, dend))
            table.setItem(row, 1, name_cell)
            table.setItem(row, 2, QTableWidgetItem(f"{dend - dstart}"))
            table.setItem(row, 3, QTableWidgetItem(f"0x{off:X}"))

        table.setSortingEnabled(True)
        self._pabgb_record_count.setText(f"{len(filtered)}/{len(self._pabgb_records)} records")

    def _pabgb_record_selected(self) -> None:
        if self._pabgb_raw_data is None:
            return

        rows = self._pabgb_record_table.selectionModel().selectedRows()
        if not rows:
            return

        name_cell = self._pabgb_record_table.item(rows[0].row(), 1)
        if not name_cell:
            return
        rec = name_cell.data(Qt.UserRole)
        if not rec:
            return

        off, key, name, dstart, dend = rec
        data = self._pabgb_raw_data[dstart:dend]

        self._pabgb_hex_label.setText(
            f"{name} (key={key})  |  Data: {dend - dstart} bytes  |  Offset: 0x{dstart:X}"
        )
        self._pabgb_hex_label.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold; padding: 4px;")

        lines = []
        for i in range(0, min(len(data), 4096), 16):
            hex_part = ' '.join(f'{b:02x}' for b in data[i:i + 16])
            ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[i:i + 16])
            lines.append(f"{dstart + i:08X}  {hex_part:<48s}  {ascii_part}")

        if len(data) > 4096:
            lines.append(f"\n... truncated ({len(data):,} bytes total, showing first 4096)")

        self._pabgb_hex_view.setPlainText('\n'.join(lines))


class BackupTab(QWidget):

    status_message = Signal(str)
    restore_requested = Signal(str)
    tab_title_changed = Signal(str)

    def __init__(self, show_guide_fn=None, parent=None):
        super().__init__(parent)
        self._loaded_path: str = ""
        self._show_guide_fn = show_guide_fn
        self._build_ui()

    def set_loaded_path(self, path: str) -> None:
        self._loaded_path = path
        self._refresh_backups()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(make_scope_label("save"))

        info_label = QLabel(
            "Auto-backups are created every time you save. "
            "Backups are stored alongside the save file in a 'backups' folder."
        )
        info_label.setWordWrap(True)
        help_row = QHBoxLayout()
        help_row.addWidget(info_label, 1)
        help_row.addWidget(make_help_btn("backup", self._show_guide_fn))
        layout.addLayout(help_row)

        self._backup_list = QListWidget()
        layout.addWidget(self._backup_list, 1)

        btn_row = QHBoxLayout()

        refresh_btn = QPushButton(tr("Refresh"))
        refresh_btn.clicked.connect(self._refresh_backups)
        btn_row.addWidget(refresh_btn)

        restore_btn = QPushButton(tr("Restore Selected"))
        restore_btn.setObjectName("accentBtn")
        restore_btn.clicked.connect(self._restore_backup)
        btn_row.addWidget(restore_btn)

        open_folder_btn = QPushButton(tr("Open Backup Folder"))
        open_folder_btn.clicked.connect(self._open_backup_folder)
        btn_row.addWidget(open_folder_btn)

        delete_btn = QPushButton(tr("Delete Selected"))
        delete_btn.clicked.connect(self._delete_backup)
        btn_row.addWidget(delete_btn)

        reset_pristine_btn = QPushButton(tr("Set Current as PRISTINE"))
        reset_pristine_btn.setToolTip(
            "Replace the PRISTINE backup with the currently loaded save. "
            "Use this if the old PRISTINE was corrupted."
        )
        reset_pristine_btn.clicked.connect(self._reset_pristine)
        btn_row.addWidget(reset_pristine_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)


    def _get_backup_dir(self) -> str:
        if not self._loaded_path:
            return ""
        save_dir = os.path.dirname(self._loaded_path)
        return os.path.join(save_dir, "backups")

    def _refresh_backups(self) -> None:
        self._backup_list.clear()
        backup_dir = self._get_backup_dir()
        if not backup_dir or not os.path.isdir(backup_dir):
            self._backup_list.addItem("(No backups found)")
            self.tab_title_changed.emit("Backup/Restore")
            return

        backups = []
        for name in os.listdir(backup_dir):
            path = os.path.join(backup_dir, name)
            if os.path.isfile(path):
                mtime = os.path.getmtime(path)
                size = os.path.getsize(path)
                backups.append((name, path, mtime, size))

        backups.sort(key=lambda x: x[2], reverse=True)

        if not backups:
            self._backup_list.addItem("(No backups found)")
            self.tab_title_changed.emit("Backup/Restore")
            return

        for name, path, mtime, size in backups:
            dt = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            is_pristine = ".PRISTINE." in name
            tag = "  [PRISTINE]" if is_pristine else ""
            display = f"{name}  |  {dt}  |  {size:,} bytes{tag}"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, path)
            if is_pristine:
                item.setForeground(QBrush(QColor(COLORS["success"])))
            self._backup_list.addItem(item)

        self.tab_title_changed.emit(f"Backup/Restore ({len(backups)})")

    def _restore_backup(self) -> None:
        current = self._backup_list.currentItem()
        if not current:
            QMessageBox.information(self, tr("Restore"), tr("Select a backup first."))
            return

        backup_path = current.data(Qt.UserRole)
        if not backup_path or not os.path.isfile(backup_path):
            QMessageBox.warning(self, tr("Restore"), tr("Backup file not found."))
            return

        if not self._loaded_path:
            QMessageBox.warning(self, tr("Restore"), tr("No save file loaded to restore to."))
            return

        reply = QMessageBox.warning(
            self, tr("Restore Backup"),
            f"Restore backup:\n{os.path.basename(backup_path)}\n\n"
            f"This will OVERWRITE your current save:\n{self._loaded_path}\n\n"
            "This cannot be undone. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            from save_crypto import load_save_file
            try:
                test = load_save_file(backup_path)
                if not test or not test.decompressed_blob or len(test.decompressed_blob) < 100:
                    raise ValueError("Backup appears corrupted (too small or empty)")
            except Exception as ve:
                reply2 = QMessageBox.warning(
                    self, tr("Backup May Be Corrupted"),
                    f"This backup failed validation:\n{ve}\n\n"
                    f"Restoring it may result in a save that crashes the game.\n"
                    f"Restore anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply2 != QMessageBox.Yes:
                    return

            shutil.copy2(backup_path, self._loaded_path)
            self.restore_requested.emit(self._loaded_path)
            self.status_message.emit(f"Restored from backup: {os.path.basename(backup_path)}")
        except Exception as e:
            QMessageBox.critical(self, tr("Restore Error"), f"Failed to restore:\n{e}")

    def _delete_backup(self) -> None:
        current = self._backup_list.currentItem()
        if not current:
            QMessageBox.information(self, tr("Delete"), tr("Select a backup first."))
            return
        backup_path = current.data(Qt.UserRole)
        if not backup_path:
            return
        name = os.path.basename(backup_path)
        reply = QMessageBox.warning(
            self, tr("Delete Backup"),
            f"Permanently delete:\n{name}\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(backup_path)
            self._refresh_backups()
            self.status_message.emit(f"Deleted backup: {name}")
        except Exception as e:
            QMessageBox.critical(self, tr("Delete Error"), f"Failed to delete:\n{e}")

    def _reset_pristine(self) -> None:
        if not self._loaded_path:
            QMessageBox.warning(self, tr("Reset PRISTINE"), tr("No save file loaded."))
            return
        backup_dir = os.path.join(os.path.dirname(self._loaded_path), "backups")
        base = os.path.basename(self._loaded_path)
        pristine_path = os.path.join(backup_dir, f"{base}.PRISTINE.bak")

        msg = "Set the currently loaded save as the new PRISTINE backup?"
        if os.path.isfile(pristine_path):
            msg += "\n\nThis will REPLACE the existing PRISTINE backup."

        reply = QMessageBox.question(
            self, tr("Reset PRISTINE"), msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy2(self._loaded_path, pristine_path)
            self._refresh_backups()
            self.status_message.emit("PRISTINE backup updated from current save.")
        except Exception as e:
            QMessageBox.critical(self, tr("Error"), f"Failed to update PRISTINE:\n{e}")

    def _open_backup_folder(self) -> None:
        backup_dir = self._get_backup_dir()
        if not backup_dir:
            QMessageBox.information(self, tr("Backup Folder"), tr("No save file loaded."))
            return
        os.makedirs(backup_dir, exist_ok=True)
        os.startfile(backup_dir)