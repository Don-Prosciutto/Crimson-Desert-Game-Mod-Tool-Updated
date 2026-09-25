from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QRect, QSize
from PySide6.QtWidgets import (
    QLabel, QLayout, QPushButton, QSizePolicy, QStyle, QTableWidgetItem,
)
from gui.theme import COLORS
from overlay_coordinator import safe_rmtree  # refuses to delete game data folders


class FlowLayout(QLayout):
    """Wrap-capable horizontal layout — children flow to next row when the
    parent gets narrower. Based on the Qt FlowLayout documentation example.

    Use this instead of QHBoxLayout for toolbars with many buttons so they
    wrap instead of forcing a super-wide window.
    """

    def __init__(self, parent=None, margin: int = 0,
                 h_spacing: int = 4, v_spacing: int = 4):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self._h_space = h_spacing
        self._v_space = v_spacing
        self._items: list = []

    def __del__(self):
        while self._items:
            self._items.pop()

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, widget, stretch: int = 0, alignment=None) -> None:
        # Drop-in replacement for QHBoxLayout.addWidget — accepts and ignores
        # the stretch/alignment args (Flow wraps naturally; stretch is moot).
        super().addWidget(widget)

    def addLayout(self, layout, stretch: int = 0) -> None:
        super().addItem(layout)

    def addStretch(self, stretch: int = 0) -> None:
        # Flow wraps naturally — addStretch is a no-op in a wrap layout.
        pass

    def addSpacing(self, _size: int) -> None:
        pass

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._doLayout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._doLayout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _doLayout(self, rect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            wid = item.widget()
            space_x = self._h_space
            space_y = self._v_space
            if wid is not None:
                style = wid.style()
                space_x = max(space_x, style.layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal))
                space_y = max(space_y, style.layoutSpacing(
                    QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical))
            next_x = x + item.sizeHint().width() + space_x
            if next_x - space_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + space_y
                next_x = x + item.sizeHint().width() + space_x
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, item.sizeHint().height())
        return y + line_height - rect.y() + m.bottom()


def make_scope_label(scope: str) -> QLabel:
    if scope == "save":
        text = "This tab modifies your SAVE FILE"
        color = COLORS["scope_save"]
        bg = "rgba(79,195,247,0.08)"
    elif scope == "game":
        text = "This tab modifies GAME FILES (requires admin + restart)"
        color = COLORS["scope_game"]
        bg = "rgba(255,183,77,0.08)"
    elif scope == "readonly":
        text = "This tab is READ-ONLY (browse only)"
        color = COLORS["text_dim"]
        bg = "rgba(176,160,136,0.05)"
    else:
        raise ValueError(f"Unknown scope {scope!r} — expected 'save', 'game', or 'readonly'")
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {color}; font-size: 11px; padding: 3px 8px; "
        f"border: 1px solid {color}; border-radius: 3px; "
        f"background-color: {bg}; font-weight: bold;"
    )
    lbl.setFixedHeight(22)
    return lbl


def _num_item(value: int) -> QTableWidgetItem:
    item = QTableWidgetItem()
    item.setData(Qt.DisplayRole, value)
    return item


def resolve_overlay_group(game_path: str, requested: int, tab_name: str,
                          parent=None) -> int | None:
    """Check if overlay folder exists. If so, ask user to overwrite or auto-pick a free slot.
    Returns the group number to use, or None if cancelled."""
    import os
    from PySide6.QtWidgets import QMessageBox
    from overlay_coordinator import is_game_data_group, free_overlay_number
    if is_game_data_group(game_path, f"{requested:04d}"):
        free = free_overlay_number(game_path)
        QMessageBox.warning(
            parent, f"Overlay {requested:04d} belongs to the game",
            f"Group {requested:04d} is part of the game itself (since game 2.03 the "
            f"game uses the numbers up to 0040). Writing there would overwrite game "
            f"files.\n\n{tab_name} will use {free:04d} instead.")
        requested = free
    group_dir = os.path.join(game_path, f"{requested:04d}")
    if not os.path.isdir(group_dir):
        return requested

    reply = QMessageBox.question(
        parent, f"Overlay {requested:04d} Exists",
        f"Folder {requested:04d}/ already exists in the game directory.\n"
        f"This may be from a previous {tab_name} mod or another tool.\n\n"
        f"Overwrite: Replace the existing overlay (use if updating your own mod)\n"
        f"New Slot: Auto-pick an unused overlay number\n"
        f"Cancel: Abort the apply",
        QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
        QMessageBox.Yes)
    reply_btn = reply
    if reply_btn == QMessageBox.Yes:
        return requested
    if reply_btn == QMessageBox.Cancel:
        return None
    return free_overlay_number(game_path)


def fitting_index(stem: str, body: bytes, pabgh: bytes, vanilla_len: int) -> bytes:
    """The .pabgh to ship with this (possibly changed) table body.

    The index stores each record's byte offset; the game relies on it. When
    records changed size the offsets are rebuilt (pabgh_index). If the
    index layout is not the usual one, the original index is only used when
    the body kept its size; otherwise RuntimeError, nothing is written."""
    from pabgh_index import rebuild_index
    new = rebuild_index(stem, body, pabgh)
    if new is not None:
        return new
    if len(body) == vanilla_len:
        return bytes(pabgh)
    raise RuntimeError(
        f"{stem}: some records changed size and the index (.pabgh) of this table "
        f"cannot be rebuilt. Nothing was written. Use Export Field JSON instead.")


def deploy_merged_pabgb(game_path: str, table_name: str, pabgb_stem: str,
                        new_pabgb: bytes, new_pabgh: bytes,
                        overlay_group: str, tab_label: str,
                        parent=None) -> bool:
    """Deploy a pabgb to an overlay, merging with any existing overlay data.

    Scans ALL overlay folders for an existing copy of this pabgb.
    If found, parses both old and new with dmm_parser, merges field-level
    changes (new edits on top of existing), and writes the combined result.
    Returns True on success.
    """
    import os, logging, shutil, tempfile
    log = logging.getLogger(__name__)

    try:
        import crimson_rs, dmm_parser
    except ImportError:
        return False

    from table_layout import INTERNAL_DIR, archive_name

    vanilla_pabgb = bytes(dmm_parser.extract_file(
        game_path, '0008', INTERNAL_DIR, f'{pabgb_stem}.pabgb'))
    vanilla_pabgh = bytes(dmm_parser.extract_file(
        game_path, '0008', INTERNAL_DIR, f'{pabgb_stem}.pabgh'))

    # (A merge step used to sit here: it read the table raw - still
    # compressed - out of every numbered folder, including the game's own
    # 0008, and deleted the folder it merged from. It could not work on 2.03
    # data and is gone; the table is written as given.)
    merged = new_pabgb
    new_pabgh = fitting_index(pabgb_stem, merged, new_pabgh, len(vanilla_pabgb))

    with tempfile.TemporaryDirectory() as tmp:
        build_dir = os.path.join(tmp, overlay_group)
        b = crimson_rs.PackGroupBuilder(
            build_dir, crimson_rs.Compression.NONE, crimson_rs.Crypto.NONE)
        b.add_file(INTERNAL_DIR, f"{pabgb_stem}.pabgb", merged)
        b.add_file(INTERNAL_DIR, f"{pabgb_stem}.pabgh", new_pabgh)
        pamt_bytes = bytes(b.finish())
        pamt_checksum = dmm_parser.parse_pamt_bytes(pamt_bytes)["checksum"]

        dst = os.path.join(game_path, overlay_group)
        if os.path.isdir(dst):
            safe_rmtree(dst)
        os.makedirs(dst, exist_ok=True)
        for fname in os.listdir(build_dir):
            shutil.copy2(os.path.join(build_dir, fname), os.path.join(dst, fname))

    papgt_path = os.path.join(game_path, "meta", "0.papgt")
    if os.path.isfile(papgt_path):
        papgt = crimson_rs.parse_papgt_file(papgt_path)
        papgt["entries"] = [e for e in papgt["entries"]
                            if e.get("group_name") != overlay_group]
        # add_papgt_entry returns a NEW dict. The old code dropped it, so the
        # overlay was written but never registered and the game ignored it.
        papgt = crimson_rs.add_papgt_entry(papgt, overlay_group, pamt_checksum, 0, 16383)
        crimson_rs.write_papgt_file(papgt, papgt_path)

    log.info("Deployed %s to %s/ (%d bytes)", pabgb_stem, overlay_group, len(merged))
    return True


def make_help_btn(guide_key: str, show_guide_fn) -> QPushButton:
    btn = QPushButton("?")
    btn.setFixedSize(28, 28)
    btn.setToolTip("Show help for this tab")
    btn.setStyleSheet(
        f"QPushButton {{ background-color: {COLORS['accent']}; color: {COLORS['on_accent']}; "
        f"font-weight: bold; font-size: 14px; border: 2px solid {COLORS['accent']}; "
        f"border-radius: 14px; padding: 0; }}"
        f"QPushButton:hover {{ background-color: {COLORS['accent_hover']}; border-color: {COLORS['accent_hover']}; }}"
    )
    btn.clicked.connect(lambda: show_guide_fn(guide_key))
    return btn
