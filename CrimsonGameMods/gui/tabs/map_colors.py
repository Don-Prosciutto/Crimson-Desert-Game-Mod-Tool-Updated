"""Map Colors page: pick a colour scheme for the world map and save it as a mod.

Presets plus a colour button per part of the map. The schematic preview is
drawn here (it is not the game's renderer); the mod changes the colour values
in ui/worldmapview.css as a DMM byte patch (map_colors.py).
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import map_colors as mc
from gui.theme import COLORS
from gui.utils import make_scope_label

log = logging.getLogger(__name__)


class _Preview(QWidget):
    """A small drawn map: sea, an island with coast, mountains, roads,
    fog and an abyss patch - enough to judge a colour scheme."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._c: Dict[str, str] = {}
        self.setMinimumSize(420, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_colors(self, colors: Dict[str, str]) -> None:
        self._c = dict(colors)
        self.update()

    def _q(self, role: str, fallback: str = "#808080", alpha: int = 255) -> QColor:
        c = QColor(self._c.get(role) or fallback)
        c.setAlpha(alpha)
        return c

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), self._q("sea"))
        sx, sy = w / 420.0, h / 300.0

        def pt(x, y):
            return QPointF(x * sx, y * sy)

        island = QPolygonF([pt(*xy) for xy in (
            (60, 70), (140, 40), (230, 55), (300, 45), (360, 90), (370, 160), (330, 230),
            (250, 260), (170, 250), (110, 270), (55, 220), (40, 140))])
        p.setPen(QPen(self._q("sea_line"), 9 * sx))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(island)
        p.setPen(QPen(self._q("land_line"), 2.5 * sx))
        p.setBrush(QBrush(self._q("paper")))
        p.drawPolygon(island)

        # height lines
        p.setPen(QPen(self._q("height", alpha=170), 1.2 * sx))
        p.setBrush(Qt.NoBrush)
        for r in (38, 54, 70):
            p.drawEllipse(pt(250, 120), r * sx, r * 0.6 * sy)
        # mountains
        p.setPen(QPen(self._q("mountain_line"), 1.6 * sx))
        p.setBrush(QBrush(self._q("mountain")))
        for (x, y, s) in ((230, 120, 26), (262, 108, 32), (292, 128, 22), (120, 110, 20)):
            p.drawPolygon(QPolygonF([pt(x - s, y + s * 0.7), pt(x, y - s * 0.7), pt(x + s, y + s * 0.7)]))
        # roads
        road = QPainterPath(pt(80, 200))
        road.cubicTo(pt(140, 170), pt(190, 210), pt(240, 190))
        road.cubicTo(pt(290, 170), pt(320, 200), pt(345, 175))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(self._q("road_line"), 6 * sx, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(road)
        p.setPen(QPen(self._q("road"), 3.2 * sx, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(road)
        wagon = QPainterPath(pt(150, 240))
        wagon.cubicTo(pt(170, 215), pt(160, 190), pt(185, 160))
        p.setPen(QPen(self._q("wagon"), 2.4 * sx, Qt.DashLine, Qt.RoundCap))
        p.drawPath(wagon)
        # restricted / wanted / religion markers
        p.setPen(Qt.NoPen)
        p.setBrush(self._q("restricted", "#802020", 120))
        p.drawEllipse(pt(110, 160), 20 * sx, 14 * sy)
        p.setBrush(self._q("religion", "#8fd6ff", 90))
        p.drawEllipse(pt(320, 140), 18 * sx, 12 * sy)
        # fog over the east
        fog = QPainterPath()
        fog.addRoundedRect(QRectF(pt(330, 20), pt(420, 300)), 18 * sx, 18 * sy)
        p.setBrush(self._q("fog", alpha=200))
        p.drawPath(fog)
        # abyss patch (hexes)
        p.setPen(QPen(self._q("abyss_fog"), 1.2 * sx))
        p.setBrush(self._q("abyss"))
        for (cx, cy) in ((30, 30), (52, 30), (41, 48)):
            r = 11
            hexagon = QPolygonF([pt(cx + r * dx, cy + r * dy) for dx, dy in (
                (1, 0), (0.5, 0.87), (-0.5, 0.87), (-1, 0), (-0.5, -0.87), (0.5, -0.87))])
            p.drawPolygon(hexagon)
        p.setPen(QColor(COLORS.get("text_dim", "#8b8f98")))
        p.drawText(self.rect().adjusted(6, 0, -6, -4), Qt.AlignBottom | Qt.AlignRight,
                   "schematic preview")
        p.end()


class MapColorsTab(QWidget):
    status_message = Signal(str)

    _MY = "My: "   # prefix of the user's own presets in the list

    def __init__(self, config: dict, save_config: Optional[Callable[[], None]] = None, parent=None):
        super().__init__(parent)
        self._config = config
        self._save_config = save_config
        self._css: Optional[bytes] = None
        self._game: Dict[str, str] = {}
        self._colors: Dict[str, str] = {}
        self._buttons: Dict[str, QPushButton] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)
        outer.addWidget(make_scope_label("game"))
        info = QLabel(
            "Give the world map a colour scheme: pick a preset or set each part yourself, "
            "then Save as mod and load the file in DMM. Disable it there for the original "
            "colours. Only the map's colours change - icons and text stay. Your own schemes: "
            "change the colours, then Save as my preset - they stay in the list.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {COLORS['text_dim']};")
        outer.addWidget(info)

        top = QHBoxLayout()
        top.addWidget(QLabel("Preset:"))
        self._preset = QComboBox()
        self._preset.setMinimumWidth(180)
        self._preset.currentIndexChanged.connect(lambda _i: self._apply_selected())
        top.addWidget(self._preset)
        reset = QPushButton("Reset to game colours")
        reset.clicked.connect(lambda: self._select("Original"))
        top.addWidget(reset)
        top.addStretch()
        save = QPushButton("Save as mod...")
        save.setObjectName("accentBtn")
        save.clicked.connect(self._save)
        top.addWidget(save)
        outer.addLayout(top)

        mine = QHBoxLayout()
        b = QPushButton("Save as my preset...")
        b.setToolTip("Keep the current colours under a name of your own")
        b.clicked.connect(self._save_preset)
        mine.addWidget(b)
        self._delete_btn = QPushButton("Delete my preset")
        self._delete_btn.clicked.connect(self._delete_preset)
        mine.addWidget(self._delete_btn)
        b = QPushButton("Load colours from a mod...")
        b.setToolTip("Read the colours of a map colour mod (one made here, or e.g. Dark Mode Map)")
        b.clicked.connect(self._load_mod)
        mine.addWidget(b)
        mine.addStretch()
        outer.addLayout(mine)

        body = QHBoxLayout()
        grp = QGroupBox("Colours")
        grid = QGridLayout(grp)
        grid.setVerticalSpacing(4)
        for i, (role, label, _t) in enumerate(mc.ROLES):
            grid.addWidget(QLabel(label), i, 0)
            b = QPushButton()
            b.setFixedSize(84, 22)
            b.setToolTip("Click to choose a colour")
            b.clicked.connect(lambda _c=False, r=role: self._pick(r))
            self._buttons[role] = b
            grid.addWidget(b, i, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(grp)
        scroll.setMinimumWidth(300)
        body.addWidget(scroll, 0)
        self._preview = _Preview()
        body.addWidget(self._preview, 1)
        outer.addLayout(body, 1)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {COLORS['text_dim']};")
        outer.addWidget(self._status)
        self._fill_presets()

    # ── presets ───────────────────────────────────────────────────────────

    def _mine(self) -> Dict[str, Dict[str, str]]:
        d = self._config.get("map_colors_presets")
        if not isinstance(d, dict):
            d = {}
            self._config["map_colors_presets"] = d
        return d

    def _store(self) -> None:
        if self._save_config:
            try:
                self._save_config()
            except Exception:  # noqa: BLE001
                log.exception("Map Colors: saving the settings failed")

    def _fill_presets(self, select: Optional[str] = None) -> None:
        cur = select or self._preset.currentText() or "Original"
        self._preset.blockSignals(True)
        self._preset.clear()
        self._preset.addItems(list(mc.PRESETS))
        mine = sorted(self._mine(), key=str.lower)
        if mine:
            self._preset.insertSeparator(self._preset.count())
            self._preset.addItems([self._MY + n for n in mine])
        i = self._preset.findText(cur)
        self._preset.setCurrentIndex(i if i >= 0 else 0)
        self._preset.blockSignals(False)
        self._delete_btn.setEnabled(self._preset.currentText().startswith(self._MY))

    def _preset_colors(self, name: str) -> Dict[str, str]:
        if name.startswith(self._MY):
            return dict(self._mine().get(name[len(self._MY):], {}))
        return dict(mc.PRESETS.get(name, {}))

    def _select(self, name: str) -> None:
        i = self._preset.findText(name)
        if i >= 0 and i != self._preset.currentIndex():
            self._preset.setCurrentIndex(i)      # -> _apply_selected
        else:
            self._apply_selected()

    def _apply_selected(self) -> None:
        name = self._preset.currentText()
        self._delete_btn.setEnabled(name.startswith(self._MY))
        self._colors = dict(self._game)
        self._colors.update(self._preset_colors(name))
        self._refresh()

    def _save_preset(self) -> None:
        cur = self._preset.currentText()
        start = cur[len(self._MY):] if cur.startswith(self._MY) else ""
        name, ok = QInputDialog.getText(self, "Save as my preset", "Name of your colour scheme:",
                                        text=start)
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in mc.PRESETS:
            QMessageBox.information(self, "Map Colors", f"'{name}' is a built-in preset - pick another name.")
            return
        mine = self._mine()
        if name in mine and QMessageBox.question(
                self, "Map Colors", f"Replace your preset '{name}'?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        mine[name] = {r: c for r, c in self._colors.items() if c.lower() != self._game.get(r, "").lower()} \
            if self._game else dict(self._colors)
        self._store()
        self._fill_presets(select=self._MY + name)
        self._apply_selected()
        self._status.setText(f"Saved your preset '{name}'.")

    def _delete_preset(self) -> None:
        cur = self._preset.currentText()
        if not cur.startswith(self._MY):
            return
        name = cur[len(self._MY):]
        if QMessageBox.question(self, "Map Colors", f"Delete your preset '{name}'?",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self._mine().pop(name, None)
        self._store()
        self._fill_presets(select="Original")
        self._apply_selected()
        self._status.setText(f"Deleted your preset '{name}'.")

    def _load_mod(self) -> None:
        if not self._ensure_loaded():
            QMessageBox.warning(self, "Map Colors", self._status.text())
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Load colours from a map colour mod",
            self._config.get("map_colors_dir", "") or os.path.expanduser("~"), "DMM mod (*.json)")
        if not path:
            return
        try:
            colors = mc.colors_from_mod(self._css, path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Map Colors", f"Could not read colours from this file:\n{e}")
            return
        if not colors:
            QMessageBox.information(self, "Map Colors", "This file changes none of the map colours.")
            return
        self._colors = dict(self._game)
        self._colors.update(colors)
        self._refresh()
        self._status.setText(f"Loaded {len(colors)} colours from {os.path.basename(path)} - "
                             "Save as my preset to keep them.")

    # ── data ──────────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> bool:
        if self._css is not None:
            return True
        gp = (self._config.get("game_install_path") or "").strip()
        if not gp or not os.path.isdir(gp):
            self._status.setText("Set the game folder first (top of the window).")
            return False
        try:
            self._css = mc.read_css(gp)
            self._game = mc.current_roles(self._css)
        except Exception as e:  # noqa: BLE001
            log.exception("Map Colors: worldmapview.css not readable")
            self._status.setText(f"The map's colour file could not be read: {e}")
            return False
        n = len(mc.find_colors(self._css))
        self._status.setText(f"Read {n} map colours from the game.")
        self._apply_selected()
        return True

    def showEvent(self, e):  # noqa: N802
        self._ensure_loaded()
        super().showEvent(e)

    def _refresh(self) -> None:
        for role, b in self._buttons.items():
            c = self._colors.get(role, "#808080")
            light = QColor(c).lightness() > 140
            b.setText(c)
            b.setStyleSheet(f"background: {c}; color: {'#111' if light else '#eee'}; "
                            f"border: 1px solid {COLORS['border']}; border-radius: 3px;")
        self._preview.set_colors(self._colors)

    def _pick(self, role: str) -> None:
        c = QColorDialog.getColor(QColor(self._colors.get(role, "#808080")), self,
                                  dict((r, l) for r, l, _t in mc.ROLES).get(role, role))
        if c.isValid():
            self._colors[role] = c.name()
            self._refresh()

    def _save(self) -> None:
        if not self._ensure_loaded():
            QMessageBox.warning(self, "Map Colors", self._status.text())
            return
        preset = self._preset.currentText()
        changed = {r: c for r, c in self._colors.items() if c.lower() != self._game.get(r, "").lower()}
        base = dict(self._game)
        base.update(self._preset_colors(preset))
        same = all(base.get(r, "").lower() == c.lower() for r, c in self._colors.items())
        shown = preset[len(self._MY):] if preset.startswith(self._MY) else preset
        title = f"Map Colors - {shown}" if same else "Map Colors - Custom"
        try:
            mod = mc.build_mod(self._css, changed, title=title)
        except ValueError as e:
            QMessageBox.information(self, "Map Colors", str(e))
            return
        fname = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in title.replace(" - ", "_"))
        start = os.path.join(self._config.get("map_colors_dir", "") or os.path.expanduser("~"),
                             fname + ".json")
        path, _ = QFileDialog.getSaveFileName(self, "Save map colours as mod", start,
                                              "DMM mod (*.json)")
        if not path:
            return
        try:
            mc.write_mod(path, mod)
        except OSError as e:
            QMessageBox.critical(self, "Map Colors", f"Could not write the file:\n{e}")
            return
        self._config["map_colors_dir"] = os.path.dirname(path)
        self._store()
        n = len(mod["patches"][0]["changes"])
        self._status.setText(f"Saved {os.path.basename(path)} ({n} colour values).")
        self.status_message.emit(f"Map colours saved: {path}")
        QMessageBox.information(
            self, "Map Colors",
            f"Saved {n} colour values to\n{path}\n\nLoad it in DMM and mount. "
            f"Use only one map colour mod at a time (also not together with other "
            f"map colour mods such as Dark Mode Map).")
