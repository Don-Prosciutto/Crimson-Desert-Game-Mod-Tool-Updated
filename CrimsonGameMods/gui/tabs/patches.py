from __future__ import annotations

import json
import logging
import os
import re
import struct
import sys
import threading
import tempfile
from typing import Callable, Optional, Tuple

from data_db import get_connection

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QFileDialog, QFrame, QGroupBox,
    QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from gui.theme import COLORS, button_css
from gui.utils import make_scope_label, make_help_btn
from i18n import tr
from paz_patcher import PazPatch, PazPatchManager, VehiclePatcher

log = logging.getLogger(__name__)


def _validate_game_path(path: str) -> bool:
    paz = os.path.join(path, "0008", "0.paz")
    paz_bak = os.path.join(path, "0008", "0.paz.sebak")
    return os.path.isfile(paz) or os.path.isfile(paz_bak)


class GamePatchesTab(QWidget):

    status_message = Signal(str)
    game_path_changed = Signal(str)
    config_save_requested = Signal()

    def __init__(self, config: dict, paz_manager: PazPatchManager, experimental_mode: bool, show_guide_fn=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._paz_manager = paz_manager
        self._experimental_mode = experimental_mode
        self._show_guide_fn = show_guide_fn
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        if path and hasattr(self, '_paz_game_path'):
            self._paz_game_path.setText(path)
            self._paz_manager.game_path = path
            self._paz_refresh_status()

    def _apply_game_path(self, path: str) -> None:
        self._paz_game_path.setText(path)
        self._paz_manager.game_path = path
        self._paz_refresh_status()
        self.game_path_changed.emit(path)

    def set_experimental_mode(self, enabled: bool) -> None:
        if hasattr(self, '_dev_export_btn_skill'):
            self._dev_export_btn_skill.setVisible(bool(enabled))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(make_scope_label("game"))

        warning = QLabel(
            "EXPERIMENTAL — Use at your own risk. "
            "These patches modify GAME FILES (PAZ archives), not save files. "
            "Always back up first. If the game updates, patches may need to be re-applied. "
            "If something goes wrong, use Restore from Backup or Steam Verify Integrity."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            f"color: {COLORS['error']}; font-weight: bold; padding: 8px; "
            f"border: 1px solid {COLORS['error']}; border-radius: 4px; "
            f"background-color: rgba(255,80,80,0.10);"
        )
        help_row = QHBoxLayout()
        help_row.addWidget(warning, 1)
        help_row.addWidget(make_help_btn("gpatch", self._show_guide_fn))
        layout.addLayout(help_row)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel(tr("Game Install Path:")))

        self._paz_game_path = QLineEdit()
        self._paz_game_path.setPlaceholderText(tr("Auto-detect or browse..."))
        path_row.addWidget(self._paz_game_path, 1)

        browse_btn = QPushButton(tr("Browse..."))
        browse_btn.clicked.connect(self._paz_browse_game_path)
        path_row.addWidget(browse_btn)

        detect_btn = QPushButton(tr("Detect"))
        detect_btn.setFixedWidth(70)
        detect_btn.setToolTip(tr("Auto-detect game installation"))
        detect_btn.clicked.connect(self._paz_auto_detect_path)
        path_row.addWidget(detect_btn)

        layout.addLayout(path_row)


        self._paz_patch_table = QTableWidget()
        self._paz_patch_table.setVisible(False)

        self._paz_status_label = QLabel("")
        self._paz_status_label.setWordWrap(True)
        self._paz_status_label.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        layout.addWidget(self._paz_status_label)

        refresh_btn = QPushButton(tr("Refresh Status"))
        refresh_btn.clicked.connect(self._paz_refresh_status)
        refresh_row = QHBoxLayout()
        refresh_row.addWidget(refresh_btn)
        refresh_row.addStretch()
        layout.addLayout(refresh_row)

        storage_grp = QGroupBox(tr("Storage Expansion (inventory.pabgb)"))
        storage_layout = QVBoxLayout(storage_grp)
        storage_info = QLabel(
            "Expand storage slots: warehouse/bank/camp to 700, player inventory to 100/240. "
            "Uses structural parsing — survives game updates."
        )
        storage_info.setWordWrap(True)
        storage_info.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        storage_layout.addWidget(storage_info)

        storage_btn_row = QHBoxLayout()
        storage_apply_btn = QPushButton(tr("Expand Storage to 700"))
        storage_apply_btn.setObjectName("accentBtn")
        storage_apply_btn.clicked.connect(self._paz_expand_storage)
        storage_apply_btn.setVisible(self._experimental_mode)
        storage_btn_row.addWidget(storage_apply_btn)
        self._storage_apply_btn = storage_apply_btn

        storage_check_btn = QPushButton(tr("Check Status"))
        storage_check_btn.clicked.connect(self._paz_check_storage)
        storage_check_btn.setVisible(self._experimental_mode)
        storage_btn_row.addWidget(storage_check_btn)
        self._storage_check_btn = storage_check_btn

        self._storage_status = QLabel("")
        self._storage_status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        storage_btn_row.addWidget(self._storage_status, 1)
        storage_layout.addLayout(storage_btn_row)
        layout.addWidget(storage_grp)


        ride_grp = QGroupBox(tr("Dragon Ride Limit (skill.pabgb)"))
        ride_layout = QVBoxLayout(ride_grp)
        ride_info = QLabel(
            "Patches Gimmick_RideLimit in skill.pabgb — the ride time limit value (vanilla: 300). "
            "Set to 999999 to try removing the 15-min Dragon ride duration cap."
        )
        ride_info.setWordWrap(True)
        ride_info.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        ride_layout.addWidget(ride_info)

        ride_btn_row = QHBoxLayout()
        ride_patch_btn = QPushButton(tr("Patch Ride Limit -> 999999"))
        ride_patch_btn.setObjectName("accentBtn")
        ride_patch_btn.setToolTip(tr("Patches Gimmick_RideLimit u32 at ds+128 from 300 to 999999"))
        ride_patch_btn.clicked.connect(self._patch_ride_limit)
        ride_patch_btn.setVisible(self._experimental_mode)
        ride_btn_row.addWidget(ride_patch_btn)
        self._ride_patch_btn = ride_patch_btn

        ride_check_btn = QPushButton(tr("Check Current Value"))
        ride_check_btn.clicked.connect(self._check_ride_limit)
        ride_check_btn.setVisible(self._experimental_mode)
        ride_btn_row.addWidget(ride_check_btn)
        self._ride_check_btn = ride_check_btn

        self._ride_limit_status = QLabel("")
        self._ride_limit_status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 4px;")
        ride_btn_row.addWidget(self._ride_limit_status, 1)
        ride_layout.addLayout(ride_btn_row)
        ride_grp.setVisible(self._experimental_mode)
        self._ride_grp = ride_grp
        layout.addWidget(ride_grp)

        layout.addStretch()


        self._paz_patches = []

        self._vehicle_patcher: Optional[VehiclePatcher] = None

        saved_path = self._config.get("game_install_path", "")
        if saved_path and os.path.isdir(saved_path):
            self._paz_game_path.setText(saved_path)
            self._paz_manager.game_path = saved_path
        else:
            self._paz_auto_detect_path()

        self._paz_populate_table()


    def _paz_populate_table(self) -> None:
        table = self._paz_patch_table
        patches = self._paz_patches
        table.setRowCount(len(patches))

        for row, patch in enumerate(patches):
            name_item = QTableWidgetItem(patch.name)
            name_item.setFont(QFont("Consolas", 11, QFont.Bold))
            table.setItem(row, 0, name_item)

            status_item = QTableWidgetItem("...")
            status_item.setForeground(QBrush(QColor(COLORS["text_dim"])))
            table.setItem(row, 1, status_item)

            table.setItem(row, 2, QTableWidgetItem(patch.description))

            table.setItem(row, 3, QTableWidgetItem("..."))

        QTimer.singleShot(100, self._paz_refresh_status)

    def _paz_refresh_status(self) -> None:
        if not hasattr(self, '_paz_patch_table'):
            return
        if not self._paz_manager.game_path:
            self._paz_status_label.setText(tr("No game path set. Use Auto-Detect or Browse."))
            return

        self._paz_status_label.setText(tr("Scanning PAZ files..."))

        from paz_patcher import PatchStatus

        patches = list(self._paz_patches)
        manager = self._paz_manager
        config = self._config

        def _do_scan() -> None:
            results = []
            for row, patch in enumerate(patches):
                try:
                    if patch.name == "Mount Death Respawn (1s)":
                        if config.get("patch_mount_cooldown_applied"):
                            status = PatchStatus("Mount Death Respawn (1s)", "Applied",
                                                 "Patch applied (per config)")
                        else:
                            status = PatchStatus("Mount Death Respawn (1s)", "Not Applied", "")
                    else:
                        status = manager.get_detailed_status(patch)
                    has_backup = manager.has_backup(patch)
                    results.append((row, status, has_backup, None))
                except Exception as e:
                    log.warning(tr("Status check failed for %s: %s"), patch.name, e)
                    results.append((row, None, False, str(e)))
            QTimer.singleShot(0, lambda: self._paz_apply_status_results(results))

        threading.Thread(target=_do_scan, daemon=True).start()

    def _paz_apply_status_results(self, results: list) -> None:
        if not hasattr(self, '_paz_patch_table'):
            return
        table = self._paz_patch_table

        for row, status, has_backup, error in results:
            if error is not None:
                status_item = table.item(row, 1)
                if status_item:
                    status_item.setText(tr("Error"))
                    status_item.setForeground(QBrush(QColor(COLORS["error"])))
                    status_item.setToolTip(error)
                continue

            status_item = table.item(row, 1)
            if status_item is None:
                status_item = QTableWidgetItem()
                table.setItem(row, 1, status_item)
            status_item.setText(status.status)
            if status.status == "Applied":
                status_item.setForeground(QBrush(QColor(COLORS["success"])))
            elif status.status == "Not Applied":
                status_item.setForeground(QBrush(QColor(COLORS["text"])))
            elif status.status == "Partial":
                status_item.setForeground(QBrush(QColor(COLORS["warning"])))
            else:
                status_item.setForeground(QBrush(QColor(COLORS["error"])))
            status_item.setToolTip(status.detail)

            bak_item = table.item(row, 3)
            if bak_item is None:
                bak_item = QTableWidgetItem()
                table.setItem(row, 3, bak_item)
            bak_item.setText("Yes" if has_backup else "No")
            bak_item.setForeground(QBrush(QColor(
                COLORS["success"] if has_backup else COLORS["text_dim"]
            )))

        self._paz_status_label.setText(tr("Status check complete."))


    def _paz_browse_game_path(self) -> None:
        current = self._paz_game_path.text().strip() or self._config.get("game_install_path", "")
        path = QFileDialog.getExistingDirectory(
            self, "Select Crimson Desert Install Folder",
            current or "C:\\"
        )
        if path:
            if not _validate_game_path(path):
                QMessageBox.warning(
                    self, tr("Invalid Path"),
                    f"Could not find game files in:\n{path}\n\n"
                    f"Expected: 0008/0.paz or 0008/0.paz.sebak\n\n"
                    f"Make sure you selected the Crimson Desert root folder."
                )
                return
            self._apply_game_path(path)

    def _paz_auto_detect_path(self) -> None:
        detected = PazPatchManager.find_game_path()
        if detected:
            self._apply_game_path(detected)
            self._paz_status_label.setText(f"Game found at: {detected}")
        else:
            self._paz_status_label.setText(
                tr("Could not auto-detect game installation. Use Browse to set the path manually.")
            )

    def _paz_get_selected_patch(self) -> Optional[PazPatch]:
        rows = self._paz_patch_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, tr("No Selection"), tr("Select a patch from the table first."))
            return None
        row = rows[0].row()
        if 0 <= row < len(self._paz_patches):
            return self._paz_patches[row]
        return None

    def _paz_apply_selected(self) -> None:
        if not self._paz_manager.game_path:
            QMessageBox.warning(self, tr("No Game Path"),
                                tr("Set the game install path first (Auto-Detect or Browse)."))
            return

        patch = self._paz_get_selected_patch()
        if not patch:
            return

        reply = QMessageBox.question(
            self, tr("Apply Patch"),
            f"Apply '{patch.name}'?\n\n"
            f"{patch.description}\n\n"
            f"A backup will be created automatically if one doesn't exist.\n"
            f"You can restore the original file at any time.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._paz_status_label.setText(f"Applying '{patch.name}'...")
        QApplication.processEvents()

        if patch.name == "Mount Death Respawn (1s)":
            ok, msg = self._paz_apply_mount_cooldown()
        else:
            ok, msg = self._paz_manager.apply_patch(patch)

        if ok:
            self._paz_status_label.setText(f"Success: {msg}")
            QMessageBox.information(self, tr("Patch Applied"), msg)
        else:
            self._paz_status_label.setText(f"Failed: {msg}")
            QMessageBox.critical(self, tr("Patch Failed"), msg)

        self._paz_refresh_status()

    def _paz_apply_mount_cooldown(self) -> Tuple[bool, str]:
        game_path = self._paz_manager.game_path
        if not game_path:
            return False, "No game path set."

        try:
            self._vehicle_patcher = VehiclePatcher(game_path)
            ok, msg = self._vehicle_patcher.apply_no_cooldown(cooldown_value=1)
            if ok:
                self._config["patch_mount_cooldown_applied"] = True
                self.config_save_requested.emit()
            return ok, msg
        except Exception as e:
            log.exception("Mount cooldown patch failed")
            return False, f"Mount cooldown patch failed: {e}"

    def _paz_restore_selected(self) -> None:
        if not self._paz_manager.game_path:
            QMessageBox.warning(self, tr("No Game Path"),
                                tr("Set the game install path first."))
            return

        patch = self._paz_get_selected_patch()
        if not patch:
            return

        if not self._paz_manager.has_backup(patch):
            QMessageBox.information(self, tr("No Backup"),
                                    f"No backup exists for {patch.paz_file}.")
            return

        reply = QMessageBox.question(
            self, tr("Restore Backup"),
            f"Restore {patch.paz_file} from backup?\n\n"
            f"This will overwrite the current PAZ file with the backup copy, "
            f"removing all patches applied to that file.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._paz_status_label.setText(tr("Restoring from backup..."))
        QApplication.processEvents()

        ok, msg = self._paz_manager.restore_backup(patch)

        if ok:
            if patch.name == "Mount Death Respawn (1s)":
                self._config.pop("patch_mount_cooldown_applied", None)
                self.config_save_requested.emit()
            self._paz_status_label.setText(f"Restored: {msg}")
            QMessageBox.information(self, tr("Backup Restored"), msg)
        else:
            self._paz_status_label.setText(f"Restore failed: {msg}")
            QMessageBox.critical(self, tr("Restore Failed"), msg)

        self._paz_refresh_status()

    def _paz_restore_all(self) -> None:
        if not self._paz_manager.game_path:
            QMessageBox.warning(self, tr("No Game Path"),
                                tr("Set the game install path first."))
            return

        reply = QMessageBox.question(
            self, tr("Restore All Backups"),
            "Restore ALL PAZ files from their backups?\n\n"
            "This will remove all patches and return game files to their "
            "original state.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._paz_status_label.setText(tr("Restoring all backups..."))
        QApplication.processEvents()

        ok, msg = self._paz_manager.restore_all_backups()

        if ok:
            self._config.pop("patch_mount_cooldown_applied", None)
            self.config_save_requested.emit()
            self._paz_status_label.setText(msg)
            QMessageBox.information(self, tr("Restore Complete"), msg)
        else:
            self._paz_status_label.setText(msg)
            QMessageBox.warning(self, tr("Restore Result"), msg)

        self._paz_refresh_status()

    def _paz_expand_storage(self) -> None:
        game_path = self._paz_game_path.text().strip()
        if not game_path:
            QMessageBox.warning(self, tr("No Game Path"), tr("Set the game install path first."))
            return

        if not self._is_admin():
            QMessageBox.warning(self, tr("Admin Required"),
                                "Writing to game files requires administrator privileges.\n\n"
                                "Right-click → Run as administrator")
            return

        reply = QMessageBox.question(
            self, tr("Expand Storage"),
            "Expand all warehouse, bank, and camp storage to 700 slots?\n\n"
            "Targets: CampWareHouse, WareHouse, Bank, Recovery, Kuku\n"
            "Player inventory is NOT modified (avoids loot bugs).\n\n"
            "A backup will be created automatically.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._storage_status.setText(tr("Patching storage..."))
        QApplication.processEvents()

        try:
            sp = StoragePatcher(game_path)
            ok, msg = sp.apply(target_slots=700)
            self._storage_status.setText(msg.split('\n')[0] if ok else f"Failed: {msg}")
            if ok:
                QMessageBox.information(self, tr("Storage Expanded"), msg)
            else:
                QMessageBox.critical(self, tr("Failed"), msg)
        except Exception as e:
            self._storage_status.setText(f"Error: {e}")
            QMessageBox.critical(self, tr("Error"), str(e))

    def _paz_check_storage(self) -> None:
        game_path = self._paz_game_path.text().strip()
        if not game_path:
            QMessageBox.warning(self, tr("No Game Path"), tr("Set the game install path first."))
            return

        try:
            sp = StoragePatcher(game_path)
            status, details = sp.check_status()
            self._storage_status.setText(f"{status}: {', '.join(details)}")
        except Exception as e:
            self._storage_status.setText(f"Error: {e}")

    def _effect_swap_blackberry_test(self) -> None:
        game_path = self._paz_game_path.text().strip()
        if not game_path:
            QMessageBox.warning(self, tr("No Game Path"), tr("Set the game install path first."))
            return
        if not self._is_admin():
            QMessageBox.warning(self, tr("Admin Required"),
                                "Writing to game files requires administrator privileges.\n"
                                "Right-click → Run as administrator")
            return

        reply = QMessageBox.question(
            self, tr("Item Effect Swap"),
            "Swap Blackberry's food effect with Narima's Horn instant Dragon CD reset?\n\n"
            "This patches iteminfo.pabgb. A backup will be created.\n"
            "Use Steam Verify Integrity to undo.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._effect_status.setText(tr("Patching..."))
        QApplication.processEvents()

        try:
            patcher = ItemEffectPatcher(game_path)
            ok, msg = patcher.swap_effect('Blackberry', 0xB0A8256B)
            self._effect_status.setText("OK" if ok else "FAILED")
            if ok:
                QMessageBox.information(self, tr("Effect Swapped"), msg)
            else:
                QMessageBox.critical(self, tr("Failed"), msg)
        except Exception as e:
            self._effect_status.setText(f"Error: {e}")
            QMessageBox.critical(self, tr("Error"), str(e))

    def _effect_check_blackberry(self) -> None:
        game_path = self._paz_game_path.text().strip()
        if not game_path:
            QMessageBox.warning(self, tr("No Game Path"), tr("Set the game install path first."))
            return
        try:
            patcher = ItemEffectPatcher(game_path)
            result = patcher.check_effect('Blackberry')
            if result:
                h, desc = result
                self._effect_status.setText(f"Blackberry effect: {desc}")
            else:
                self._effect_status.setText(tr("Could not read Blackberry effect"))
        except Exception as e:
            self._effect_status.setText(f"Error: {e}")

    def _patch_ride_limit(self) -> None:
        game_path = self._paz_game_path.text().strip()
        if not game_path:
            QMessageBox.warning(self, tr("No Game Path"), tr("Set the game install path first."))
            return
        if not self._is_admin():
            QMessageBox.warning(self, tr("Admin Required"),
                                "Writing to game files requires administrator privileges.\n"
                                "Right-click → Run as administrator")
            return

        reply = QMessageBox.question(
            self, tr("Patch Ride Limit"),
            "Patch Gimmick_RideLimit in skill.pabgb from 300 to 999999?\n\n"
            "This may extend or remove the Dragon ride time limit.\n"
            "A backup will be created. Use Steam Verify Integrity to undo.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._ride_limit_status.setText(tr("Patching..."))
        QApplication.processEvents()

        try:
            from paz_patcher import MountPatcher
            mp = MountPatcher(game_path)
            entry = mp._find_pamt_entry('skill.pabgb')
            if not entry:
                self._ride_limit_status.setText(tr("skill.pabgb not found"))
                return

            data = bytearray(mp._extract(entry))
            ds = mp._find_record_data(bytes(data), 'Gimmick_RideLimit')
            if not ds:
                self._ride_limit_status.setText(tr("Gimmick_RideLimit not found"))
                return

            old = struct.unpack_from('<I', data, ds + 128)[0]
            struct.pack_into('<I', data, ds + 128, 999999)
            ok, msg = mp._repack(entry, bytes(data))

            if ok:
                self._ride_limit_status.setText(f"Patched: {old} -> 999999")
                QMessageBox.information(self, tr("Ride Limit Patched"),
                                        f"Gimmick_RideLimit: {old} -> 999999\n{msg}")
            else:
                self._ride_limit_status.setText(f"Failed: {msg}")
        except Exception as e:
            self._ride_limit_status.setText(f"Error: {e}")

    def _check_ride_limit(self) -> None:
        game_path = self._paz_game_path.text().strip()
        if not game_path:
            QMessageBox.warning(self, tr("No Game Path"), tr("Set the game install path first."))
            return
        try:
            from paz_patcher import MountPatcher
            mp = MountPatcher(game_path)
            entry = mp._find_pamt_entry('skill.pabgb')
            if not entry:
                self._ride_limit_status.setText(tr("skill.pabgb not found"))
                return
            data = mp._extract(entry)
            ds = mp._find_record_data(data, 'Gimmick_RideLimit')
            if ds:
                val = struct.unpack_from('<I', data, ds + 128)[0]
                self._ride_limit_status.setText(f"Current value: {val} (vanilla: 300)")
            else:
                self._ride_limit_status.setText(tr("Gimmick_RideLimit not found"))
        except Exception as e:
            self._ride_limit_status.setText(f"Error: {e}")

    def _paz_verify_signatures(self) -> None:
        if not self._paz_manager.game_path:
            QMessageBox.warning(self, tr("No Game Path"),
                                tr("Set the game install path first."))
            return

        self._paz_status_label.setText(tr("Verifying signatures..."))
        QApplication.processEvents()

        results = self._paz_manager.verify_signatures()

        lines = ["Signature Verification Results:\n"]
        all_ok = True
        for r in results:
            icon = "[OK]" if r.status == "OK" else "[FAIL]"
            if r.status != "OK":
                all_ok = False
            lines.append(f"  {icon} {r.name}: {r.detail}")

        detail = "\n".join(lines)
        self._paz_status_label.setText(
            "All signatures verified." if all_ok
            else "Some signatures could not be found. See details."
        )

        QMessageBox.information(
            self,
            "Signature Verification" if all_ok else "Signature Issues",
            detail,
        )


class GameMapTab(QWidget):

    status_message = Signal(str)

    def __init__(self, show_guide_fn=None, parent=None):
        super().__init__(parent)
        self._show_guide_fn = show_guide_fn
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(make_scope_label("readonly"))

        info = QLabel(
            "GAME MAP — Search across 24K+ entities: skills, knowledge, quests, missions, items, buffs, NPCs. "
            "Shows relationships: what quest teaches what skill, what item grants what buff."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['accent']}; padding: 4px; font-weight: bold; "
            f"border: 1px solid {COLORS['accent']}; border-radius: 4px; "
            f"background-color: rgba(79,195,247,0.08);")
        layout.addWidget(info)

        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        search_row.addWidget(QLabel(tr("Search:")))
        self._gm_search = QLineEdit()
        self._gm_search.setPlaceholderText(tr("Search anything: Force Palm, Fire Resistance, Ancient Ring, quest name..."))
        self._gm_search.returnPressed.connect(self._gm_do_search)
        search_row.addWidget(self._gm_search, 1)

        self._gm_type_filter = QComboBox()
        self._gm_type_filter.addItems(["All", "skill", "knowledge", "quest", "mission", "item", "buff",
                                       "store", "npc", "character", "tribe", "faction", "region",
                                       "dropset", "save_type"])
        self._gm_type_filter.setFixedWidth(100)
        search_row.addWidget(self._gm_type_filter)

        search_btn = QPushButton(tr("Search"))
        search_btn.setObjectName("accentBtn")
        search_btn.clicked.connect(self._gm_do_search)
        search_row.addWidget(search_btn)

        self._gm_status = QLabel("")
        self._gm_status.setStyleSheet(f"color: {COLORS['accent']};")
        search_row.addWidget(self._gm_status)

        layout.addLayout(search_row)

        gm_splitter = QSplitter(Qt.Horizontal)
        gm_splitter.setChildrenCollapsible(False)

        results_frame = QFrame()
        results_vl = QVBoxLayout(results_frame)
        results_vl.setContentsMargins(0, 0, 0, 0)
        results_vl.setSpacing(2)
        results_vl.addWidget(QLabel(tr("Results:")))
        self._gm_table = QTableWidget()
        self._gm_table.setColumnCount(4)
        self._gm_table.setHorizontalHeaderLabels(["Type", "Key", "Name", "English"])
        self._gm_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._gm_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._gm_table.setSelectionMode(QAbstractItemView.SingleSelection)
        hdr = self._gm_table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        self._gm_table.setColumnWidth(2, 180)
        hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        self._gm_table.setColumnWidth(3, 180)
        self._gm_table.verticalHeader().setDefaultSectionSize(22)
        self._gm_table.setSortingEnabled(True)
        self._gm_table.selectionModel().selectionChanged.connect(self._gm_on_selected)
        results_vl.addWidget(self._gm_table, 1)
        results_frame.setMinimumWidth(200)
        gm_splitter.addWidget(results_frame)

        detail_frame = QFrame()
        detail_vl = QVBoxLayout(detail_frame)
        detail_vl.setContentsMargins(0, 0, 0, 0)
        detail_vl.setSpacing(4)

        self._gm_detail_header = QLabel(tr("Select an item to see details"))
        self._gm_detail_header.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold; font-size: 13px;")
        self._gm_detail_header.setWordWrap(True)
        detail_vl.addWidget(self._gm_detail_header)

        self._gm_props = QTextEdit()
        self._gm_props.setReadOnly(True)
        self._gm_props.setFont(QFont("Consolas", 10))
        self._gm_props.setMaximumHeight(150)
        detail_vl.addWidget(self._gm_props)

        detail_vl.addWidget(QLabel(tr("Relationships:")))
        self._gm_relations = QTableWidget()
        self._gm_relations.setColumnCount(4)
        self._gm_relations.setHorizontalHeaderLabels(["Direction", "Type", "Key", "Name"])
        self._gm_relations.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._gm_relations.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._gm_relations.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self._gm_relations.setColumnWidth(3, 180)
        self._gm_relations.verticalHeader().setDefaultSectionSize(22)
        self._gm_relations.doubleClicked.connect(self._gm_follow_link)
        detail_vl.addWidget(self._gm_relations, 1)

        detail_frame.setMinimumWidth(200)
        gm_splitter.addWidget(detail_frame)

        gm_splitter.setStretchFactor(0, 2)
        gm_splitter.setStretchFactor(1, 3)
        layout.addWidget(gm_splitter, 1)


        self._gm_all_entities = {}
        self._gm_links_from = {}
        self._gm_links_to = {}
        self._load_game_map()

    def _load_game_map(self):
        try:
            db = get_connection()

            for row in db.execute("SELECT section, key, data FROM game_map_entities"):
                entity = json.loads(row['data'])
                etype = entity.get('type', row['section'].rstrip('s'))
                eid = f"{etype}:{entity['key']}"
                self._gm_all_entities[eid] = entity

            for row in db.execute("SELECT from_id, to_id, data FROM game_map_links"):
                link = json.loads(row['data'])
                self._gm_links_from.setdefault(row['from_id'], []).append(link)
                self._gm_links_to.setdefault(row['to_id'], []).append(link)

            total = len(self._gm_all_entities)
            link_count = sum(len(v) for v in self._gm_links_from.values())
            self._gm_status.setText(f"{total:,} entities loaded")
            log.info("Game map loaded: %d entities, %d links", total, link_count)
        except Exception as exc:
            log.warning(tr("Game map load failed: %s"), exc)
            self._gm_status.setText(f"Load failed: {exc}")

    def _gm_do_search(self):
        if not self._gm_all_entities:
            return

        query = self._gm_search.text().strip().lower()
        type_filter = self._gm_type_filter.currentText()
        if not query:
            return

        results = []
        for eid, entity in self._gm_all_entities.items():
            if type_filter != "All" and entity.get('type') != type_filter:
                continue
            name = entity.get('name', '').lower()
            eng = entity.get('english_name', '').lower()
            key_str = str(entity.get('key', ''))
            if query in name or query in eng or query == key_str:
                results.append(entity)

        results = results[:500]

        table = self._gm_table
        table.setSortingEnabled(False)
        table.setRowCount(len(results))

        TYPE_COLORS = {
            'skill': '#4FC3F7', 'knowledge': '#81C784', 'quest': '#FFB74D',
            'mission': '#FF8A65', 'item': '#CE93D8', 'buff': '#F06292',
            'store': '#A1887F', 'npc': '#90A4AE',
        }

        for row, entity in enumerate(results):
            etype = entity.get('type', '?')

            type_w = QTableWidgetItem(etype)
            color = TYPE_COLORS.get(etype, COLORS['text'])
            type_w.setForeground(QBrush(QColor(color)))
            type_w.setFont(QFont("Consolas", 9, QFont.Bold))
            table.setItem(row, 0, type_w)

            key_w = QTableWidgetItem()
            key_w.setData(Qt.DisplayRole, entity.get('key', 0))
            key_w.setData(Qt.UserRole, entity)
            table.setItem(row, 1, key_w)

            name_w = QTableWidgetItem(entity.get('name', ''))
            table.setItem(row, 2, name_w)

            eng_w = QTableWidgetItem(entity.get('english_name', ''))
            if entity.get('english_name'):
                eng_w.setForeground(QBrush(QColor(COLORS['accent'])))
            table.setItem(row, 3, eng_w)

        table.setSortingEnabled(True)
        self._gm_status.setText(f"{len(results)} results")

    def _gm_on_selected(self, *_args):
        rows = self._gm_table.selectionModel().selectedRows()
        if not rows:
            return
        w = self._gm_table.item(rows[0].row(), 1)
        if not w:
            return
        entity = w.data(Qt.UserRole)
        if not entity:
            return

        etype = entity.get('type', '?')
        eid = f"{etype}:{entity['key']}"
        eng = entity.get('english_name', '')

        header = f"{eng or entity.get('name', '?')}  ({etype} #{entity['key']})"
        self._gm_detail_header.setText(header)

        props = []
        for k, v in sorted(entity.items()):
            if k in ('type',) or isinstance(v, (list, dict)) and not v:
                continue
            if isinstance(v, list):
                props.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
            elif isinstance(v, dict):
                props.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
            else:
                props.append(f"{k}: {v}")
        self._gm_props.setPlainText("\n".join(props))

        links_out = self._gm_links_from.get(eid, [])
        links_in = self._gm_links_to.get(eid, [])

        rel_table = self._gm_relations
        rel_table.setRowCount(len(links_out) + len(links_in))
        row = 0

        for link in links_out:
            target = self._gm_all_entities.get(link['to'], {})
            dir_w = QTableWidgetItem(tr("→ out"))
            dir_w.setForeground(QBrush(QColor("#4FC3F7")))
            rel_table.setItem(row, 0, dir_w)
            rel_table.setItem(row, 1, QTableWidgetItem(link.get('type', '?')))
            key_w = QTableWidgetItem(str(target.get('key', link['to'])))
            key_w.setData(Qt.UserRole, target)
            rel_table.setItem(row, 2, key_w)
            rel_table.setItem(row, 3, QTableWidgetItem(
                target.get('english_name', target.get('name', link['to']))))
            row += 1

        for link in links_in:
            source = self._gm_all_entities.get(link['from'], {})
            dir_w = QTableWidgetItem(tr("← in"))
            dir_w.setForeground(QBrush(QColor("#FFB74D")))
            rel_table.setItem(row, 0, dir_w)
            rel_table.setItem(row, 1, QTableWidgetItem(link.get('type', '?')))
            key_w = QTableWidgetItem(str(source.get('key', link['from'])))
            key_w.setData(Qt.UserRole, source)
            rel_table.setItem(row, 2, key_w)
            rel_table.setItem(row, 3, QTableWidgetItem(
                source.get('english_name', source.get('name', link['from']))))
            row += 1

    def _gm_follow_link(self, index):
        row = index.row()
        key_w = self._gm_relations.item(row, 2)
        if not key_w:
            return
        target = key_w.data(Qt.UserRole)
        if not target or not isinstance(target, dict):
            return
        name = target.get('english_name', target.get('name', ''))
        if name:
            self._gm_search.setText(name)
            self._gm_type_filter.setCurrentText(target.get('type', 'All'))
            self._gm_do_search()


class SkillsTab(QWidget):

    status_message = Signal(str)

    def __init__(self, config: dict, show_guide_fn=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._show_guide_fn = show_guide_fn
        self._game_path: str = ""
        self._build_ui()

    def set_game_path(self, path: str) -> None:
        self._game_path = path
        if hasattr(self, '_skill_game_path') and path:
            self._skill_game_path.setText(path)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(make_scope_label("game"))

        warning = QLabel(
            "Edits GAME DATA (skill.pabgb). "
            "Modify skill parameters like cooldown, use count, damage values. "
            "Export as Mod to apply."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            f"color: {COLORS['warning']}; font-weight: bold; padding: 4px; "
            f"border: 1px solid {COLORS['warning']}; border-radius: 4px; "
            f"background-color: rgba(255,193,7,0.10);"
        )
        help_row = QHBoxLayout()
        help_row.addWidget(warning, 1)
        help_row.addWidget(make_help_btn("skills", self._show_guide_fn))
        layout.addLayout(help_row)

        path_row = QHBoxLayout()
        path_row.setSpacing(4)
        path_row.addWidget(QLabel(tr("Game:")))
        self._skill_game_path = QLineEdit()
        self._skill_game_path.setReadOnly(True)
        self._skill_game_path.setPlaceholderText(tr("Auto-detect or browse..."))
        if self._game_path:
            self._skill_game_path.setText(self._game_path)
        path_row.addWidget(self._skill_game_path, 1)

        extract_btn = QPushButton(tr("Extract Skills"))
        extract_btn.setObjectName("accentBtn")
        extract_btn.setToolTip(tr("Extract skill.pabgb from game PAZ archives and parse all entries"))
        extract_btn.clicked.connect(self._skill_extract)
        path_row.addWidget(extract_btn)
        layout.addLayout(path_row)

        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        search_row.addWidget(QLabel(tr("Search:")))
        self._skill_search = QLineEdit()
        self._skill_search.setPlaceholderText(tr("Skill name (e.g. JiJeongTa, Slash, Dodge)..."))
        self._skill_search.returnPressed.connect(self._skill_search_items)
        search_row.addWidget(self._skill_search, 1)
        search_btn = QPushButton(tr("Search"))
        search_btn.clicked.connect(self._skill_search_items)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        skill_splitter = QSplitter(Qt.Horizontal)
        skill_splitter.setChildrenCollapsible(False)

        skills_frame = QFrame()
        skills_vl = QVBoxLayout(skills_frame)
        skills_vl.setContentsMargins(0, 0, 0, 0)
        skills_vl.setSpacing(2)
        skills_vl.addWidget(QLabel(tr("Skills:")))
        self._skill_table = QTableWidget()
        self._skill_table.setColumnCount(4)
        self._skill_table.setHorizontalHeaderLabels(["Key", "Name", "Size", "Strings"])
        self._skill_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._skill_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._skill_table.setSelectionMode(QAbstractItemView.SingleSelection)
        hdr = self._skill_table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        self._skill_table.setColumnWidth(1, 200)
        self._skill_table.verticalHeader().setDefaultSectionSize(22)
        self._skill_table.setSortingEnabled(True)
        self._skill_table.selectionModel().selectionChanged.connect(self._skill_on_selected)
        skills_vl.addWidget(self._skill_table, 1)
        skills_frame.setMinimumWidth(250)
        skill_splitter.addWidget(skills_frame)

        fields_frame = QFrame()
        fields_vl = QVBoxLayout(fields_frame)
        fields_vl.setContentsMargins(0, 0, 0, 0)
        fields_vl.setSpacing(2)
        self._skill_field_header = QLabel(tr("Select a skill to view fields"))
        self._skill_field_header.setStyleSheet(f"color: {COLORS['accent']}; font-weight: bold;")
        fields_vl.addWidget(self._skill_field_header)
        self._skill_field_table = QTableWidget()
        self._skill_field_table.setColumnCount(5)
        self._skill_field_table.setHorizontalHeaderLabels(["Offset", "Type", "Raw Hex", "Value", "Label"])
        self._skill_field_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._skill_field_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._skill_field_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        fhdr = self._skill_field_table.horizontalHeader()
        fhdr.setSectionResizeMode(4, QHeaderView.Interactive)
        self._skill_field_table.setColumnWidth(4, 120)
        self._skill_field_table.verticalHeader().setDefaultSectionSize(22)
        self._skill_field_table.doubleClicked.connect(self._skill_edit_field)
        fields_vl.addWidget(self._skill_field_table, 1)

        self._skill_strings_label = QLabel("")
        self._skill_strings_label.setWordWrap(True)
        self._skill_strings_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; padding: 3px; font-size: 11px; "
            f"border: 1px solid {COLORS['border']}; border-radius: 3px;")
        fields_vl.addWidget(self._skill_strings_label)

        fields_frame.setMinimumWidth(350)
        skill_splitter.addWidget(fields_frame)

        skill_splitter.setStretchFactor(0, 2)
        skill_splitter.setStretchFactor(1, 3)
        skill_splitter.setSizes([300, 500])
        layout.addWidget(skill_splitter, 1)

        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(6)

        export_btn = QPushButton(tr("Export as Mod"))
        export_btn.setStyleSheet(button_css("neutral") + " font-weight: bold;")
        export_btn.setToolTip(tr("ADVANCED — UNSUPPORTED. Export modified skill.pabgb as mod."))
        export_btn.clicked.connect(self._skill_export_mod)
        export_btn.setVisible(False)
        bottom_bar.addWidget(export_btn)
        self._dev_export_btn_skill = export_btn

        save_cfg_btn = QPushButton(tr("Save Config"))
        save_cfg_btn.setToolTip(tr("Save edits as a reusable config file"))
        save_cfg_btn.clicked.connect(self._skill_save_config)
        bottom_bar.addWidget(save_cfg_btn)

        load_cfg_btn = QPushButton(tr("Load Config"))
        load_cfg_btn.setToolTip(tr("Load a config file and re-apply edits"))
        load_cfg_btn.clicked.connect(self._skill_load_config)
        bottom_bar.addWidget(load_cfg_btn)

        self._skill_status = QLabel("")
        self._skill_status.setWordWrap(True)
        self._skill_status.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 2px;")
        bottom_bar.addWidget(self._skill_status, 1)

        layout.addLayout(bottom_bar)


        self._skill_data: Optional[bytearray] = None
        self._skill_schema_data: Optional[bytes] = None
        self._skill_original: Optional[bytes] = None
        self._skill_parser_result = None
        self._skill_current_entry = None
        self._skill_modified = False
        self._skill_edits: dict = {}

    def _skill_extract(self) -> None:
        game_path = self._game_path
        if not game_path:
            QMessageBox.warning(self, tr("Skills"), tr("Set the game path first (Browse at top)."))
            return
        self._skill_game_path.setText(game_path)

        self._skill_status.setText(tr("Extracting skill.pabgb..."))
        QApplication.processEvents()

        try:
            import crimson_rs
            dir_path = "gamedata/binary__/client/bin"
            raw_data = crimson_rs.extract_file(game_path, '0008', dir_path, 'skill.pabgb')
            raw_schema = crimson_rs.extract_file(game_path, '0008', dir_path, 'skill.pabgh')
        except Exception as e:
            self._skill_status.setText(f"Extract failed: {e}")
            QMessageBox.critical(self, tr("Extract Failed"), str(e))
            return

        self._skill_status.setText(tr("Parsing entries..."))
        QApplication.processEvents()

        try:
            from universal_pabgb_parser import parse_pabgb
            self._skill_data = bytearray(raw_data)
            self._skill_schema_data = raw_schema
            self._skill_original = bytes(raw_data)
            self._skill_parser_result = parse_pabgb(
                bytes(raw_data), raw_schema, 'skill', deep=True)
            self._skill_modified = False
            self._skill_edits = {}

            count = self._skill_parser_result.entry_count

            self._skill_display_names = {}
            try:
                import re as _re
                loc_path = None
                for base in [os.path.dirname(os.path.abspath(__file__)),
                             getattr(sys, '_MEIPASS', ''), os.getcwd()]:
                    p = os.path.join(base, 'localizationstring_eng_items.tsv')
                    if os.path.isfile(p):
                        loc_path = p
                        break
                if loc_path:
                    with open(loc_path, 'r', encoding='utf-8-sig') as lf:
                        for line in lf:
                            for m in _re.finditer(r'Knowledge:Knowledge_(\w+)#([^}"<]+)', line):
                                suffix = m.group(1)
                                display = m.group(2).strip()
                                self._skill_display_names[f'Skill_{suffix}'] = display

                    for entry in self._skill_parser_result.entries:
                        dn = self._skill_display_names.get(entry.name)
                        if not dn:
                            base_name = entry.name.replace('Skill_', '')
                            dn = self._skill_display_names.get(f'Skill_{base_name}')
                        if dn:
                            entry.display_name = dn
                        else:
                            entry.display_name = ""

                    named = sum(1 for e in self._skill_parser_result.entries if e.display_name)
                    log.info("Skill display names loaded: %d/%d", named, count)
            except Exception as le:
                log.warning(tr("Localization load failed: %s"), le)

            self._skill_status.setText(
                f"Extracted: {len(raw_data):,} bytes, {count} skills. "
                f"Search by name (e.g. 'Force Palm', 'Slash', 'JiJeongTa').")
        except Exception as e:
            log.exception("Unhandled exception")
            self._skill_status.setText(f"Parse failed: {e}")
            QMessageBox.critical(self, tr("Parse Failed"), str(e))

    def _skill_search_items(self) -> None:
        if not self._skill_parser_result:
            QMessageBox.warning(self, tr("Skills"), tr("Extract skills first."))
            return

        query = self._skill_search.text().strip()
        if not query:
            results = self._skill_parser_result.entries
        else:
            q = query.lower()
            results = []
            for e in self._skill_parser_result.entries:
                if q in e.name.lower():
                    results.append(e)
                elif hasattr(e, 'display_name') and e.display_name and q in e.display_name.lower():
                    results.append(e)
                elif any(q in s.lower() for s in e.strings):
                    results.append(e)

        table = self._skill_table
        table.setSortingEnabled(False)
        table.setRowCount(len(results))

        for row, entry in enumerate(results):
            key_w = QTableWidgetItem()
            key_w.setData(Qt.DisplayRole, entry.key)
            key_w.setData(Qt.UserRole, entry)
            table.setItem(row, 0, key_w)

            display = getattr(entry, 'display_name', '') or ''
            if display:
                name_text = f"{display}  ({entry.name})"
            else:
                name_text = entry.name
            name_w = QTableWidgetItem(name_text)
            name_w.setToolTip(f"Internal: {entry.name}\nKey: {entry.key}\nOffset: 0x{entry.file_offset:X}")
            if display:
                name_w.setForeground(QBrush(QColor(COLORS['accent'])))
            table.setItem(row, 1, name_w)

            size_w = QTableWidgetItem()
            size_w.setData(Qt.DisplayRole, entry.entry_size)
            table.setItem(row, 2, size_w)

            str_count = len(entry.strings)
            str_w = QTableWidgetItem()
            str_w.setData(Qt.DisplayRole, str_count)
            if entry.strings:
                str_w.setToolTip("\n".join(entry.strings[:5]))
            table.setItem(row, 3, str_w)

        table.setSortingEnabled(True)
        self._skill_status.setText(f"{len(results)} skills found")

    def _skill_on_selected(self, *_args) -> None:
        rows = self._skill_table.selectionModel().selectedRows()
        if not rows:
            return
        w = self._skill_table.item(rows[0].row(), 0)
        if not w:
            return
        entry = w.data(Qt.UserRole)
        if not entry:
            return
        self._skill_current_entry = entry
        self._skill_refresh_fields(entry)

    def _skill_refresh_fields(self, entry) -> None:
        self._skill_field_header.setText(
            f"{entry.name} (key={entry.key}, {entry.entry_size}B, "
            f"payload={len(entry.payload)}B)")

        from universal_pabgb_parser import _deep_decode_payload
        payload = entry.payload
        if self._skill_data and self._skill_edits:
            import struct as _s
            entry_data = self._skill_data[entry.file_offset:entry.file_offset + entry.entry_size]
            eid_bytes = 4
            nlen = _s.unpack_from('<I', entry_data, eid_bytes)[0]
            payload_off = eid_bytes + 4 + nlen + 1
            payload = bytes(entry_data[payload_off:])

        fields = _deep_decode_payload(payload, 'skill')

        table = self._skill_field_table
        table.setRowCount(len(fields))

        for row, fld in enumerate(fields):
            off_w = QTableWidgetItem(f"+0x{fld.offset:04X}")
            off_w.setFont(QFont("Consolas", 10))
            off_w.setData(Qt.UserRole, fld)
            table.setItem(row, 0, off_w)

            type_w = QTableWidgetItem(fld.type)
            type_color = {
                'f32': '#4FC3F7', 'string': '#81C784', 'hash': '#FFB74D',
                'u32': COLORS['text'], 'raw': COLORS['text_dim'],
            }.get(fld.type, COLORS['text'])
            type_w.setForeground(QBrush(QColor(type_color)))
            table.setItem(row, 1, type_w)

            raw_w = QTableWidgetItem(fld.raw.hex())
            raw_w.setFont(QFont("Consolas", 10))
            table.setItem(row, 2, raw_w)

            if fld.type == 'f32':
                val_w = QTableWidgetItem(f"{fld.value:.6f}")
            elif fld.type == 'string':
                val_w = QTableWidgetItem(f'"{fld.value}"')
            elif fld.type == 'hash':
                val_w = QTableWidgetItem(f"0x{fld.value:08X}")
            else:
                val_w = QTableWidgetItem(str(fld.value))
            val_w.setFont(QFont("Consolas", 10))
            table.setItem(row, 3, val_w)

            label_w = QTableWidgetItem(fld.label)
            label_w.setForeground(QBrush(QColor(COLORS['warning'])))
            table.setItem(row, 4, label_w)

        if entry.strings:
            self._skill_strings_label.setText(
                "Strings: " + " | ".join(entry.strings[:5])
                + (f" (+{len(entry.strings)-5} more)" if len(entry.strings) > 5 else ""))
            self._skill_strings_label.setVisible(True)
        else:
            self._skill_strings_label.setVisible(False)

    def _skill_edit_field(self, index) -> None:
        if not self._skill_data or not self._skill_current_entry:
            return

        row = index.row()
        fld_item = self._skill_field_table.item(row, 0)
        if not fld_item:
            return
        fld = fld_item.data(Qt.UserRole)
        if not fld or fld.type == 'string':
            return

        import struct as _s
        entry = self._skill_current_entry

        eid_bytes = 4
        nlen = _s.unpack_from('<I', self._skill_data, entry.file_offset + eid_bytes)[0]
        payload_start = entry.file_offset + eid_bytes + 4 + nlen + 1
        abs_offset = payload_start + fld.offset

        if fld.type == 'f32':
            from PySide6.QtWidgets import QInputDialog
            new_val, ok = QInputDialog.getDouble(
                self, "Edit Float",
                f"Field at +0x{fld.offset:04X} ({fld.label or fld.type})\n"
                f"Current: {fld.value:.6f}",
                fld.value, -1e9, 1e9, 6)
            if not ok:
                return
            old_bytes = self._skill_data[abs_offset:abs_offset + 4]
            new_bytes = _s.pack('<f', new_val)
            self._skill_data[abs_offset:abs_offset + 4] = new_bytes
            label = f"{fld.label or 'f32'} {fld.value:.4f} -> {new_val:.4f}"

        elif fld.type in ('u32', 'hash'):
            from PySide6.QtWidgets import QInputDialog
            new_val, ok = QInputDialog.getInt(
                self, "Edit Value",
                f"Field at +0x{fld.offset:04X} ({fld.label or fld.type})\n"
                f"Current: {fld.value}",
                fld.value, 0, 2147483647)
            if not ok:
                return
            old_bytes = self._skill_data[abs_offset:abs_offset + 4]
            new_bytes = _s.pack('<I', new_val)
            self._skill_data[abs_offset:abs_offset + 4] = new_bytes
            label = f"{fld.label or 'u32'} {fld.value} -> {new_val}"

        else:
            return

        self._skill_edits[abs_offset] = (old_bytes, new_bytes, label)
        self._skill_modified = True
        self._skill_refresh_fields(entry)
        self._skill_status.setText(
            f"Edited +0x{fld.offset:04X}: {label}. "
            f"{len(self._skill_edits)} edit(s). Click 'Export as Mod' to write.")

    def _skill_export_mod(self) -> None:
        if not self._skill_data or not self._skill_modified:
            QMessageBox.information(self, tr("Skills"), tr("No modifications to export."))
            return

        game_path = self._game_path
        if not game_path:
            QMessageBox.warning(self, tr("Skills"), tr("Set the game path first."))
            return

        edit_lines = [f"  {label}" for _, (_, _, label) in
                      sorted(self._skill_edits.items())]
        reply = QMessageBox.question(
            self, tr("Export Skill Mod"),
            f"Export {len(self._skill_edits)} edit(s) as a mod?\n\n"
            + "\n".join(edit_lines[:10])
            + ("\n  ..." if len(edit_lines) > 10 else "")
            + "\n\nOutput: packs/<name>/ folder with PAZ overlay.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return

        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Export Skill Mod",
                                        "Mod name (used as folder name):",
                                        text="My Skill Mod")
        if not ok or not name.strip():
            return
        name = name.strip()

        self._skill_status.setText(tr("Packing with pack_mod..."))
        QApplication.processEvents()

        try:
            import crimson_rs.pack_mod
            import tempfile
            import shutil

            mod_group = "0036"
            exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            packs_dir = os.path.join(exe_dir, "packs")
            folder_name = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
            out_path = os.path.join(packs_dir, folder_name)

            if os.path.isdir(out_path):
                shutil.rmtree(out_path)
            os.makedirs(out_path, exist_ok=True)

            with tempfile.TemporaryDirectory() as tmp_dir:
                mod_dir = os.path.join(tmp_dir, "gamedata", "binary__", "client", "bin")
                os.makedirs(mod_dir, exist_ok=True)
                with open(os.path.join(mod_dir, "skill.pabgb"), "wb") as f:
                    f.write(bytes(self._skill_data))
                if self._skill_schema_data:
                    with open(os.path.join(mod_dir, "skill.pabgh"), "wb") as f:
                        f.write(self._skill_schema_data)

                pack_out = os.path.join(tmp_dir, "output")
                os.makedirs(pack_out, exist_ok=True)

                crimson_rs.pack_mod.pack_mod(
                    game_dir=game_path,
                    mod_folder=tmp_dir,
                    output_dir=pack_out,
                    group_name=mod_group,
                )

                shutil.copytree(os.path.join(pack_out, mod_group),
                                os.path.join(out_path, mod_group))
                shutil.copytree(os.path.join(pack_out, "meta"),
                                os.path.join(out_path, "meta"))

            modinfo = {
                "id": name.lower().replace(" ", "_"),
                "name": name, "version": "1.0.0",
                "game_version": "1.00.03", "author": "CrimsonSaveEditor",
                "description": f"Skill mod: {len(self._skill_edits)} edits",
            }
            with open(os.path.join(out_path, "modinfo.json"), "w", encoding="utf-8") as f:
                json.dump(modinfo, f, indent=2)

            paz_size = os.path.getsize(os.path.join(out_path, mod_group, "0.paz"))
            self._skill_status.setText(f"Exported to packs/{folder_name}/ ({paz_size:,}B)")
            QMessageBox.information(self, tr("Skill Mod Exported"),
                f"Mod exported to:\n{out_path}\n\n"
                f"{len(self._skill_edits)} edit(s), PAZ: {paz_size:,} bytes\n\n"
                f"Import into CDUMM or copy {mod_group}/ + meta/ to game directory.")

        except Exception as e:
            log.exception("Unhandled exception")
            self._skill_status.setText(f"Export failed: {e}")
            QMessageBox.critical(self, tr("Export Failed"), str(e))

    def _skill_save_config(self) -> None:
        if not self._skill_edits:
            QMessageBox.information(self, tr("Save Config"), tr("No edits to save."))
            return

        edits_list = []
        for abs_off, (old_b, new_b, label) in sorted(self._skill_edits.items()):
            skill_name = "?"
            skill_key = 0
            if self._skill_parser_result:
                for e in self._skill_parser_result.entries:
                    if e.file_offset <= abs_off < e.file_offset + e.entry_size:
                        skill_name = e.name
                        skill_key = e.key
                        break
            edits_list.append({
                "skill_name": skill_name, "skill_key": skill_key,
                "abs_offset": abs_off, "old_hex": old_b.hex(), "new_hex": new_b.hex(),
                "label": label,
            })

        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Save Config",
                                        "Config name:", text="My Skill Config")
        if not ok or not name.strip():
            return

        config = {
            "format": "crimson_skill_config", "version": 1,
            "name": name.strip(),
            "description": f"{len(edits_list)} skill edit(s)",
            "edits": edits_list,
        }
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Skill Config", f"{name.strip()}.json", "JSON (*.json)")
        if not path:
            return

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        self._skill_status.setText(f"Config saved: {os.path.basename(path)}")

    def _skill_load_config(self) -> None:
        if not self._skill_data:
            QMessageBox.warning(self, tr("Load Config"), tr("Extract skills first."))
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Load Skill Config", "", "JSON (*.json);;All (*)")
        if not path:
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, tr("Load Config"), str(e))
            return

        if config.get('format') != 'crimson_skill_config':
            QMessageBox.warning(self, tr("Load Config"), tr("Not a skill config file."))
            return

        self._skill_data = bytearray(self._skill_original)
        self._skill_edits = {}

        applied = 0
        for edit in config.get('edits', []):
            abs_off = edit['abs_offset']
            old_hex = edit['old_hex']
            new_hex = edit['new_hex']
            new_bytes = bytes.fromhex(new_hex)
            old_bytes = bytes.fromhex(old_hex)

            current = bytes(self._skill_data[abs_off:abs_off + len(new_bytes)])
            if current == old_bytes:
                self._skill_data[abs_off:abs_off + len(new_bytes)] = new_bytes
                self._skill_edits[abs_off] = (old_bytes, new_bytes, edit.get('label', ''))
                applied += 1

        self._skill_modified = bool(self._skill_edits)

        from universal_pabgb_parser import parse_pabgb
        self._skill_parser_result = parse_pabgb(
            bytes(self._skill_data), self._skill_schema_data, 'skill', deep=True)

        if self._skill_current_entry:
            updated = self._skill_parser_result.get(self._skill_current_entry.key)
            if updated:
                self._skill_current_entry = updated
                self._skill_refresh_fields(updated)

        self._skill_status.setText(
            f"Loaded config: {applied}/{len(config.get('edits', []))} edits applied. "
            f"Click 'Export as Mod' to write.")
