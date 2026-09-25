"""CrimsonGameMods Simple - one-click mods for Crimson Desert.

Tick the mods you want and press "Apply" (or just "Start Game", which
applies first). Simple writes them straight into the game folder as its own
pack group "cgmsimple"; the work itself is done by simple_engine.py.

- Other mods (DMM, ...) stay untouched: Simple builds on top of them.
- "Remove Simple Mods" takes out only what Simple added.
- After a game update (or after changing DMM mods) Simple shows it and one
  click on "Apply" rebuilds the mods on the new files.
"""
from __future__ import annotations

import json
import logging
import os
import string
import subprocess
import sys
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QFrame, QScrollArea, QSizePolicy,
)

import simple_engine as engine
import simple_report

log = logging.getLogger(__name__)

APP_VERSION = "2.0.0"
GAME_BUILD = "2.03.02"          # the game version this build was tested with

# ─── Palette ──────────────────────────────────────────────────────────
# "Graphite", the default look of CrimsonGameMods since v2.3.0 (same values
# as gui/theme.py - copied, because importing the gui package would pull in
# the whole main tool).
BG        = "#2b2d30"
PANEL     = "#323438"
HEADER    = "#3c3f43"
ACCENT    = "#548af7"
TEXT      = "#dfe1e5"
TEXT_DIM  = "#a0a3aa"
SELECTED  = "#2e436e"
BORDER    = "#4a4d52"
INPUT_BG  = "#26282b"
SUCCESS   = "#6aab73"
ERROR     = "#f07178"
WARN      = "#d8ab4e"
CARD_BG   = "#323438"
CARD_HOVER = "#3c3f43"
COMBO_BG  = "#2f3a50"
ON_COLOR  = "#548af7"
OFF_COLOR = "#4a4d52"
SECTION_CLR = "#a0a3aa"
# button roles: background, text, border/hover
BTN_PRIMARY = ("#3574f0", "#ffffff", "#4a86f7")
BTN_SUCCESS = ("#3d7a45", "#ffffff", "#4e8a55")
BTN_DANGER  = ("#4a2c2e", "#f28b82", "#b3413c")
BTN_NEUTRAL = ("#3c3f43", "#dfe1e5", "#4a4d52")

STYLESHEET = f"""
QWidget {{ background-color: {BG}; color: {TEXT};
    font-family: 'Segoe UI', Consolas, sans-serif; font-size: 13px; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background-color: {BG}; width: 12px; border: none; }}
QScrollBar::handle:vertical {{ background-color: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QToolTip {{ background-color: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; }}
QMessageBox QPushButton {{ background: {HEADER}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 4px; padding: 5px 14px; min-width: 70px; }}
QMessageBox QPushButton:hover {{ border-color: {ACCENT}; }}
"""

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__)),
    "simple_launcher_config.json")


# ─── Mod Definitions ─────────────────────────────────────────────────
QOL_MEMBERS = {"no_cooldown", "max_charges", "max_stacks", "inf_durability"}
EVERYTHING_MEMBERS = QOL_MEMBERS | {
    "make_dyeable", "five_sockets", "unlock_abyss", "universal_prof"}

COMBO_DEFS = {
    "enable_everything": EVERYTHING_MEMBERS,
    "enable_all_qol": QOL_MEMBERS,
}

# Only one of each pair can be on.
MUTEX_PAIRS = [("drop_5x", "drop_max"), ("bagspace_240", "bagspace_700")]

# Asked before switching on.
WARN_ON = {
    "five_sockets": (
        "More sockets and abyss gear can make a save with many socketed gems load "
        "forever: the game allows only about 23 buff lines on all equipped gear together.\n\n"
        "If that happens, press 'Remove Simple Mods' and the save loads again."),
    "unlock_abyss": None,          # same text as five_sockets
    "npcs_killable": (
        "Story and quest NPCs can then die too. If one of them dies, a quest may not "
        "be finishable any more.\n\nOnly switch this on if you know what you are doing."),
}
WARN_ON["unlock_abyss"] = WARN_ON["five_sockets"]
WARN_ON["enable_everything"] = WARN_ON["five_sockets"]

# Asked before switching off.
WARN_OFF = {
    "five_sockets": (
        "Items go back to their normal number of sockets. A gem that sits in one of the "
        "extra sockets is then no longer shown and may be lost when the game saves.\n\n"
        "Take the gems out in the game first."),
}
WARN_OFF["enable_everything"] = WARN_OFF["five_sockets"]

MOD_DEFS = [
    # ── Combo Badges ──
    {"id": "enable_everything", "title": "Enable Everything (items)",
     "desc": "All item mods: QoL + Dyeable + 5 Sockets + Abyss Unlock + Universal Proficiency",
     "section": "Combos", "combo": True},
    {"id": "enable_all_qol", "title": "Enable All QoL",
     "desc": "Max Stacks + Max Charges + Infinite Durability + No Cooldown",
     "section": "Combos", "combo": True},
    # ── Item Mods ──
    {"id": "no_cooldown", "title": "No Cooldown",
     "desc": "Item cooldowns down to 1 second (Kuku items 8 seconds)", "section": "Item Mods"},
    {"id": "max_charges", "title": "Max Charges",
     "desc": "Items with charges get 99 charges", "section": "Item Mods"},
    {"id": "max_stacks", "title": "Max Stacks",
     "desc": "Stackable items stack up to 999,999", "section": "Item Mods"},
    {"id": "inf_durability", "title": "Infinite Durability",
     "desc": "Durability 65,535 - gear practically never breaks", "section": "Item Mods"},
    {"id": "make_dyeable", "title": "Make All Dyeable",
     "desc": "Every equipment piece can be dyed", "section": "Item Mods"},
    {"id": "five_sockets", "title": "5 Sockets",
     "desc": "Gear that has gem sockets gets 5 of them, all unlocked", "section": "Item Mods"},
    {"id": "thief_gloves_no_cd", "title": "Thief Gloves: No Cooldown",
     "desc": "Only the Thief Gloves: 30 minute cooldown down to 1 second", "section": "Item Mods"},
    {"id": "refine_cost_1", "title": "Refinement Costs 1",
     "desc": "Refining gear needs only 1 of each material, at every level", "section": "Item Mods"},
    {"id": "unlock_abyss", "title": "Unlock Abyss Gear",
     "desc": "Abyss gear can be equipped without the abyss requirement", "section": "Item Mods"},
    {"id": "universal_prof", "title": "Universal Proficiency",
     "desc": "Kliff, Damiane and Oongka can wear each other's gear", "section": "Item Mods"},
    # ── Skills ──
    {"id": "infinite_stamina", "title": "Infinite Stamina",
     "desc": "Skills cost no stamina / spirit", "section": "Skills"},
    # ── World ──
    {"id": "mounts_in_towns", "title": "Mounts in Towns",
     "desc": "Summon and ride mounts in towns, no summon cooldown", "section": "World"},
    {"id": "npcs_killable", "title": "All NPCs Killable",
     "desc": "Removes the protection from NPCs (can break quests!)", "section": "World"},
    # ── Drops ──
    {"id": "drop_5x", "title": "5x Drop Rates",
     "desc": "All drop chances x5 (at most 100 %)", "section": "Drops"},
    {"id": "drop_max", "title": "Max Drop Rates",
     "desc": "All drop chances 100 %", "section": "Drops"},
    # ── Player ──
    {"id": "speed_3x", "title": "3x Player Speed",
     "desc": "Attack speed and move speed x3", "section": "Player"},
    {"id": "gift_trust_5x", "title": "5x Trust from Gifts",
     "desc": "Gifts to NPCs give 5x the trust (talking and quests unchanged)", "section": "Player"},
    {"id": "merc_max", "title": "Max Mercenaries / Pets",
     "desc": "Summon limit 9999, no hire limit", "section": "Player"},
    # ── Difficulty ──
    {"id": "hard_2x_hp", "title": "Hard Mode: 2x Enemy HP Bonus",
     "desc": "On Hard difficulty enemies get +30 % HP, bosses +100 % (normally 15 % / 50 %)",
     "section": "Difficulty"},
    # ── Stores ──
    {"id": "store_max_stock", "title": "All Stores Max Stock",
     "desc": "Every store item can be bought 999,999 times", "section": "Stores"},
    # ── Bag Space ──
    {"id": "bagspace_240", "title": "Bag Space 240 / 700",
     "desc": "Inventory 240 slots, storage / warehouse / bank 700", "section": "Bag Space"},
    {"id": "bagspace_700", "title": "Bag Space 700 / 700",
     "desc": "Inventory 700 slots, storage / warehouse / bank 700", "section": "Bag Space"},
]
ALL_MOD_IDS = {md["id"] for md in MOD_DEFS if not md.get("combo")}
assert ALL_MOD_IDS == set(engine.MOD_FUNCS), "MOD_DEFS and simple_engine are out of sync"


# ─── Utilities ────────────────────────────────────────────────────────
def find_game_path() -> str:
    """Same search as the main tool: ask Steam first, then guess.

    This used to have its own short guess list that only knew
    "SteamLibrary" on other drives and required 0.paz - so it found
    nothing for an ordinary D:\\Steam install, and nothing with a mod
    loader in place, where the file is called 0.paz.sebak.
    """
    try:
        from paz_patcher import PazPatchManager
        found = PazPatchManager.find_game_path()
        if found:
            return found
    except Exception:  # noqa: BLE001 - the launcher must still start
        pass

    candidates = []
    for letter in string.ascii_uppercase:
        for folder in ("SteamLibrary", "Steam", "Games", "SteamGames"):
            candidates.append(
                f"{letter}:\\{folder}\\steamapps\\common\\Crimson Desert")
    candidates.extend([
        r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert",
        r"C:\Program Files\Steam\steamapps\common\Crimson Desert",
        r"C:\Program Files\Epic Games\CrimsonDesert",
    ])
    for p in candidates:
        for name in ("0.paz", "0.paz.sebak"):
            if os.path.isfile(os.path.join(p, "0008", name)):
                return p
    return ""


def is_game_running() -> bool:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq CrimsonDesert.exe", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL, text=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "CrimsonDesert.exe" in out
    except Exception:
        return False


def can_write_game_dir(gp: str) -> bool:
    try:
        t = os.path.join(gp, ".se_write_test")
        with open(t, "w") as f:
            f.write("t")
        os.remove(t)
        return True
    except Exception:
        return False



def game_folder_ok(gp: str) -> bool:
    return bool(gp) and os.path.isfile(os.path.join(gp, "0008", "0.pamt")) \
        and os.path.isfile(os.path.join(gp, "meta", "0.papgt"))


# ─── Background work ──────────────────────────────────────────────────
class ReportWorker(QThread):
    progress = Signal(str)
    done = Signal(str)                  # path of the saved report
    failed = Signal(str)

    def __init__(self, game_path: str, selected: set):
        super().__init__()
        self.game_path = game_path
        self.selected = sorted(selected)

    def run(self):
        try:
            text = simple_report.build_report(APP_VERSION, GAME_BUILD, self.game_path,
                                              self.selected, self.progress.emit)
            self.done.emit(simple_report.write_report(text))
        except Exception as e:  # noqa: BLE001
            log.exception("Simple: report failed")
            self.failed.emit(f"{type(e).__name__}: {e}")


class EngineWorker(QThread):
    progress = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str, bool)          # message, refused (parser does not fit)

    def __init__(self, game_path: str, mods: set, remove_only: bool = False):
        super().__init__()
        self.game_path = game_path
        self.mods = set(mods)
        self.remove_only = remove_only

    def run(self):
        try:
            if self.remove_only or not self.mods:
                engine.remove(self.game_path, self.progress.emit)
                self.finished_ok.emit({"mods": {}, "removed": True})
            else:
                self.finished_ok.emit(engine.apply(self.game_path, self.mods, self.progress.emit))
        except engine.RefusedError as e:
            self.failed.emit(str(e), True)
        except PermissionError as e:
            self.failed.emit(f"Windows did not allow writing into the game folder:\n{e}\n\n"
                             "Close the game and try again, or start Simple as administrator.",
                             False)
        except Exception as e:  # noqa: BLE001 - shown to the user
            log.exception("Simple: apply failed")
            self.failed.emit(f"{type(e).__name__}: {e}", False)

def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ─── Mod Card Widget ──────────────────────────────────────────────────
class ModCard(QFrame):
    toggled = Signal(str, bool)

    def __init__(self, mod_id: str, title: str, desc: str,
                 is_combo: bool = False, parent=None):
        super().__init__(parent)
        self.mod_id = mod_id
        self.title = title
        self._enabled = False
        self._busy = False
        self._is_combo = is_combo

        self.setFixedHeight(72 if not is_combo else 78)
        self.setCursor(Qt.PointingHandCursor)
        self._update_style()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        self._update_dot()
        lay.addWidget(self._dot, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(1)
        self._title_lbl = QLabel(title)
        sz = 13 if is_combo else 12
        self._title_lbl.setFont(QFont("Segoe UI", sz, QFont.Bold))
        self._title_lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
        col.addWidget(self._title_lbl)
        self._desc_lbl = QLabel(desc)
        self._desc_lbl.setStyleSheet(
            f"color: {TEXT_DIM}; background: transparent; font-size: 10px;")
        self._desc_lbl.setWordWrap(True)
        col.addWidget(self._desc_lbl)
        lay.addLayout(col, 1)

        self._badge = QLabel("OFF")
        self._badge.setFixedWidth(50)
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self._update_badge()
        lay.addWidget(self._badge, 0, Qt.AlignVCenter)

    def _update_style(self):
        bg = COMBO_BG if self._is_combo else CARD_BG
        border = ON_COLOR if self._enabled else BORDER
        self.setStyleSheet(
            f"ModCard {{ background-color: {bg}; border: 2px solid {border}; "
            f"border-radius: 6px; }}"
            f"ModCard:hover {{ background-color: {CARD_HOVER}; }}")

    def _update_dot(self):
        c = ON_COLOR if self._enabled else OFF_COLOR
        self._dot.setStyleSheet(
            f"background-color: {c}; border-radius: 5px; border: none;")

    def _update_badge(self):
        if self._enabled:
            self._badge.setStyleSheet(
                f"background-color: {ON_COLOR}; color: #ffffff; "
                f"border-radius: 4px; padding: 2px 6px; border: none;")
            self._badge.setText("ON")
        else:
            self._badge.setStyleSheet(
                f"background-color: {OFF_COLOR}; color: {TEXT_DIM}; "
                f"border-radius: 4px; padding: 2px 6px; border: none;")
            self._badge.setText("OFF")

    def set_enabled(self, on: bool):
        self._enabled = on
        self._update_style()
        self._update_dot()
        self._update_badge()

    def set_busy(self, busy: bool):
        self._busy = busy
        self.setCursor(Qt.WaitCursor if busy else Qt.PointingHandCursor)

    def mousePressEvent(self, ev):
        if not self._busy:
            self.toggled.emit(self.mod_id, not self._enabled)
        super().mousePressEvent(ev)




# ─── Main Window ──────────────────────────────────────────────────────
def _btn_style(role) -> str:
    bg, fg, hover = role
    return (f"QPushButton {{ background: {bg}; color: {fg}; font-weight: bold; font-size: 12px; "
            f"border: 1px solid {hover}; border-radius: 4px; padding: 7px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton:disabled {{ background: {PANEL}; color: #6b6e75; border-color: {BORDER}; }}")


class SimpleWindow(QWidget):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"CrimsonGameMods Simple v{APP_VERSION}  (game {GAME_BUILD})")
        self.setMinimumSize(680, 600)
        self.resize(740, 800)
        self.setStyleSheet(STYLESHEET)

        self._config = load_config()
        self._game_path = self._config.get("game_path", "") or find_game_path()
        # what the user ticked; what is in the game comes from the marker
        self._active: set[str] = set(self._config.get("active_mods", [])) & ALL_MOD_IDS
        self._installed: set[str] = set()
        self._health = ("none", "")
        self._worker: Optional[EngineWorker] = None
        self._after_apply = None
        self._cards: dict[str, ModCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(8)

        hdr = QLabel("CrimsonGameMods Simple")
        hdr.setFont(QFont("Segoe UI", 17, QFont.Bold))
        hdr.setStyleSheet(f"color: {TEXT};")
        hdr.setAlignment(Qt.AlignCenter)
        root.addWidget(hdr)

        how = QLabel("1. Click the mods you want   2. Press Apply (or Start Game)   3. Play")
        how.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        how.setAlignment(Qt.AlignCenter)
        root.addWidget(how)

        # Game path
        pr = QHBoxLayout()
        pr.setSpacing(6)
        pl = QLabel("Game:")
        pl.setStyleSheet(f"color: {TEXT_DIM};")
        pl.setFixedWidth(40)
        pr.addWidget(pl)
        self._path_lbl = QLabel(self._game_path or "Not found - click Browse")
        self._path_lbl.setStyleSheet(
            f"color: {TEXT}; background: {INPUT_BG}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 5px 7px;")
        self._path_lbl.setWordWrap(True)
        pr.addWidget(self._path_lbl, 1)
        bb = QPushButton("Browse")
        bb.setFixedWidth(65)
        bb.setStyleSheet(
            f"QPushButton {{ background: {HEADER}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 5px; }}"
            f"QPushButton:hover {{ border-color: {ACCENT}; }}")
        bb.clicked.connect(self._browse)
        pr.addWidget(bb)
        self._report_btn = QPushButton("Create Report")
        self._report_btn.setToolTip("Saves a report file on your desktop (versions, what Simple "
                                    "installed, a check of each mod, the log). Send it as feedback.")
        self._report_btn.setStyleSheet(
            f"QPushButton {{ background: {HEADER}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 5px 8px; }}"
            f"QPushButton:hover {{ border-color: {ACCENT}; }}")
        self._report_btn.clicked.connect(self._on_report)
        pr.addWidget(self._report_btn)
        root.addLayout(pr)

        # State of the game: what is installed, updates, other mods
        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setAlignment(Qt.AlignCenter)
        self._banner.setMinimumHeight(50)          # room for two lines
        self._banner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        root.addWidget(self._banner)

        # Main content: nav sidebar + card scroll area side by side
        content = QHBoxLayout()
        content.setSpacing(6)

        nav_widget = QWidget()
        nav_widget.setObjectName("navSide")
        nav_widget.setFixedWidth(150)
        nav_widget.setStyleSheet(
            f"QWidget#navSide {{ background: {PANEL}; border-radius: 4px; }}")
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 6, 0, 6)
        nav_layout.setSpacing(2)

        sections = []
        for md in MOD_DEFS:
            s = md.get("section", "")
            if s and s not in sections:
                sections.append(s)

        for sec in sections:
            lbl = QPushButton(sec)
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.setFont(QFont("Segoe UI", 9))
            lbl.setFixedHeight(26)
            lbl.setStyleSheet(
                f"QPushButton {{ color: {TEXT}; background: {PANEL}; border: none; "
                f"border-left: 3px solid transparent; border-radius: 0; "
                f"text-align: left; padding: 2px 8px; font-size: 12px; }}"
                f"QPushButton:hover {{ background: {HEADER}; border-left: 3px solid {ACCENT}; }}")
            lbl.clicked.connect(lambda _, s=sec: self._scroll_to_section(s))
            nav_layout.addWidget(lbl)
        nav_layout.addStretch(1)
        content.addWidget(nav_widget)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self._cl = QVBoxLayout(inner)
        self._cl.setContentsMargins(0, 0, 0, 0)
        self._cl.setSpacing(5)

        self._section_widgets: dict[str, QLabel] = {}
        last_section = None
        for md in MOD_DEFS:
            sec = md.get("section", "")
            if sec != last_section:
                sl = QLabel(sec)
                sl.setFont(QFont("Segoe UI", 10, QFont.Bold))
                sl.setStyleSheet(f"color: {SECTION_CLR}; padding: 6px 0 2px 4px;")
                self._cl.addWidget(sl)
                self._section_widgets[sec] = sl
                last_section = sec
            card = ModCard(md["id"], md["title"], md["desc"], is_combo=md.get("combo", False))
            card.toggled.connect(self._on_toggle)
            self._cards[md["id"]] = card
            self._cl.addWidget(card)

        self._cl.addSpacing(400)
        self._scroll.setWidget(inner)
        content.addWidget(self._scroll, 1)
        root.addLayout(content, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {BORDER};")
        root.addWidget(sep)

        br = QHBoxLayout()
        br.setSpacing(8)
        self._remove_btn = QPushButton("Remove Simple Mods")
        self._remove_btn.setFixedHeight(36)
        self._remove_btn.setToolTip("Takes out everything Simple added to the game. "
                                    "Mods from DMM or other tools are not touched.")
        self._remove_btn.setStyleSheet(_btn_style(BTN_DANGER))
        self._remove_btn.clicked.connect(self._on_remove)
        br.addWidget(self._remove_btn)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setFixedHeight(36)
        self._apply_btn.setToolTip("Writes the selected mods into the game.")
        self._apply_btn.setStyleSheet(_btn_style(BTN_PRIMARY))
        self._apply_btn.clicked.connect(lambda: self._apply())
        br.addWidget(self._apply_btn)
        self._start_btn = QPushButton("Start Game")
        self._start_btn.setFixedHeight(36)
        self._start_btn.setToolTip("Applies your selection first if needed, then starts the game.")
        self._start_btn.setStyleSheet(_btn_style(BTN_SUCCESS))
        self._start_btn.clicked.connect(self._on_start)
        br.addWidget(self._start_btn)
        root.addLayout(br)

        self._status = QLabel("Ready")
        self._status.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._refresh_state()

    # ── State ──
    def _on_report(self):
        if self._worker and self._worker.isRunning():
            return
        self._report_btn.setEnabled(False)
        self._set_status("Creating the report (takes a few seconds)...", ACCENT)
        w = ReportWorker(self._game_path, self._active)
        self._report_worker = w
        w.progress.connect(lambda m: self._set_status(m, ACCENT))
        w.done.connect(self._on_report_done)
        w.failed.connect(lambda m: (self._report_btn.setEnabled(True),
                                    self._set_status("Report failed.", ERROR),
                                    QMessageBox.critical(self, "Report", m)))
        w.start()

    def _on_report_done(self, path: str):
        self._report_btn.setEnabled(True)
        self._set_status(f"Report saved: {path}", SUCCESS)
        QApplication.clipboard().setText(path)
        QMessageBox.information(
            self, "Report saved",
            f"The report was saved here:\n\n{path}\n\n"
            "Please send this file together with a short description of what you did "
            "and what happened in the game.\n\n(The path is also copied to the clipboard.)")
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except Exception:  # noqa: BLE001 - only a convenience
            pass

    def _refresh_state(self):
        """Read what is installed in the game and update everything."""
        gp = self._game_path
        self._installed = set()
        if game_folder_ok(gp):
            try:
                self._health = engine.health(gp)
            except Exception as e:  # noqa: BLE001
                self._health = ("stale", f"Could not read the game state: {e}")
            mark = engine.installed(gp) or {}
            if self._health[0] != "none":
                self._installed = set(mark.get("mods", [])) & ALL_MOD_IDS
            if self._health[0] == "ok" and "active_mods" not in self._config:
                self._active = set(self._installed)
        else:
            self._health = ("nogame", "")
        log.info("Simple: game %r state %s %s installed=%s selected=%s", gp, self._health[0],
                 self._health[1], sorted(self._installed), sorted(self._active))
        self._sync_badges()
        self._update_banner()

    def _pending(self) -> bool:
        if self._health[0] == "stale":
            return bool(self._active or self._installed)
        return self._active != self._installed

    def _update_banner(self):
        state, text = self._health
        pending = self._pending()
        if state == "nogame":
            msg, col = "Game folder not found - click Browse and pick the Crimson Desert folder.", ERROR
        elif state == "stale":
            msg, col = text, WARN
        elif pending:
            msg, col = "You changed the selection - press Apply (or Start Game) to write it into the game.", ACCENT
        elif state == "ok":
            ver = (engine.installed(self._game_path) or {}).get("game_version", "?")
            msg, col = f"Active in the game: {len(self._installed)} mod(s)  (game {ver}).", SUCCESS
        else:
            msg, col = "No Simple mods in the game yet.", TEXT_DIM
        self._banner.setText(msg)
        self._banner.setStyleSheet(
            f"color: {col}; background: {PANEL}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 6px; font-size: 12px;")
        busy = bool(self._worker and self._worker.isRunning())
        self._apply_btn.setEnabled(pending and not busy and state != "nogame")
        self._apply_btn.setText("Apply  (changes pending)" if pending else "Apply")
        self._remove_btn.setEnabled(not busy and state in ("ok", "stale"))
        self._start_btn.setEnabled(not busy)

    def _sync_badges(self):
        for mid, card in self._cards.items():
            if mid in COMBO_DEFS:
                card.set_enabled(COMBO_DEFS[mid].issubset(self._active))
            else:
                card.set_enabled(mid in self._active)

    def _apply_mutex(self, toggled_id: str):
        for a, b in MUTEX_PAIRS:
            if toggled_id == a and a in self._active:
                self._active.discard(b)
            elif toggled_id == b and b in self._active:
                self._active.discard(a)

    def _save_active(self):
        self._config["active_mods"] = sorted(self._active)
        save_config(self._config)

    # ── Actions ──
    def _scroll_to_section(self, section: str):
        w = self._section_widgets.get(section)
        if w:
            y = w.mapTo(self._scroll.widget(), w.rect().topLeft()).y()
            self._scroll.verticalScrollBar().setValue(y)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select the Crimson Desert folder")
        if not d:
            return
        if not game_folder_ok(d):
            QMessageBox.warning(self, "Not the game folder",
                                "This folder has no 0008 and meta folder.\n\n"
                                "Pick the folder called 'Crimson Desert' (in Steam: right-click "
                                "the game > Manage > Browse local files).")
            return
        self._game_path = d
        self._path_lbl.setText(d)
        self._config["game_path"] = d
        save_config(self._config)
        self._refresh_state()

    def _preflight(self) -> bool:
        if not game_folder_ok(self._game_path):
            QMessageBox.warning(self, "No Game Folder", "Set the game folder first (Browse).")
            return False
        if is_game_running():
            QMessageBox.warning(self, "Game Running", "Close the game first, then try again.")
            return False
        if not can_write_game_dir(self._game_path):
            QMessageBox.warning(self, "No Write Access",
                                f"Cannot write to:\n{self._game_path}\n\n"
                                "Start Simple as administrator (right-click > Run as administrator).")
            return False
        return True

    def _ask(self, title: str, text: str) -> bool:
        return QMessageBox.warning(self, title, text + "\n\nContinue?",
                                   QMessageBox.Yes | QMessageBox.No,
                                   QMessageBox.Yes) == QMessageBox.Yes

    def _on_toggle(self, mod_id: str, want_on: bool):
        if self._worker and self._worker.isRunning():
            return
        if want_on and mod_id in WARN_ON and not self._ask("Please read", WARN_ON[mod_id]):
            return
        if (not want_on and mod_id in WARN_OFF
                and ("five_sockets" in self._installed)
                and not self._ask("Please read", WARN_OFF[mod_id])):
            return
        if mod_id in COMBO_DEFS:
            if want_on:
                self._active |= COMBO_DEFS[mod_id]
            else:
                self._active -= COMBO_DEFS[mod_id]
        elif want_on:
            self._active.add(mod_id)
        else:
            self._active.discard(mod_id)
        self._apply_mutex(mod_id)
        log.info("Simple: %s %s -> selected %s", mod_id, "on" if want_on else "off",
                 sorted(self._active))
        self._sync_badges()
        self._save_active()
        self._update_banner()

    def _apply(self, then=None) -> None:
        if self._worker and self._worker.isRunning():
            return
        if not self._preflight():
            return
        self._first_run_note()
        self._after_apply = then
        self._run(EngineWorker(self._game_path, self._active),
                  "Writing the mods into the game..." if self._active else "Removing Simple's mods...")

    def _first_run_note(self):
        """Tell once when other mods change the same tables."""
        if self._config.get("dmm_note_seen") or not self._active:
            return
        try:
            stems = {t for m in self._active for t in engine.MOD_TABLES[m]}
            other = engine.foreign_overlays(self._game_path, stems)
        except Exception:  # noqa: BLE001
            return
        if not other:
            return
        self._config["dmm_note_seen"] = True
        save_config(self._config)
        groups = ", ".join(sorted(other))
        QMessageBox.information(
            self, "Other mods found",
            f"Other mods already change some of the same game files ({groups}).\n\n"
            "Simple keeps them and adds its changes on top.\n\n"
            "Important: if you later change your mods in DMM (or another mod manager), "
            "open Simple again and press Apply - Simple shows a note when that is needed.")

    def _on_remove(self):
        if self._worker and self._worker.isRunning():
            return
        if not self._preflight():
            return
        warn = WARN_OFF["five_sockets"] + "\n\n" if "five_sockets" in self._installed else ""
        if not self._ask("Remove Simple Mods",
                         warn + "This takes out all mods Simple added to the game.\n"
                         "Mods from DMM or other tools stay as they are."):
            return
        self._active.clear()
        self._save_active()
        self._sync_badges()
        self._after_apply = None
        self._run(EngineWorker(self._game_path, set(), remove_only=True), "Removing Simple's mods...")

    def _on_start(self):
        if self._pending() and self._health[0] != "nogame":
            self._apply(then=self._start_game)
        else:
            self._start_game()

    def _start_game(self):
        log.info("Simple: start game")
        if not self._game_path:
            QMessageBox.warning(self, "No Game Path", "Set game folder first.")
            return
        exe = os.path.join(self._game_path, "bin64", "CrimsonDesert.exe")
        if not os.path.isfile(exe):
            exe = os.path.join(self._game_path, "CrimsonDesert.exe")
        if not os.path.isfile(exe):
            try:
                os.startfile("steam://rungameid/3321460")  # noqa: S606 - Windows only
                self._set_status("Launching via Steam...", SUCCESS)
            except Exception:  # noqa: BLE001
                QMessageBox.warning(self, "Launch Failed", "Could not find the game or Steam.")
            return
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe))
            self._set_status("Game launched - have fun!", SUCCESS)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Launch Failed", str(e))

    # ── Worker ──
    def _set_status(self, text: str, color: str = TEXT_DIM):
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _run(self, worker: EngineWorker, text: str):
        for c in self._cards.values():
            c.set_busy(True)
        self._set_status(text, ACCENT)
        self._worker = worker
        worker.progress.connect(lambda m: self._set_status(m, ACCENT))
        worker.finished_ok.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.start()
        self._update_banner()

    def _end(self):
        for c in self._cards.values():
            c.set_busy(False)

    def _on_done(self, report):
        self._worker = None
        self._end()
        self._refresh_state()
        if report.get("removed"):
            self._set_status("Simple's mods removed.", SUCCESS)
        else:
            self._set_status(f"Done - {len(report.get('mods', {}))} mod(s) written into the game.", SUCCESS)
            log.info("Simple: changes per mod %s", report.get("mods"))
        then, self._after_apply = self._after_apply, None
        if then:
            then()

    def _on_failed(self, msg: str, refused: bool):
        log.error("Simple: %s: %s", "refused" if refused else "failed", msg)
        self._worker = None
        self._after_apply = None
        self._end()
        self._refresh_state()
        self._set_status("Nothing was changed." if refused else "Failed - see the message.", ERROR)
        if refused:
            QMessageBox.warning(
                self, "Not compatible with this game version",
                msg + "\n\nThe game was NOT changed. Wait for an updated Simple version.\n\n"
                "Click 'Create Report' at the top and send the file.")
        else:
            QMessageBox.critical(self, "Error", f"Failed:\n\n{msg}\n\n"
                                 "Click 'Create Report' at the top and send the file.")


def main():
    simple_report.setup_logging(APP_VERSION)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = SimpleWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
