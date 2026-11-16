"""Items & Gear › Rarity Matters - rarer gear really is better.

In the game a Common and a Legendary weapon of the same type have almost
the same attack and defense at the same refinement level (2.05: about
11 000 / 20 000 / 33 000 attack at +0 / +5 / +10 for every rarity).
This page changes that with a percentage per rarity, the same at every
refinement level (+0 ... +10), on attack (stat 1000002 DDD) and defense
(1000003 DPV) of iteminfo.enchant_data_list[*].enchant_stat_data.

Modes (presets_engine.rarity_factors):
  stronger  Legendary +5 % per level, Epic / Rare / Uncommon 70 / 40 / 20 %
            of that, Common stays vanilla.
  harder    same gaps, but Legendary stays vanilla and the rest goes down
            (Common too). No gear gets stronger than vanilla.

The table shows the effect on a real example: the median attack of the most
common weapon type in the installed game. Export: one Field JSON (format 3.1)
for DMM, incl. the DLC-only items, every intent checked with apply_intents
(presets_engine.build_targets).
"""
from __future__ import annotations

import json
import logging
import os
import statistics

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from gui.theme import COLORS, button_css
from gui.utils import make_scope_label, ui_card, ui_dim, ui_info, ui_title
from presets_engine import (RARITY_LEVELS, RARITY_STATS, RARITY_STEP, TABLE_DIR, _rarity_matters,
                            build_targets, rarity_factors)

log = logging.getLogger(__name__)

TIERS = [(1, "Common"), (2, "Uncommon"), (3, "Rare"), (4, "Epic"), (5, "Legendary")]
TIER_COLORS = {1: "#b0b0b0", 2: "#6BCB77", 3: "#4FC3F7", 4: "#B57BFF", 5: "#FFB347"}
REFINES = (0, 5, 10)
FALLBACK = {0: 11000, 5: 20000, 10: 33000}      # game 2.05, if the game cannot be read

INFO = ("In the game, rarity barely matters: at the same refinement level a Common and a "
        "Legendary weapon have almost the same attack and defense. This page changes that.\n\n"
        "Stronger: rarer gear gets more attack and defense than in the game. Common stays.\n"
        "Harder: Legendary stays as in the game, all lower rarities get weaker (Common too). "
        "No gear is stronger than in the game.\n\n"
        "The percentage is the same at every refinement level (+0 to +10), so refining still "
        "matters. Includes the DLC items (DMM skips them without the DLC).")


def _fmt(v: float) -> str:
    return f"{int(round(v)):,}".replace(",", " ")


def _pct(f: float) -> str:
    p = (f - 1.0) * 100.0
    if abs(p) < 0.05:
        return "unchanged"
    txt = f"{p:+.1f}".rstrip("0").rstrip(".")
    return txt.replace("-", "−") + " %"


class RarityTab(QWidget):
    status_message = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._game_path = config.get("game_install_path", "") or ""
        self._recs: list = []
        self._sample = dict(FALLBACK)
        self._sample_from_game = False
        self._loaded = False
        self._build_ui()
        self._refresh()

    def set_game_path(self, path: str) -> None:
        if (path or "") != self._game_path:
            self._game_path = path or ""
            self._loaded = False

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(10)
        lay.addWidget(make_scope_label("game"))

        head, hv = ui_card()
        t = QHBoxLayout()
        t.addWidget(ui_title("Rarity Matters"), 1)
        t.addWidget(ui_info(INFO))
        hv.addLayout(t)
        hv.addWidget(ui_dim("Rarer gear should be better: choose how strongly rarity counts. "
                            "The table below shows what it does to attack."))
        row = QHBoxLayout()
        row.addWidget(ui_dim("Mode", True))
        self._mode = QComboBox()
        self._mode.addItem("Stronger - rarer gear above vanilla", "stronger")
        self._mode.addItem("Harder - Legendary stays vanilla, lower rarities weaker", "harder")
        self._mode.currentIndexChanged.connect(self._mode_changed)
        row.addWidget(self._mode, 2)
        row.addSpacing(12)
        row.addWidget(ui_dim("Level", True))
        self._level = QComboBox()
        self._level.currentIndexChanged.connect(lambda _i: self._refresh())
        row.addWidget(self._level, 2)
        hv.addLayout(row)
        lay.addWidget(head)

        card, cv = ui_card()
        cv.addWidget(ui_title("What it does", 13))
        self._table = QTableWidget(len(TIERS), 2 + len(REFINES))
        self._table.setHorizontalHeaderLabels(
            ["Rarity", "Change"] + [f"+{r}" for r in REFINES])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setFocusPolicy(Qt.NoFocus)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cv.addWidget(self._table)
        self._note = ui_dim("")
        cv.addWidget(self._note)
        self._count = ui_dim("")
        cv.addWidget(self._count)
        lay.addWidget(card)

        bar = QHBoxLayout()
        save = QPushButton("Save as mod (Field JSON)")
        save.setStyleSheet("QPushButton { " + button_css("success") + " font-weight: bold; "
                           "padding: 6px 16px; }")
        save.setToolTip("Saves one mod file for DMM with the chosen mode and level.")
        save.clicked.connect(self._export)
        bar.addWidget(save)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {COLORS['text_dim']};")
        bar.addWidget(self._status, 1)
        lay.addLayout(bar)
        lay.addStretch(1)
        self._fill_levels()

    def _fill_levels(self) -> None:
        keep = self._level.currentData() or 5
        harder = self._mode.currentData() == "harder"
        self._level.blockSignals(True)
        self._level.clear()
        for n in RARITY_LEVELS:
            if harder:
                low = round((1.0 - rarity_factors(n, "harder")[1]) * 100)
                self._level.addItem(f"Level {n} - lower rarities down to -{low} %", n)
            else:
                self._level.addItem(f"Level {n} - up to +{n * RARITY_STEP} % over vanilla", n)
        self._level.setCurrentIndex(RARITY_LEVELS.index(keep))
        self._level.blockSignals(False)

    def _mode_changed(self, *_a) -> None:
        self._fill_levels()
        self._refresh()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._loaded:
            self._load()

    # ── data ──────────────────────────────────────────────────────────
    def _param(self):
        return (self._mode.currentData() or "stronger", self._level.currentData() or 5)

    def _load(self) -> None:
        self._loaded = True
        gp = self._game_path
        if not gp or not os.path.isdir(os.path.join(gp, "0008")):
            self._status.setText("Set the game folder to see the numbers of your game.")
            self._refresh()
            return
        self._status.setText("Reading iteminfo...")
        QApplication.processEvents()
        try:
            import dmm_parser
            body = bytes(dmm_parser.extract_file(gp, "0008", TABLE_DIR, "iteminfo.pabgb"))
            head = bytes(dmm_parser.extract_file(gp, "0008", TABLE_DIR, "iteminfo.pabgh"))
            self._recs = list(dmm_parser.parse_table("iteminfo", body, head))
            typical = self._typical_attack(self._recs)
            self._sample = typical or dict(FALLBACK)
            self._sample_from_game = typical is not None
            self._status.setText("")
        except Exception as e:  # noqa: BLE001
            log.warning("Rarity: iteminfo not read: %s", e)
            self._recs = []
            self._status.setText(f"Could not read the game ({e}) - showing example numbers.")
        self._refresh()

    @staticmethod
    def _attack(rec: dict, lv: int):
        el = rec.get("enchant_data_list") or []
        if len(el) <= lv:
            return None
        for s in ((el[lv].get("enchant_stat_data") or {}).get("stat_list_static") or []):
            v = s.get("change_mb")
            if s.get("stat") == RARITY_STATS[0] and isinstance(v, int) and v > 0:
                return v
        return None

    def _typical_attack(self, recs: list):
        """Median attack at +0/+5/+10 of the most common weapon type that has
        all five rarities."""
        groups: dict = {}
        for r in recs:
            t = r.get("item_tier")
            if t in (1, 2, 3, 4, 5) and self._attack(r, 10):
                groups.setdefault(r.get("equip_type_info"), {}).setdefault(t, []).append(r)
        full = [(sum(len(v) for v in g.values()), k) for k, g in groups.items() if len(g) == 5]
        if not full:
            return None
        _n, best = max(full)
        items = [r for v in groups[best].values() for r in v]
        out = {}
        for lv in REFINES:
            vals = [a for a in (self._attack(r, lv) for r in items) if a]
            if not vals:
                return None
            out[lv] = statistics.median(vals)
        return out

    # ── table ─────────────────────────────────────────────────────────
    def _refresh(self) -> None:
        mode, level = self._param()
        f = rarity_factors(level, mode)
        for row, (tier, name) in enumerate(TIERS):
            fac = f.get(tier, 1.0)
            cells = [name, _pct(fac)]
            for lv in REFINES:
                base = self._sample[lv]
                cells.append(_fmt(base) if abs(fac - 1.0) < 1e-9
                             else f"{_fmt(base)}  →  {_fmt(base * fac)}")
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignCenter if col else (Qt.AlignLeft | Qt.AlignVCenter))
                if col == 0:
                    it.setForeground(QBrush(QColor(TIER_COLORS[tier])))
                    fnt = it.font()
                    fnt.setBold(True)
                    it.setFont(fnt)
                elif col == 1 and abs(fac - 1.0) >= 1e-9:
                    it.setForeground(QBrush(QColor(COLORS.get("success", "#6BCB77") if fac > 1
                                                   else COLORS.get("error", "#E06C75"))))
                self._table.setItem(row, col, it)
        self._table.resizeRowsToContents()
        h = self._table.horizontalHeader().height() + 2 * self._table.frameWidth()
        self._table.setFixedHeight(h + sum(self._table.rowHeight(r) for r in range(len(TIERS))))
        self._note.setText(
            ("Numbers: median attack of the most common weapon type in your game, "
             if self._sample_from_game else "Numbers: typical weapon attack (example), ")
            + "vanilla → with this setting. Defense changes by the same percentages. "
              "The game's item texts keep showing the old numbers.")
        if self._recs:
            intents = _rarity_matters(self._recs, (mode, level))
            items = len({i["key"] for i in intents})
            self._count.setText(f"This setting changes {_fmt(len(intents))} values in "
                                f"{_fmt(items)} items (+ DLC items).")
        else:
            self._count.setText("")

    # ── export ────────────────────────────────────────────────────────
    def _export(self) -> None:
        gp = self._game_path or self._config.get("game_install_path", "")
        if not gp or not os.path.isfile(os.path.join(gp, "meta", "0.papgt")):
            QMessageBox.warning(self, "Rarity Matters", "Set the game folder first.")
            return
        mode, level = self._param()
        label = self._level.currentText()
        default = f"RarityMatters_{'Harder' if mode == 'harder' else 'Stronger'}_L{level}.field.json"
        path, _ = QFileDialog.getSaveFileName(self, "Save as mod", default,
                                              "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            return
        try:
            targets = build_targets(gp, {"rarity_matters": (mode, level)},
                                    lambda m: (self._status.setText(m),
                                               QApplication.processEvents()))
        except Exception as e:  # noqa: BLE001
            log.warning("Rarity export failed: %s", e)
            self._status.setText(f"Failed: {e}")
            QMessageBox.critical(self, "Rarity Matters", str(e))
            return
        n = sum(len(i) for _s, i, _r in targets)
        items = len({x["key"] for _s, i, _r in targets for x in i})
        title = "Rarity Matters" + (" (Harder)" if mode == "harder" else "")
        doc = {
            "modinfo": {"title": title, "version": "1.0", "author": "CrimsonGameMods",
                        "description": f"{label}: rarer gear is better ({n} values in "
                                       f"{items} items, incl. DLC items).",
                        "note": "Format 3 - field names, survives game updates"},
            "format": 3, "format_minor": 1,
            "targets": [{"file": f"{stem}.pabgb", "intents": intents}
                        for stem, intents, _r in targets],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
        self._status.setText(f"Saved {n} changes to {os.path.basename(path)}")
        self.status_message.emit(f"Rarity Matters saved: {os.path.basename(path)}")
        QMessageBox.information(
            self, "Save as mod",
            f"Saved {n} changes in {items} items, all checked.\n\n"
            f"Load the file in DMM, activate it and mount.\n\nFile: {path}")
