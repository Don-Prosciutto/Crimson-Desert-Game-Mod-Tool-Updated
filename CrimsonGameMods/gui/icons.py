"""Small line icons, the app emblem and the window icon (new look, 2.5).

Icons are drawn from short SVG path strings (24x24, stroke only) with QtSvg,
in any colour, so they follow the theme. The emblem ("Abyss Cells": three
hexagons, the top one filled) is drawn with QPainter - no image files.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QLabel

# Line icons, 24x24 viewBox, stroke-only paths.
_ICONS: Dict[str, List[str]] = {
    "home": ["M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"],
    "mounts": ["M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18z", "m15.5 8.5-2 5-5 2 2-5z"],
    "characters": ["M20 21a8 8 0 0 0-16 0", "M12 12a4 4 0 1 0 0-8a4 4 0 0 0 0 8z"],
    "mesh": ["M17 2l4 4-4 4", "M3 11V9a3 3 0 0 1 3-3h15", "M7 22l-4-4 4-4", "M21 13v2a3 3 0 0 1-3 3H3"],
    "buffs": ["M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z",
              "M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"],
    "stacker": ["M12 2 2 7l10 5 10-5z", "M2 17l10 5 10-5", "M2 12l10 5 10-5"],
    "stores": ["M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z", "M3 6h18", "M16 10a4 4 0 0 1-8 0"],
    "bagspace": ["M21 8 12 3 3 8v8l9 5 9-5z", "M3 8l9 5 9-5", "M12 13v8"],
    "map": ["M9 4 3 6v14l6-2 6 2 6-2V4l-6 2z", "M9 4v14", "M15 6v14"],
    "drops": ["M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",
              "M8.5 8.5h.01", "M15.5 15.5h.01", "M12 12h.01"],
    "spawn": ["M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18z", "M12 1v5", "M12 18v5", "M1 12h5", "M18 12h5"],
    "skill": ["M6 3v12", "M18 9a3 3 0 1 0 0-6a3 3 0 0 0 0 6z", "M6 21a3 3 0 1 0 0-6a3 3 0 0 0 0 6z",
              "M18 9a9 9 0 0 1-9 9"],
    "pets": ["M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21l7.8-7.5 1-1.1a5.5 5.5 0 0 0 0-7.8z"],
    "browser": ["M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z", "M3 9h18", "M9 9v12"],
    "save": ["M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z", "M17 21v-8H7v8", "M7 3v5h8"],
    "equip": ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"],
    "socket": ["M6 3h12l4 6-10 13L2 9z", "M2 9h20", "M12 22 8 9l4-6 4 6z"],
    "swap": ["M16 3h5v5", "M4 20 21 3", "M21 16v5h-5", "M15 15l6 6", "M4 4l5 5"],
    "dye": ["M12 22a7 7 0 0 0 7-7c0-4-7-13-7-13S5 11 5 15a7 7 0 0 0 7 7z"],
    "quest": ["M9 11l3 3L22 4", "M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"],
    "world": ["M12 21a9 9 0 1 0 0-18a9 9 0 0 0 0 18z", "M3 12h18", "M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"],
    "knowledge": ["M4 19.5A2.5 2.5 0 0 1 6.5 17H20", "M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"],
    "gate": ["M12 2 21 7v10l-9 5-9-5V7z", "M12 8l4 2.5v4L12 17l-4-2.5v-4z"],
    "player": ["M12 12a4 4 0 1 0 0-8a4 4 0 0 0 0 8z", "M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"],
    "faction": ["M4 22V4", "M4 4h13l-2 4 2 4H4"],
    "backup": ["M21 8v13H3V8", "M1 3h22v5H1z", "M10 12h4"],
    "items": ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M14 14h7v7h-7z", "M3 14h7v7H3z"],
    "packs": ["M16.5 9.4 7.5 4.2", "M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.7z",
              "M3.3 7 12 12l8.7-5", "M12 22V12"],
    "presets": ["M4 21v-7", "M4 10V3", "M12 21v-9", "M12 8V3", "M20 21v-5", "M20 12V3",
                "M1 14h6", "M9 8h6", "M17 16h6"],
    "loader": ["M12 3v12", "m7 10 5 5 5-5", "M5 21h14"],
    "debug": ["M8 2l1.9 1.9", "M14.1 3.9 16 2", "M9 7.1V6a3 3 0 1 1 6 0v1.1",
              "M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6z", "M12 20v-9"],
    "dot": ["M12 15a3 3 0 1 0 0-6a3 3 0 0 0 0 6z"],
    "folder": ["M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"],
}

# Page label (lower case, start of the name) -> icon. First match wins.
_LABEL_ICON = [
    ("home", "home"), ("mount", "mounts"), ("character", "characters"), ("mesh", "mesh"),
    ("itembuff", "buffs"), ("buff", "buffs"), ("stacker", "stacker"), ("store", "stores"),
    ("bagspace", "bagspace"), ("map", "map"), ("dropset", "drops"), ("spawn", "spawn"),
    ("skilltree", "skill"), ("skill", "skill"), ("mercpet", "pets"), ("mercenar", "pets"),
    ("game browser", "browser"), ("pabgb", "browser"), ("game data", "browser"),
    ("presets", "presets"), ("load manager", "loader"), ("loader", "loader"),
    ("inventory", "save"), ("equipment", "equip"), ("socket", "socket"), ("item swap", "swap"),
    ("repurchase", "stores"), ("dye", "dye"), ("quest", "quest"), ("abyss", "gate"),
    ("waypoint", "map"), ("knowledge", "knowledge"), ("player", "player"), ("faction", "faction"),
    ("backup", "backup"), ("item database", "items"), ("item pack", "packs"), ("items", "items"),
    ("world", "world"), ("save editor", "save"), ("game mods", "stacker"), ("debug", "debug"),
    ("fieldedit", "mounts"), ("gpatch", "presets"),
]


def icon_name_for(label: str) -> str:
    low = (label or "").strip().lower()
    for key, name in _LABEL_ICON:
        if low.startswith(key) or key in low:
            return name
    return "dot"


_cache: Dict[tuple, QIcon] = {}


def icon(name: str, color: str, size: int = 18, stroke: float = 1.8) -> QIcon:
    """A line icon as QIcon in the given colour (cached)."""
    key = (name, color, size, stroke)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    paths = _ICONS.get(name) or _ICONS["dot"]
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
           + "".join(f'<path d="{d}"/>' for d in paths) + "</svg>")
    ic = QIcon()
    try:
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        for scale in (1, 2):
            px = size * scale
            img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            r.render(p, QRectF(0, 0, px, px))
            p.end()
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(scale)
            ic.addPixmap(pm)
    except Exception:  # noqa: BLE001 - no QtSvg: no icon, never a crash
        pass
    _cache[key] = ic
    return ic


# ── emblem ─────────────────────────────────────────────────────────────────

_HEX_TOP = [(50, 8), (66, 17), (66, 35), (50, 44), (34, 35), (34, 17)]
_HEX_LEFT = [(33, 38), (49, 47), (49, 65), (33, 74), (17, 65), (17, 47)]
_HEX_RIGHT = [(67, 38), (83, 47), (83, 65), (67, 74), (51, 65), (51, 47)]


def paint_emblem(p: QPainter, rect: QRectF, color: str = "#2DD4BF") -> None:
    """Draw the emblem into rect (a 100x100 design scaled to fit)."""
    s = min(rect.width(), rect.height()) / 100.0
    ox = rect.x() + (rect.width() - 100 * s) / 2
    oy = rect.y() + (rect.height() - 100 * s) / 2

    def poly(pts):
        return QPolygonF([QPointF(ox + x * s, oy + y * s) for x, y in pts])

    col = QColor(color)
    width = max(1.2, 6 * s if s * 100 < 48 else 4 * s)
    pen = QPen(col, width)
    pen.setJoinStyle(Qt.RoundJoin)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(pen)
    p.setBrush(col)
    p.drawPolygon(poly(_HEX_TOP))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(poly(_HEX_LEFT))
    p.drawPolygon(poly(_HEX_RIGHT))
    p.restore()


def emblem_pixmap(size: int, color: str = "#2DD4BF", dpr: float = 2.0) -> QPixmap:
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    paint_emblem(p, QRectF(0, 0, px, px), color)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def window_icon(color: str = "#2DD4BF", tile: Optional[str] = "#0A101C") -> QIcon:
    """The emblem on a dark rounded tile, in the usual window-icon sizes."""
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        if tile:
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
            p.fillPath(path, QColor(tile))
        m = size * 0.1
        paint_emblem(p, QRectF(m, m, size - 2 * m, size - 2 * m), color)
        p.end()
        ic.addPixmap(QPixmap.fromImage(img))
    return ic


class ElidedLabel(QLabel):
    """A one-line label that shortens a long text in the middle ("D:/Ste…
    Desert") instead of cutting it off; text() returns the full text."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text or ""
        self._elide()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        w = max(20, self.width() - 16)
        QLabel.setText(self, self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, w))
