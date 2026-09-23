from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from gui.theme import COLORS, button_css

log = logging.getLogger(__name__)

PAZ_GROUP = "0014"
SLEEP_SEQ_DIR = "sequencer/binary__/baseseq/contents"
SLEEP_BED_DIR = "sequencer/binary__/baseseq/gimmickcalledseq"
NPC_DIRS = [
    "sequencer/binary__/stageseq/funcnpc",
    "sequencer/binary__/stageseq/basecamp",
]

SLEEP_FILES = [
    (SLEEP_SEQ_DIR, "cd_seq_minigame_sleep"),
    (SLEEP_BED_DIR, "gimmick_sleep_bed_left"),
    (SLEEP_BED_DIR, "gimmick_sleep_bed_right"),
]


def _npc_display_name(dirname: str, stem: str) -> str:
    label = stem
    for prefix in (
        "cd_seq_basecamp_funcnpc_",
        "cd_seq_funcnpc_",
        "cd_seq_basecamp_",
    ):
        if label.startswith(prefix):
            label = label[len(prefix):]
            break
    label = label.replace("_", " ").strip().title()
    if "basecamp" in dirname:
        label += " (basecamp)"
    else:
        label += " (funcnpc)"
    return label


def _stem_from_pastage(filename: str) -> str:
    name = filename
    if name.endswith(".pastage"):
        name = name[:-len(".pastage")]
    parts = name.rsplit("_", 1)
    if len(parts) == 2 and re.match(r'^[0-9a-fA-F]+$', parts[1]):
        return parts[0]
    return name


class PasEditorTab(QWidget):
    config_save_requested = Signal()
    status_message = Signal(str)

    def __init__(
        self,
        config: dict,
        game_path_getter: Callable[[], str],
        rebuild_papgt_fn: Optional[Callable[[str, str], str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._config = config
        self._get_game_path = game_path_getter
        self._rebuild_papgt_fn = rebuild_papgt_fn
        self._npc_index: list[dict] = []
        self._swap_queue: list[dict] = []
        self._build_ui()

    def set_experimental_mode(self, enabled: bool) -> None:
        pass

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        tutorial = QLabel(
            "<b>PAS Editor</b> — Sequencer file modding<br>"
            "<b>Sleep Mod:</b> Removes the sleep cooldown so you can sleep "
            "repeatedly without waiting.<br>"
            "<b>NPC Swap:</b> Replace one NPC's sequencer files with another's "
            "to move NPC behavior between locations.<br>"
            "<b>Workflow:</b> Configure options, then click <b>Apply to Game</b>. "
            "Restart the game to see changes."
        )
        tutorial.setTextFormat(Qt.RichText)
        tutorial.setWordWrap(True)
        tutorial.setStyleSheet(
            f"color: {COLORS['text']}; background-color: {COLORS['panel']}; "
            f"padding: 8px; border: 2px solid {COLORS['accent']}; "
            f"border-radius: 6px;"
        )
        layout.addWidget(tutorial)

        top_row = QHBoxLayout()
        top_row.addStretch()

        apply_btn = QPushButton("Apply to Game")
        apply_btn.setStyleSheet(
            button_css("danger") + " font-weight: bold;"
        )
        apply_btn.clicked.connect(self._apply_to_game)
        top_row.addWidget(apply_btn)

        top_row.addWidget(QLabel("Overlay:"))
        self._overlay_spin = QSpinBox()
        self._overlay_spin.setRange(1, 9999)
        self._overlay_spin.setValue(
            self._config.get("pas_editor_overlay_dir", 68)
        )
        self._overlay_spin.setFixedWidth(70)
        self._overlay_spin.valueChanged.connect(
            lambda v: self._config.update({"pas_editor_overlay_dir": int(v)})
        )
        top_row.addWidget(self._overlay_spin)

        restore_btn = QPushButton("Restore")
        restore_btn.setStyleSheet(
            button_css("neutral") + " font-weight: bold;"
        )
        restore_btn.clicked.connect(self._restore)
        top_row.addWidget(restore_btn)

        layout.addLayout(top_row)

        sleep_group = QGroupBox("Sleep Mod")
        sleep_layout = QVBoxLayout(sleep_group)
        self._sleep_check = QCheckBox("Remove sleep cooldown")
        self._sleep_check.setToolTip(
            "Patches the sleep sequencer files so the cooldown check\n"
            "always evaluates to True, allowing repeated sleeping."
        )
        sleep_layout.addWidget(self._sleep_check)
        layout.addWidget(sleep_group)

        npc_group = QGroupBox("NPC Sequencer Swap")
        npc_layout = QVBoxLayout(npc_group)

        scan_row = QHBoxLayout()
        scan_btn = QPushButton("Scan NPCs")
        scan_btn.setStyleSheet(
            f"background-color: {COLORS['accent']}; color: white; font-weight: bold;"
        )
        scan_btn.clicked.connect(self._scan_npcs)
        scan_row.addWidget(scan_btn)
        scan_row.addStretch()
        npc_layout.addLayout(scan_row)

        combo_row = QHBoxLayout()
        combo_row.addWidget(QLabel("Source NPC:"))
        self._src_combo = QComboBox()
        self._src_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        combo_row.addWidget(self._src_combo, 1)

        combo_row.addWidget(QLabel("Target NPC:"))
        self._tgt_combo = QComboBox()
        self._tgt_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        combo_row.addWidget(self._tgt_combo, 1)

        add_btn = QPushButton("Add Swap")
        add_btn.setStyleSheet(
            f"background-color: {COLORS['accent']}; color: white; font-weight: bold;"
        )
        add_btn.clicked.connect(self._add_swap)
        combo_row.addWidget(add_btn)
        npc_layout.addLayout(combo_row)

        queue_row = QHBoxLayout()
        queue_row.addWidget(QLabel("Queued swaps:"))
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_swaps)
        queue_row.addWidget(clear_btn)
        queue_row.addStretch()
        npc_layout.addLayout(queue_row)

        self._swap_list = QListWidget()
        self._swap_list.setMaximumHeight(120)
        npc_layout.addWidget(self._swap_list)

        layout.addWidget(npc_group)

        layout.addStretch()

        self._status = QLabel("Configure options and click Apply to Game.")
        self._status.setStyleSheet(
            f"color: {COLORS['text_dim']}; padding: 4px;"
        )
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    def _scan_npcs(self) -> None:
        try:
            import crimson_rs
        except Exception as e:
            QMessageBox.critical(self, "Scan", f"crimson_rs import failed:\n{e}")
            return

        game_path = self._get_game_path()
        if not game_path:
            QMessageBox.warning(self, "Scan", "Set the game install path first.")
            return

        self._status.setText("Scanning PAZ group 0014 for NPC sequencers...")
        QApplication.processEvents()

        try:
            pamt_path = os.path.join(game_path, PAZ_GROUP, "0.pamt")
            if not os.path.isfile(pamt_path):
                QMessageBox.critical(
                    self, "Scan",
                    f"PAMT not found at {pamt_path}\n"
                    f"Make sure the game install path is correct."
                )
                return

            pamt = crimson_rs.parse_pamt_file(pamt_path)
            npcs: dict[str, dict] = {}

            for d in pamt.get("directories", []):
                dpath = d.get("path", "")
                is_npc_dir = False
                for npc_dir in NPC_DIRS:
                    if dpath.startswith(npc_dir):
                        is_npc_dir = True
                        break
                if not is_npc_dir:
                    continue

                files_in_dir = [f.get("name", "") for f in d.get("files", [])]
                paseq_files = [f for f in files_in_dir if f.endswith(".paseq")]

                if not paseq_files:
                    continue

                for paseq in paseq_files:
                    stem = paseq[:-len(".paseq")]
                    if stem in npcs:
                        continue

                    all_files = []
                    all_files.append(paseq)
                    paseqc = stem + ".paseqc"
                    if paseqc in files_in_dir:
                        all_files.append(paseqc)
                    for f in files_in_dir:
                        if f.endswith(".pastage") and _stem_from_pastage(f) == stem:
                            all_files.append(f)

                    npcs[stem] = {
                        "stem": stem,
                        "dir_path": dpath,
                        "files": sorted(all_files),
                        "display": _npc_display_name(dpath, stem),
                    }

            self._npc_index = sorted(npcs.values(), key=lambda x: x["display"])

            self._src_combo.clear()
            self._tgt_combo.clear()
            for npc in self._npc_index:
                label = f"{npc['display']}  [{npc['stem']}]"
                self._src_combo.addItem(label, npc)
                self._tgt_combo.addItem(label, npc)

            self._status.setText(
                f"Found {len(self._npc_index)} NPCs with sequencer files."
            )
        except Exception as e:
            log.exception("NPC scan failed")
            QMessageBox.critical(self, "Scan", f"Scan failed:\n{e}")

    def _add_swap(self) -> None:
        src_idx = self._src_combo.currentIndex()
        tgt_idx = self._tgt_combo.currentIndex()
        if src_idx < 0 or tgt_idx < 0:
            QMessageBox.information(
                self, "Add Swap", "Scan NPCs first, then select source and target."
            )
            return
        if src_idx == tgt_idx:
            QMessageBox.information(
                self, "Add Swap", "Source and target must be different."
            )
            return

        src = self._src_combo.currentData()
        tgt = self._tgt_combo.currentData()

        for existing in self._swap_queue:
            if existing["tgt"]["stem"] == tgt["stem"]:
                QMessageBox.information(
                    self, "Add Swap",
                    f"Target '{tgt['display']}' already has a swap queued."
                )
                return

        self._swap_queue.append({"src": src, "tgt": tgt})
        item = QListWidgetItem(
            f"{src['display']}  ->  {tgt['display']}"
        )
        self._swap_list.addItem(item)

    def _clear_swaps(self) -> None:
        self._swap_queue.clear()
        self._swap_list.clear()

    def _apply_to_game(self) -> None:
        sleep_enabled = self._sleep_check.isChecked()
        has_swaps = len(self._swap_queue) > 0

        if not sleep_enabled and not has_swaps:
            QMessageBox.information(
                self, "Apply",
                "Nothing to apply. Enable the sleep mod or add NPC swaps."
            )
            return

        try:
            import crimson_rs
        except Exception as e:
            QMessageBox.critical(self, "Apply", f"crimson_rs import failed:\n{e}")
            return

        game_path = self._get_game_path()
        if not game_path:
            QMessageBox.warning(self, "Apply", "Set the game install path first.")
            return

        overlay_group = f"{self._overlay_spin.value():04d}"
        changes: list[str] = []

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                group_dir = os.path.join(tmp_dir, overlay_group)
                os.makedirs(group_dir, exist_ok=True)

                builder = crimson_rs.PackGroupBuilder(
                    group_dir,
                    crimson_rs.Compression.NONE,
                    crimson_rs.Crypto.NONE,
                )

                if sleep_enabled:
                    self._status.setText("Extracting and patching sleep files...")
                    QApplication.processEvents()
                    self._pack_sleep_mod(crimson_rs, game_path, builder)
                    changes.append("Sleep cooldown removed")

                if has_swaps:
                    self._status.setText("Extracting and packing NPC swaps...")
                    QApplication.processEvents()
                    for swap in self._swap_queue:
                        self._pack_npc_swap(
                            crimson_rs, game_path, builder,
                            swap["src"], swap["tgt"],
                        )
                        changes.append(
                            f"NPC swap: {swap['src']['display']} -> "
                            f"{swap['tgt']['display']}"
                        )

                self._status.setText("Finishing PAZ pack...")
                QApplication.processEvents()
                pamt_bytes = bytes(builder.finish())
                pamt_checksum = crimson_rs.parse_pamt_bytes(pamt_bytes)["checksum"]

                game_overlay = os.path.join(game_path, overlay_group)
                if os.path.isdir(game_overlay):
                    shutil.rmtree(game_overlay)
                os.makedirs(game_overlay, exist_ok=True)

                for f in os.listdir(group_dir):
                    shutil.copy2(
                        os.path.join(group_dir, f),
                        os.path.join(game_overlay, f),
                    )

                papgt_path = os.path.join(game_path, "meta", "0.papgt")
                bak = papgt_path + ".paseditor_bak"
                if not os.path.exists(bak) and os.path.isfile(papgt_path):
                    shutil.copy2(papgt_path, bak)

                cur = crimson_rs.parse_papgt_file(papgt_path)
                cur["entries"] = [
                    e for e in cur["entries"]
                    if e.get("group_name") != overlay_group
                ]
                cur = crimson_rs.add_papgt_entry(
                    cur, overlay_group, pamt_checksum,
                    is_optional=0, language=0x3FFF,
                )
                crimson_rs.write_papgt_file(cur, papgt_path)

            try:
                from shared_state import record_overlay
                record_overlay(game_path, overlay_group, "PAS Editor", [])
            except Exception:
                pass

            with open(os.path.join(game_overlay, ".se_paseditor"), "w") as f:
                f.write("Created by CrimsonGameMods PAS Editor\n")
                for c in changes:
                    f.write(f"  {c}\n")

            summary = "\n".join(changes)
            self._status.setText(f"Deployed to {overlay_group}/")
            self.status_message.emit(
                f"PAS Editor overlay deployed to {overlay_group}/"
            )
            QMessageBox.information(
                self, "Applied",
                f"PAS Editor overlay deployed to {overlay_group}/\n\n"
                f"{summary}\n\n"
                f"Restart the game to apply changes.",
            )

        except PermissionError:
            QMessageBox.critical(
                self, "Apply",
                "Permission denied. Run the editor as Administrator.",
            )
        except Exception as e:
            log.exception("PAS Editor apply failed")
            QMessageBox.critical(self, "Apply", f"Failed:\n{e}")

    def _pack_sleep_mod(self, crimson_rs, game_path: str, builder) -> None:
        for dir_path, stem in SLEEP_FILES:
            paseq_name = stem + ".paseq"
            pastage_name = stem + ".pastage"

            pastage_data = bytes(
                crimson_rs.extract_file(game_path, PAZ_GROUP, dir_path, pastage_name)
            )
            patched = pastage_data.replace(b"False", b"True ")
            count = pastage_data.count(b"False")
            log.info(
                "Sleep mod: %s — replaced %d occurrence(s) of False->True",
                pastage_name, count,
            )

            builder.add_file(dir_path, pastage_name, patched)

            try:
                paseq_data = bytes(
                    crimson_rs.extract_file(game_path, PAZ_GROUP, dir_path, paseq_name)
                )
                builder.add_file(dir_path, paseq_name, paseq_data)
            except Exception as e:
                log.warning("Could not extract %s: %s", paseq_name, e)

    def _pack_npc_swap(
        self, crimson_rs, game_path: str, builder,
        src: dict, tgt: dict,
    ) -> None:
        src_dir = src["dir_path"]
        tgt_dir = tgt["dir_path"]
        src_stem = src["stem"]
        tgt_stem = tgt["stem"]
        src_files = src["files"]
        tgt_files = tgt["files"]

        src_pastages = sorted(
            [f for f in src_files if f.endswith(".pastage")]
        )
        tgt_pastages = sorted(
            [f for f in tgt_files if f.endswith(".pastage")]
        )

        for src_file in src_files:
            if src_file.endswith(".pastage"):
                continue

            src_data = bytes(
                crimson_rs.extract_file(game_path, PAZ_GROUP, src_dir, src_file)
            )
            ext = ""
            if src_file.endswith(".paseq"):
                ext = ".paseq"
            elif src_file.endswith(".paseqc"):
                ext = ".paseqc"
            else:
                continue

            tgt_filename = tgt_stem + ext
            builder.add_file(tgt_dir, tgt_filename, src_data)
            log.info("NPC swap: %s/%s -> %s/%s", src_dir, src_file, tgt_dir, tgt_filename)

        for i, src_pastage in enumerate(src_pastages):
            src_data = bytes(
                crimson_rs.extract_file(game_path, PAZ_GROUP, src_dir, src_pastage)
            )
            if i < len(tgt_pastages):
                tgt_filename = tgt_pastages[i]
            else:
                tgt_filename = src_pastage.replace(src_stem, tgt_stem, 1)

            builder.add_file(tgt_dir, tgt_filename, src_data)
            log.info(
                "NPC swap pastage: %s/%s -> %s/%s",
                src_dir, src_pastage, tgt_dir, tgt_filename,
            )

    def _restore(self) -> None:
        game_path = self._get_game_path()
        if not game_path:
            QMessageBox.warning(self, "Restore", "Set the game install path first.")
            return

        overlay_group = f"{self._overlay_spin.value():04d}"
        game_overlay = os.path.join(game_path, overlay_group)

        if not os.path.isdir(game_overlay):
            QMessageBox.information(
                self, "Nothing to restore",
                f"No {overlay_group}/ overlay found.",
            )
            return

        try:
            if self._rebuild_papgt_fn:
                msg = self._rebuild_papgt_fn(game_path, overlay_group)
                log.info("PAPGT restore: %s", msg)
            else:
                papgt_path = os.path.join(game_path, "meta", "0.papgt")
                bak = papgt_path + ".paseditor_bak"
                if os.path.exists(bak):
                    shutil.copy2(bak, papgt_path)

            shutil.rmtree(game_overlay)

            try:
                from overlay_coordinator import post_restore
                post_restore(game_path, overlay_group)
            except Exception:
                pass

            self._status.setText("Restored -- overlay removed")
            self.status_message.emit(
                f"PAS Editor overlay {overlay_group}/ removed"
            )
            QMessageBox.information(
                self, "Restored",
                f"Removed {overlay_group}/ overlay.\n"
                f"Restart the game to revert to vanilla.",
            )
        except Exception as e:
            log.exception("PAS Editor restore failed")
            QMessageBox.critical(self, "Restore", f"Failed:\n{e}")
