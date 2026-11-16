"""Presets page - one-click value mods for tables that have no page of their own.

Each preset turns into Field JSON intents on the unmodded game table
(group 0008). The same intents are used two ways:
  * Export Field JSON - one multi-target mod file to install with DMM
    (recommended: DMM combines it with the other mods).
  * Apply to Game - DMM's own apply_intents builds the changed tables, which
    are written as one overlay group.
Before anything is exported or written, every intent must apply.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from typing import Dict, Optional, Tuple

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget, QScrollArea, QApplication,
)

from gui.theme import COLORS, button_css
from gui.utils import make_scope_label

from presets_engine import PRESETS, TABLE_DIR, DEFAULT_GROUP, MARKER, build_targets, other_overlays_with

log = logging.getLogger(__name__)


# ── page ────────────────────────────────────────────────────────────────

class PresetsTab(QWidget):
    status_message = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._game_path = config.get("game_install_path", "")
        self._rows: Dict[str, Tuple[QCheckBox, Optional[QComboBox]]] = {}
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._game_path = path or ""

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        lay.addWidget(make_scope_label("game"))
        intro = QLabel(
            "One-click mods for game values that have no page of their own. Tick what you "
            "want, then Export Field JSON and install the file with DMM (recommended - DMM "
            "combines it with your other mods), or Apply to Game.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        lay.addWidget(intro)

        cards = QWidget()
        cl = QVBoxLayout(cards)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        for p in PRESETS:
            card = QFrame()
            card.setStyleSheet(f"QFrame {{ border: 1px solid {COLORS['border']}; "
                               f"border-radius: 6px; background: {COLORS['panel']}; }}")
            h = QHBoxLayout(card)
            h.setContentsMargins(10, 8, 10, 8)
            v = QVBoxLayout()
            cb = QCheckBox(p["title"])
            cb.setStyleSheet("QCheckBox { font-weight: bold; border: none; }")
            v.addWidget(cb)
            d = QLabel(f"{p['desc']}\nTable: {p['table']}")
            d.setStyleSheet(f"color: {COLORS['text_dim']}; border: none;")
            d.setWordWrap(True)
            v.addWidget(d)
            h.addLayout(v, 1)
            combo = None
            if p.get("choices"):
                combo = QComboBox()
                names = p.get("choice_names") or []
                for i, c in enumerate(p["choices"]):
                    text = names[i] if i < len(names) else f"{p.get('choice_label', '')}{c}"
                    combo.addItem(text, c)
                combo.setCurrentIndex(p["choices"].index(p.get("default", p["choices"][0])))
                h.addWidget(combo)
            self._rows[p["id"]] = (cb, combo)
            cl.addWidget(card)
        cl.addWidget(self._build_lumen_card())
        cl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(cards)
        lay.addWidget(scroll, 1)

        bar = QHBoxLayout()
        exp = QPushButton("Export Field JSON (for DMM)")
        exp.setStyleSheet("QPushButton { " + button_css("success") + " font-weight: bold; "
                          "padding: 6px 16px; }")
        exp.clicked.connect(self._export)
        bar.addWidget(exp)
        app = QPushButton("Apply to Game")
        app.clicked.connect(self._apply)
        bar.addWidget(app)
        rem = QPushButton("Remove from Game")
        rem.clicked.connect(self._remove)
        bar.addWidget(rem)
        bar.addStretch(1)
        bar.addWidget(QLabel("Overlay:"))
        self._group_spin = QSpinBox()
        self._group_spin.setRange(41, 9999)
        self._group_spin.setValue(int(self._config.get("presets_overlay_group", DEFAULT_GROUP)))
        self._group_spin.setToolTip("Folder number for Apply to Game (0041 and up; "
                                    "0000-0040 belong to the game)")
        bar.addWidget(self._group_spin)
        lay.addLayout(bar)
        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {COLORS['accent']}; padding: 2px;")
        lay.addWidget(self._status)

    # ── Weapon effect colour (own mod, byte patch) ──
    def _build_lumen_card(self) -> QFrame:
        import weapon_colors
        card = QFrame()
        card.setStyleSheet(f"QFrame {{ border: 1px solid {COLORS['border']}; "
                           f"border-radius: 6px; background: {COLORS['panel']}; }}")
        h = QHBoxLayout(card)
        h.setContentsMargins(10, 8, 10, 8)
        v = QVBoxLayout()
        t = QLabel("Weapon effect colour")
        t.setStyleSheet("font-weight: bold; border: none;")
        v.addWidget(t)
        d = QLabel("A weapon's glow in another colour, as bright as the game's - e.g. the "
                   "Lumen Sword's pink beam in blue. Saved as its own DMM mod.")
        d.setStyleSheet(f"color: {COLORS['text_dim']}; border: none;")
        d.setWordWrap(True)
        v.addWidget(d)
        h.addLayout(v, 1)
        self._lumen_weapon = QComboBox()
        self._lumen_weapon.setMinimumWidth(220)
        for wid, w in weapon_colors.WEAPONS.items():
            self._lumen_weapon.addItem(w["name"] + (" (DLC)" if w.get("dlc") else ""), wid)
        h.addWidget(self._lumen_weapon)
        self._lumen_combo = QComboBox()
        self._lumen_combo.setMinimumWidth(150)
        for name, hexc in weapon_colors.PRESETS:
            self._lumen_combo.addItem(self._swatch_icon(hexc), name, hexc)
        self._lumen_combo.currentIndexChanged.connect(lambda _i: self._lumen_update_swatch())
        h.addWidget(self._lumen_combo)
        custom = QPushButton("Custom…")
        custom.setToolTip("Pick any colour")
        custom.clicked.connect(self._lumen_custom)
        h.addWidget(custom)
        self._lumen_swatch = QLabel()
        self._lumen_swatch.setFixedSize(26, 26)
        h.addWidget(self._lumen_swatch)
        save = QPushButton("Save as mod")
        save.setStyleSheet("QPushButton { " + button_css("primary") + " font-weight: bold; "
                           "padding: 6px 14px; }")
        save.setToolTip("Saves a DMM mod that recolours the effect (load it in DMM and mount).")
        save.clicked.connect(self._lumen_save)
        h.addWidget(save)
        self._lumen_update_swatch()
        return card

    @staticmethod
    def _swatch_icon(hexc: str) -> QIcon:
        pm = QPixmap(14, 14)
        pm.fill(QColor(hexc))
        return QIcon(pm)

    def _lumen_color(self) -> str:
        return self._lumen_combo.currentData() or "#2f6bff"

    def _lumen_update_swatch(self) -> None:
        self._lumen_swatch.setStyleSheet(
            f"background: {self._lumen_color()}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 4px;")

    def _lumen_custom(self) -> None:
        c = QColorDialog.getColor(QColor(self._lumen_color()), self, "Weapon effect colour")
        if not c.isValid():
            return
        hexc = c.name()
        for i in range(self._lumen_combo.count()):
            if self._lumen_combo.itemData(i) == hexc:
                self._lumen_combo.setCurrentIndex(i)
                return
        self._lumen_combo.addItem(self._swatch_icon(hexc), hexc.upper(), hexc)
        self._lumen_combo.setCurrentIndex(self._lumen_combo.count() - 1)

    def _lumen_save(self) -> None:
        import weapon_colors
        gp = self._game_path or self._config.get("game_install_path", "")
        if not gp or not os.path.isfile(os.path.join(gp, "meta", "0.papgt")):
            QMessageBox.warning(self, "Weapon effect colour", "Set the game folder first.")
            return
        hexc = self._lumen_color()
        wid = self._lumen_weapon.currentData() or "lumen"
        wname = weapon_colors.WEAPONS[wid]["name"]
        cname = self._lumen_combo.currentText()
        try:
            mod = weapon_colors.build_mod(weapon_colors.read_files(gp, wid), hexc,
                                         title=f"{wname} - {cname}", weapon=wid)
        except Exception as e:  # noqa: BLE001
            log.warning("Weapon effect colour failed: %s", e)
            QMessageBox.critical(self, "Weapon effect colour", str(e))
            return
        fname = (wname.split("/")[0].strip() + "_" + cname).replace("#", "").replace(" ", "")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as mod", f"{fname}.json", "DMM mod (*.json);;All Files (*)")
        if not path:
            return
        weapon_colors.write_mod(path, mod)
        n = sum(len(p["changes"]) for p in mod["patches"])
        self._status.setText(f"{wname}: {n} colour values saved to {os.path.basename(path)}")
        QMessageBox.information(
            self, "Save as mod",
            f"Saved ({n} colour values).\n\nLoad the file in DMM, activate it and mount. "
            f"Only one colour mod per weapon at a time.\n\nFile: {path}")

    # ── helpers ──
    def _chosen(self) -> Dict[str, object]:
        out = {}
        for pid, (cb, combo) in self._rows.items():
            if cb.isChecked():
                out[pid] = combo.currentData() if combo is not None else None
        return out

    def _progress(self, msg: str) -> None:
        self._status.setText(msg)
        QApplication.processEvents()

    def _targets(self):
        gp = self._game_path or self._config.get("game_install_path", "")
        if not gp or not os.path.isfile(os.path.join(gp, "meta", "0.papgt")):
            QMessageBox.warning(self, "Presets", "Set the game folder first.")
            return None, None
        chosen = self._chosen()
        if not chosen:
            QMessageBox.information(self, "Presets", "Tick at least one preset.")
            return None, None
        try:
            return gp, build_targets(gp, chosen, self._progress)
        except Exception as e:  # noqa: BLE001
            log.warning("Presets failed: %s", e)
            self._status.setText(f"Failed: {e}")
            QMessageBox.critical(self, "Presets", str(e))
            return None, None

    def _titles(self) -> str:
        return ", ".join(p["title"] for p in PRESETS if p["id"] in self._chosen())

    # ── actions ──
    def _export(self) -> None:
        gp, targets = self._targets()
        if not targets:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Field JSON", "CGM_Presets.field.json",
            "Field JSON (*.field.json *.json);;All Files (*)")
        if not path:
            self._status.setText("")
            return
        n = sum(len(i) for _s, i, _r in targets)
        doc = {
            "modinfo": {"title": "CGM Presets", "version": "1.0",
                        "author": "CrimsonGameMods Presets",
                        "description": self._titles(),
                        "note": "Format 3 - field names, survives game updates"},
            "format": 3, "format_minor": 1,
            "targets": [{"file": f"{stem}.pabgb", "intents": intents}
                        for stem, intents, _r in targets],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1, ensure_ascii=False)
        self._status.setText(f"Exported {n} changes to {os.path.basename(path)}")
        QMessageBox.information(
            self, "Export Field JSON",
            f"{n} changes in {len(targets)} table(s), all checked with DMM's own apply.\n\n"
            f"File: {path}\n\nInstall it with DMM like any other mod.")

    def _apply(self) -> None:
        gp, targets = self._targets()
        if not targets:
            return
        from gui.utils import resolve_overlay_group
        num = resolve_overlay_group(gp, self._group_spin.value(), "Presets", parent=self)
        if num is None:
            self._status.setText("")
            return
        self._group_spin.setValue(num)
        grp = f"{num:04d}"
        stems = [s for s, _i, _r in targets]
        others = other_overlays_with(gp, stems, grp)
        warn = ""
        if others:
            warn = ("\n\nOther mods also change these tables:\n" + "\n".join(
                f"  {s}: {', '.join(g)}" for s, g in others.items()) +
                "\nApply builds the tables from the unmodded game, so only one version "
                "can win. To combine them, use Export Field JSON and install it with DMM.")
        if QMessageBox.question(
                self, "Apply Presets",
                f"Write {self._titles()} into overlay {grp}?{warn}\n\nRestart the game afterwards.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            self._status.setText("")
            return
        try:
            import dmm_parser
            from overlay_coordinator import safe_rmtree, safe_papgt_add
            with tempfile.TemporaryDirectory() as tmp:
                build = os.path.join(tmp, grp)
                b = dmm_parser.PackGroupBuilder(build, dmm_parser.Compression.NONE,
                                                dmm_parser.Crypto.NONE)
                for stem, _i, res in targets:
                    b.add_file(TABLE_DIR, f"{stem}.pabgb", bytes(res["body"]))
                    if res.get("pabgh"):
                        b.add_file(TABLE_DIR, f"{stem}.pabgh", bytes(res["pabgh"]))
                    else:
                        b.add_file(TABLE_DIR, f"{stem}.pabgh", bytes(dmm_parser.extract_file(
                            gp, "0008", TABLE_DIR, f"{stem}.pabgh")))
                checksum = dmm_parser.parse_pamt_bytes(bytes(b.finish()))["checksum"]
                dst = os.path.join(gp, grp)
                if os.path.isdir(dst):
                    safe_rmtree(dst)
                os.makedirs(dst, exist_ok=True)
                for fn in os.listdir(build):
                    shutil.copy2(os.path.join(build, fn), os.path.join(dst, fn))
                with open(os.path.join(dst, MARKER), "w", encoding="utf-8") as f:
                    f.write(f"CrimsonGameMods Presets: {self._titles()}\n")
            msg = safe_papgt_add(gp, grp, checksum)
            try:
                from shared_state import record_overlay
                record_overlay(gp, grp, "Presets", [f"{s}.pabgb" for s in stems])
            except Exception:  # noqa: BLE001
                pass
            self._config["presets_overlay_group"] = num
            self._status.setText(f"Applied to {grp}. {msg}")
            self.status_message.emit(f"Presets written to {grp}/")
            QMessageBox.information(self, "Apply Presets",
                                    f"Written to {os.path.join(gp, grp)}.\n\nRestart the game.")
        except Exception as e:  # noqa: BLE001
            log.warning("Presets apply failed: %s", e)
            self._status.setText(f"Apply failed: {e}")
            QMessageBox.critical(self, "Apply Presets", str(e))

    def _remove(self) -> None:
        gp = self._game_path or self._config.get("game_install_path", "")
        grp = f"{self._group_spin.value():04d}"
        dst = os.path.join(gp, grp)
        if not gp or not os.path.isfile(os.path.join(dst, MARKER)):
            QMessageBox.information(self, "Presets",
                                    f"No Presets overlay in {grp}/ - nothing to remove.")
            return
        if QMessageBox.question(self, "Remove Presets", f"Remove the Presets overlay {grp}/?",
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            from overlay_coordinator import remove_papgt_groups, safe_rmtree
            remove_papgt_groups(gp, [grp])
            safe_rmtree(dst)
            self._status.setText(f"Removed {grp}/.")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Remove Presets", str(e))
