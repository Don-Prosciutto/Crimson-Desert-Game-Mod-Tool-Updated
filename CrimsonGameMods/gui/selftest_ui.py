"""Window side of the game compatibility self-test (see selftest.py).

- runs the test in a background thread when the game path is known and the
  stored result does not describe this game version and parser build;
- shows the result in the status bar (click for details);
- blocks the pages whose tables do not fit: greyed out in the navigation,
  their controls disabled, the reason in the tooltip.

Mixed into MainWindow; uses self._config, self._save_config, self._nav,
self._status.
"""

from __future__ import annotations

import logging
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from gui.theme import COLORS

log = logging.getLogger(__name__)

_CONFIG_KEY = "selftest_result"
_SEEN_KEY = "selftest_warning_seen"


class _Relay(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)


class SelfTestMixin:

    # ── status bar ────────────────────────────────────────────────────

    def _selftest_build_status(self) -> None:
        btn = QPushButton("Game check: not run yet")
        btn.setFlat(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("Checks whether the bundled parser still reads and writes every "
                       "table of the installed game correctly. Click for details.")
        btn.clicked.connect(self._selftest_show_details)
        self._selftest_btn = btn
        self._selftest_running = False
        self._selftest_relay = _Relay()
        self._selftest_relay.progress.connect(self._selftest_on_progress)
        self._selftest_relay.finished.connect(self._selftest_on_finished)
        self._selftest_relay.failed.connect(self._selftest_on_failed)
        self._status.addPermanentWidget(btn)
        self._selftest_paint(self._config.get(_CONFIG_KEY))

    def _selftest_paint(self, result) -> None:
        import selftest
        btn = getattr(self, "_selftest_btn", None)
        if btn is None:
            return
        text = selftest.summary(result)
        if not result:
            color = COLORS["text_dim"]
        elif selftest.failed_tables(result):
            color = COLORS["warning"]
        else:
            color = COLORS["success"]
        btn.setText(text)
        btn.setStyleSheet(f"QPushButton {{ color: {color}; border: none; padding: 0 8px; }}"
                          f"QPushButton:hover {{ text-decoration: underline; }}")

    # ── running ───────────────────────────────────────────────────────

    def _selftest_start(self, path: str = "", force: bool = False) -> None:
        import selftest
        path = path or self._config.get("game_install_path", "")
        if not path or not os.path.isfile(os.path.join(path, "0008", "0.pamt")):
            self._selftest_paint(None)
            if force:
                QMessageBox.information(self, "Game Check",
                                        "Set the game folder first (Browse or Auto-Detect).")
            return
        stored = self._config.get(_CONFIG_KEY)
        if not force and selftest.is_current(stored, path):
            self._selftest_apply(stored)
            return
        if self._selftest_running:
            return
        self._selftest_running = True
        self._selftest_btn.setText("Game check: running...")
        relay = self._selftest_relay

        def work():
            try:
                result = selftest.run(path, progress=lambda i, n, t: relay.progress.emit(i, n, t))
                relay.finished.emit(result)
            except Exception as e:  # noqa: BLE001 - reported in the window
                log.exception("Self-test failed")
                relay.failed.emit(f"{type(e).__name__}: {e}")

        threading.Thread(target=work, name="selftest", daemon=True).start()

    def _selftest_on_progress(self, i: int, n: int, table: str) -> None:
        if table:
            self._selftest_btn.setText(f"Game check: {i + 1}/{n} {table}")

    def _selftest_on_failed(self, msg: str) -> None:
        self._selftest_running = False
        self._selftest_btn.setText("Game check: could not run")
        self._selftest_btn.setToolTip(msg)

    def _selftest_on_finished(self, result: dict) -> None:
        import selftest
        self._selftest_running = False
        self._config[_CONFIG_KEY] = result
        self._save_config()
        self._selftest_apply(result)
        bad = selftest.failed_tables(result)
        seen = f"{result.get('game_version')}|{result.get('parser')}"
        if bad and self._config.get(_SEEN_KEY) != seen:
            self._config[_SEEN_KEY] = seen
            self._save_config()
            self._selftest_show_details()

    # ── blocking pages ────────────────────────────────────────────────

    def _selftest_apply(self, result) -> None:
        self._selftest_paint(result)
        self._selftest_apply_to_nav()

    def _selftest_apply_to_nav(self) -> None:
        """Grey out and disable the pages whose tables failed. Called again after
        every rebuild of the navigation."""
        import selftest
        nav = getattr(self, "_nav", None)
        result = self._config.get(_CONFIG_KEY)
        if nav is None:
            return
        path = self._config.get("game_install_path", "")
        blocked = selftest.blocked_pages(result) if selftest.is_current(result, path) else {}
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        itr = QTreeWidgetItemIterator(nav)
        while itr.value():
            item = itr.value()
            itr += 1
            data = item.data(0, Qt.UserRole)
            if not data or data[0] != "page":
                continue
            widget = data[2]
            cls = type(widget).__name__
            base = item.data(0, Qt.UserRole + 1)
            if base is None:
                base = item.text(0)
                item.setData(0, Qt.UserRole + 1, base)
                item.setData(0, Qt.UserRole + 2, item.toolTip(0))
            if cls in blocked:
                tables = ", ".join(blocked[cls])
                item.setText(0, f"{base}  (blocked)")
                item.setForeground(0, QColor(COLORS["text_dim"]))
                item.setToolTip(0, f"Blocked: {tables} does not read/write correctly with game "
                                   f"{result.get('game_version')}. Building mods here could damage "
                                   f"the game data. Wait for a parser update - see the game check "
                                   f"in the status bar.")
                widget.setEnabled(False)
            else:
                item.setText(0, base)
                item.setData(0, Qt.ForegroundRole, None)
                item.setToolTip(0, item.data(0, Qt.UserRole + 2) or "")
                if getattr(widget, "_selftest_blocked", False):
                    widget.setEnabled(True)
            widget._selftest_blocked = cls in blocked

    # ── details ───────────────────────────────────────────────────────

    def _selftest_show_details(self) -> None:
        import selftest
        result = self._config.get(_CONFIG_KEY)
        path = self._config.get("game_install_path", "")
        text = selftest.report_text(result)
        if result and not selftest.is_current(result, path):
            text = ("This result is from an earlier game version or parser build - "
                    "run the check again.\n\n") + text
        dlg = QDialog(self)
        dlg.setWindowTitle("Game Check")
        dlg.resize(760, 440)
        lay = QVBoxLayout(dlg)
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        box.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        lay.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        again = buttons.addButton("Run check again", QDialogButtonBox.ActionRole)
        copy = buttons.addButton("Copy", QDialogButtonBox.ActionRole)
        again.clicked.connect(lambda: (dlg.accept(), self._selftest_start(force=True)))
        copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        dlg.exec()
