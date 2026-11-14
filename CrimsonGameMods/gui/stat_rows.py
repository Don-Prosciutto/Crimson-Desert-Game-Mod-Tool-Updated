"""Painting for the "Current stats and buffs" list in Edit items (new look 2.5).

The list is filled as plain text rows - "--- Sockets (3/5) ---" for a
section, "DDD (Damage) ← click to select for …" plus a value for an entry,
coloured and in Consolas. Other code reads and selects those rows, so they
stay as they are; this delegate only draws them differently:

  * a section row becomes a heading (no dashes) with a small bar in the
    section's colour and a line under it,
  * an "=== … ===" row becomes a quiet info line,
  * an entry shows its name in the normal font, the "← click to …" hint as
    a small pencil, and the value right-aligned and bold.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from gui.theme import COLORS

_SECTION = re.compile(r"^\s*-{2,}\s*(.*?)\s*-{2,}\s*$")
_INFO = re.compile(r"^\s*={2,}\s*(.*?)\s*={2,}\s*$")


def _strong() -> str:
    return COLORS.get("text_strong", COLORS["text"])


def _kind(index) -> tuple:
    """('section'|'info'|'entry', clean text, hint) for the row of `index`."""
    model = index.model() if index is not None and index.isValid() else None
    if model is None:
        return "none", "", ""
    first = model.index(index.row(), 0).data(Qt.DisplayRole) or ""
    m = _SECTION.match(first)
    if m:
        return "section", m.group(1), ""
    m = _INFO.match(first)
    if m:
        return "info", m.group(1).replace("Showing Enchant Level", "Enchant level"), ""
    text = index.data(Qt.DisplayRole) or ""
    hint = ""
    if index.column() == 0 and "←" in text:
        text, hint = text.split("←", 1)
    return "entry", text.strip(), hint.strip()


class StatRowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):  # noqa: N802
        return QSize(option.rect.width(), 32)

    def paint(self, painter, option, index):
        kind, text, hint = _kind(index)
        if kind == "none":
            return super().paint(painter, option, index)
        r = option.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        base = QFont(option.font)
        base.setFamilies(["Segoe UI", "Inter", "Noto Sans", "Arial"])
        own = index.model().index(index.row(), 0).data(Qt.ForegroundRole)
        accent = own.color() if hasattr(own, "color") else QColor(COLORS["accent"])

        if kind == "section":
            if index.column() == 0:
                f = QFont(base)
                f.setBold(True)
                f.setPointSizeF(max(9.0, base.pointSizeF() + 0.5))
                painter.setFont(f)
                bar = QRectF(r.left() + 6, r.top() + 9, 4, r.height() - 16)
                painter.setPen(Qt.NoPen)
                painter.setBrush(accent)
                painter.drawRoundedRect(bar, 2, 2)
                painter.setPen(QColor(_strong()))
                painter.drawText(r.adjusted(18, 2, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
            painter.setPen(QPen(QColor(COLORS.get("border_soft", COLORS["border"])), 1))
            painter.drawLine(r.left(), r.bottom(), r.right(), r.bottom())
            painter.restore()
            return

        if kind == "info":
            if index.column() == 0:
                f = QFont(base)
                f.setItalic(True)
                f.setPointSizeF(max(8.0, base.pointSizeF() - 0.5))
                painter.setFont(f)
                painter.setPen(QColor(COLORS["text_dim"]))
                painter.drawText(r.adjusted(8, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
            painter.restore()
            return

        # entry
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        if selected or hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(COLORS["selected"] if selected else COLORS["header"]))
            painter.drawRect(r)
        painter.setFont(base)
        if index.column() == 0:
            dot = QRectF(r.left() + 10, r.center().y() - 3, 6, 6)
            painter.setPen(Qt.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(dot)
            painter.setPen(QColor(_strong() if selected else COLORS["text"]))
            tr = r.adjusted(24, 0, -(22 if hint else 6), 0)
            shown = painter.fontMetrics().elidedText(text, Qt.ElideRight, tr.width())
            painter.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft, shown)
            if hint:
                painter.setPen(QColor(COLORS["text_dim"] if not hover else COLORS["accent"]))
                painter.drawText(QRect(r.right() - 20, r.top(), 18, r.height()),
                                 Qt.AlignCenter, "✎")
        else:
            f = QFont(base)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(QColor(_strong()))
            painter.drawText(r.adjusted(4, 0, -10, 0), Qt.AlignVCenter | Qt.AlignRight, text)
        painter.restore()

    def helpEvent(self, event, view, option, index):  # noqa: N802
        # the "click to …" hint as tooltip when the cell has none
        kind, _text, hint = _kind(index)
        if kind == "none":
            return False
        if kind == "entry" and hint and not index.data(Qt.ToolTipRole):
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(event.globalPos(), "← " + hint, view)
            return True
        return super().helpEvent(event, view, option, index)


def install(table) -> None:
    """Use the delegate on `table` and give its rows a calm frame."""
    table.setItemDelegate(StatRowDelegate(table))
    table.setMouseTracking(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(32)
    table.setStyleSheet(
        f"QTableWidget {{ background: transparent; border: none; }}"
        f"QTableWidget::item {{ border: none; }}")
