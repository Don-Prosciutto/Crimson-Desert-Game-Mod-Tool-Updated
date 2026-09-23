"""File > Check DMM Mods for Conflicts: dialog around mod_conflicts.analyze()."""

from __future__ import annotations

import logging
import os
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QMessageBox, QPlainTextEdit,
    QProgressDialog, QVBoxLayout,
)

log = logging.getLogger(__name__)


class _Relay(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)


def _dmm_dir(win, ask: bool) -> str:
    import mod_conflicts
    cfg = win._config
    cands = [cfg.get("dmm_dir", "")]
    exe = cfg.get("dmm_exe_path", "")
    if exe:
        cands.append(os.path.dirname(exe))
    found = None if ask else mod_conflicts.find_dmm_dir(cands)
    while not found:
        picked = QFileDialog.getExistingDirectory(
            win, "Pick the DMM folder (the one with DMM.exe and config.json)",
            cands[0] or os.path.expanduser("~/Downloads"))
        if not picked:
            return ""
        found = mod_conflicts.find_dmm_dir([picked])
        if not found:
            QMessageBox.warning(win, "Mod Conflicts",
                                "No DMM config.json with a mod list in that folder.")
    if cfg.get("dmm_dir") != found:
        cfg["dmm_dir"] = found
        win._save_config()
    return found


def run(win, ask_folder: bool = False) -> None:
    game = win._config.get("game_install_path", "")
    if not game or not os.path.isfile(os.path.join(game, "0008", "0.pamt")):
        QMessageBox.warning(win, "Mod Conflicts", "Set the game path first (Browse or Auto-Detect).")
        return
    dmm_dir = _dmm_dir(win, ask_folder)
    if not dmm_dir:
        return

    prog = QProgressDialog("Reading the active DMM mods...", None, 0, 0, win)
    prog.setWindowTitle("Mod Conflicts")
    prog.setWindowModality(Qt.WindowModal)
    prog.setMinimumDuration(0)
    prog.setMinimumWidth(460)
    relay = _Relay(win)

    def on_progress(i, n, what):
        prog.setMaximum(max(n, 1))
        prog.setValue(i)
        if what:
            prog.setLabelText(f"Checking: {what}")

    def on_done(rep):
        prog.close()
        _show(win, rep.text(), dmm_dir)

    def on_fail(msg):
        prog.close()
        QMessageBox.critical(win, "Mod Conflicts", f"The check could not run:\n\n{msg}")

    relay.progress.connect(on_progress)
    relay.finished.connect(on_done)
    relay.failed.connect(on_fail)
    win._conflict_relay = relay      # keep alive until the thread is done

    def work():
        try:
            import mod_conflicts
            relay.finished.emit(mod_conflicts.analyze(
                dmm_dir, game, progress=lambda i, n, w: relay.progress.emit(i, n, w)))
        except Exception as e:  # noqa: BLE001 - shown to the user
            log.exception("Mod conflict check failed")
            relay.failed.emit(f"{type(e).__name__}: {e}")

    threading.Thread(target=work, name="mod-conflicts", daemon=True).start()
    prog.show()


def _show(win, text: str, dmm_dir: str) -> None:
    dlg = QDialog(win)
    dlg.setWindowTitle("Mod Conflicts - active DMM mods")
    dlg.resize(980, 620)
    lay = QVBoxLayout(dlg)
    box = QPlainTextEdit(text)
    box.setReadOnly(True)
    box.setLineWrapMode(QPlainTextEdit.NoWrap)
    box.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
    lay.addWidget(box)
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    copy = buttons.addButton("Copy report", QDialogButtonBox.ActionRole)
    other = buttons.addButton("Other DMM folder...", QDialogButtonBox.ActionRole)
    copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
    other.clicked.connect(lambda: (dlg.accept(), run(win, ask_folder=True)))
    other.setToolTip(f"Currently: {dmm_dir}")
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    dlg.exec()
