"""A small dialog: tick several entries of a list (with a colour swatch)."""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)


def _swatch(hexc: Optional[str]) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(QColor(hexc) if hexc else QColor(0, 0, 0, 0))
    return QIcon(pm)


def pick_several(parent, title: str, text: str, items: List[Tuple[str, Optional[str]]],
                 checked: Optional[List[str]] = None) -> Optional[List[str]]:
    """items: (label, '#rrggbb' or None). Returns the ticked labels in list
    order, or None when cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(340)
    lay = QVBoxLayout(dlg)
    lab = QLabel(text)
    lab.setWordWrap(True)
    lay.addWidget(lab)
    lst = QListWidget()
    pre = set(checked or [])
    for label, hexc in items:
        it = QListWidgetItem(_swatch(hexc), label)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if label in pre else Qt.Unchecked)
        lst.addItem(it)
    lay.addWidget(lst, 1)
    row = QHBoxLayout()
    for cap, state in (("All", Qt.Checked), ("None", Qt.Unchecked)):
        b = QPushButton(cap)
        b.clicked.connect(lambda _c=False, s=state: [lst.item(i).setCheckState(s)
                                                     for i in range(lst.count())])
        row.addWidget(b)
    row.addStretch()
    lay.addLayout(row)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    if dlg.exec() != QDialog.Accepted:
        return None
    return [lst.item(i).text() for i in range(lst.count())
            if lst.item(i).checkState() == Qt.Checked]
