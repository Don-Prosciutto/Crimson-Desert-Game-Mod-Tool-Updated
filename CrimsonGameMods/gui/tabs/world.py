from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
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
from overlay_coordinator import safe_rmtree, _safe_overlay_default  # guard game data folders

log = logging.getLogger(__name__)


def _is_admin() -> bool:
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


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
            "then Export Field JSON v3 and load it in DMM. "
            "DLC items can be added to any shop (needs the DLC in game); prices come "
            "from each item's price in the shop's currency. Added offers "
            "appear in game after the shop restocks."
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

        export_v3_btn = QPushButton("Export Field JSON v3")
        export_v3_btn.setToolTip("Export store changes as DMM v3.1 field JSON (field-level, survives updates)")
        export_v3_btn.clicked.connect(self._store_export_field_json_v3)
        top_row.addWidget(export_v3_btn)

        store_apply_btn = QPushButton(tr("Apply to Game"))
        store_apply_btn.setObjectName("accentBtn")
        store_apply_btn.setToolTip(
            "Deploy modified storeinfo to the game as a PAZ overlay.\n"
            "Original game files are NOT modified. Restart game to take effect.")
        store_apply_btn.clicked.connect(self._store_apply)
        top_row.addWidget(store_apply_btn)

        store_restore_btn = QPushButton(tr("Restore"))
        store_restore_btn.setStyleSheet(button_css("neutral") + " padding: 4px 8px;")
        store_restore_btn.setToolTip("Remove the store overlay and restore vanilla storeinfo.")
        store_restore_btn.clicked.connect(self._store_restore)
        top_row.addWidget(store_restore_btn)

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

        # The "Only shops that can sell DLC items" filter is gone (2.4.8): DLC
        # items work in every shop when the offer is written like the DLC
        # writes its own (flag_a = 1, no sub_data) - see _store_dlc_offer.

        self._store_list = QTableWidget()
        self._store_list.setColumnCount(5)
        self._store_list.setHorizontalHeaderLabels(["Key", "Store Name", "Items", "Currency", "Vendor"])
        self._store_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._store_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._store_list.setSelectionMode(QAbstractItemView.SingleSelection)
        sh = self._store_list.horizontalHeader()
        sh.setSectionResizeMode(0, QHeaderView.Interactive)
        self._store_list.setColumnWidth(0, 80)
        sh.setSectionResizeMode(1, QHeaderView.Interactive)
        self._store_list.setColumnWidth(1, 280)  # room for "[DLC items OK] "
        sh.setSectionResizeMode(2, QHeaderView.Interactive)
        self._store_list.setColumnWidth(2, 60)
        sh.setSectionResizeMode(3, QHeaderView.Interactive)
        self._store_list.setColumnWidth(3, 80)
        sh.setSectionResizeMode(4, QHeaderView.Interactive)
        self._store_list.setColumnWidth(4, 140)
        self._store_list.verticalHeader().setDefaultSectionSize(24)
        self._store_list.selectionModel().selectionChanged.connect(self._store_selected)
        store_vlayout.addWidget(self._store_list)
        splitter.addWidget(store_frame)

        items_frame = QFrame()
        items_vlayout = QVBoxLayout(items_frame)
        items_vlayout.setContentsMargins(0, 0, 0, 0)
        items_vlayout.addWidget(QLabel(tr("Items in Store:")))

        self._store_items_table = QTableWidget()
        self._store_items_table.setColumnCount(9)
        self._store_items_table.setHorizontalHeaderLabels([
            "", "Key", "Item Name", "Category", "Limit",
            "Base Price", "In Game", "Buy %", "Sell %",
        ])
        # Price in the shop = item's base price (in the shop's currency)
        #   x the shop's price factor x the offer's Buy %.
        # Checked in game: Hernand fishing shop (70 %): Natural Pearl 50000 -> 350.00,
        # Ricefish 45 -> 32. The game shows amounts from 100 on as x.yz.
        for col, tip in ((5, "The item's own price in this shop's currency, shown like the game\n"
                             "shows money (from 100 on as x.yz: 50000 -> 500.00)."),
                         (6, "What the shop asks in game: base price x shop factor x Buy %.\n"
                             "From 100 on the game shows it as x.yz (e.g. 35000 -> 350.00)."),
                         (7, "Price factor of this offer for buying, in %. 100 = normal.\n"
                             "Double-click to change (e.g. 50 = half price)."),
                         (8, "Price factor of this offer for selling to the shop, in %.")):
            hi = self._store_items_table.horizontalHeaderItem(col)
            if hi is not None:
                hi.setToolTip(tip)
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
        ih.setSectionResizeMode(7, QHeaderView.Interactive)
        self._store_items_table.setColumnWidth(7, 60)
        ih.setSectionResizeMode(8, QHeaderView.Interactive)
        self._store_items_table.setColumnWidth(8, 60)
        row_h = max(ICON_SIZE + 6, 28) if self._icons_enabled else 24
        self._store_items_table.verticalHeader().setDefaultSectionSize(row_h)
        items_vlayout.addWidget(self._store_items_table)

        edit_row = QHBoxLayout()
        swap_btn = QPushButton(tr("Swap Selected"))
        swap_btn.setObjectName("accentBtn")
        swap_btn.setToolTip(tr("Replace selected item(s) with a different item from the database"))
        swap_btn.clicked.connect(self._store_swap_item)
        edit_row.addWidget(swap_btn)

        add_btn = QPushButton("Add Item")
        add_btn.setObjectName("accentBtn")
        add_btn.setToolTip(
            "Add an item as a NEW offer to this shop (nothing is replaced).\n"
            "Stock: the 'Set Limit' value.\n"
            "In game the new offer shows up after the shop restocks\n"
            "(see 'Updated in ...' at the shop; sleeping or waiting is enough).")
        add_btn.clicked.connect(self._store_add_item)
        edit_row.addWidget(add_btn)

        remove_btn = QPushButton("Remove Added")
        remove_btn.setToolTip(
            "Take offers you added with 'Add Item' out again (before exporting).\n"
            "The shop's own offers stay - to hide one of those, set its limit to 0.")
        remove_btn.clicked.connect(self._store_remove_added)
        edit_row.addWidget(remove_btn)

        dlc_vendor_btn = QPushButton("DLC Vendor...")
        dlc_vendor_btn.setToolTip(
            "Turn the selected shop into a DLC vendor: adds the DLC's weapons,\n"
            "armor, materials, blueprints ... as new offers, optionally all at\n"
            "one price in Silver. Works in every shop (needs the DLC in game).")
        dlc_vendor_btn.clicked.connect(self._store_dlc_vendor)
        edit_row.addWidget(dlc_vendor_btn)

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

        self._store_dmm = None
        self._store_modified = False
        self._store_change_count = 0


    def _store_get_item_name(self, item_key: int) -> str:
        if not hasattr(self, '_store_item_names'):
            self._store_item_names = {}
            try:
                db = get_connection()
                for row in db.execute("SELECT item_key, name FROM items"):
                    self._store_item_names[row['item_key']] = row['name']
            except Exception:
                pass
        return self._store_item_names.get(item_key, f"Item_{item_key}")

    def _store_get_stock_item_key(self, stock: dict) -> int:
        v = stock.get('value')
        if isinstance(v, dict):
            return v.get('raw_q', 0)
        return 0

    def _store_extract(self) -> None:
        game_path = self._game_path.strip()
        if not game_path:
            QMessageBox.warning(self, tr("No Game Path"), tr("Set the game install path using the Browse button at the top."))
            return

        self._store_status.setText(tr("Loading storeinfo..."))
        QApplication.processEvents()

        try:
            import crimson_rs, dmm_parser, copy
            dp = "gamedata/binary__/client/bin"
            gb = bytes(crimson_rs.extract_file(game_path, "0008", dp, "storeinfo.pabgb"))
            gh = bytes(crimson_rs.extract_file(game_path, "0008", dp, "storeinfo.pabgh"))
            self._store_dmm = dmm_parser.parse_table('store_info', gb, gh)
            self._store_dmm_vanilla = copy.deepcopy(self._store_dmm)
            self._store_gh = gh
            self._store_game_path = game_path
            self._store_load_dlc(game_path)

            log.info("Store loaded via dmm_parser: %d stores (+%d DLC)",
                     len(self._store_dmm), len(self._store_dlc))
            n_plus = sum(1 for o in self._store_origin.values() if o == "dlc_plus")
            n_only = sum(1 for o in self._store_origin.values() if o == "dlc_only")
            self._store_status.setText(
                f"Loaded {len(self._store_dmm)} stores"
                + (f" + DLC ({n_only} new, {n_plus} with a DLC version)" if self._store_dlc else ""))
            self._store_populate_list()
            self._store_modified = False
            self._store_change_count = 0
            self._store_changes_label.setText("")
        except Exception as e:
            log.error("Store extract failed: %s", e)
            log.exception("Unhandled exception")
            self._store_status.setText(f"Failed: {e}")

    # ── DLC shops ([DLC shop] / [DLC items OK]) ──────────────────────────────────────────────────────
    # Since game 2.04 the DLC ships its own shop table (dlc/<name>/storeinfo):
    # new shops, and its own version of many base-game shops. Tested in game
    # (01.11.2026): a DLC item in a base-game shop stayed an empty slot with
    # price 0 - the offer was a copy of a base-game offer (flag_a 0). Written
    # like the DLC's own offers (flag_a 1, no sub_data, slot type 0) it shows
    # with its price in any shop (13.11.2026, Alden/Store_Her_General; the
    # same way AerowynX's "Expanded Vendor Inventory - DLC Items" does it).
    # Changing the slot type makes the game crash when the shop opens.
    # The game uses the DLC version of a shop when it has one, so that is the
    # version shown and edited here. DMM applies a shop edit (by key and
    # position) to both copies.

    def _store_load_dlc(self, game_path: str) -> None:
        import copy
        self._store_dlc = []
        self._store_dlc_vanilla = []
        self._store_origin = {int(r.get('key', 0)): "base" for r in self._store_dmm}
        self._store_dlc_items = set()
        try:
            import dmm_parser
            from item_db import _dlc_tables
        except Exception as e:  # noqa: BLE001
            log.warning("DLC shops not loaded: %s", e)
            return
        base_keys = set(self._store_origin)
        for root, d, bname in _dlc_tables(dmm_parser, game_path, "0008",
                                          "storeinfo.", ".staticinfobody"):
            hname = bname[:-len(".staticinfobody")] + ".staticinfoheader"
            try:
                rows = dmm_parser.parse_table(
                    'store_info',
                    bytes(dmm_parser.extract_file(root, "0008", d, bname)),
                    bytes(dmm_parser.extract_file(root, "0008", d, hname)))
            except Exception as e:  # noqa: BLE001
                log.warning("DLC shops of %s not readable: %s", root, e)
                continue
            for r in rows:
                k = int(r.get('key', 0))
                if any(int(x.get('key', 0)) == k for x in self._store_dlc):
                    continue
                self._store_dlc.append(r)
                self._store_origin[k] = "dlc_plus" if k in base_keys else "dlc_only"
        self._store_dlc_vanilla = copy.deepcopy(self._store_dlc)
        # Items only a DLC has (category "DLC" in the item list).
        try:
            db = get_connection()
            self._store_dlc_items = {
                int(row['item_key']) for row in
                db.execute("SELECT item_key FROM items WHERE category = 'DLC'")}
        except Exception:  # noqa: BLE001
            self._store_dlc_items = set()
        log.info("DLC shops: %d (%d new, %d with a DLC version)", len(self._store_dlc),
                 sum(1 for o in self._store_origin.values() if o == "dlc_only"),
                 sum(1 for o in self._store_origin.values() if o == "dlc_plus"))

    def _store_record(self, key: int):
        """The shop record the game uses: the DLC version if there is one."""
        for s in getattr(self, '_store_dlc', None) or []:
            if s.get('key') == key:
                return s
        for s in self._store_dmm or []:
            if s.get('key') == key:
                return s
        return None

    def _store_character_name(self, key: int) -> str:
        cache = getattr(self, '_store_char_names', None)
        if cache is None:
            cache = {}
            try:
                db = get_connection()
                cache = {int(r['character_key']): r['display_name'] or r['internal_name']
                         for r in db.execute("SELECT character_key, display_name, internal_name FROM characters")}
            except Exception:  # noqa: BLE001
                pass
            self._store_char_names = cache
        return cache.get(int(key), "")

    def _store_vendor_names(self, key: int) -> list:
        """Who runs the shop (English names), so it can be found in game.
        From npcinfo.store_info -> character name, base game + DLC, game 2.04.05
        (data/store_vendors.json, made with work/dlcitems/npc/gen_vendors.py).
        The tables have no map position - only the name."""
        cache = getattr(self, '_store_vendors', None)
        if cache is None:
            cache = {}
            try:
                from data_db import _load_json_fallback
                cache = {int(k): list(v) for k, v in (_load_json_fallback('store_vendors.json') or {}).items()}
            except Exception:  # noqa: BLE001
                pass
            self._store_vendors = cache
        return cache.get(int(key or 0), [])

    def _store_can_sell_dlc(self, key: int) -> bool:
        return getattr(self, '_store_origin', {}).get(int(key), "base") != "base"

    def _store_dlc_offer(self, offer: dict, item_key: int) -> None:
        """A DLC item's offer gets flag_a = 1, as in the DLC's own shops.
        With the base-game value 0 the game shows the slot empty with
        price 0 (tested 01.11. and 13.11.2026)."""
        if int(item_key) in getattr(self, '_store_dlc_items', set()):
            offer['flag_a'] = 1

    def _store_currency_name(self, store) -> str:
        cur = int(store.get('exchange_item_info_for_buy', 0) or 0)
        if not cur:
            return "-"
        return self._store_get_item_name(cur)

    def _store_item_price(self, item_key: int, currency: int):
        """Price of an item in a currency, from the item's own price list
        (main + DLC item table). None: the item has no price in it (shows 0)."""
        cache = getattr(self, '_store_price_cache', None)
        if cache is None:
            cache = {}
            try:
                import dmm_parser
                from table_layout import INTERNAL_DIR
                from item_db import _dlc_tables
                gp = getattr(self, '_store_game_path', '') or self._game_path.strip()
                tables = [bytes(dmm_parser.extract_file(gp, "0008", INTERNAL_DIR, "iteminfo.pabgb"))]
                for root, d, n in _dlc_tables(dmm_parser, gp, "0008", "iteminfo.", ".staticinfobody"):
                    try:
                        tables.append(bytes(dmm_parser.extract_file(root, "0008", d, n)))
                    except Exception:  # noqa: BLE001
                        pass
                for raw in tables:
                    for it in dmm_parser.parse_iteminfo_from_bytes(raw):
                        k = int(it.get('key', 0))
                        if k in cache:
                            continue
                        cache[k] = {int(p.get('key', 0)): int((p.get('price') or {}).get('price', 0) or 0)
                                    for p in (it.get('price_list') or [])}
            except Exception as e:  # noqa: BLE001
                log.warning("Item prices not available: %s", e)
            self._store_price_cache = cache
        prices = cache.get(int(item_key))
        if prices is None:
            return None
        return prices.get(int(currency))

    def _store_update_change_count(self, delta: int = 1) -> None:
        self._store_change_count += delta
        self._store_modified = self._store_change_count > 0
        if self._store_change_count > 0:
            self._store_changes_label.setText(f"{self._store_change_count} change(s)")
        else:
            self._store_changes_label.setText("")

    def _store_populate_list(self, filter_text: str = "") -> None:
        if not hasattr(self, '_store_dmm') or not self._store_dmm:
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
        # Every shop once, in the version the game uses.
        stores = [self._store_record(s.get('key')) or s for s in self._store_dmm]
        stores += [s for s in getattr(self, '_store_dlc', None) or []
                   if self._store_origin.get(int(s.get('key', 0))) == "dlc_only"]
        if q:
            stores = [s for s in stores
                      if q in s.get('string_key', '').lower()
                      or q in str(s.get('key', ''))
                      or q in self._store_display_names.get(str(s.get('key', '')), "").lower()
                      or any(q in v.lower() for v in self._store_vendor_names(s.get('key', 0)))]

        table = self._store_list
        table.setSortingEnabled(False)
        table.setRowCount(len(stores))
        for row, store in enumerate(stores):
            skey = store.get('key', 0)
            sname = store.get('string_key', '')
            stock = store.get('stock_data_list', [])

            key_item = QTableWidgetItem()
            key_item.setData(Qt.DisplayRole, skey)
            key_item.setData(Qt.UserRole, skey)
            table.setItem(row, 0, key_item)

            display = self._store_display_names.get(str(skey), "")
            if not display:
                display = sname.replace("Store_", "").replace("_", " ")
            origin = getattr(self, '_store_origin', {}).get(int(skey), "base")
            tag = {"dlc_only": "[DLC shop] ", "dlc_plus": "[DLC items OK] "}.get(origin, "")
            name_item = QTableWidgetItem(tag + display)
            name_item.setToolTip(sname + {
                "dlc_only": "\nOnly exists with the DLC - can sell DLC items.",
                "dlc_plus": "\nThe DLC ships its own version of this shop - can sell DLC items.\n"
                            "Shown and edited here: the DLC version.",
            }.get(origin, "\nBase-game shop."))
            if origin != "base":
                name_item.setForeground(QBrush(QColor(COLORS['accent'])))
            table.setItem(row, 1, name_item)

            count_item = QTableWidgetItem()
            count_item.setData(Qt.DisplayRole, len(stock))
            if stock:
                count_item.setForeground(QBrush(QColor(COLORS['success'])))
            table.setItem(row, 2, count_item)

            fmt_item = QTableWidgetItem(self._store_currency_name(store))
            fmt_item.setToolTip("Items are priced in this currency (from each item's own price list).")
            table.setItem(row, 3, fmt_item)

            vendors = self._store_vendor_names(skey)
            vtext = ", ".join(vendors[:2]) + (f" +{len(vendors) - 2}" if len(vendors) > 2 else "")
            vend_item = QTableWidgetItem(vtext or "-")
            vend_item.setToolTip(("Run by: " + ", ".join(vendors) + "\nLook for this name in the town of the shop.")
                                 if vendors else "No vendor found for this shop.")
            table.setItem(row, 4, vend_item)
        table.setSortingEnabled(True)

    def _store_filter(self, text: str) -> None:
        self._store_populate_list(text)

    def _store_get_selected_store(self):
        if not hasattr(self, '_store_dmm') or not self._store_dmm:
            return None
        rows = self._store_list.selectionModel().selectedRows()
        if not rows:
            return None
        key_item = self._store_list.item(rows[0].row(), 0)
        if not key_item:
            return None
        target_key = key_item.data(Qt.UserRole)
        return self._store_record(target_key)

    def _store_selected(self, *_args) -> None:
        store = self._store_get_selected_store()
        if not store:
            return

        stock_list = store.get('stock_data_list', [])
        table = self._store_items_table
        self._store_suppress_cell_edit = True
        table.setSortingEnabled(False)
        table.setRowCount(len(stock_list))

        non_editable_flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        editable_flags = non_editable_flags | Qt.ItemIsEditable

        currency = int(store.get('exchange_item_info_for_buy', 0) or 0)
        factors = store.get('price_increase_percent_list') or []
        shop_raw = int(factors[0]) if factors and 0 < int(factors[0]) < 10**9 else 1_000_000
        shop_factor = shop_raw / 1_000_000
        vendors = self._store_vendor_names(store.get('key', 0))
        self._store_status.setText(
            f"{store.get('string_key', '')}"
            + (f" (vendor: {', '.join(vendors[:3])}{' ...' if len(vendors) > 3 else ''})" if vendors else "")
            + f": prices in {self._store_currency_name(store)}, "
            f"shop price factor {shop_factor * 100:.0f} %")

        for row, stock in enumerate(stock_list):
            item_key = self._store_get_stock_item_key(stock)
            buy_price = stock.get('raw_a', 0)
            sell_price = stock.get('raw_b', 0)
            trade_flags = stock.get('raw_c', 0)

            icon_item = QTableWidgetItem()
            if self._icons_enabled:
                px = self._icon_cache.get_pixmap(item_key)
                if px:
                    icon_item.setIcon(QIcon(px))
            icon_item.setFlags(non_editable_flags)
            table.setItem(row, 0, icon_item)

            key_cell = QTableWidgetItem()
            key_cell.setData(Qt.DisplayRole, item_key)
            key_cell.setData(Qt.UserRole, row)
            key_cell.setFlags(non_editable_flags)
            table.setItem(row, 1, key_cell)

            # Entry type: 0 = a normal buy offer (what the shop sells; the Buy
            # list shows 'buyable_stock_count' of them). Type 3 = what the shop
            # buys from you ('sellable_stock_count' of them - e.g. the fishing
            # shops' fish and creatures such as Electric Eel). Other types
            # (9 furniture pieces, 1 skills) are special. All but type 0 are
            # listed, not editable - another entry type on a normal slot crashed
            # the game in a test.
            disc = stock.get('value', {}).get('disc') if isinstance(stock.get('value'), dict) else None
            part = self._store_part(store, row)
            plain = disc == 0 and part == "buy"
            name = self._store_get_item_name(item_key)
            if disc == 3 and name.startswith("Item_"):
                name = self._store_character_name(item_key) or name
            cat = self._name_db.get_category(item_key) if hasattr(self, '_name_db') else ""
            if not plain:
                cat = "shop buys this" if part == "sell" else f"special (type {disc})"
            color = QColor(CATEGORY_COLORS.get(cat, COLORS["text"])) if plain else QColor(COLORS['text_dim'])
            name_w = QTableWidgetItem(name)
            name_w.setForeground(QBrush(color))
            name_w.setFlags(non_editable_flags)
            if not plain:
                name_w.setToolTip("Special entry (type %s), not a normal buy offer.\n"
                                  "Left as it is: Swap, Add and the limits only work on normal offers." % disc)
            table.setItem(row, 2, name_w)

            cat_w = QTableWidgetItem(cat)
            cat_w.setForeground(QBrush(color))
            cat_w.setFlags(non_editable_flags)
            table.setItem(row, 3, cat_w)

            limit_w = QTableWidgetItem()
            if trade_flags >= 0xFFFFFFFF:
                limit_w.setText("\u221e")          # 4294967295 = no limit
            else:
                limit_w.setData(Qt.DisplayRole, trade_flags)
            if trade_flags >= 999 and plain:
                limit_w.setForeground(QBrush(QColor(COLORS['success'])))
            limit_w.setFlags(editable_flags if plain else non_editable_flags)
            limit_w.setToolTip("Double-click to edit purchase limit" if plain else "")
            table.setItem(row, 4, limit_w)

            base = self._store_item_price(item_key, currency) if (currency and plain) else None
            base_w = QTableWidgetItem()
            game_w = QTableWidgetItem()
            if base is None:
                base_w.setText("\u2014" if not plain else "none")
                game_w.setText("\u2014" if not plain else "0")
                if plain:
                    game_w.setForeground(QBrush(QColor(COLORS['error'])))
                    game_w.setToolTip("No price in this shop's currency - shows as 0 in game.")
            else:
                # Same format as the game and the In Game column: 50000 -> 500.00
                base_w.setText(_store_format_price(base))
                base_w.setToolTip(f"Base price {_store_format_price(base)} "
                                  f"(raw value {base}) in this shop's currency")
                # integer maths: 45 x 70 % must give 31.5 -> 32 like the game, not 31.49999
                game_w.setText(_store_format_price(base * shop_raw * int(buy_price), 10**12))
            base_w.setFlags(non_editable_flags)
            game_w.setFlags(non_editable_flags)
            table.setItem(row, 5, base_w)
            table.setItem(row, 6, game_w)

            buy_w = QTableWidgetItem()
            buy_w.setData(Qt.DisplayRole, round(buy_price / 10_000, 2))
            buy_w.setFlags(editable_flags if plain else non_editable_flags)
            buy_w.setToolTip("Buy price factor in % (100 = normal). Double-click to edit.")
            table.setItem(row, 7, buy_w)

            sell_w = QTableWidgetItem()
            sell_w.setData(Qt.DisplayRole, round(sell_price / 10_000, 2))
            sell_w.setFlags(editable_flags if plain else non_editable_flags)
            sell_w.setToolTip("Sell price factor in % (100 = normal). Double-click to edit.")
            table.setItem(row, 8, sell_w)

        table.setSortingEnabled(True)
        self._store_suppress_cell_edit = False

    def _store_cell_changed(self, cell) -> None:
        if getattr(self, '_store_suppress_cell_edit', False):
            return
        col = cell.column()
        if col not in (4, 7, 8):
            return
        if not hasattr(self, '_store_dmm') or not self._store_dmm:
            return

        store = self._store_get_selected_store()
        if not store:
            return

        stock_list = store.get('stock_data_list', [])
        row = self._store_stock_index(cell.row())
        if row >= len(stock_list):
            return
        stock = stock_list[row]

        raw = cell.data(Qt.DisplayRole)
        try:
            if col == 4:
                new_val = int(raw)
            else:
                # Buy % / Sell % -> stored as millionths (100 % = 1000000)
                new_val = int(round(float(str(raw).replace(',', '.').rstrip('%')) * 10_000))
            if new_val < 0:
                raise ValueError
        except (TypeError, ValueError):
            self._store_suppress_cell_edit = True
            orig = {4: stock.get('raw_c', 0), 7: round(stock.get('raw_a', 0) / 10_000, 2),
                    8: round(stock.get('raw_b', 0) / 10_000, 2)}[col]
            cell.setData(Qt.DisplayRole, orig)
            self._store_suppress_cell_edit = False
            return

        if col == 4:
            if new_val > 0xFFFFFFFF:
                new_val = 0xFFFFFFFF
            stock['raw_c'] = new_val
            if new_val >= 999:
                cell.setForeground(QBrush(QColor(COLORS['success'])))
            else:
                cell.setForeground(QBrush(QColor(COLORS['text'])))
        elif col == 7:
            stock['raw_a'] = min(new_val, 0xFFFFFFFFFFFFFFFF)
        elif col == 8:
            stock['raw_b'] = min(new_val, 0xFFFFFFFFFFFFFFFF)

        self._store_update_change_count(1)
        item_key = self._store_get_stock_item_key(stock)
        col_name = {4: 'limit', 7: 'buy %', 8: 'sell %'}[col]
        if col == 7:
            # refresh the In Game column (deferred: we are inside itemChanged)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._store_selected)
        shown = new_val if col == 4 else f"{new_val / 10_000:g} %"
        msg = f"Set {col_name}={shown} on {self._store_get_item_name(item_key)}"
        self._store_status.setText(msg)
        if col == 7:
            QTimer.singleShot(0, lambda m=msg: self._store_status.setText(m))

    def _store_stock_index(self, view_row: int) -> int:
        """Position in stock_data_list for a table row. The table can be
        sorted, so the row on screen is not the position in the list; the
        position is stored on the key cell when the table is filled."""
        cell = self._store_items_table.item(view_row, 1)
        idx = cell.data(Qt.UserRole) if cell is not None else None
        return int(idx) if idx is not None else view_row

    def _store_get_selected_items(self):
        rows = set(self._store_stock_index(idx.row())
                   for idx in self._store_items_table.selectedIndexes())
        return sorted(rows)

    def _store_swap_item(self) -> None:
        if not hasattr(self, '_store_dmm') or not self._store_dmm:
            QMessageBox.warning(self, tr("Stores"), tr("Load store data first."))
            return

        store = self._store_get_selected_store()
        if not store:
            QMessageBox.warning(self, tr("Swap"), tr("Select a store first."))
            return

        sel_rows = self._store_get_selected_items()
        if not sel_rows:
            QMessageBox.information(self, tr("No Selection"), tr("Select item(s) to swap."))
            return

        stock_list = store.get('stock_data_list', [])

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
                for k, n in getattr(self, '_store_item_names', {}).items():
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

        new_name = self._store_get_item_name(new_key)

        skey = int(store.get('key', 0))
        currency = int(store.get('exchange_item_info_for_buy', 0) or 0)
        if currency:
            price = self._store_item_price(new_key, currency)
            if price is None and getattr(self, '_store_price_cache', None):
                reply = QMessageBox.question(
                    self, "No price in this shop's currency",
                    f"This shop sells for {self._store_currency_name(store)}, and "
                    f"{new_name} has no price in it - it will show as 0 in the shop.\n\n"
                    f"Swap anyway?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply != QMessageBox.Yes:
                    return

        swapped = 0
        for row in sel_rows:
            if row < len(stock_list) and self._store_is_buy_offer(store, row):
                stock = stock_list[row]
                v = stock.get('value')
                if isinstance(v, dict):
                    v['raw_q'] = new_key
                    p = v.get('payload')
                    if isinstance(p, dict):
                        p['body'] = new_key
                    self._store_dlc_offer(stock, new_key)
                    swapped += 1
                    self._store_update_change_count()

        if swapped:
            self._store_status.setText(f"Swapped {swapped} item(s) to {new_name}")
            self._store_selected()
        else:
            QMessageBox.warning(self, tr("Swap Failed"), tr("Could not swap any items."))

    @staticmethod
    def _store_part(store, index: int) -> str:
        """The stock list is [Buy list][Sell list]: the first
        'buyable_stock_count' entries are what the shop sells, the next
        'sellable_stock_count' what it buys from you (599 of 615 shops add up
        exactly). Position decides, not the entry type."""
        b = int(store.get('buyable_stock_count', 0) or 0)
        n = int(store.get('sellable_stock_count', 0) or 0)
        if index < b:
            return "buy"
        if index < b + n:
            return "sell"
        return "other"

    def _store_is_buy_offer(self, store, index: int) -> bool:
        lst = store.get('stock_data_list') or []
        if index >= len(lst):
            return False
        v = lst[index].get('value')
        return (self._store_part(store, index) == "buy"
                and isinstance(v, dict) and v.get('disc') == 0)

    def _store_vanilla_len(self, store) -> int:
        """Number of offers the shop has in the game (before any change here)."""
        key = store.get('key')
        for lst in (getattr(self, '_store_dlc_vanilla', None) or [], self._store_dmm_vanilla or []):
            for s in lst:
                if s.get('key') == key:
                    return len(s.get('stock_data_list') or [])
        return len(store.get('stock_data_list') or [])

    def _store_remove_added(self) -> None:
        store = self._store_get_selected_store()
        if not store:
            QMessageBox.warning(self, "Remove Added", tr("Select a store first."))
            return
        rows = self._store_get_selected_items()
        stock_list = store.get('stock_data_list') or []
        ids = getattr(self, '_store_added_ids', set())
        added = [r for r in rows if r < len(stock_list) and id(stock_list[r]) in ids]
        if not added:
            QMessageBox.information(
                self, "Remove Added",
                "Only offers added with 'Add Item' can be taken out here.\n\n"
                "To hide one of the shop's own offers, select it and set its limit "
                "to 0 ('Set Limit' 0, 'Apply Limit') - it disappears at the next restock.")
            return
        names = []
        price_edits = getattr(self, '_store_item_price_edits', None) or {}
        for r in sorted(added, reverse=True):
            _k = self._store_get_stock_item_key(stock_list[r])
            names.append(self._store_get_item_name(_k))
            price_edits.pop(_k, None)        # price set by DLC Vendor goes too
            ids.discard(id(stock_list[r]))
            store['buyable_stock_count'] = max(0, int(store.get('buyable_stock_count', 0) or 0) - 1)
            del stock_list[r]
        for i, s_ in enumerate(stock_list):
            s_['raw_d'] = i
        self._store_update_change_count(-len(names))
        self._store_selected()
        self._store_status.setText(f"Removed {len(names)} added offer(s): {', '.join(reversed(names))}")

    def _store_add_item(self) -> None:
        """Append an item as a new offer (DMM op array_append).

        Tested in game (01.11.2026, Hernand fishing shop + Natural Pearl): the
        original offers stay, the new one appears after the shop restocks -
        the game keeps each shop's stock per slot in the save, and a new slot
        only joins at the next restock. DMM numbers the new slot itself in
        every copy of the shop (raw_d), so other mods adding to the same shop
        do not collide.
        """
        import copy
        if not hasattr(self, '_store_dmm') or not self._store_dmm:
            QMessageBox.warning(self, tr("Stores"), tr("Load store data first."))
            return
        store = self._store_get_selected_store()
        if not store:
            QMessageBox.warning(self, "Add Item", tr("Select a store first."))
            return
        stock_list = store.setdefault('stock_data_list', [])
        # Template: a plain offer of this shop (slot type 0, the one normal
        # items use). Another slot type crashed the game in a test.
        plain = [s for i, s in enumerate(stock_list) if self._store_is_buy_offer(store, i)]
        if not plain:
            QMessageBox.warning(
                self, "Add Item",
                f"{store.get('string_key', '')} has no normal offer to copy the "
                f"layout from, so nothing can be added here safely.")
            return
        template = next((s for s in plain if not s.get('sub_data')), plain[0])

        dlg = ItemSearchDialog(
            self._name_db, title="Add Item to Shop",
            prompt="Select the item to add as a new offer:", parent=self,
        ) if hasattr(self, '_name_db') else None
        if dlg is None or dlg.exec() != QDialog.Accepted or not dlg.selected_key:
            return
        new_key = dlg.selected_key
        new_name = self._store_get_item_name(new_key)

        skey = int(store.get('key', 0))
        currency = int(store.get('exchange_item_info_for_buy', 0) or 0)
        if currency:
            price = self._store_item_price(new_key, currency)
            if price is None and getattr(self, '_store_price_cache', None):
                reply = QMessageBox.question(
                    self, "No price in this shop's currency",
                    f"This shop sells for {self._store_currency_name(store)}, and "
                    f"{new_name} has no price in it - it will show as 0 in the shop.\n\n"
                    f"Add anyway?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply != QMessageBox.Yes:
                    return

        entry = copy.deepcopy(template)
        entry['value']['raw_q'] = new_key
        if isinstance(entry['value'].get('payload'), dict):
            entry['value']['payload']['body'] = new_key
        # The list is [Buy list][Sell list]. The new offer goes to the end of
        # the Buy list, and 'buyable_stock_count' grows by one. Appended after
        # the Sell list it was in the shop's stock but not in the Buy list
        # (in game 01.11.2026), and raising the count alone pulled the first
        # Sell entry into the Buy list instead.
        pos = min(int(store.get('buyable_stock_count', 0) or 0), len(stock_list))
        entry['raw_c'] = int(self._store_limit_spin.value()) or 1
        entry['raw_e'] = max(int(s.get('raw_e', 0) or 0) for s in plain) + 1
        entry['sub_data'] = None          # no mission / trust lock
        entry['effect_list'] = []
        entry['lookup_a'] = skey
        self._store_dlc_offer(entry, new_key)
        stock_list.insert(pos, entry)
        for i, s_ in enumerate(stock_list):
            s_['raw_d'] = i               # slot number = position
        store['buyable_stock_count'] = int(store.get('buyable_stock_count', 0) or 0) + 1
        self._store_added_ids = getattr(self, '_store_added_ids', set())
        self._store_added_ids.add(id(entry))
        self._store_update_change_count()
        self._store_selected()
        self._store_status.setText(
            f"Added {new_name} (stock {entry['raw_c']}) - appears in game after the shop restocks")


    def _store_dlc_vendor(self) -> None:
        """Add the DLC's items (by group) to the selected shop, optionally all
        at one price: the items' own Silver price is set to it (iteminfo,
        so selling them is worth that too - no buy-cheap-sell-dear loop) and
        each offer's factor evens out the shop's price factor."""
        import copy
        if not getattr(self, '_store_dmm', None):
            QMessageBox.warning(self, tr("Stores"), tr("Load store data first."))
            return
        store = self._store_get_selected_store()
        if not store:
            QMessageBox.warning(self, "DLC Vendor", tr("Select a store first."))
            return
        skey = int(store.get('key', 0))
        sname = store.get('string_key', '')
        stock_list = store.setdefault('stock_data_list', [])
        plain = [s_ for i, s_ in enumerate(stock_list) if self._store_is_buy_offer(store, i)]
        if not plain:
            QMessageBox.warning(self, "DLC Vendor",
                                f"{sname} has no normal offer to copy the layout from.")
            return
        template = next((s_ for s_ in plain if not s_.get('sub_data')), plain[0])

        import dlc_vendor as dv
        if getattr(self, '_store_dlc_vendor_items', None) is None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                gp = getattr(self, '_store_game_path', '') or self._game_path.strip()
                self._store_dlc_vendor_items = dv.dlc_items(gp)
            except Exception as e:  # noqa: BLE001
                self._store_dlc_vendor_items = None
                QApplication.restoreOverrideCursor()
                QMessageBox.critical(self, "DLC Vendor", f"DLC items not readable:\n{e}")
                return
            QApplication.restoreOverrideCursor()
        groups = dv.grouped(self._store_dlc_vendor_items)
        have = {self._store_get_stock_item_key(s_) for s_ in stock_list}
        currency = int(store.get('exchange_item_info_for_buy', 0) or 0)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"DLC Vendor - {sname}")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Add these DLC items as new offers (items the shop "
                             "already has are skipped):"))
        boxes = {}
        for gid, label in dv.GROUPS:
            n = sum(1 for it in groups[gid] if int(it['key']) not in have)
            cb = QCheckBox(f"{label} ({n})")
            cb.setChecked(n > 0)
            cb.setEnabled(n > 0)
            boxes[gid] = cb
            lay.addWidget(cb)
        price_row = QHBoxLayout()
        price_cb = QCheckBox("Everything costs")
        price_cb.setChecked(currency == dv.SILVER)
        price_cb.setEnabled(currency == dv.SILVER)
        price_spin = QSpinBox()
        price_spin.setRange(1, 1_000_000)
        price_spin.setValue(10)
        price_spin.setSuffix(" Silver")
        price_row.addWidget(price_cb)
        price_row.addWidget(price_spin)
        price_row.addStretch()
        lay.addLayout(price_row)
        hint = QLabel(
            "Sets each item's own Silver price so this shop shows exactly that\n"
            "(no discount label); other vendors pay a bit less for it.\n"
            "Stock per offer: the 'Set Limit' value."
            if currency == dv.SILVER else
            "This shop does not sell for Silver - the items keep their own prices.")
        hint.setStyleSheet(f"color: {COLORS['text_dim']};")
        lay.addWidget(hint)
        btns = QHBoxLayout()
        ok_b = QPushButton("Add")
        ok_b.setObjectName("accentBtn")
        cancel_b = QPushButton("Cancel")
        ok_b.clicked.connect(dlg.accept)
        cancel_b.clicked.connect(dlg.reject)
        btns.addStretch()
        btns.addWidget(ok_b)
        btns.addWidget(cancel_b)
        lay.addLayout(btns)
        if dlg.exec() != QDialog.Accepted:
            return

        chosen = [it for gid, _ in dv.GROUPS if boxes[gid].isChecked()
                  for it in groups[gid] if int(it['key']) not in have]
        if not chosen:
            return
        set_price = price_cb.isChecked() and currency == dv.SILVER
        target_raw = int(price_spin.value()) * 100       # 10 Silver -> 1000 (shown 10.00)
        factors = store.get('price_increase_percent_list') or []
        shop_raw = int(factors[0]) if factors and 0 < int(factors[0]) < 10**9 else 1_000_000
        # The shop shows item price x shop factor (offer factor raw_a 1.0).
        # Changing raw_a shows the price with a discount label (e.g. "-18 %",
        # tested 03.11.2026); so the offer keeps 1.0 and the item's own price
        # is set to target / shop factor instead (13.11.2026).
        item_raw = max(1, int(round(target_raw * 1_000_000 / shop_raw)))

        edits = getattr(self, '_store_item_price_edits', None)
        if edits is None:
            edits = self._store_item_price_edits = {}
        cache = getattr(self, '_store_price_cache', None)
        pos = min(int(store.get('buyable_stock_count', 0) or 0), len(stock_list))
        next_e = max(int(s_.get('raw_e', 0) or 0) for s_ in plain) + 1
        limit = int(self._store_limit_spin.value()) or 1
        self._store_added_ids = getattr(self, '_store_added_ids', set())
        for it in chosen:
            k = int(it['key'])
            entry = copy.deepcopy(template)
            entry['value']['raw_q'] = k
            if isinstance(entry['value'].get('payload'), dict):
                entry['value']['payload']['body'] = k
            entry['raw_c'] = limit
            entry['raw_e'] = next_e
            next_e += 1
            entry['sub_data'] = None
            entry['effect_list'] = []
            entry['lookup_a'] = skey
            self._store_dlc_offer(entry, k)
            stock_list.insert(pos, entry)
            pos += 1
            self._store_added_ids.add(id(entry))
            if set_price:
                edits[k] = {'entry': it.get('string_key', ''),
                            'price_list': dv.price_list_with(it, dv.SILVER, item_raw)}
                if isinstance(cache, dict):
                    cache.setdefault(k, {})[dv.SILVER] = item_raw
        for i, s_ in enumerate(stock_list):
            s_['raw_d'] = i
        store['buyable_stock_count'] = int(store.get('buyable_stock_count', 0) or 0) + len(chosen)
        self._store_update_change_count(len(chosen))
        self._store_selected()
        self._store_status.setText(
            f"DLC Vendor: added {len(chosen)} offers to {sname}"
            + (f", all at {price_spin.value()} Silver" if set_price else "")
            + " - appear in game after the shop restocks. Export Field JSON v3 to save.")

    def _store_set_limit(self) -> None:
        if not hasattr(self, '_store_dmm') or not self._store_dmm:
            return
        store = self._store_get_selected_store()
        if not store:
            return

        stock_list = store.get('stock_data_list', [])
        sel_rows = self._store_get_selected_items()
        if not sel_rows:
            QMessageBox.information(self, tr("Set Limit"), tr("Select item(s) first."))
            return

        new_limit = self._store_limit_spin.value()
        changed = 0
        for row in sel_rows:
            if row < len(stock_list) and self._store_is_buy_offer(store, row):
                stock_list[row]['raw_c'] = new_limit
                changed += 1

        if changed:
            self._store_update_change_count(changed)
            self._store_status.setText(f"Set limit={new_limit} on {changed} item(s)")
            self._store_selected()

    def _store_set_all_limits(self) -> None:
        store = self._store_get_selected_store()
        stock_list = store.get('stock_data_list', []) if store else []
        if not stock_list:
            QMessageBox.information(self, tr("Set All Limits"), tr("Select a store with items first."))
            return

        new_limit = self._store_limit_spin.value()
        sname = store.get('string_key', '')
        reply = QMessageBox.question(
            self, tr("Set All Limits"),
            f"Set purchase limit to {new_limit} for ALL {len(stock_list)} items in {sname}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # Only normal buy offers - the other entry types (creatures, furniture,
        # skills) keep their own value (often "no limit").
        plain = [st for i, st in enumerate(stock_list) if self._store_is_buy_offer(store, i)]
        for stock in plain:
            stock['raw_c'] = new_limit

        self._store_update_change_count(len(plain))
        self._store_status.setText(f"Set limit={new_limit} on all {len(plain)} offers")
        self._store_selected()

    def _store_import_json(self) -> None:
        if not hasattr(self, '_store_dmm') or not self._store_dmm:
            QMessageBox.warning(self, tr("Import"), tr("Load store data first."))
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Import JSON Vendor Patch", "",
            "JSON Files (*.json *.field.json);;All Files (*)")
        if not path:
            return

        try:
            import dmm_parser
            with open(path, 'r', encoding='utf-8') as f:
                patch_data = json.load(f)

            applied = 0
            skipped = 0
            mod_name = (patch_data.get('modinfo', {}).get('title')
                        or patch_data.get('name')
                        or os.path.basename(path))

            intents = []
            if patch_data.get('format') == 3:
                for t in patch_data.get('targets', []):
                    if 'storeinfo' in t.get('file', ''):
                        intents.extend(t.get('intents', []))
                if not intents:
                    intents = patch_data.get('intents', [])

            if intents:
                dmm_by_key = {it['key']: it for it in self._store_dmm}
                for intent in intents:
                    key = intent.get('key')
                    field = intent.get('field', '')
                    new_val = intent.get('new')
                    target = dmm_by_key.get(key)
                    if not target:
                        skipped += 1
                        continue
                    if field and new_val is not None:
                        target[field] = new_val
                        applied += 1
                    else:
                        skipped += 1
            else:
                body = bytearray(dmm_parser.serialize_table('store_info', self._store_dmm))
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
                        else:
                            skipped += 1
                self._store_dmm = dmm_parser.parse_table('store_info', bytes(body), self._store_gh)

            self._store_modified = True
            self._store_update_change_count(applied)
            self._store_populate_list(self._store_search.text())
            self._store_selected()

            self._store_status.setText(f"Imported '{mod_name}': {applied} applied, {skipped} skipped")
            QMessageBox.information(self, tr("Import Complete"),
                f"Mod: {mod_name}\n"
                f"Applied: {applied}\n"
                f"Skipped: {skipped}")

        except Exception as e:
            QMessageBox.critical(self, tr("Import Error"), str(e))


    def _store_build_changes(self, original: bytes, current: bytes) -> list:
        changes = []
        i = 0
        while i < min(len(current), len(original)):
            if current[i] != original[i]:
                start = i
                while i < min(len(current), len(original)) and current[i] != original[i]:
                    i += 1
                changes.append({
                    "offset": start,
                    "label": f"Offset 0x{start:X}",
                    "original": original[start:i].hex(),
                    "patched": current[start:i].hex(),
                })
            else:
                i += 1
        return changes

    def _store_export_json(self) -> None:
        if not hasattr(self, '_store_dmm') or not self._store_dmm:
            QMessageBox.warning(self, tr("Export"), tr("Load store data first."))
            return
        if not hasattr(self, '_store_dmm_vanilla'):
            QMessageBox.warning(self, tr("Export"), tr("No original data to diff against."))
            return

        import dmm_parser
        current = dmm_parser.serialize_table('store_info', self._store_dmm)
        original = dmm_parser.serialize_table('store_info', self._store_dmm_vanilla)

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
        if not hasattr(self, '_store_dmm') or not self._store_dmm:
            QMessageBox.warning(self, tr("Stores"), tr("Load store data first."))
            return

        if not self._store_modified:
            QMessageBox.information(self, tr("No Changes"), tr("No modifications to apply."))
            return

        game_path = getattr(self, '_store_game_path', '') or self._game_path.strip()
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.critical(self, tr("Invalid Game Path"),
                f"Game path not found:\n{game_path}\n\n"
                "Set the correct path using the Browse button at the top.")
            return

        from gui.utils import resolve_overlay_group
        requested = self._store_overlay_spin.value()
        group_num = resolve_overlay_group(game_path, requested, "Stores", parent=self)
        if group_num is None:
            return
        if group_num != requested:
            self._store_overlay_spin.setValue(group_num)

        import dmm_parser
        body_data = dmm_parser.serialize_table('store_info', self._store_dmm)
        header_data = self._store_gh

        store_dir = f"{group_num:04d}"
        reply = QMessageBox.question(
            self, tr("Apply Store Changes"),
            f"Pack modified storeinfo into {store_dir}/ override directory?\n\n"
            f"Data: pabgb={len(body_data):,} bytes, pabgh={len(header_data):,} bytes\n\n"
            f"TIP: Use 'Export Field JSON v3' to get a DMM-compatible mod file instead.\n\n"
            f"Uses PackGroupBuilder overlay.\n"
            f"Original 0008/0.paz is NOT modified.\n"
            f"To undo: click Restore Original.\n\n"
            f"The game must be restarted for changes to take effect.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._store_status.setText(tr("Packing overlay..."))
        QApplication.processEvents()

        try:
            import crimson_rs
            import shutil
            import tempfile

            INTERNAL_DIR = "gamedata/binary__/client/bin"

            with tempfile.TemporaryDirectory() as tmp_dir:
                group_dir = os.path.join(tmp_dir, store_dir)
                builder = crimson_rs.PackGroupBuilder(
                    group_dir, crimson_rs.Compression.NONE,
                    crimson_rs.Crypto.NONE)
                builder.add_file(INTERNAL_DIR, "storeinfo.pabgb", body_data)
                builder.add_file(INTERNAL_DIR, "storeinfo.pabgh", header_data)
                pamt_bytes = bytes(builder.finish())
                pamt_checksum = crimson_rs.parse_pamt_bytes(pamt_bytes)["checksum"]

                papgt_path = os.path.join(game_path, "meta", "0.papgt")
                papgt_backup = papgt_path + ".store_sebak"
                if os.path.isfile(papgt_path) and not os.path.isfile(papgt_backup):
                    shutil.copy2(papgt_path, papgt_backup)

                game_mod = os.path.join(game_path, store_dir)
                if os.path.isdir(game_mod):
                    safe_rmtree(game_mod)
                os.makedirs(game_mod, exist_ok=True)
                for fn in os.listdir(group_dir):
                    shutil.copy2(os.path.join(group_dir, fn),
                                 os.path.join(game_mod, fn))

                papgt = crimson_rs.parse_papgt_file(papgt_path)
                papgt["entries"] = [e for e in papgt["entries"]
                                    if e.get("group_name") != store_dir]
                papgt = crimson_rs.add_papgt_entry(
                    papgt, store_dir, pamt_checksum, 0, 16383)
                crimson_rs.write_papgt_file(papgt, papgt_path)

                with open(os.path.join(game_mod, ".se_storemod"), "w") as mf:
                    mf.write("Created by CrimsonSaveEditor Stores tab\n")

            paz_size = os.path.getsize(os.path.join(game_mod, "0.paz"))

            papgt_verify = ""
            try:
                import crimson_rs as _crs
                papgt_check = _crs.parse_papgt_file(papgt_path)
                overlay_entries = [e['group_name'] for e in papgt_check['entries'] if not (str(e['group_name']).isdigit() and int(e['group_name']) <= 40)]
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
                f"Packed to {store_dir}/ ({paz_size:,} bytes)\n"
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
            safe_rmtree(game_mod)
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

    def _store_export_field_json_v3(self) -> None:
        """Export store changes as DMM v3.1 field JSON using crimson_rs."""
        if not hasattr(self, '_store_dmm') or not self._store_dmm:
            QMessageBox.warning(self, "Export Field JSON v3", "Load store data first.")
            return
        if not hasattr(self, '_store_dmm_vanilla') or not self._store_dmm_vanilla:
            QMessageBox.warning(self, "Export Field JSON v3", "No vanilla baseline. Re-load store data.")
            return
        import copy
        intents = []
        needs_dlc = False
        replaced_lists = []
        base_van = {r['key']: r for r in self._store_dmm_vanilla}
        pairs = [(rec, base_van.get(rec.get('key'))) for rec in self._store_dmm]
        dlc_van = {r['key']: r for r in getattr(self, '_store_dlc_vanilla', None) or []}
        pairs += [(rec, dlc_van.get(rec.get('key'))) for rec in getattr(self, '_store_dlc', None) or []]
        dlc_items = getattr(self, '_store_dlc_items', set())
        for rec, van in pairs:
            ikey = rec.get('key')
            skey = rec.get('string_key', '')
            if van is None:
                continue
            origin = getattr(self, '_store_origin', {}).get(int(ikey or 0), "base")
            is_dlc_version = rec is not base_van.get(ikey) and any(
                rec is x for x in getattr(self, '_store_dlc', None) or [])
            for field in rec:
                if field in ('key', 'string_key'):
                    continue
                if rec[field] != van.get(field):
                    if (field == 'stock_data_list'
                            and len(rec[field]) > len(van.get(field) or [])
                            and int(van.get('sellable_stock_count', 0) or 0) > 0):
                        # Offers inserted before the Sell list: DMM can only
                        # append, so the whole list is written (as Expanded
                        # Vendor Inventory does for its shops with a Sell list).
                        new = [{'entry': skey, 'key': ikey, 'field': field,
                                'op': 'set', 'new': rec[field]}]
                        replaced_lists.append(skey)
                    else:
                        new = _store_field_diff(skey, ikey, field, van.get(field), rec[field])
                    intents.extend(new)
                    # A DLC item in any shop (also a base-game one, 2.4.8):
                    # the mod needs the DLC.
                    if _store_intents_use(new, dlc_items):
                        needs_dlc = True
                    if not is_dlc_version:
                        continue
                    # DMM applies a shop edit by key and position to both copies
                    # of the shop. Players without the DLC only have the base
                    # copy: a DLC-only shop, a DLC item, or a position that holds
                    # a different item in the base copy would go wrong there.
                    if origin == "dlc_only":
                        needs_dlc = True
                    for it in new:
                        if isinstance(it.get('new'), int) and it['new'] in dlc_items:
                            needs_dlc = True
                        if isinstance(it.get('new'), list) and origin == "dlc_plus":
                            needs_dlc = True      # whole DLC list onto the base copy
                        v_add = ((it.get('value') or {}).get('value') or {}) if it.get('op') == 'array_append' else {}
                        if v_add.get('raw_q') in dlc_items:
                            needs_dlc = True
                    if field != 'stock_data_list' and origin == "dlc_plus" and \
                            (base_van.get(ikey) or {}).get(field) != van.get(field):
                        # e.g. buyable_stock_count: the base copy starts from a
                        # different value, the number written would be wrong there
                        needs_dlc = True
                    if field == 'stock_data_list':
                        b = (base_van.get(ikey) or {}).get('stock_data_list') or []
                        v = van.get('stock_data_list') or []
                        for i in range(len(v)):
                            if i < len(rec[field]) and rec[field][i] != v[i] and (
                                    i >= len(b) or b[i].get('value') != v[i].get('value')):
                                needs_dlc = True

        if not intents:
            QMessageBox.information(self, "Export Field JSON v3", "No field-level changes detected.")
            return

        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Export Field JSON v3", "Mod name:", text="My Store Mod")
        if not ok or not name.strip():
            return
        name = name.strip()
        path, _ = QFileDialog.getSaveFileName(self, "Export Field JSON v3",
            name.replace(' ', '_') + '.field.json',
            "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            return
        modinfo = {'title': name, 'version': '1.0', 'author': 'CrimsonGameMods Stores',
                   'description': f'{len(intents)} field-level intent(s)',
                   'note': 'Format 3 field JSON for storeinfo.pabgb'}
        # Item prices set by "DLC Vendor" (items only the DLC has: DMM writes
        # them into the DLC's item table).
        price_intents = [
            {'entry': e['entry'], 'key': k, 'field': 'price_list', 'op': 'set',
             'new': e['price_list']}
            for k, e in sorted((getattr(self, '_store_item_price_edits', None) or {}).items())]
        if price_intents:
            needs_dlc = True
        if needs_dlc:
            # DMM skips the mod with a clear message for players without the DLC.
            modinfo['requires_dlc'] = True
        targets = [{'file': 'storeinfo.pabgb', 'intents': intents}]
        if price_intents:
            targets.append({'file': 'iteminfo.pabgb', 'intents': price_intents})
            modinfo['description'] += f', {len(price_intents)} item price(s)'
        doc = {
            'modinfo': modinfo,
            'format': 3, 'format_minor': 1,
            'targets': targets,
        }
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=2, ensure_ascii=False, default=str)
            self._store_status.setText(f"Exported {len(intents)} field intents to {os.path.basename(path)}")
            QMessageBox.information(self, "Export Field JSON v3",
                f"Exported {len(intents)} field-level intents.\n\nFile: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))


def _store_format_price(numerator: int, denominator: int = 1) -> str:
    """A price the way the game shows it: below 100 as a whole number, from
    100 on divided by 100 with two decimals (35000 -> 350.00).
    Rounded half up like the game (45 x 70 % = 31.5 -> 32)."""
    v = (2 * int(numerator) + int(denominator)) // (2 * int(denominator))
    return str(v) if v < 100 else f"{v / 100:.2f}"


def _store_intents_use(intents, item_keys) -> bool:
    """True if any intent writes one of item_keys as an offer's item
    (raw_q / payload body, or a plain 'new' value)."""
    if not item_keys:
        return False

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("raw_q", "body") and isinstance(v, int) and v in item_keys:
                    return True
                if walk(v):
                    return True
        elif isinstance(o, list):
            return any(walk(v) for v in o)
        return False

    for it in intents:
        if isinstance(it.get('new'), int) and it['new'] in item_keys:
            return True
        if walk(it.get('new')) or walk(it.get('value')):
            return True
    return False


def _store_field_diff(entry, key, path, a, b):
    """Field intents for one changed store field, as narrow as possible.

    The export used to write the whole stock list of a shop as one change
    (stock_data_list = [... 20 entries ...]). Next to another vendor mod
    (e.g. Expanded Vendor Inventory) DMM then had two complete lists for
    the same shop, and the result mixed both. A swapped item or a changed
    limit is now exported as just that value
    (stock_data_list[3].value.raw_q, stock_data_list[3].raw_c); only a list
    that changed length is still written whole.
    """
    if a == b:
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in b:
            if a.get(k) != b.get(k):
                if k not in a:
                    return [{'entry': entry, 'key': key, 'field': path, 'op': 'set', 'new': b}]
                out.extend(_store_field_diff(entry, key, f"{path}.{k}", a.get(k), b.get(k)))
        if set(a) - set(b):
            return [{'entry': entry, 'key': key, 'field': path, 'op': 'set', 'new': b}]
        return out
    if (isinstance(a, list) and isinstance(b, list) and len(a) <= len(b)
            and all(isinstance(x, dict) for x in a + b)):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(_store_field_diff(entry, key, f"{path}[{i}]", x, y))
        # Offers added on the Stores tab: appended, never a replaced list.
        for y in b[len(a):]:
            out.append({'entry': entry, 'key': key, 'op': 'array_append',
                        'field': path, 'value': y})
        return out
    return [{'entry': entry, 'key': key, 'field': path, 'op': 'set', 'new': b}]


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
        """Return modified spawn pabgb buffers for Stacker Pull All Edits."""
        result = {}
        _PAIRS = [
            ('terrainregionautospawninfo.pabgb', '_spawn_data',          '_spawn_original'),
            ('spawningpoolautospawninfo.pabgb',  '_spawn_life_data',     '_spawn_life_original'),
            ('factionnode.pabgb',                '_spawn_fnode_ops_data','_spawn_fnode_ops_original'),
            ('factionnodespawninfo.pabgb',        '_spawn_node_data',    '_spawn_node_original'),
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
        self._spawn_overlay_spin.setValue(_safe_overlay_default(self._config.get("spawn_overlay_dir", 70), 70))
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
        spawn_field_json_btn.setStyleSheet(button_css("primary") + " font-weight: bold;")
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
        restore_btn.setToolTip(tr(""))
        restore_btn.clicked.connect(self._spawn_restore)
        header.addWidget(restore_btn)


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

        # "x Camp Min" removed (2.03.02): MinOp is not mapped in the 2.03 data,
        # the button did nothing.

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
            "STEP 3: Click 'Export Field JSON v3' and load into DMM,\n"
            "         or use 'Apply to Game' then restart to see changes.\n\n"
            "QUICK ACTIONS:\n"
            "  x Camp MaxOp — Max enemies per camp (cap: 255)\n"
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
            import dmm_parser as _dmp_spawn
            import copy as _copy_spawn

            dir_path = "gamedata/binary__/client/bin"
            body = bytes(crimson_rs.extract_file(game_path, "0008", dir_path,
                                           "terrainregionautospawninfo.pabgb"))
            schema = bytes(crimson_rs.extract_file(game_path, "0008", dir_path,
                                              "terrainregionautospawninfo.pabgh"))

            self._spawn_dmm = _dmp_spawn.parse_table('terrain_region_auto_spawn_info', body, schema)
            self._spawn_dmm_vanilla = _copy_spawn.deepcopy(self._spawn_dmm)
            # Spawn regions only the DLC has (ocean, islands). Listed as
            # "[DLC] ...", exported as Field JSON only - Apply and Export as
            # Mod write the main tables.
            self._spawn_dlc_dmm = []
            self._spawn_fnode_dlc_dmm = []
            try:
                from item_db import dlc_only_records as _dlc_recs
                self._spawn_dlc_dmm = _dlc_recs(
                    game_path, "terrainregionautospawninfo", "terrain_region_auto_spawn_info",
                    {int(r.get('key', 0)) for r in self._spawn_dmm})
            except Exception as _dlc_err:  # noqa: BLE001
                log.warning("DLC spawn regions not loaded: %s", _dlc_err)
            self._spawn_dlc_dmm_vanilla = _copy_spawn.deepcopy(self._spawn_dlc_dmm)
            _dlc_region_keys = {int(r.get('key', 0)) for r in self._spawn_dlc_dmm}

            def _rname(rec, name=None):
                n = rec.get('string_key', '') if name is None else name
                return f"[DLC] {n}" if int(rec.get('key', 0)) in _dlc_region_keys else n
            self._spawn_data = bytearray(body)
            self._spawn_original = bytes(body)
            self._spawn_schema = schema
            self._spawn_modified = False
            self._spawn_changes_label.setText("")

            elements = []

            for region in self._spawn_dmm + self._spawn_dlc_dmm:
                region_key = region.get('key', 0)
                region_name = _rname(region)
                for spawn_entry in region.get('spawn_list', []):
                    for spline in spawn_entry.get('spline_list', []):
                        for inner in spline.get('inner_list', []):
                            char_key = inner.get('raw_a', 0)
                            spawn_count = inner.get('flag_a', 0)
                            timer_ms = spline.get('raw_qword', 0)
                            elements.append({
                                'region_key': region_key,
                                'region_name': region_name,
                                'char_key': char_key,
                                'spawn_count': spawn_count,
                                'timer_ms': timer_ms,
                                'vanilla_count': spawn_count,
                                'vanilla_timer': timer_ms,
                                'inner_ref': inner,
                                'spline_ref': spline,
                                'source': 'terrain',
                            })

            self._spawn_elements = elements
            log.info("Loaded %d terrain spawn entries via dmm_parser", len(elements))

            self._spawn_char_names = {}
            try:
                char_gb = bytes(crimson_rs.extract_file(
                    game_path, "0008", dir_path, "characterinfo.pabgb"))
                char_gh = bytes(crimson_rs.extract_file(
                    game_path, "0008", dir_path, "characterinfo.pabgh"))
                char_entries = _dmp_spawn.parse_table('character_info', char_gb, char_gh)
                for ce in char_entries:
                    name = ce.get('string_key', '')
                    parts = name.rsplit('_', 1)
                    if len(parts) == 2 and parts[1].isdigit():
                        name = parts[0]
                    self._spawn_char_names[ce['key']] = name.replace('_', ' ')
                try:
                    from item_db import dlc_only_records as _dlc_recs
                    for ce in _dlc_recs(game_path, "characterinfo", "character_info",
                                        {int(c['key']) for c in char_entries}):
                        name = ce.get('string_key', '')
                        parts = name.rsplit('_', 1)
                        if len(parts) == 2 and parts[1].isdigit():
                            name = parts[0]
                        self._spawn_char_names[ce['key']] = "[DLC] " + name.replace('_', ' ')
                except Exception as _dce:  # noqa: BLE001
                    log.warning("DLC character names not loaded: %s", _dce)
                log.info("Loaded %d character names via dmm_parser", len(self._spawn_char_names))
            except Exception as _ce:
                log.warning(tr("Could not load character names: %s"), _ce)

            import ctypes as _ct_rates
            rate_count = 0
            for region in self._spawn_dmm + self._spawn_dlc_dmm:
                rkey = region.get('key', 0)
                rname = _rname(region)
                for se in region.get('spawn_list', []):
                    for sp in se.get('spline_list', []):
                        rate_u32 = sp.get('raw_g', 0)
                        rate_f = _ct_rates.c_float.from_buffer_copy(
                            _ct_rates.c_uint32(rate_u32 & 0xFFFFFFFF)).value
                        elements.append({
                            'region_key': rkey,
                            'region_name': rname,
                            'char_key': 0,
                            'spawn_count': rate_f,
                            'timer_ms': -1,
                            'source': 'rate',
                            'rate_value': rate_f,
                            'vanilla_rate': rate_f,
                            'spline_ref': sp,
                        })
                        rate_count += 1
            log.info("Loaded %d spawn rates via dmm_parser (spline.raw_g)", rate_count)

            try:
                fnode_body = bytes(crimson_rs.extract_file(
                    game_path, "0008", dir_path, "factionnode.pabgb"))
                fnode_gh = bytes(crimson_rs.extract_file(
                    game_path, "0008", dir_path, "factionnode.pabgh"))

                self._spawn_fnode_dmm = _dmp_spawn.parse_table('faction_node_info', fnode_body, fnode_gh)
                self._spawn_fnode_dmm_vanilla = _copy_spawn.deepcopy(self._spawn_fnode_dmm)
                self._spawn_fnode_ops_data = bytearray(fnode_body)
                self._spawn_fnode_ops_original = fnode_body
                self._spawn_fnode_ops_schema = fnode_gh
                try:
                    from item_db import dlc_only_records as _dlc_recs
                    self._spawn_fnode_dlc_dmm = _dlc_recs(
                        game_path, "factionnode", "faction_node_info",
                        {int(r.get('key', 0)) for r in self._spawn_fnode_dmm})
                except Exception as _dlc_err:  # noqa: BLE001
                    log.warning("DLC faction nodes not loaded: %s", _dlc_err)
                self._spawn_fnode_dlc_dmm_vanilla = _copy_spawn.deepcopy(self._spawn_fnode_dlc_dmm)
                _dlc_node_keys = {int(r.get('key', 0)) for r in self._spawn_fnode_dlc_dmm}

                fnode_ops_count = 0
                for entry in self._spawn_fnode_dmm + self._spawn_fnode_dlc_dmm:
                    node_name = entry.get('string_key', '').replace('Node_', '').replace('_', ' ')
                    if int(entry.get('key', 0)) in _dlc_node_keys:
                        node_name = f"[DLC] {node_name}"
                    fsl = entry.get('faction_schedule_list', [])
                    for si, sched in enumerate(fsl):
                        rde = sched.get('raw_data_ext', {})
                        max_op = rde.get('flag', 0)
                        sched_label = f"{node_name} [sched {si}]" if len(fsl) > 1 else node_name
                        sil = sched.get('slot_inner_list', [])
                        sub_elems = [{'count': sl.get('lookup_a', 0), 'time': sl.get('raw_a', 0),
                                      'slot_ref': sl} for sl in sil]
                        elements.append({
                            'region_key': entry.get('key', 0),
                            'region_name': sched_label,
                            'char_key': 0,
                            'spawn_count': max_op,
                            'timer_ms': 0,
                            'vanilla_count': max_op,
                            'vanilla_timer': 0,
                            'source': 'fnode_ops',
                            'sched_ref': sched,
                            'rde_ref': rde,
                            'min_op': -1,
                            'vanilla_min_op': -1,
                            'sub_elements': sub_elems,
                            'worker_count': -1,
                        })
                        fnode_ops_count += 1

                log.info("Loaded %d factionnode operator schedules via dmm_parser", fnode_ops_count)

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
            _n_dlc = len(self._spawn_dlc_dmm) + len(self._spawn_fnode_dlc_dmm)
            self._spawn_status.setText(
                f"Loaded {len(elements)} spawn definitions across {len(seen_regions)} regions"
                + (f" ({_n_dlc} from the DLC - Field JSON only)" if _n_dlc else ""))

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

        self._spawn_filtered = filtered
        self._spawn_table.setRowCount(len(filtered))
        for row, el in enumerate(filtered):
            src = el.get('source', 'terrain')
            is_terrain = src == 'terrain'

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
            item.setData(Qt.UserRole, row)
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
                orig_rate = el.get('vanilla_rate', rate_val)
                if abs(rate_val - orig_rate) > 0.001:
                    item.setBackground(QColor(20, 40, 80))
                item.setToolTip(f"Spawn rate (vanilla: {orig_rate:.2f})")
            elif is_terrain:
                item = QTableWidgetItem(str(el['spawn_count']))
                orig = el.get('vanilla_count', el['spawn_count'])
                if el['spawn_count'] != orig:
                    item.setBackground(QColor(60, 40, 20))
            elif is_fnode_ops:
                item = QTableWidgetItem(str(el['spawn_count']))
                vanilla_fo = el.get('vanilla_count', el['spawn_count'])
                if el['spawn_count'] != vanilla_fo:
                    item.setBackground(QColor(60, 30, 10))
            else:
                item = QTableWidgetItem("?")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setForeground(QColor(150, 150, 150))
            self._spawn_table.setItem(row, 5, item)

            if is_fnode_ops:
                min_op = el.get('min_op', -1)
                item = QTableWidgetItem(str(min_op))
                vanilla_min = el.get('vanilla_min_op', min_op)
                if min_op != vanilla_min:
                    item.setBackground(QColor(60, 30, 10))
            else:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setForeground(QColor(150, 150, 150))
            self._spawn_table.setItem(row, 6, item)

            if is_fnode_ops:
                sub_elems = el.get('sub_elements', [])
                parts = [str(se.get('count', 0)) for se in sub_elems]
                display = ' / '.join(parts)
                item = QTableWidgetItem(display)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setToolTip(
                    f"Per-slot operator counts\n"
                    f"Use 'Multiply Sub-Slot Counts' button to change")
            else:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._spawn_table.setItem(row, 7, item)

            if is_fnode_ops:
                item = QTableWidgetItem("—")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            else:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._spawn_table.setItem(row, 8, item)

            if is_terrain:
                item = QTableWidgetItem(str(el['timer_ms']))
                orig_t = el.get('vanilla_timer', el['timer_ms'])
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
        fidx = item0.data(Qt.UserRole)
        if fidx is None or not hasattr(self, '_spawn_filtered') or fidx >= len(self._spawn_filtered):
            return
        el = self._spawn_filtered[fidx]
        src = el.get('source', '')
        if src not in ('terrain', 'fnode_ops', 'rate'):
            return

        cell = self._spawn_table.item(row, col)
        if not cell:
            return

        if src == 'rate' and col == 5:
            try:
                new_val = float(cell.text())
            except ValueError:
                return
            new_val = max(0.01, min(new_val, 20.0))
            sp = el.get('spline_ref')
            if sp is not None:
                import ctypes as _ct_re
                sp['raw_g'] = _ct_re.c_uint32.from_buffer_copy(_ct_re.c_float(new_val)).value
            el['spawn_count'] = new_val
            el['rate_value'] = new_val
            self._spawn_modified = True
            self._spawn_update_changes()
            return

        if src == 'fnode_ops' and col == 5:
            try:
                new_val = int(cell.text())
            except ValueError:
                return
            new_val = max(1, min(new_val, 255))
            rde = el.get('rde_ref')
            if rde is not None:
                rde['flag'] = new_val
            el['spawn_count'] = new_val
            self._spawn_modified = True
            self._spawn_update_changes()
            return

        if src == 'fnode_ops' and col == 6:
            return

        if src == 'fnode_ops' and col == 8:
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
            inner = el.get('inner_ref')
            if inner is not None:
                inner['flag_a'] = new_val
            el['spawn_count'] = new_val
        elif col == 9:
            spline = el.get('spline_ref')
            if spline is not None:
                spline['raw_qword'] = new_val
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
                fidx = item0.data(Qt.UserRole)
                if fidx is None or not hasattr(self, '_spawn_filtered') or fidx >= len(self._spawn_filtered):
                    continue
                el = self._spawn_filtered[fidx]
                if not el:
                    continue
                src = el.get('source', '')
                if src == 'terrain':
                    iv = min(int(val), 100)
                    inner = el.get('inner_ref')
                    if inner is not None:
                        inner['flag_a'] = iv
                    el['spawn_count'] = iv
                    changed += 1
                elif src == 'fnode_ops':
                    iv = max(1, min(int(val), 255))
                    rde = el.get('rde_ref')
                    if rde is not None:
                        rde['flag'] = iv
                    el['spawn_count'] = iv
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
                # the cell holds the position in _spawn_filtered, not the row
                fidx = item0.data(Qt.UserRole)
                if fidx is None or fidx >= len(getattr(self, '_spawn_filtered', [])):
                    continue
                el = self._spawn_filtered[fidx]
                if not el or el.get('source') != 'terrain':
                    continue
                spline = el.get('spline_ref')
                if spline is not None:
                    spline['raw_qword'] = val
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
                fidx = item0.data(Qt.UserRole)
                if fidx is None or not hasattr(self, '_spawn_filtered') or fidx >= len(self._spawn_filtered):
                    continue
                el = self._spawn_filtered[fidx]
                if not el:
                    continue
                src = el.get('source', '')
                if src == 'terrain':
                    new_val = min(int(el['spawn_count'] * val), 100)
                    inner = el.get('inner_ref')
                    if inner is not None:
                        inner['flag_a'] = new_val
                    el['spawn_count'] = new_val
                    changed += 1
                elif src == 'fnode_ops':
                    new_val = max(1, min(int(el['spawn_count'] * val), 255))
                    rde = el.get('rde_ref')
                    if rde is not None:
                        rde['flag'] = new_val
                    el['spawn_count'] = new_val
                    changed += 1
            if changed:
                self._spawn_modified = True
                self._spawn_filter()
                self._spawn_update_changes()
                self._spawn_status.setText(f"Multiplied {changed} entries by {val}x")

    def _spawn_update_changes(self):
        if not self._spawn_elements:
            return
        changes = 0
        for el in self._spawn_elements:
            src = el.get('source', '')
            if src == 'terrain':
                if el['spawn_count'] != el.get('vanilla_count', el['spawn_count']):
                    changes += 1
                elif el['timer_ms'] != el.get('vanilla_timer', el['timer_ms']):
                    changes += 1
            elif src == 'fnode_ops':
                if el['spawn_count'] != el.get('vanilla_count', el['spawn_count']):
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
            if src == 'terrain':
                old = el['spawn_count']
                new_val = min(int(old * mult), 100)
                if new_val != old:
                    inner = el.get('inner_ref')
                    if inner is not None:
                        inner['flag_a'] = new_val
                    el['spawn_count'] = new_val
                    count += 1
            elif src == 'fnode_ops':
                old = el['spawn_count']
                new_val = max(1, min(int(old * mult), 255))
                if new_val != old:
                    rde = el.get('rde_ref')
                    if rde is not None:
                        rde['flag'] = new_val
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
                slot = se.get('slot_ref')
                if slot is None:
                    continue
                old = se['count']
                if old > 20:
                    continue
                if old == 0 and fill_value > 0:
                    new_val = int(min(fill_value * mult, 255))
                    slot['lookup_a'] = new_val
                    se['count'] = new_val
                    dormant_filled += 1
                    count_changed += 1
                elif old > 0:
                    new_val = int(min(old * mult, 255))
                    slot['lookup_a'] = new_val
                    se['count'] = new_val
                    count_changed += 1

        self._spawn_modified = True
        self._spawn_filter()
        self._spawn_update_changes()
        self._spawn_status.setText(
            f"Multiplied {count_changed} sub-slot counts by {mult}x "
            f"({dormant_filled} dormant slots filled)")

    def _spawn_halve_sub_times(self):
        if not self._spawn_elements:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        count = 0
        for el in self._spawn_elements:
            if el.get('source') != 'fnode_ops':
                continue
            for se in el.get('sub_elements', []):
                old = se.get('time', 0)
                if old <= 0:
                    continue
                new_val = max(old // 2, 10)
                if new_val != old:
                    slot = se.get('slot_ref')
                    if slot is not None:
                        slot['raw_a'] = new_val
                    se['time'] = new_val
                    count += 1

        self._spawn_modified = True
        self._spawn_filter()
        self._spawn_update_changes()
        self._spawn_status.setText(f"Halved {count} sub-slot time values")


    def _spawn_increase_all_smart(self):
        if not self._spawn_data:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        mult = self._spawn_multiplier.value()
        results = []

        camp_max = 0
        for el in self._spawn_elements:
            if el.get('source') != 'fnode_ops': continue
            old = el.get('spawn_count', 0)
            new_val = max(1, min(int(old * mult), 255))
            if new_val != old:
                rde = el.get('rde_ref')
                if rde is not None:
                    rde['flag'] = new_val
                el['spawn_count'] = new_val
                camp_max += 1
        if camp_max: results.append(f"{camp_max} camp MaxOp x{mult}")

        if hasattr(self, '_spawn_dmm') and self._spawn_dmm:
            try:
                def _u32f(v):
                    import ctypes as _ct
                    return _ct.c_float.from_buffer_copy(_ct.c_uint32(v & 0xFFFFFFFF)).value
                def _f32u(f):
                    import ctypes as _ct
                    return _ct.c_uint32.from_buffer_copy(_ct.c_float(f)).value

                limit_c = mps_c = dist_c = safety_c = 0
                for region in self._spawn_dmm:
                    for se in region.get('spawn_list', []):
                        if se.get('raw_a', 0) == 1:
                            se['raw_a'] = 0
                            limit_c += 1
                        if se.get('raw_b', 0) == 1:
                            se['raw_b'] = 0
                            mps_c += 1
                        dist_f = _u32f(se.get('raw_e', 0))
                        if 10.0 < dist_f < 10000.0:
                            se['raw_e'] = _f32u(min(dist_f * 2, 2000.0))
                            dist_c += 1
                        safe_f = _u32f(se.get('raw_f', 0))
                        if safe_f > 20.0:
                            se['raw_f'] = _f32u(safe_f / 2)
                            safety_c += 1

                if limit_c: results.append(f"{limit_c} spawn caps removed")
                if mps_c: results.append(f"{mps_c} spawn spacing loosened")
                if dist_c: results.append(f"{dist_c} spawn distance x2")
                if safety_c: results.append(f"{safety_c} safety dist halved")
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
            import dmm_parser as _dmp_life
            import copy as _copy_life
            dir_path = "gamedata/binary__/client/bin"

            life_body = bytes(crimson_rs.extract_file(
                game_path, "0008", dir_path, "spawningpoolautospawninfo.pabgb"))
            life_gh = bytes(crimson_rs.extract_file(
                game_path, "0008", dir_path, "spawningpoolautospawninfo.pabgh"))

            self._spawn_life_dmm = _dmp_life.parse_table(
                'spawning_pool_auto_spawn_info', life_body, life_gh)
            self._spawn_life_dmm_vanilla = _copy_life.deepcopy(self._spawn_life_dmm)
            self._spawn_life_data = bytearray(life_body)
            self._spawn_life_original = life_body
            self._spawn_life_schema = life_gh

            log.info("Loaded %d spawning pool entries via dmm_parser", len(self._spawn_life_dmm))

            def _u32f(v):
                import ctypes as _ct
                return _ct.c_float.from_buffer_copy(_ct.c_uint32(v & 0xFFFFFFFF)).value
            def _f32u(f):
                import ctypes as _ct
                return _ct.c_uint32.from_buffer_copy(_ct.c_float(f)).value

            limit_c = mps_c = safety_c = dist_c = 0
            for pool in self._spawn_life_dmm:
                for se in pool.get('spawn_list', []):
                    if se.get('raw_a', 0) == 1:
                        se['raw_a'] = 0
                        limit_c += 1
                    if se.get('raw_b', 0) == 1:
                        se['raw_b'] = 0
                        mps_c += 1
                    dist_f = _u32f(se.get('raw_e', 0))
                    if 10.0 < dist_f < 10000.0:
                        se['raw_e'] = _f32u(min(dist_f * 2, 2000.0))
                        dist_c += 1
                    safe_f = _u32f(se.get('raw_f', 0))
                    if safe_f > 5.0:
                        se['raw_f'] = _f32u(safe_f / 2)
                        safety_c += 1

            self._spawn_life_data = bytearray(_dmp_life.serialize_table(
                'spawning_pool_auto_spawn_info', self._spawn_life_dmm))

            self._spawn_modified = True
            results = []
            if limit_c: results.append(f"{limit_c} caps removed")
            if mps_c: results.append(f"{mps_c} spacing loosened")
            if dist_c: results.append(f"{dist_c} distances x2")
            if safety_c: results.append(f"{safety_c} safety halved")

            summary = ", ".join(results) if results else "no changes"
            self._spawn_status.setText(
                f"Ambient life: {len(self._spawn_life_dmm)} pools modified ({summary})")

            QMessageBox.information(self, tr("Ambient Life Increased"),
                f"Modified {len(self._spawn_life_dmm)} spawning pools:\n\n"
                f"  {chr(10).join(results)}\n\n"
                f"Serialized via dmm_parser — update-proof.")

        except Exception as e:
            log.exception("Unhandled exception")
            self._spawn_status.setText(f"Error: {e}")
            QMessageBox.critical(self, tr("Error"), f"Failed to load ambient life data:\n{e}")

    def _spawn_multiply_rates(self):
        if not hasattr(self, '_spawn_dmm') or not self._spawn_dmm:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        mult = self._spawn_multiplier.value()
        try:
            import ctypes as _ct_mr
            count = 0
            for region in self._spawn_dmm:
                for se in region.get('spawn_list', []):
                    for sp in se.get('spline_list', []):
                        rate_u32 = sp.get('raw_g', 0)
                        current = _ct_mr.c_float.from_buffer_copy(
                            _ct_mr.c_uint32(rate_u32 & 0xFFFFFFFF)).value
                        base = current if current > 0.001 else 1.0
                        new_val = min(base * mult, 20.0)
                        sp['raw_g'] = _ct_mr.c_uint32.from_buffer_copy(
                            _ct_mr.c_float(new_val)).value
                        count += 1
            self._spawn_modified = True
            self._spawn_update_changes()
            self._spawn_status.setText(f"Multiplied {count} spawn rates by {mult}x via dmm_parser")
        except Exception as e:
            log.exception("Unhandled exception")
            QMessageBox.critical(self, tr("SpawnEdit"), f"Failed to multiply rates: {e}")

    def _spawn_halve_timers(self):
        if not self._spawn_data or not self._spawn_elements:
            QMessageBox.information(self, tr("SpawnEdit"), tr("Load spawn data first."))
            return

        count = 0
        for el in self._spawn_elements:
            if el.get('source') != 'terrain':
                continue
            old = el['timer_ms']
            new_val = max(old // 2, 50)
            if new_val != old:
                spline = el.get('spline_ref')
                if spline is not None:
                    spline['raw_qword'] = new_val
                el['timer_ms'] = new_val
                count += 1

        self._spawn_modified = True
        self._spawn_filter()
        self._spawn_update_changes()
        self._spawn_status.setText(f"Halved {count} respawn timers")

    def _spawn_reset(self):
        import copy as _copy_reset
        if hasattr(self, '_spawn_dmm_vanilla') and self._spawn_dmm_vanilla:
            self._spawn_dmm = _copy_reset.deepcopy(self._spawn_dmm_vanilla)
        for _attr in ('_spawn_dlc_dmm', '_spawn_fnode_dlc_dmm'):
            if getattr(self, _attr + '_vanilla', None) is not None:
                setattr(self, _attr, _copy_reset.deepcopy(getattr(self, _attr + '_vanilla')))
        if self._spawn_original:
            self._spawn_data = bytearray(self._spawn_original)
        if hasattr(self, '_spawn_node_original') and self._spawn_node_original:
            self._spawn_node_data = bytearray(self._spawn_node_original)
        if hasattr(self, '_spawn_fnode_ops_original') and self._spawn_fnode_ops_original:
            self._spawn_fnode_ops_data = bytearray(self._spawn_fnode_ops_original)

        for el in self._spawn_elements:
            src = el.get('source', '')
            if src == 'terrain':
                el['spawn_count'] = el.get('vanilla_count', el['spawn_count'])
                el['timer_ms'] = el.get('vanilla_timer', el['timer_ms'])
                inner = el.get('inner_ref')
                if inner is not None:
                    inner['flag_a'] = el['spawn_count']
                spline = el.get('spline_ref')
                if spline is not None:
                    spline['raw_qword'] = el['timer_ms']
            elif src == 'fnode_ops':
                el['spawn_count'] = el.get('vanilla_count', el['spawn_count'])
                rde = el.get('rde_ref')
                if rde is not None:
                    rde['flag'] = el['spawn_count']
        self._spawn_modified = False
        self._spawn_changes_label.setText("")
        self._spawn_filter()
        self._spawn_status.setText(tr("Reset to vanilla values"))

    def _spawn_dlc_note(self) -> str:
        """Apply / Export as Mod write the main tables only: say so when DLC
        regions were edited."""
        n = 0
        for attr in ('_spawn_dlc_dmm', '_spawn_fnode_dlc_dmm'):
            cur = getattr(self, attr, None) or []
            van = getattr(self, attr + '_vanilla', None) or []
            n += sum(1 for a, b in zip(cur, van) if a != b)
        if not n:
            return ""
        return (f"{n} edited DLC region(s)/node(s) are not included here - "
                f"use 'Export Field JSON v3' for them.\n\n")

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

        self._spawn_status.setText(tr("Packing overlay..."))
        QApplication.processEvents()

        try:
            import crimson_rs
            import tempfile
            import shutil

            game_path = self._config.get("game_install_path", "")

            if os.path.isdir(out_path):
                shutil.rmtree(out_path)
            os.makedirs(out_path, exist_ok=True)

            INTERNAL_DIR = "gamedata/binary__/client/bin"
            mod_group = f"{self._spawn_overlay_spin.value():04d}"

            import dmm_parser as _dmp_exp
            if hasattr(self, '_spawn_dmm') and self._spawn_dmm:
                terrain_exp_bytes = _dmp_exp.serialize_table(
                    'terrain_region_auto_spawn_info', self._spawn_dmm)
            else:
                terrain_exp_bytes = bytes(self._spawn_data)

            spawn_files = [
                ("terrainregionautospawninfo", terrain_exp_bytes, self._spawn_schema),
            ]
            if hasattr(self, '_spawn_node_data') and self._spawn_node_data:
                spawn_files.append(("factionnodespawninfo", self._spawn_node_data,
                    getattr(self, '_spawn_node_schema', None)))
            if hasattr(self, '_spawn_fnode_dmm') and self._spawn_fnode_dmm:
                import dmm_parser as _dmp_fn
                fnode_bytes = _dmp_fn.serialize_table('faction_node_info', self._spawn_fnode_dmm)
                spawn_files.append(("factionnode", fnode_bytes,
                    getattr(self, '_spawn_fnode_ops_schema', None)))
            elif hasattr(self, '_spawn_fnode_ops_data') and self._spawn_fnode_ops_data:
                spawn_files.append(("factionnode", self._spawn_fnode_ops_data,
                    getattr(self, '_spawn_fnode_ops_schema', None)))
            if hasattr(self, '_spawn_life_data') and self._spawn_life_data:
                spawn_files.append(("spawningpoolautospawninfo", self._spawn_life_data,
                    getattr(self, '_spawn_life_schema', None)))

            with tempfile.TemporaryDirectory() as tmp_dir:
                group_dir = os.path.join(tmp_dir, mod_group)
                builder = crimson_rs.PackGroupBuilder(
                    group_dir, crimson_rs.Compression.NONE,
                    crimson_rs.Crypto.NONE)

                for stem, data, schema in spawn_files:
                    builder.add_file(INTERNAL_DIR, f"{stem}.pabgb", bytes(data))
                    pabgh = schema
                    if not pabgh:
                        pabgh = bytes(crimson_rs.extract_file(
                            game_path, "0008", INTERNAL_DIR, f"{stem}.pabgh"))
                    builder.add_file(INTERNAL_DIR, f"{stem}.pabgh", bytes(pabgh))

                pamt_bytes = bytes(builder.finish())
                pamt_checksum = crimson_rs.parse_pamt_bytes(pamt_bytes)["checksum"]

                paz_dst = os.path.join(out_path, mod_group)
                os.makedirs(paz_dst, exist_ok=True)
                for fn in os.listdir(group_dir):
                    shutil.copy2(os.path.join(group_dir, fn),
                                 os.path.join(paz_dst, fn))

                meta_dst = os.path.join(out_path, "meta")
                os.makedirs(meta_dst, exist_ok=True)
                papgt = {"entries": []}
                papgt = crimson_rs.add_papgt_entry(
                    papgt, mod_group, pamt_checksum, 0, 16383)
                crimson_rs.write_papgt_file(papgt, os.path.join(meta_dst, "0.papgt"))

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
        """Export SpawnEdit modifications as Format 3.1 field JSON using structured intents.

        Compares current dmm_parser records against vanilla baseline at the parsed
        dict level — same pattern as _store_export_field_json_v3. Produces semantic
        intents (entry name + key + field name) that DMM 1.3.6b can apply correctly
        to any game version without raw byte offset fragility.
        """
        try:
            has_terrain = (hasattr(self, '_spawn_dmm') and self._spawn_dmm and
                           hasattr(self, '_spawn_dmm_vanilla') and self._spawn_dmm_vanilla)
            has_fnode   = (hasattr(self, '_spawn_fnode_dmm') and self._spawn_fnode_dmm and
                           hasattr(self, '_spawn_fnode_dmm_vanilla') and self._spawn_fnode_dmm_vanilla)
            has_life    = (hasattr(self, '_spawn_life_dmm') and self._spawn_life_dmm and
                           hasattr(self, '_spawn_life_dmm_vanilla') and self._spawn_life_dmm_vanilla)

            if not any([has_terrain, has_fnode, has_life]):
                QMessageBox.information(self, tr('Export Field JSON v3'),
                    tr('No spawn data loaded. Extract spawn data first.'))
                return

            def _deep_diff_value(cur, van, path, leaf_intents):
                """Recursively walk cur vs van, collecting leaf-level changes as
                (path, new_value) pairs. Uses DMM's bracket+dot notation:
                  list[N].field   →  e.g. faction_schedule_list[0].slot_inner_list[2].lookup_a
                  dict.field      →  e.g. raw_data_ext.flag
                Rules:
                  - dicts: recurse key-by-key
                  - lists of same length with dict items: recurse element-by-element
                  - lists of different length OR list of scalars: whole replacement
                  - scalars: emit leaf if changed
                """
                if isinstance(cur, dict) and isinstance(van, dict):
                    for k in cur:
                        sub_path = f'{path}.{k}' if path else k
                        _deep_diff_value(cur[k], van.get(k), sub_path, leaf_intents)
                elif (isinstance(cur, list) and isinstance(van, list)
                      and len(cur) == len(van)
                      and all(isinstance(c, dict) for c in cur)):
                    for i, (c_item, v_item) in enumerate(zip(cur, van)):
                        _deep_diff_value(c_item, v_item, f'{path}[{i}]', leaf_intents)
                else:
                    # Scalar, list of scalars, or length mismatch → whole replacement
                    if cur != van:
                        leaf_intents.append((path, cur))

            def _struct_diff(current_records, vanilla_records, skip_fields=('key', 'string_key')):
                """Diff two dmm_parser record lists using deep field-path diffing.
                Emits precise nested intents (e.g. faction_schedule_list[0].slot_inner_list[2].lookup_a)
                instead of whole-list replacements, so DMM can apply each scalar change
                independently without needing to re-serialize complex nested structures."""
                van_by_key = {r['key']: r for r in vanilla_records}
                intents = []
                for rec in current_records:
                    rkey  = rec.get('key')
                    rskey = rec.get('string_key', f'entry_{rkey}')
                    van   = van_by_key.get(rkey)
                    if van is None:
                        continue
                    for field in rec:
                        if field in skip_fields:
                            continue
                        if rec[field] == van.get(field):
                            continue
                        # Deep diff this field — collect all leaf-level changes
                        leaf_changes = []
                        _deep_diff_value(rec[field], van.get(field), field, leaf_changes)
                        for fpath, new_val in leaf_changes:
                            intents.append({
                                'entry': rskey,
                                'key':   rkey,
                                'field': fpath,
                                'op':    'set',
                                'new':   new_val,
                            })
                return intents

            targets = []

            # Records only the DLC has: DMM applies these to the DLC's tables.
            # A mod with nothing else in it needs the DLC.
            dlc_intents = 0
            base_intents = 0

            def _with_dlc(base_list, dlc_attr):
                nonlocal dlc_intents, base_intents
                found = _struct_diff(*base_list)
                base_intents += len(found)
                dlc = getattr(self, dlc_attr, None) or []
                dlc_van = getattr(self, dlc_attr + '_vanilla', None) or []
                if dlc and dlc_van:
                    extra = _struct_diff(dlc, dlc_van)
                    dlc_intents += len(extra)
                    found = found + extra
                return found

            # terrainregionautospawninfo
            if has_terrain:
                intents = _with_dlc((self._spawn_dmm, self._spawn_dmm_vanilla), '_spawn_dlc_dmm')
                if intents:
                    targets.append({
                        'file': 'terrainregionautospawninfo.pabgb',
                        'intents': intents,
                    })

            # factionnode
            if has_fnode:
                intents = _with_dlc((self._spawn_fnode_dmm, self._spawn_fnode_dmm_vanilla),
                                    '_spawn_fnode_dlc_dmm')
                if intents:
                    targets.append({
                        'file': 'factionnode.pabgb',
                        'intents': intents,
                    })

            # spawningpoolautospawninfo
            if has_life:
                intents = _struct_diff(self._spawn_life_dmm, self._spawn_life_dmm_vanilla)
                base_intents += len(intents)
                if intents:
                    targets.append({
                        'file': 'spawningpoolautospawninfo.pabgb',
                        'intents': intents,
                    })

            if not targets:
                QMessageBox.information(self, tr('Export Field JSON v3'),
                    tr('No differences found. Make changes using the spawn editor first.'))
                return

            total   = sum(len(t['intents']) for t in targets)
            summary = ', '.join(
                f"{len(t['intents'])} {t['file'].split('.')[0]}" for t in targets)

            path, _ = QFileDialog.getSaveFileName(
                self, tr('Export Field JSON v3'), 'SpawnEdit.field.json',
                'Field JSON (*.field.json *.json);;All Files (*)')
            if not path:
                return

            doc = {
                'modinfo': {
                    'title':       'SpawnEdit Mod',
                    'version':     '1.0',
                    'author':      'CrimsonGameMods SpawnEdit',
                    'description': (f'{total} field-level intent(s) across '
                                    f'{len(targets)} target(s) — {summary}'),
                    'note': ('Format 3.1 multi-target field JSON. '
                             'Structured intents via dmm_parser — update-proof, '
                             'compatible with DMM 1.3.6b+.'),
                },
                'format':       3,
                'format_minor': 1,
                'targets':      targets,
            }
            if dlc_intents and not base_intents:
                doc['modinfo']['requires_dlc'] = True

            with open(path, 'w', encoding='utf-8') as _f:
                import json as _json_out
                _json_out.dump(doc, _f, indent=2, ensure_ascii=False, default=str)

            self._spawn_status.setText(
                f'Exported {total} field intents to {os.path.basename(path)}')
            QMessageBox.information(self, tr('Export Field JSON v3'),
                f'Exported {total} structured field intent(s) across '
                f'{len(targets)} target(s):\n'
                + '\n'.join(f'  \u2022 {t["file"]}: {len(t["intents"])} intent(s)'
                            for t in targets)
                + (('\n\nOnly DLC regions edited - the mod needs the DLC.'
                    if not base_intents else
                    f'\n\n{dlc_intents} intent(s) are for DLC regions - players '
                    'without the DLC get the rest.') if dlc_intents else '')
                + f'\n\nFile: {path}')

        except Exception as _err:
            import traceback as _tb
            QMessageBox.critical(self, tr('Export Field JSON v3 — Error'),
                f'An error occurred:\n{_err}\n\n{_tb.format_exc()}')

    def _spawn_apply(self):

        if not self._spawn_data or not self._spawn_modified:
            QMessageBox.information(self, tr("SpawnEdit"), tr("No modifications to apply."))
            return

        game_path = self._config.get("game_install_path", "")
        if not game_path or not os.path.isdir(game_path):
            QMessageBox.critical(self, tr("Game Path"), tr("Game install path not set."))
            return

        from gui.utils import resolve_overlay_group
        _req = self._spawn_overlay_spin.value()
        _num = resolve_overlay_group(game_path, _req, "SpawnEdit", parent=self)
        if _num is None:
            return
        if _num != _req:
            self._spawn_overlay_spin.setValue(_num)
        mod_group = f"{_num:04d}"
        reply = QMessageBox.question(
            self, tr("Apply Spawn Changes"),
            f"Deploy modified spawn data to the game?\n\n"
            f"Creates {mod_group}/ overlay. Restart game to take effect.\n"
            f"Original files are NOT modified. Use Restore to undo.\n\n"
            f"{self._spawn_dlc_note()}"
            f"TIP: Use 'Export Field JSON v3' to get a DMM-compatible mod file instead.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self._spawn_status.setText(tr("Packing overlay..."))
        QApplication.processEvents()

        try:
            import crimson_rs
            import shutil
            import tempfile
            from pathlib import Path

            gp = Path(game_path)
            INTERNAL_DIR = "gamedata/binary__/client/bin"

            # Serialize terrain from dmm_parser if available
            import dmm_parser as _dmp_apply
            if hasattr(self, '_spawn_dmm') and self._spawn_dmm:
                terrain_bytes = _dmp_apply.serialize_table(
                    'terrain_region_auto_spawn_info', self._spawn_dmm)
            else:
                terrain_bytes = bytes(self._spawn_data)

            spawn_files = [
                ("terrainregionautospawninfo", terrain_bytes, self._spawn_schema),
            ]
            if hasattr(self, '_spawn_node_data') and self._spawn_node_data:
                spawn_files.append(("factionnodespawninfo", self._spawn_node_data,
                    getattr(self, '_spawn_node_schema', None)))
            if hasattr(self, '_spawn_fnode_dmm') and self._spawn_fnode_dmm:
                import dmm_parser as _dmp_fn
                fnode_bytes = _dmp_fn.serialize_table('faction_node_info', self._spawn_fnode_dmm)
                spawn_files.append(("factionnode", fnode_bytes,
                    getattr(self, '_spawn_fnode_ops_schema', None)))
            elif hasattr(self, '_spawn_fnode_ops_data') and self._spawn_fnode_ops_data:
                spawn_files.append(("factionnode", self._spawn_fnode_ops_data,
                    getattr(self, '_spawn_fnode_ops_schema', None)))
            if hasattr(self, '_spawn_life_data') and self._spawn_life_data:
                spawn_files.append(("spawningpoolautospawninfo", self._spawn_life_data,
                    getattr(self, '_spawn_life_schema', None)))

            with tempfile.TemporaryDirectory() as tmp_dir:
                group_dir = os.path.join(tmp_dir, mod_group)
                builder = crimson_rs.PackGroupBuilder(
                    group_dir, crimson_rs.Compression.NONE,
                    crimson_rs.Crypto.NONE)

                for stem, data, schema in spawn_files:
                    builder.add_file(INTERNAL_DIR, f"{stem}.pabgb", bytes(data))
                    pabgh = schema
                    if not pabgh:
                        pabgh = bytes(crimson_rs.extract_file(
                            game_path, "0008", INTERNAL_DIR, f"{stem}.pabgh"))
                    builder.add_file(INTERNAL_DIR, f"{stem}.pabgh", bytes(pabgh))

                pamt_bytes = bytes(builder.finish())
                pamt_checksum = crimson_rs.parse_pamt_bytes(pamt_bytes)["checksum"]

                papgt_path = gp / "meta" / "0.papgt"
                backup_path = papgt_path.with_suffix(".papgt.spawn_bak")
                if papgt_path.exists() and not backup_path.exists():
                    shutil.copy2(papgt_path, backup_path)

                dest = gp / mod_group
                dest.mkdir(exist_ok=True)
                for fn in os.listdir(group_dir):
                    shutil.copy2(os.path.join(group_dir, fn), str(dest / fn))

                papgt = crimson_rs.parse_papgt_file(str(papgt_path))
                papgt["entries"] = [e for e in papgt["entries"]
                                    if e.get("group_name") != mod_group]
                papgt = crimson_rs.add_papgt_entry(
                    papgt, mod_group, pamt_checksum, 0, 16383)
                crimson_rs.write_papgt_file(papgt, str(papgt_path))

            self._spawn_status.setText(f"Applied to {mod_group}/")
            QMessageBox.information(self, tr("Applied"),
                f"Spawn mod deployed to {mod_group}/.\n"
                f"Restart the game for changes to take effect.")

        except Exception as e:
            log.exception("Unhandled exception")
            self._spawn_status.setText(f"Apply failed: {e}")
            QMessageBox.critical(self, tr("Apply Failed"), str(e))

    def _spawn_restore(self):
        """Restore Vanilla — reset in-memory edits first, then also remove any
        deployed disk overlay if one exists (requires game path)."""
        if not self._spawn_original:
            QMessageBox.warning(self, tr("Restore Vanilla"),
                "Load Spawn Data first before restoring.")
            return

        # Always reset in-memory edits (same as old Reset Edits button)
        self._spawn_reset()

        # Also attempt to remove disk overlay if game path is set
        game_path = self._config.get("game_install_path", "")
        if game_path and os.path.isdir(game_path):
            mod_group = f"{self._spawn_overlay_spin.value():04d}"
            game_mod = os.path.join(game_path, mod_group)
            if os.path.isdir(game_mod):
                try:
                    import shutil
                    # _rebuild_papgt_fn was never passed to SpawnTab, so this
                    # always failed before and the overlay stayed.
                    from overlay_coordinator import remove_papgt_groups
                    safe_rmtree(game_mod)
                    msg = remove_papgt_groups(game_path, [mod_group])
                    self._spawn_status.setText(tr("Restored vanilla spawns"))
                    QMessageBox.information(self, tr("Restore Vanilla"),
                        f"Spawn data reset to vanilla and {mod_group}/ overlay removed.\n"
                        f"{msg}\nRestart the game for changes to take effect.")
                    return
                except Exception as e:
                    QMessageBox.critical(self, tr("Restore Failed"), str(e))
                    return

        self._spawn_status.setText(tr("Reset to vanilla"))


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
        if not result and body is not None and getattr(self, '_dropset_modified', False):
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
            _safe_overlay_default(self._config.get("dropset_overlay_dir", 71), 71))
        self._dropset_overlay_spin.setFixedWidth(70)
        self._dropset_overlay_spin.setToolTip(
            "Overlay group number (0042 = default). Change if another mod\n"
            "already uses this slot. Apply to Game writes to <game>/NNNN/;\n"
            "Restore removes the same NNNN/.")
        self._dropset_overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"dropset_overlay_dir": int(v)}))
        top_row.addWidget(self._dropset_overlay_spin)

        restore_btn = QPushButton(tr("Restore"))
        restore_btn.setToolTip(tr("Remove drop table mod and restore vanilla"))
        restore_btn.clicked.connect(self._dropset_restore)
        top_row.addWidget(restore_btn)

        export_field_btn = QPushButton("Export Field JSON v3")
        export_field_btn.setStyleSheet(button_css("primary") + " font-weight: bold;")
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

        reset_vanilla_btn = QPushButton("Reset to Vanilla")
        reset_vanilla_btn.setStyleSheet(
            "QPushButton { " + button_css("danger") + " font-weight: bold; }")
        reset_vanilla_btn.setToolTip(
            "Discard all in-memory drop table edits and revert to vanilla state.\n"
            "Does not affect any deployed game files — use Restore for that.")
        reset_vanilla_btn.clicked.connect(self._dropset_reset_to_vanilla)
        top_row.addWidget(reset_vanilla_btn)

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

        preset_row.addWidget(QLabel(tr("Min Rate")))
        self._boost_min_rate = QSpinBox()
        self._boost_min_rate.setRange(1, 99)
        self._boost_min_rate.setValue(10)
        self._boost_min_rate.setSuffix(" %")
        self._boost_min_rate.setMinimumWidth(82)
        self._boost_min_rate.setMinimumHeight(26)
        preset_row.addWidget(self._boost_min_rate)

        preset_row.addWidget(QLabel(tr("Multiplier")))
        self._boost_multiplier = QSpinBox()
        self._boost_multiplier.setRange(1, 99)
        self._boost_multiplier.setValue(1)
        self._boost_multiplier.setSuffix(" x")
        self._boost_multiplier.setMinimumWidth(82)
        self._boost_multiplier.setMinimumHeight(26)
        preset_row.addWidget(self._boost_multiplier)

        preset_row.addWidget(QLabel(tr("Alpha")))
        self._boost_alpha = QDoubleSpinBox()
        self._boost_alpha.setRange(0.01, 0.99)
        self._boost_alpha.setValue(0.05)
        self._boost_alpha.setSingleStep(0.01)
        self._boost_alpha.setDecimals(2)
        self._boost_alpha.setMinimumWidth(82)
        self._boost_alpha.setMinimumHeight(26)
        preset_row.addWidget(self._boost_alpha)

        boost_apply_btn = QPushButton(tr("Apply"))
        boost_apply_btn.setToolTip(
            tr("Apply logarithmic rate boost to ALL named drop sets.\n"
               "\n"
               "Rate: F(x) = min + (100−min)×ln(1+αx)/ln(1+100α)\n"
               "  x = original rate %; output in [min%, 100%]\n"
               "  Low alpha ≈ linear; high alpha ≈ steep ramp for low rates.\n"
               "\n"
               "Qty: each item’s quantity is multiplied by Multiplier.\n"
               "Affects all named sets (chests, factions, monsters, etc.)."))
        boost_apply_btn.clicked.connect(self._dropset_global_boost_formula)
        preset_row.addWidget(boost_apply_btn)

        preset_row.addWidget(QLabel("  +Rate:"))
        for mult, label in [(5, "5x+20%"), (10, "10x+20%"), (50, "50x+20%"), (100, "100x+20%")]:
            btn = QPushButton(label)
            btn.setToolTip(
                f"x{mult} quantity + 20% rate increase on original values.\n"
                f"Rates capped at 100%. Affects all named drop sets.")
            btn.clicked.connect(lambda checked, m=mult: self._dropset_global_boost(m, rate_boost_percent=20))
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

            import dmm_parser as _dmp_ds
            import copy as _copy_ds
            hdr = bytes(header_data)
            bod = bytes(body_data)
            self._dropset_dmm = _dmp_ds.parse_table('drop_set_info', bod, hdr)
            self._dropset_dmm_vanilla = _copy_ds.deepcopy(self._dropset_dmm)
            self._dropset_gh = hdr

            # dmm_parser-backed editor (dropset_dmm). The old byte reader
            # (dropset_editor) wrote 254 of 14747 sets back wrong on 2.03.
            from dropset_dmm import DmmDropsetEditor
            editor = DmmDropsetEditor()
            editor.load_bytes(hdr, bod)

            editor.load_item_names()

            # Drop sets only the DLC has (sea creatures, islands ...). They
            # are listed as "[DLC]" and go into Field JSON exports only.
            self._dropset_dlc_items = set()
            n_dlc = 0
            try:
                from item_db import dlc_only_records, dlc_only_item_keys
                _dlc_recs = dlc_only_records(game_path, "dropsetinfo", "drop_set_info",
                                             {int(r["key"]) for r in self._dropset_dmm})
                n_dlc = editor.add_dlc_records(_dlc_recs)
                self._dropset_dmm_vanilla.extend(_copy_ds.deepcopy(_dlc_recs))
                self._dropset_dlc_items = dlc_only_item_keys(game_path)
            except Exception as _dlc_err:  # noqa: BLE001
                log.warning("DLC drop sets not loaded: %s", _dlc_err)

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
                f"Loaded {editor.record_count:,} drop sets"
                + (f" + {n_dlc:,} from the DLC (Field JSON only)" if n_dlc else ""))
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
                        if search in s["name"].lower() or search in str(s["key"])
                        or (search == "dlc" and s.get("dlc"))]

        self._dropset_list.setSortingEnabled(False)
        self._dropset_list.setRowCount(len(filtered))
        for row, s in enumerate(filtered):
            key_item = QTableWidgetItem()
            key_item.setData(Qt.DisplayRole, s["key"])
            self._dropset_list.setItem(row, 0, key_item)
            _nm = s["name"] or f"(key {s['key']})"
            if s.get("dlc"):
                _nm = f"[DLC] {_nm}"
            _ni = QTableWidgetItem(_nm)
            if s.get("dlc"):
                _ni.setToolTip("Only in the DLC. Edits go into 'Export Field JSON' "
                               "(not into Apply / Export as Mod).")
            self._dropset_list.setItem(row, 1, _ni)
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

    def _dropset_dlc_apply_note(self) -> str:
        """Apply / Export as Mod write the main table only: say so when DLC
        drop sets were edited."""
        ed = self._dropset_editor
        dlc = ed.dlc_keys if ed is not None and hasattr(ed, 'dlc_keys') else set()
        if not dlc:
            return ""
        van = {int(r['key']): r for r in getattr(self, '_dropset_dmm_vanilla', None) or []
               if int(r['key']) in dlc}
        n = sum(1 for k in dlc if ed.record(k) != van.get(k))
        if not n:
            return ""
        return (f"{n} edited DLC drop set(s) are not included here - "
                f"use 'Export Field JSON' for them.\n\n")

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
            # Read the changed sets again from the updated bytes. The old
            # objects still carry their old byte positions; Loot Bonanza adds
            # drops, so everything after them moved. Caching the old objects
            # (as this did before) made the next write-out put them back at
            # the old positions and damaged dropsetinfo.
            fresh = []
            for ds in modified:
                re_ds = self._dropset_editor.parse_dropset(ds.key)
                if re_ds is not None:
                    fresh.append(re_ds)
            for ds in fresh:
                self._dropset_mark_modified(key=ds.key)
            modified = fresh
            self._dropset_filter()

            if self._dropset_current_key is not None:
                self._dropset_refresh_items()

            names = ", ".join(ds.name or f"key={ds.key}" for ds in modified)
            self._dropset_status.setText(f"Applied '{preset}' to {len(modified)} sets")
            QMessageBox.information(self, tr("Preset Applied"),
                f"'{preset}' applied to:\n{names}\n\n"
                "")
        except Exception as e:
            log.exception("Unhandled exception")
            QMessageBox.critical(self, tr("Preset Failed"), str(e))

    def _dropset_global_boost(self, multiplier: int, rate_boost_percent=None):
        if not self._dropset_editor:
            QMessageBox.warning(self, tr("DropSets"), tr("Load drop set data first."))
            return

        summaries = self._dropset_editor.get_all_sets_summary(named_only=True)
        count = len(summaries)

        if rate_boost_percent is None:
            reply = QMessageBox.question(
                self, f"Global {multiplier}x Loot",
                f"Set ALL {count} named drop sets to:\n"
                f"  - 100% drop rate on every item\n"
                f"  - x{multiplier} quantity on every item\n\n"
                f"This affects chests, factions, monsters, quests — everything.\n"
                f"Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            mode_desc = "100% rates"
        else:
            reply = QMessageBox.question(
                self, f"Global {multiplier}x + {rate_boost_percent}% Rate Boost",
                f"Apply to ALL {count} named drop sets:\n"
                f"  - Increase drop rates by {rate_boost_percent}% of original (capped at 100%)\n"
                f"  - x{multiplier} quantity multiplier on every item\n\n"
                f"This affects chests, factions, monsters, quests — everything.\n"
                f"Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            mode_desc = f"+{rate_boost_percent}% rates"
        if reply != QMessageBox.Yes:
            return

        self._dropset_status.setText(f"Applying {multiplier}x ({mode_desc}) to {count} sets...")
        QApplication.processEvents()

        modified = []
        for s in summaries:
            ds = self._dropset_editor.parse_dropset(s["key"])
            if not ds:
                continue
            if rate_boost_percent is None:
                self._dropset_editor.boost_rates(ds, rate=1_000_000)
            else:
                for drop in ds.drops:
                    if drop.rates < 1_000_000:
                        increase = int(drop.rates * (rate_boost_percent / 100.0))
                        drop.rates = min(drop.rates + increase, 1_000_000)
                        drop.rates_100 = drop.rates // 10000
            for drop in ds.drops:
                base_min = max(drop.max_amt, 1)
                base_max = max(drop.min_amt, 1)
                drop.max_amt = min(base_min * multiplier, 999999)
                drop.min_amt = min(base_max * multiplier, 999999)
            modified.append(ds)
            self._dropset_editor._parsed_sets[ds.key] = ds
            self._dropset_dirty_keys.add(s["key"])

        self._dropset_modified = True
        self._dropset_change_count += count
        self._dropset_changes_label.setText(f"{self._dropset_change_count} change(s)")

        if self._dropset_current_key is not None:
            self._dropset_refresh_items()

        self._dropset_status.setText(
            f"Applied {multiplier}x ({mode_desc}) to {len(modified)} drop sets")
        if rate_boost_percent is None:
            detail = (f"Modified {len(modified)} drop sets:\n"
                f"  - All rates set to 100%\n"
                f"  - All quantities x{multiplier}\n\n"
                f"Use 'Export as Mod' to save.")
        else:
            detail = (f"Modified {len(modified)} drop sets:\n"
                f"  - Rates increased by {rate_boost_percent}% (capped at 100%)\n"
                f"  - Quantities multiplied by x{multiplier}\n\n"
                f"Use 'Export as Mod' to save.")
        QMessageBox.information(self, tr("Global Boost Applied"), detail)

    def _dropset_global_boost_formula(self):
        import math
        if not self._dropset_editor:
            QMessageBox.warning(self, tr("DropSets"), tr("Load drop set data first."))
            return

        min_rate = self._boost_min_rate.value()   # percent floor, 1–99
        multiplier = self._boost_multiplier.value()  # qty multiplier only
        alpha = self._boost_alpha.value()

        summaries = self._dropset_editor.get_all_sets_summary(named_only=True)
        count = len(summaries)

        reply = QMessageBox.question(
            self, tr("Global Loot Boost"),
            f"Apply logarithmic rate boost to ALL {count} named drop sets?\n\n"
            f"  Rate: F(x) = {min_rate} + (100−{min_rate})×ln(1+{alpha}x)/ln(1+{100*alpha:.2f})\n"
            f"  Qty:  each quantity ×{multiplier}\n\n"
            f"Affects chests, factions, monsters, quests — everything.\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        log_denom = math.log(1 + alpha * 100)  # formula max is always 100%

        def boosted_rate(original_pct: float) -> int:
            x = max(0.0, min(original_pct, 100.0))
            if x <= 0:
                new_pct = min_rate
            else:
                new_pct = min_rate + (100 - min_rate) * math.log(1 + alpha * x) / log_denom
            return max(0, min(1_000_000, int(new_pct) * 10_000))

        self._dropset_status.setText(f"Applying formula boost to {count} sets...")
        QApplication.processEvents()

        modified = []
        for s in summaries:
            ds = self._dropset_editor.parse_dropset(s["key"])
            if not ds:
                continue
            for drop in ds.drops:
                original_pct = drop.rates / 10_000
                drop.rates = boosted_rate(original_pct)
                drop.rates_100 = drop.rates // 10_000
                base_min = max(drop.max_amt, 1)
                base_max = max(drop.min_amt, 1)
                drop.max_amt = min(base_min * multiplier, 999_999)
                drop.min_amt = min(base_max * multiplier, 999_999)
            modified.append(ds)
            self._dropset_editor._parsed_sets[ds.key] = ds
            self._dropset_dirty_keys.add(s["key"])

        self._dropset_modified = True
        self._dropset_change_count += count
        self._dropset_changes_label.setText(f"{self._dropset_change_count} change(s)")

        if self._dropset_current_key is not None:
            self._dropset_refresh_items()

        self._dropset_status.setText(
            f"Formula boost applied to {len(modified)} sets — rate [{min_rate}%→100%] α={alpha}, x{multiplier} qty")
        QMessageBox.information(self, tr("Global Boost Applied"),
            f"Modified {len(modified)} drop sets.\n\n"
            f"  Rate: [{min_rate}%, 100%] logarithmic (α={alpha})\n"
            f"  Qty multiplier: ×{multiplier}\n\n"
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
            "")


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
                f"{self._dropset_dlc_apply_note()}"
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

        from gui.utils import resolve_overlay_group
        _req = self._dropset_overlay_spin.value()
        _num = resolve_overlay_group(game_path, _req, "DropSets", parent=self)
        if _num is None:
            return
        if _num != _req:
            self._dropset_overlay_spin.setValue(_num)
        group_name = f"{_num:04d}"

        reply = QMessageBox.question(
            self, tr("Apply DropSet Changes"),
            f"Deploy modified drop tables to the game?\n\n"
            f"Data: pabgb ({len(body_data):,} bytes) + pabgh ({len(header_data):,} bytes)\n"
            f"Overlay: {group_name}/\n\n"
            f"Original game files are NOT modified.\n"
            f"TIP: Use 'Export Field JSON v3' to get a DMM-compatible mod file instead.\n\n"
            f"{self._dropset_dlc_apply_note()}"
            f"To undo: click Restore.\n"
            f"Restart the game for changes to take effect.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self._dropset_status.setText(tr("Packing overlay..."))
        QApplication.processEvents()

        try:
            import crimson_rs
            import shutil
            import tempfile
            from pathlib import Path

            gp = Path(game_path)
            INTERNAL_DIR = "gamedata/binary__/client/bin"

            with tempfile.TemporaryDirectory() as tmp_dir:
                grp_dir = os.path.join(tmp_dir, group_name)
                builder = crimson_rs.PackGroupBuilder(
                    grp_dir, crimson_rs.Compression.NONE,
                    crimson_rs.Crypto.NONE)
                builder.add_file(INTERNAL_DIR, "dropsetinfo.pabgb", body_data)
                builder.add_file(INTERNAL_DIR, "dropsetinfo.pabgh", header_data)
                pamt_bytes = bytes(builder.finish())
                pamt_checksum = crimson_rs.parse_pamt_bytes(pamt_bytes)["checksum"]

                papgt_path = gp / "meta" / "0.papgt"
                backup_path = papgt_path.with_suffix(".papgt.dropset_bak")
                if papgt_path.exists() and not backup_path.exists():
                    shutil.copy2(papgt_path, backup_path)

                dest = gp / group_name
                dest.mkdir(exist_ok=True)
                for fn in os.listdir(grp_dir):
                    shutil.copy2(os.path.join(grp_dir, fn), str(dest / fn))

                papgt = crimson_rs.parse_papgt_file(str(papgt_path))
                papgt["entries"] = [e for e in papgt["entries"]
                                    if e.get("group_name") != group_name]
                papgt = crimson_rs.add_papgt_entry(
                    papgt, group_name, pamt_checksum, 0, 16383)
                crimson_rs.write_papgt_file(papgt, str(papgt_path))

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

    def _dropset_reset_to_vanilla(self) -> None:
        """Discard all in-memory drop table edits and revert to vanilla state.
        Does NOT remove any deployed game overlay — use Restore for that.
        """
        if not getattr(self, '_dropset_editor', None):
            QMessageBox.warning(self, tr("Reset to Vanilla"),
                "Load drop set data first (click 'Load DropSets').")
            return
        if not getattr(self, '_dropset_modified', False):
            QMessageBox.information(self, tr("Reset to Vanilla"),
                "No in-memory changes to reset.")
            return
        reply = QMessageBox.question(
            self, tr("Reset to Vanilla"),
            "Discard all in-memory drop table edits and revert to vanilla?\n\n"
            "This does NOT remove any deployed game overlay.\n"
            "Use the Restore button to remove a deployed overlay.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._dropset_editor.load_bytes(self._dropset_original_header, self._dropset_original_body)
        self._dropset_dirty_keys.clear()
        self._dropset_modified = False
        self._dropset_change_count = 0
        self._dropset_changes_label.setText("0 change(s)")
        self._dropset_filter()
        if self._dropset_current_key:
            self._dropset_refresh_items()
        self._dropset_status.setText(tr("Reset to vanilla"))

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
            # No disk overlay — offer to reset in-memory edits to vanilla
            has_memory = (
                getattr(self, '_dropset_original_body', None) is not None
                and getattr(self, '_dropset_editor', None) is not None
                and getattr(self, '_dropset_modified', False)
            )
            if has_memory:
                reply2 = QMessageBox.question(
                    self, tr("Restore Vanilla"),
                    f"No {group_name}/ overlay found on disk.\n\n"
                    "You have unsaved in-memory drop table edits.\n"
                    "Reset all drop tables back to vanilla?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply2 == QMessageBox.Yes:
                    self._dropset_editor.load_bytes(self._dropset_original_header, self._dropset_original_body)
                    self._dropset_dirty_keys.clear()
                    self._dropset_modified = False
                    self._dropset_change_count = 0
                    self._dropset_changes_label.setText("0 change(s)")
                    self._dropset_filter()
                    if self._dropset_current_key:
                        self._dropset_refresh_items()
                    self._dropset_status.setText(tr("Reset to vanilla (in-memory only)"))
                    QMessageBox.information(self, tr("Restore Vanilla"),
                        "Drop tables reset to vanilla.\n\n"
                        "No game files were modified.")
            else:
                QMessageBox.information(self, tr("Nothing to Restore"),
                    f"No {group_name}/ overlay found and no in-memory changes detected.")
            return

        reply = QMessageBox.question(
            self, tr("Restore Original"),
            tr(f"Remove the {group_name}/ overlay and its pack list entry?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        try:
            import shutil
            messages = []

            # Only take our entry out of the pack list. Copying the backup
            # from the first Apply back (as before) also dropped every mod
            # registered since, DMM's included.
            from overlay_coordinator import remove_papgt_groups
            messages.append(remove_papgt_groups(game_path, [group_name]))

            safe_rmtree(overlay)
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
            from dropset_dmm import DmmDropsetEditor

            orig = DmmDropsetEditor()
            orig.load_bytes(self._dropset_original_header, self._dropset_original_body)

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

            self._dropset_editor.load_bytes(self._dropset_original_header, self._dropset_original_body)

            applied = skipped = 0
            for key_str, entry in dropsets.items():
                try:
                    key = int(key_str)
                except (ValueError, TypeError):
                    skipped += 1
                    continue
                ds = self._dropset_editor.parse_dropset(key)
                if not ds:
                    skipped += 1
                    continue
                drops_cfg = entry.get("drops", [])

                try:
                    # Update existing drop slots
                    for i, dcfg in enumerate(drops_cfg):
                        ik  = dcfg.get("item_key", 0)
                        rp  = float(dcfg.get("rate_pct", 0))
                        qmi = dcfg.get("qty_min", 1)
                        qma = dcfg.get("qty_max", 1)
                        # Internal field names are swapped: max_amt=qty_min, min_amt=qty_max
                        if i < len(ds.drops):
                            ds.drops[i].item_key     = ik
                            ds.drops[i].item_key_dup = ik
                            ds.drops[i].rates        = int(rp * 10000)
                            ds.drops[i].rates_100    = int(rp)
                            ds.drops[i].max_amt      = qmi
                            ds.drops[i].min_amt      = qma
                        else:
                            # Config has more drops than vanilla — add new slot
                            try:
                                self._dropset_editor.add_item(
                                    ds, ik,
                                    rate=int(rp * 10000),
                                    min_qty=qmi,
                                    max_qty=qma,
                                )
                                if ds.drops:
                                    d = ds.drops[-1]
                                    d.rates      = int(rp * 10000)
                                    d.rates_100  = int(rp)
                                    d.max_amt    = qmi
                                    d.min_amt    = qma
                            except Exception:
                                pass

                    # Remove extra vanilla slots that the config doesn't mention
                    _safety = 0
                    while len(ds.drops) > len(drops_cfg) and _safety < 200:
                        _safety += 1
                        prev_len = len(ds.drops)
                        # (remove_item takes an item key, not a position - the
                        # old call never removed anything)
                        ds.drops.pop()
                        if len(ds.drops) >= prev_len:
                            break  # remove_item didn't shrink the list — stop
                except Exception as _de:
                    skipped += 1
                    continue

                self._dropset_dirty_keys.add(key)
                applied += 1

            # Snapshot dirty keys BEFORE flush — flush clears _dropset_dirty_keys
            _keys_to_reparse = set(self._dropset_dirty_keys)
            self._dropset_flush_dirty()

            # Re-populate _parsed_sets after flush so Export Field JSON finds
            # the modified objects. flush_dirty clears both dirty_keys and
            # may evict _parsed_sets entries during apply_modifications.
            for key in _keys_to_reparse:
                try:
                    ds_reparsed = self._dropset_editor.parse_dropset(key)
                    if ds_reparsed is not None:
                        self._dropset_editor._parsed_sets[key] = ds_reparsed
                        self._dropset_dirty_keys.add(key)  # restore for Export
                except Exception:
                    pass

            self._dropset_modified = True
            self._dropset_change_count = applied
            self._dropset_changes_label.setText(f"{applied} change(s)")
            self._dropset_filter()
            if self._dropset_current_key:
                self._dropset_refresh_items()

            msg = f"Loaded config '{config.get('name', os.path.basename(path))}':\n\n"
            msg += f"  {applied} drop set(s) applied"
            if skipped:
                msg += f"\n  {skipped} skipped (not found in current game data)"
            self._dropset_status.setText(
                f"Loaded config: {applied} drop set(s) from {os.path.basename(path)}")
            QMessageBox.information(self, tr("Load Config"), msg)

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

        # Write pending edits into the table, then compare every set with the
        # vanilla records (dmm_parser field names). The old export used the
        # old reader's names (drops / rates / min_amt) and only worked right
        # after a preset: after Apply its cache was empty ("No cached
        # DropSet objects").
        self._dropset_flush_dirty()
        intents = self._dropset_editor.diff_intents(self._dropset_dmm_vanilla)
        modified_entries = {i['key'] for i in intents}

        if not intents:
            QMessageBox.information(self, "Export",
                "No drop data found in modified entries.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Field JSON", "DropSets.field.json",
            "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            return

        modinfo = {
            'title':       'DropSets Mod',
            'version':     '1.0',
            'author':      'CrimsonGameMods DropSets',
            'description': (f'{len(intents)} field-level intent(s) '
                            f'from {len(modified_entries)} modified entries'),
            'note':        'Format 3 — field names, survives game updates',
        }
        # Needs the DLC: only DLC sets edited, or a DLC item put into a set.
        # A mixed mod stays usable without the DLC - DMM skips the DLC sets.
        _dlc_sets = self._dropset_editor.dlc_keys
        _dlc_items = getattr(self, '_dropset_dlc_items', set()) or set()
        _only_dlc = bool(intents) and all(int(i['key']) in _dlc_sets for i in intents)
        _dlc_item_used = False
        for _it in intents:
            if int(_it['key']) in _dlc_sets or not isinstance(_it.get('new'), list):
                continue
            for _d in _it['new']:
                if isinstance(_d, dict) and int(_d.get('raw_at_120', 0) or 0) in _dlc_items:
                    _dlc_item_used = True
                    break
        needs_dlc = _only_dlc or _dlc_item_used
        if needs_dlc:
            modinfo['requires_dlc'] = True
        doc = {
            'modinfo': modinfo,
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
        _n_dlc = sum(1 for k in modified_entries if k in _dlc_sets)
        _dlc_txt = ""
        if needs_dlc:
            _dlc_txt = "The mod needs the DLC (DMM skips it without).\n\n"
        elif _n_dlc:
            _dlc_txt = (f"{_n_dlc} of them are DLC drop sets - players without "
                        "the DLC get the rest.\n\n")
        QMessageBox.information(self, "Export Field JSON",
            f"Exported {len(intents)} field-level intents\n"
            f"from {len(modified_entries)} modified entries.\n\n"
            f"{_dlc_txt}"
            f"File: {path}")

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

        target = doc.get('target', 'dropsetinfo.pabgb')
        intents = doc.get('intents') or []
        if 'targets' in doc:
            intents = [i for t in doc['targets'] if t.get('file') == 'dropsetinfo.pabgb'
                       for i in t.get('intents') or []]
        applied, skipped = self._dropset_editor.apply_field_intents(intents)
        if applied:
            self._dropset_modified = True
            self._dropset_change_count += applied
            self._dropset_changes_label.setText(f"{self._dropset_change_count} change(s)")
            self._dropset_filter()
            if self._dropset_current_key is not None:
                self._dropset_refresh_items()

        self._dropset_status.setText(
            f"Imported {applied} intents, {skipped} skipped.")
        QMessageBox.information(self, "Import Field JSON",
            f"Applied {applied} intent(s), skipped {skipped}.\n\n"
            f"Click Apply to Game or Export Field JSON v3.")


