"""Bigger item pictures: hover over an item icon in any list for a large
preview, click it for a window with the full 256 px picture.

One event filter on the application covers every table (Game Mods, Save
Editor, Items), so no list needs its own code. It only reacts to cells that
carry an icon; everything else passes through untouched.
"""
from __future__ import annotations

import html
import os
import tempfile

from PySide6.QtCore import QEvent, QObject, Qt, QPoint
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QLabel, QToolTip,
                               QVBoxLayout)

_PREVIEW_PX = 160      # tooltip
_WINDOW_PX = 256       # click window (the pictures are 256 x 256)


class IconPreview(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dir = os.path.join(tempfile.gettempdir(), "crimson_gamemods_icons")
        self._files = {}
        self._window = None

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _pixmap(index):
        deco = index.data(Qt.DecorationRole)
        if isinstance(deco, QIcon) and not deco.isNull():
            sizes = deco.availableSizes()
            size = max(sizes, key=lambda s: s.width()) if sizes else None
            return deco.pixmap(size) if size else deco.pixmap(_WINDOW_PX, _WINDOW_PX)
        if isinstance(deco, QPixmap) and not deco.isNull():
            return deco
        return None

    @staticmethod
    def _row_name(index) -> str:
        model = index.model()
        for col in range(model.columnCount()):
            text = model.index(index.row(), col).data(Qt.DisplayRole)
            if isinstance(text, str) and any(ch.isalpha() for ch in text):
                return text
        return ""

    def _png_path(self, pixmap: QPixmap) -> str:
        key = pixmap.cacheKey()
        path = self._files.get(key)
        if path and os.path.isfile(path):
            return path
        os.makedirs(self._dir, exist_ok=True)
        path = os.path.join(self._dir, f"{key & 0xFFFFFFFFFFFF:x}.png")
        pixmap.save(path, "PNG")
        self._files[key] = path
        return path

    def _show_window(self, pixmap: QPixmap, name: str, parent) -> None:
        if self._window is not None:
            self._window.close()
        dlg = QDialog(parent.window() if parent is not None else None)
        dlg.setWindowTitle(name or "Item")
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(dlg)
        pic = QLabel()
        pic.setAlignment(Qt.AlignCenter)
        pic.setPixmap(pixmap.scaled(_WINDOW_PX, _WINDOW_PX, Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation))
        lay.addWidget(pic)
        if name:
            cap = QLabel(name)
            cap.setAlignment(Qt.AlignCenter)
            cap.setStyleSheet("font-weight: bold; padding: 4px;")
            lay.addWidget(cap)
        dlg.mousePressEvent = lambda _e: dlg.close()
        dlg.show()
        self._window = dlg

    # -- filter -------------------------------------------------------------
    def eventFilter(self, obj, event):
        et = event.type()
        if et not in (QEvent.ToolTip, QEvent.MouseButtonRelease):
            return False
        view = obj.parent()
        if not isinstance(view, QAbstractItemView) or obj is not view.viewport():
            return False
        try:
            pos = event.pos() if et == QEvent.ToolTip else event.position().toPoint()
        except AttributeError:
            return False
        index = view.indexAt(pos)
        if not index.isValid():
            return False
        pixmap = self._pixmap(index)
        if pixmap is None or pixmap.width() < 8:
            return False
        name = self._row_name(index)
        if et == QEvent.ToolTip:
            path = self._png_path(pixmap)
            tip = (f"<img src='{html.escape(path)}' width='{_PREVIEW_PX}' height='{_PREVIEW_PX}'>"
                   + (f"<br><b>{html.escape(name)}</b>" if name else "")
                   + "<br><i>Click for a bigger view</i>")
            QToolTip.showText(event.globalPos(), tip, view)
            return True
        if event.button() == Qt.LeftButton and not index.data(Qt.DisplayRole):
            # Only icon-only cells (the picture column); a click on a name
            # still just selects the row.
            self._show_window(pixmap, name, view)
        return False
