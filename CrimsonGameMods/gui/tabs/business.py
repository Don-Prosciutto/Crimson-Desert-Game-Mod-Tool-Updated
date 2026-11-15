"""Shops & Loot › Businesses (DLC Charting the Unknown).

Your businesses (facility management) get bonuses when
you sell several goods with the same tag: e.g. 4 "Furniture" goods raise
the satisfaction rate by 70 %, 6 "Plank" goods the selling price by 40 %.
This page changes those bonuses and how many goods each level needs.

Game data (DLC only, parsed with dmm_parser):
  managementneedssynergyinfo.dlc_01  - 30 tags, each with 3-4 levels
      level_list[i].required_count   goods needed for level i
      level_list[i].management_buff_info -> the level's bonus
  managementbuffinfo.dlc_01          - the bonuses
      effect.effect_type + effect.data:
        2 selling price      value, 1 000 000 = 100 %
        3 worker speed       buff_list (buff level 1-3) - not changed here
        4 customers          rate, 1.0 = 100 %
        5 satisfaction rate  value, 1 000 000 = 100 %
        6 popularity gained  value, whole number
        7 customer patience  value, 30 = 1 %  (600 = 20 %)
        8 special guests     value, 1 000 000 = 100 %
Units checked against the game's own texts (2.05.00, e.g. "Furniture Level
4 | Satisfaction Rate +70 %" = value 700000).

Export: Field JSON (format 3.1, two targets), requires_dlc. DMM applies it.
The game's tooltip texts keep the original numbers (they are separate text).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from gui.theme import COLORS, button_css
from gui.utils import make_scope_label, ui_card, ui_dim, ui_info, ui_title

log = logging.getLogger(__name__)

SYN_TABLE = "managementneedssynergyinfo"
BUFF_TABLE = "managementbuffinfo"

# In-game names (English, game 2.05.00) of the 30 tags; string_key -> name.
TAG_NAMES = {
    "Meat": "Meat", "Seafood": "Seafood", "Grain": "Crops", "Soup": "Soup",
    "Roast": "Grilled", "Steam": "Steamed / Braised", "Mix": "Pan-Fried",
    "Traditional": "Traditional", "Delicacy": "Delicacy", "Refined": "Refined",
    "Dining": "Feast", "Classic": "Classic", "Practical": "Practical",
    "Luxury": "Premium", "Simple": "Simple", "Storagelayer": "Cabinet",
    "Furniture": "Furniture", "Arms": "Weapons", "Wood": "Wood", "Plank": "Plank",
    "Firearms": "Firearm", "Plate": "Plate", "Ingot": "Iron",
    "HandFootwear": "Gloves / Footwear", "Cloakwear": "Cloak", "Headwear": "Headgear",
    "Bodywear": "Armor", "Blue": "Blue", "Yellow": "Yellow", "Red": "Red",
}

# effect_type -> (label, field in effect.data, to %, from %)
EFFECTS = {
    2: ("Selling price", "value", lambda v: v / 10000.0, lambda p: int(round(p * 10000))),
    4: ("Customers", "rate", lambda v: v * 100.0, lambda p: round(p / 100.0, 4)),
    5: ("Satisfaction rate", "value", lambda v: v / 10000.0, lambda p: int(round(p * 10000))),
    6: ("Popularity gained", "value", lambda v: float(v), lambda p: int(round(p))),
    7: ("Customer patience", "value", lambda v: v / 30.0, lambda p: int(round(p * 30))),
    8: ("Special guest chance", "value", lambda v: v / 10000.0, lambda p: int(round(p * 10000))),
}
WORKER_SPEED = 3          # buff_list with buff levels - shown, not changed

INFO = ("Your businesses in the DLC Charting the Unknown (facility management).\n\n"
        "Selling several goods with the same tag gives the business a bonus, e.g.\n"
        "4 Furniture goods: satisfaction rate +70 %, 6 Plank goods: selling price +40 %.\n\n"
        "Here you change how big each bonus is and how many goods a level needs.\n"
        "Save as mod, load the file in DMM and mount it. Needs the DLC.\n\n"
        "The tooltips in the game keep showing the original numbers - they are separate texts.")


def _effect_text(etype: int, pct: float) -> str:
    if etype == WORKER_SPEED:
        return f"Buff level {pct:g}"
    if etype == 6:
        return f"+{pct:g}"
    return f"+{pct:g} %"


class BusinessTab(QWidget):
    status_message = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._game_path = config.get("game_install_path", "") or ""
        self._syn: list = []            # synergy records (edited copy)
        self._syn_van: dict = {}        # key -> vanilla record
        self._buff: dict = {}           # key -> buff record (edited copy)
        self._buff_van: dict = {}
        self._rows: list = []           # (syn_key, level index) per table row
        self._loaded = False
        self._filling = False
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._game_path = path or ""

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(make_scope_label("game"))
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        load_btn = QPushButton("Reload")
        load_btn.setToolTip("Read the business bonuses from the game again")
        load_btn.clicked.connect(lambda: self._load(force=True))
        top.addWidget(load_btn)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {COLORS['text_dim']};")
        top.addWidget(self._status, 1)
        top.addWidget(ui_info(INFO))
        layout.addLayout(top)

        quick, qv = ui_card()
        qv.addWidget(ui_title("Quick changes"))
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        r1.addWidget(ui_dim("All bonuses", True))
        self._mult = QComboBox()
        for label, f in (("x 1.5", 1.5), ("x 2", 2.0), ("x 3", 3.0)):
            self._mult.addItem(label, f)
        self._mult.setCurrentIndex(1)
        r1.addWidget(self._mult)
        mult_btn = QPushButton("Make stronger")
        mult_btn.setObjectName("accentBtn")
        mult_btn.setToolTip("Multiply every bonus (from the game's values). Worker speed stays.")
        mult_btn.clicked.connect(self._quick_multiply)
        r1.addWidget(mult_btn)
        r1.addWidget(ui_dim("Selling price, customers, satisfaction, popularity, patience, special guests."), 1)
        qv.addLayout(r1)
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        fewer_btn = QPushButton("Fewer goods needed")
        fewer_btn.setToolTip("Levels 1 / 2 / 3 / 4 need 1 / 2 / 3 / 4 goods with the tag\n"
                             "(the game: up to 7). Tags that need fewer already keep theirs.")
        fewer_btn.clicked.connect(self._quick_fewer)
        r2.addWidget(fewer_btn)
        reset_btn = QPushButton("Back to game values")
        reset_btn.clicked.connect(self._quick_reset)
        r2.addWidget(reset_btn)
        r2.addWidget(ui_dim("Every level: 1 / 2 / 3 / 4 goods with the tag."), 1)
        qv.addLayout(r2)
        layout.addWidget(quick)

        table_card, tv = ui_card()
        frow = QHBoxLayout()
        frow.setSpacing(8)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search a tag, e.g. Furniture…")
        self._search.setMinimumHeight(32)
        self._search.textChanged.connect(self._apply_filter)
        frow.addWidget(self._search, 1)
        self._kind = QComboBox()
        self._kind.addItem("All bonuses", 0)
        for et, (label, *_r) in EFFECTS.items():
            self._kind.addItem(label, et)
        self._kind.addItem("Worker speed", WORKER_SPEED)
        self._kind.setMinimumWidth(180)
        self._kind.currentIndexChanged.connect(self._apply_filter)
        frow.addWidget(self._kind)
        tv.addLayout(frow)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Tag", "Bonus", "Level", "Goods needed", "Bonus value", "Game (goods → bonus)"])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for c, w in ((2, 70), (3, 120), (4, 120), (5, 190)):
            self._table.setColumnWidth(c, w)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked
                                    | QAbstractItemView.EditKeyPressed)
        self._table.itemChanged.connect(self._cell_changed)
        tv.addWidget(self._table, 1)
        tv.addWidget(ui_dim("Double-click 'Goods needed' or 'Bonus value' to change it. "
                            "Changed values are highlighted."))
        layout.addWidget(table_card, 1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self._summary = QLabel("<b>In the mod:</b><br>• nothing changed yet")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(f"background: {COLORS['input_bg']}; border: 1px solid "
                                    f"{COLORS['border']}; border-radius: 8px; padding: 6px 10px;")
        foot.addWidget(self._summary, 1)
        save_btn = QPushButton("Save as mod (Field JSON for DMM)")
        save_btn.setStyleSheet(button_css("primary") + " font-weight: bold; padding: 8px 16px;")
        save_btn.setMinimumHeight(40)
        save_btn.setToolTip("Saves the changes as one Field JSON mod (needs the DLC).\n"
                            "Load it in DMM, activate it and mount.")
        save_btn.clicked.connect(self._export)
        foot.addWidget(save_btn)
        layout.addLayout(foot)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._loaded:
            self._load()

    # ── data ──────────────────────────────────────────────────────────
    def _read_table(self, stem: str) -> list:
        import dmm_parser
        from item_db import _dlc_tables
        for root, d, hname in _dlc_tables(dmm_parser, self._game_path, "0008",
                                          f"{stem}.", ".staticinfoheader"):
            bname = hname[:-len(".staticinfoheader")] + ".staticinfobody"
            head = bytes(dmm_parser.extract_file(root, "0008", d, hname))
            body = bytes(dmm_parser.extract_file(root, "0008", d, bname))
            return list(dmm_parser.parse_table(stem, body, head))
        return []

    def _load(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        if not self._game_path or not os.path.isdir(self._game_path):
            self._status.setText("Set the game folder first (top of the window), then open this tab again.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            syn = self._read_table(SYN_TABLE)
            buffs = self._read_table(BUFF_TABLE)
        except Exception as e:  # noqa: BLE001
            log.exception("Businesses: reading the DLC tables failed")
            self._status.setText(f"Could not read the business data: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        if not syn or not buffs:
            self._status.setText("No business data found - the DLC Charting the Unknown is needed.")
            self._loaded = True
            return
        from perf_util import vanilla_copy
        self._syn = syn
        self._syn_van = {r["key"]: vanilla_copy(r) for r in syn}
        self._buff = {r["key"]: r for r in buffs}
        self._buff_van = {r["key"]: vanilla_copy(r) for r in buffs}
        self._loaded = True
        self._fill()
        self._status.setText(f"{len(syn)} tags with {sum(len(r['level_list']) for r in syn)} "
                             f"levels from the DLC.")

    # ── table ─────────────────────────────────────────────────────────
    def _bonus_of(self, buff: dict):
        """(effect type, % value or None)."""
        eff = buff.get("effect") or {}
        et = int(eff.get("effect_type") or 0)
        data = eff.get("data") or {}
        if et in EFFECTS:
            _l, field, to_pct, _f = EFFECTS[et]
            v = data.get(field)
            return et, (to_pct(v) if isinstance(v, (int, float)) else None)
        if et == WORKER_SPEED:
            bl = data.get("buff_list") or []
            lvl = bl[0].get("buff_level") if bl else None
            return et, (float(lvl) if isinstance(lvl, int) else None)
        return et, None

    def _fill(self) -> None:
        self._filling = True
        t = self._table
        t.setRowCount(0)
        self._rows = []
        dim = QBrush(QColor(COLORS["text_dim"]))
        for rec in sorted(self._syn, key=lambda r: TAG_NAMES.get(r.get("string_key", ""), r.get("string_key", ""))):
            name = TAG_NAMES.get(rec.get("string_key", ""), rec.get("string_key", ""))
            for i, lvl in enumerate(rec.get("level_list") or []):
                buff = self._buff.get(lvl.get("management_buff_info"))
                if buff is None:
                    continue
                et, pct = self._bonus_of(buff)
                label = EFFECTS[et][0] if et in EFFECTS else ("Worker speed" if et == WORKER_SPEED else f"Effect {et}")
                if et in EFFECTS and et != 6:
                    label += " (%)"
                r = t.rowCount()
                t.insertRow(r)
                self._rows.append((rec["key"], i))
                for c, txt in enumerate((name if i == 0 else "", label, str(i + 1))):
                    # tag names stay as the game shows them (English), "\u200b" = not translated
                    it = QTableWidgetItem("\u200b" + txt if c == 0 and txt else txt)
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if c == 0 and not txt:
                        it.setToolTip("\u200b" + name)
                    t.setItem(r, c, it)
                need = QTableWidgetItem(str(lvl.get("required_count", 0)))
                t.setItem(r, 3, need)
                val = QTableWidgetItem("" if pct is None else f"{pct:g}")
                if et == WORKER_SPEED or pct is None:
                    val.setFlags(val.flags() & ~Qt.ItemIsEditable)
                    val.setText(_effect_text(et, pct) if pct is not None else "-")
                    val.setToolTip("Worker speed comes from a buff level - not changed here.")
                    val.setForeground(dim)
                t.setItem(r, 4, val)
                van_buff = self._buff_van.get(buff["key"]) or buff
                van_lvl = (self._syn_van.get(rec["key"]) or rec)["level_list"][i]
                _e, van_pct = self._bonus_of(van_buff)
                game = QTableWidgetItem(f"{van_lvl.get('required_count', 0)} → "
                                        + (_effect_text(et, van_pct) if van_pct is not None else "-"))
                game.setFlags(game.flags() & ~Qt.ItemIsEditable)
                game.setForeground(dim)
                t.setItem(r, 5, game)
                self._mark_row(r)
        self._filling = False
        self._apply_filter()
        self._update_summary()

    def _mark_row(self, r: int) -> None:
        syn_key, i = self._rows[r]
        rec = next(x for x in self._syn if x["key"] == syn_key)
        van = self._syn_van[syn_key]
        lvl, vlvl = rec["level_list"][i], van["level_list"][i]
        buff = self._buff[lvl["management_buff_info"]]
        vbuff = self._buff_van[lvl["management_buff_info"]]
        hi = QBrush(QColor(COLORS["accent"]))
        normal = QBrush(QColor(COLORS["text"]))
        self._table.item(r, 3).setForeground(hi if lvl["required_count"] != vlvl["required_count"] else normal)
        if self._table.item(r, 4).flags() & Qt.ItemIsEditable:
            self._table.item(r, 4).setForeground(hi if buff["effect"] != vbuff["effect"] else normal)

    def _apply_filter(self, *_a) -> None:
        q = self._search.text().strip().lower()
        kind = self._kind.currentData()
        for r, (syn_key, i) in enumerate(self._rows):
            rec = next(x for x in self._syn if x["key"] == syn_key)
            name = TAG_NAMES.get(rec.get("string_key", ""), rec.get("string_key", ""))
            buff = self._buff[rec["level_list"][i]["management_buff_info"]]
            et = int((buff.get("effect") or {}).get("effect_type") or 0)
            hide = (bool(q) and q not in name.lower() and q not in rec.get("string_key", "").lower()) \
                or (kind and et != kind)
            self._table.setRowHidden(r, hide)

    def _cell_changed(self, item: QTableWidgetItem) -> None:
        if self._filling:
            return
        r, c = item.row(), item.column()
        if r >= len(self._rows) or c not in (3, 4):
            return
        syn_key, i = self._rows[r]
        rec = next(x for x in self._syn if x["key"] == syn_key)
        lvl = rec["level_list"][i]
        try:
            num = float(item.text().replace("%", "").replace("+", "").replace(",", ".").strip())
        except ValueError:
            num = None
        self._filling = True
        try:
            if c == 3:
                if num is None or num < 1:
                    item.setText(str(lvl["required_count"]))
                else:
                    lvl["required_count"] = int(round(num))
                    item.setText(str(lvl["required_count"]))
            else:
                buff = self._buff[lvl["management_buff_info"]]
                et = int(buff["effect"]["effect_type"])
                if et in EFFECTS and num is not None and num >= 0:
                    _l, field, to_pct, from_pct = EFFECTS[et]
                    buff["effect"]["data"][field] = from_pct(num)
                    item.setText(f"{to_pct(buff['effect']['data'][field]):g}")
                else:
                    _e, pct = self._bonus_of(buff)
                    item.setText("" if pct is None else f"{pct:g}")
        finally:
            self._filling = False
        self._mark_row(r)
        self._update_summary()

    # ── quick changes ─────────────────────────────────────────────────
    def _need_loaded(self) -> bool:
        if not self._loaded or not self._syn:
            self._load(force=True)
        return bool(self._syn)

    def _quick_multiply(self) -> None:
        if not self._need_loaded():
            return
        f = float(self._mult.currentData() or 2.0)
        n = 0
        for key, buff in self._buff.items():
            et = int((buff.get("effect") or {}).get("effect_type") or 0)
            if et not in EFFECTS or not self._used_buff(key):
                continue
            _l, field, to_pct, from_pct = EFFECTS[et]
            van = self._buff_van[key]["effect"]["data"].get(field)
            if isinstance(van, (int, float)):
                buff["effect"]["data"][field] = from_pct(to_pct(van) * f)
                n += 1
        self._fill()
        self.status_message.emit(f"Businesses: {n} bonuses x{f:g}")

    def _used_buff(self, key: int) -> bool:
        return any(l.get("management_buff_info") == key
                   for rec in self._syn for l in rec.get("level_list") or [])

    def _quick_fewer(self) -> None:
        if not self._need_loaded():
            return
        for rec in self._syn:
            for i, lvl in enumerate(rec.get("level_list") or []):
                van = self._syn_van[rec["key"]]["level_list"][i]["required_count"]
                lvl["required_count"] = min(van, i + 1)
        self._fill()

    def _quick_reset(self) -> None:
        if not self._loaded:
            return
        from perf_util import vanilla_copy
        self._syn = [vanilla_copy(self._syn_van[r["key"]]) for r in self._syn]
        self._buff = {k: vanilla_copy(v) for k, v in self._buff_van.items()}
        self._fill()

    # ── summary + export ──────────────────────────────────────────────
    def _intents(self):
        syn_int, buff_int = [], []
        for rec in self._syn:
            van = self._syn_van[rec["key"]]
            for i, lvl in enumerate(rec.get("level_list") or []):
                if lvl["required_count"] != van["level_list"][i]["required_count"]:
                    syn_int.append({"entry": rec.get("string_key", ""), "key": rec["key"],
                                    "field": f"level_list[{i}].required_count", "op": "set",
                                    "new": int(lvl["required_count"])})
        for key, buff in self._buff.items():
            et = int((buff.get("effect") or {}).get("effect_type") or 0)
            if et not in EFFECTS:
                continue
            field = EFFECTS[et][1]
            new = buff["effect"]["data"].get(field)
            old = self._buff_van[key]["effect"]["data"].get(field)
            if new != old:
                buff_int.append({"entry": buff.get("string_key", ""), "key": key,
                                 "field": f"effect.data.{field}", "op": "set", "new": new})
        return syn_int, buff_int

    def _update_summary(self) -> None:
        syn_int, buff_int = self._intents()
        lines = []
        if buff_int:
            lines.append(f"{len(buff_int)} bonus value(s)")
        if syn_int:
            lines.append(f"{len(syn_int)} level(s) need fewer or more goods")
        self._summary.setText("<b>In the mod:</b><br>" + (
            "<br>".join("• " + x for x in lines) if lines else "• nothing changed yet"))

    def _export(self) -> None:
        syn_int, buff_int = self._intents()
        if not syn_int and not buff_int:
            QMessageBox.information(self, "Businesses (DLC)", "Nothing changed yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as mod", "Businesses.field.json",
            "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            return
        targets = []
        if buff_int:
            targets.append({"file": f"{BUFF_TABLE}.pabgb", "intents": buff_int})
        if syn_int:
            targets.append({"file": f"{SYN_TABLE}.pabgb", "intents": syn_int})
        total = len(buff_int) + len(syn_int)
        doc = {
            "modinfo": {
                "title": "Business bonuses",
                "version": "1.0",
                "author": "CrimsonGameMods",
                "description": f"{total} change(s) to the business tag bonuses (DLC)",
                "note": "Format 3.1 field JSON. Needs the DLC Charting the Unknown.",
                "requires_dlc": True,
            },
            "format": 3,
            "format_minor": 1,
            "targets": targets,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        self._status.setText(f"Saved {total} change(s) to {os.path.basename(path)}")
        QMessageBox.information(
            self, "Save as mod",
            f"Saved {total} change(s).\n\nLoad the file in DMM, activate it and mount. "
            f"Needs the DLC.\n\nFile: {path}")
