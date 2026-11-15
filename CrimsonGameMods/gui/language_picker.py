
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressBar, QDialogButtonBox, QMessageBox,
    QAbstractItemView, QWidget,
)

import lang_pack_downloader as lpd

log = logging.getLogger(__name__)


class _DownloadWorker(QThread):
    step = Signal(str, int, int)
    finished_with = Signal(bool)

    def __init__(self, lang: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._lang = lang

    def run(self) -> None:
        def _cb(label: str, received: int, total: int) -> None:
            self.step.emit(label, received, total)
        try:
            ok = lpd.download_pack(self._lang, progress_cb=_cb)
        except Exception as e:
            log.exception("language download crashed: %s", e)
            ok = False
        self.finished_with.emit(bool(ok))


@dataclass
class _LangRow:
    code: str
    native: str
    english: str
    installed: bool


def _build_rows() -> List[_LangRow]:
    rows: List[_LangRow] = [
        _LangRow(code="en", native="English", english="English", installed=True),
    ]

    manifest: Dict[str, Dict[str, object]] = {}
    try:
        manifest = lpd.get_remote_manifest()
    except Exception:
        manifest = {}

    codes = list(manifest.keys()) if manifest else list(lpd.SUPPORTED_LANGS)
    for c in lpd.SUPPORTED_LANGS:
        if c not in codes:
            codes.append(c)

    for code in codes:
        if code == "en":
            continue
        meta = manifest.get(code, {}) if manifest else {}
        native = str(meta.get("native") or lpd.local_pack_native_name(code)
                     or lpd.NATIVE_NAMES.get(code, code))
        english = str(meta.get("english") or lpd.ENGLISH_NAMES.get(code, code))
        installed = lpd.is_pack_local(code)
        rows.append(_LangRow(code=code, native=native, english=english,
                             installed=installed))

    rows[1:] = sorted(rows[1:], key=lambda r: r.english.lower())
    return rows


class LanguagePickerDialog(QDialog):

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        config_path: str,
        config: Optional[dict] = None,
        on_applied: Optional[Callable[[str], None]] = None,
        blocking: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Language / 言語 / 语言 / 언어")
        self.setModal(True)
        self.resize(560, 480)

        self._config_path = config_path
        self._config: dict = config if config is not None else {}
        self._on_applied = on_applied
        self._blocking = blocking

        self._worker: Optional[_DownloadWorker] = None
        self._rows: List[_LangRow] = _build_rows()

        self._build_ui()
        self._populate_table()


    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QLabel(
            "Pick a display language. Non-English packs download from GitHub "
            "(~200 KB) on first use and are cached locally."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(
            ["Code", "Language", "English Name", "Status"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setAlternatingRowColors(True)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self._table, 1)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("")
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        btn_row = QHBoxLayout()
        self._apply_btn = QPushButton("Download && Apply")
        self._apply_btn.setDefault(True)
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        btn_row.addWidget(self._apply_btn)

        self._skip_btn = QPushButton("Skip (Keep English)")
        self._skip_btn.clicked.connect(self._on_skip_clicked)
        btn_row.addWidget(self._skip_btn)

        btn_row.addStretch(1)

        if not self._blocking:
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(self.reject)
            btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        current = self._config.get("default_lang") or self._config.get("language") or "en"
        current_row = 0
        for i, row in enumerate(self._rows):
            self._table.insertRow(i)
            code_item = QTableWidgetItem(row.code)
            code_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(i, 0, code_item)
            self._table.setItem(i, 1, QTableWidgetItem(row.native))
            self._table.setItem(i, 2, QTableWidgetItem(row.english))
            if row.code == "en":
                status = "Built-in"
            else:
                status = "Installed" if row.installed else "Download"
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(i, 3, status_item)

            if row.code == current:
                current_row = i
        self._table.selectRow(current_row)


    def _selected_row(self) -> Optional[_LangRow]:
        idx = self._table.currentRow()
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None

    def _on_skip_clicked(self) -> None:
        self._persist_language("en")
        self._apply_runtime("en")
        self.accept()

    def _on_apply_clicked(self) -> None:
        row = self._selected_row()
        if row is None:
            return

        if row.code == "en":
            self._persist_language("en")
            self._apply_runtime("en")
            self.accept()
            return

        if row.installed or lpd.is_pack_local(row.code):
            if not lpd.has_names_pack(row.code):
                # The UI pack is inside the tool; the item / quest name pack
                # (~1 MB) comes from GitHub in the background, used from the
                # next start. No internet: names simply stay English.
                import threading
                threading.Thread(target=lambda c=row.code: lpd.download_names(c),
                                 daemon=True).start()
            self._persist_language(row.code)
            self._apply_runtime(row.code)
            self._maybe_show_restart_toast(row)
            self.accept()
            return

        self._start_download(row)


    def _start_download(self, row: _LangRow) -> None:
        self._apply_btn.setEnabled(False)
        self._skip_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._progress.setFormat(f"Downloading {row.code}.json…")

        self._worker = _DownloadWorker(row.code, self)
        self._worker.step.connect(self._on_worker_step)
        self._worker.finished_with.connect(lambda ok, r=row: self._on_worker_done(r, ok))
        self._worker.start()

    def _on_worker_step(self, label: str, received: int, total: int) -> None:
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(received)
            pct = int(received * 100 / max(total, 1))
            self._progress.setFormat(f"{label}  {pct}%")
        else:
            self._progress.setRange(0, 0)
            self._progress.setFormat(f"{label}  {received // 1024} KB")

    def _on_worker_done(self, row: _LangRow, ok: bool) -> None:
        self._apply_btn.setEnabled(True)
        self._skip_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._progress.setFormat("")

        if not ok:
            QMessageBox.warning(
                self,
                "Download Failed",
                f"Could not download {row.code}.json from GitHub.\n\n"
                f"Check your internet connection and try again, or pick a "
                f"different language.\n\n"
                f"URL: {lpd.GITHUB_BASE}/{row.code}.json",
            )
            row.installed = lpd.is_pack_local(row.code)
            self._refresh_status(row)
            return

        row.installed = True
        self._refresh_status(row)
        self._persist_language(row.code)
        self._apply_runtime(row.code)
        self._maybe_show_restart_toast(row)
        self.accept()

    def _refresh_status(self, row: _LangRow) -> None:
        for i, r in enumerate(self._rows):
            if r is row:
                status = "Installed" if row.installed else "Download"
                item = self._table.item(i, 3)
                if item is not None:
                    item.setText(status)
                break


    def _persist_language(self, lang: str) -> None:
        cfg: dict = {}
        try:
            if os.path.isfile(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f) or {}
        except Exception:
            cfg = {}

        cfg["default_lang"] = lang
        cfg["language"] = lang

        try:
            os.makedirs(os.path.dirname(self._config_path) or ".", exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.warning("Failed to persist language choice: %s", e)

        self._config.update(cfg)

    def _apply_runtime(self, lang: str) -> None:
        try:
            import gui_i18n
            gui_i18n.set_language(lang)
        except Exception as e:
            log.warning("gui_i18n.set_language(%s) failed: %s", lang, e)
        try:
            import localization
            localization.set_language(lang)
        except Exception:
            pass
        if self._on_applied:
            try:
                self._on_applied(lang)
            except Exception as e:
                log.warning("language on_applied callback failed: %s", e)

    def _maybe_show_restart_toast(self, row: _LangRow) -> None:
        QMessageBox.information(
            self,
            "Language Applied",
            f"Language set to {row.native} ({row.english}).\n\n"
            f"Newly-created widgets are translated automatically, but "
            f"already-built panels keep their old text until you restart.\n\n"
            f"For best results:\n"
            f"  1. Close and reopen the editor, OR\n"
            f"  2. Delete editor_config.json (next to the .exe) and restart "
            f"to force a clean reload — useful if you upgraded from an older build.",
        )


    @classmethod
    def run(
        cls,
        parent: Optional[QWidget],
        *,
        config_path: str,
        config: Optional[dict] = None,
        on_applied: Optional[Callable[[str], None]] = None,
        blocking: bool = False,
    ) -> Optional[str]:
        dlg = cls(parent, config_path=config_path, config=config,
                  on_applied=on_applied, blocking=blocking)
        result = dlg.exec()
        if result == QDialog.Accepted:
            return dlg._config.get("default_lang") or "en"
        return None


__all__ = ["LanguagePickerDialog"]
