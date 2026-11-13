"""Home: the start page of the Game Mod Tool.

Status of game / DLC / save, how a mod gets into the game, what is new, and
one card per page (a click opens it). The page only reads; it changes
nothing. The main window passes in callbacks so this file stays free of
main-window internals.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from gui.theme import COLORS

RELEASES_URL = "https://github.com/Don-Prosciutto/Crimson-Desert-Game-Mod-Tool-Updated/releases"

# Shown under "New in this version". Keep it to a few lines.
WHATS_NEW = [
    "Works with game 2.05.00",
    "Stores, characters and drop sets read correctly again",
    "Quest, mission and character names updated (incl. DLC)",
    'From 2.4.6: Mounts tab, Mesh Swap "Look only", DLC Vendor',
]

# (page label as in the navigation, short description). The label is matched
# against the start of the page's name, so "MercPets" finds
# "MercPets (game files)".
GAME_CARDS = [
    ("Mounts", "Call mounts everywhere, ride longer, no cooldown – DLC mounts too."),
    ("Characters", "Make NPCs attackable, give player characters other move sets."),
    ("Mesh Swap", "Give a character or mount the look of another (transmog)."),
    ("ItemBuffs", "Item stats, buffs, passives, stack sizes, durability."),
    ("Stacker Tool", "Combine several item mods into one, without conflicts."),
    ("Stores", "What vendors sell and for how much – incl. DLC Vendor."),
    ("BagSpace", "More inventory and storage slots."),
    ("DropSets", "What enemies, chests and gathering drop."),
    ("SpawnEdit", "How many creatures spawn and how fast they come back."),
    ("SkillTree", "Swap move sets, skill cooldowns and costs."),
    ("MercPets", "Mercenaries and pets in the game files."),
    ("Game Browser", "Look into any game table (for tinkerers)."),
]
SAVE_CARDS = [
    ("Save Editor", "Inventory, equipment, sockets, refining, dyes, mercenaries."),
    ("World", "Quests, knowledge, waypoints & abyss gates, factions."),
    ("Backup", "Backups of your save files."),
]
MORE_CARDS = [
    ("Items", "Item database with icons and item packs."),
]


class _Card(QFrame):
    def __init__(self, title: str, desc: str, accent: str, on_click: Callable[[], None]):
        super().__init__()
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("homeCard")
        self.setStyleSheet(
            f"QFrame#homeCard {{ background: {COLORS['panel']}; border: 1px solid "
            f"{COLORS['border']}; border-radius: 6px; }}"
            f"QFrame#homeCard:hover {{ border: 1px solid {accent}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 10)
        lay.setSpacing(3)
        t = QLabel(title)
        t.setStyleSheet("font-weight: bold; background: transparent; border: none;")
        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(f"color: {COLORS['text_dim']}; background: transparent; border: none;")
        lay.addWidget(t)
        lay.addWidget(d)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(event)


def _box(title: str) -> tuple:
    f = QFrame()
    f.setObjectName("homeBox")
    f.setStyleSheet(
        f"QFrame#homeBox {{ background: {COLORS['panel']}; border: 1px solid "
        f"{COLORS['border']}; border-radius: 6px; }}"
        f"QFrame#homeBox QLabel {{ background: transparent; border: none; }}")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 10, 14, 12)
    lay.setSpacing(4)
    h = QLabel(title)
    h.setStyleSheet("font-weight: bold;")
    lay.addWidget(h)
    return f, lay


class HomePage(QWidget):
    """goto(label) opens a page; status() returns
    (game_path, game_version, dlc_installed, save_path or "");
    the show-at-start setting lives in config['home_at_start']."""

    def __init__(self, version: str, goto: Callable[[str], None],
                 status: Callable[[], tuple], config: dict,
                 save_config: Optional[Callable[[], None]] = None,
                 support: Optional[Callable[[], None]] = None, parent=None):
        super().__init__(parent)
        self._support = support
        self._goto = goto
        self._status = status
        self._config = config
        self._save_config = save_config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(26, 20, 26, 20)
        v.setSpacing(10)

        title = QLabel(f"Crimson Desert Game Mod Tool  "
                       f"<span style='color:{COLORS['text_dim']}; font-size:13px; "
                       f"font-weight:normal'>v{version}</span>")
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        v.addWidget(title)
        sub = QLabel("Make mods for DMM and edit your save. Pick a page on the left "
                     "or click a card below.")
        sub.setStyleSheet(f"color: {COLORS['text_dim']};")
        v.addWidget(sub)

        row = QHBoxLayout()
        row.setSpacing(12)
        st_box, st_lay = _box("Status")
        self._status_label = QLabel("")
        self._status_label.setTextFormat(Qt.RichText)
        self._status_label.setWordWrap(True)
        st_lay.addWidget(self._status_label)
        st_lay.addStretch()
        if support is not None:
            sp = QLabel(f"<a href='support' style='color:{COLORS['accent']}'>Problems? "
                        "Create a support package…</a>")
            sp.setTextFormat(Qt.RichText)
            sp.setToolTip("A zip with versions, the tool's and DMM's log, the settings and\n"
                          "(if you want) the mod with the problem - to send when something\n"
                          "goes wrong. No save files, no game files.")
            sp.linkActivated.connect(lambda _l: self._support())
            st_lay.addWidget(sp)
        row.addWidget(st_box, 1)

        how_box, how_lay = _box("How a mod gets into the game")
        how = QLabel(
            f"1. Change something on a <span style='color:{COLORS['scope_game']}'>"
            f"GAME FILES</span> page<br>"
            "2. Click <b>Save as mod</b> / <b>Export Field JSON</b><br>"
            "3. Load the file in <b>DMM</b> and mount – done. Disable it there to undo."
            f"<br><br><span style='color:{COLORS['text_dim']}'>[DLC] = needs the DLC. "
            "DMM skips such a mod without it.</span>")
        how.setTextFormat(Qt.RichText)
        how.setWordWrap(True)
        how_lay.addWidget(how)
        how_lay.addStretch()
        row.addWidget(how_box, 1)

        new_box, new_lay = _box(f"New in v{version}")
        new = QLabel("<br>".join(f"• {x}" for x in WHATS_NEW)
                     + f"<br><br><a href='{RELEASES_URL}' style='color:{COLORS['accent']}'>"
                     "Full changelog…</a>")
        new.setTextFormat(Qt.RichText)
        new.setOpenExternalLinks(True)
        new.setWordWrap(True)
        new_lay.addWidget(new)
        new_lay.addStretch()
        row.addWidget(new_box, 1)
        v.addLayout(row)

        v.addWidget(self._section("GAME FILES", "makes mods, load them in DMM",
                                  COLORS["scope_game"]))
        v.addLayout(self._grid(GAME_CARDS, COLORS["scope_game"]))
        v.addWidget(self._section("SAVE FILE", "changes your loaded save (back it up first)",
                                  COLORS["scope_save"]))
        v.addLayout(self._grid(SAVE_CARDS, COLORS["scope_save"]))
        v.addWidget(self._section("MORE", "reference", COLORS["text_dim"]))
        v.addLayout(self._grid(MORE_CARDS, COLORS["accent"]))

        self._start_cb = QCheckBox("Show this page at start (otherwise: the page used last)")
        self._start_cb.setChecked(bool(self._config.get("home_at_start", True)))
        self._start_cb.toggled.connect(self._on_start_toggled)
        v.addSpacing(6)
        v.addWidget(self._start_cb)
        v.addStretch()

    def _section(self, name: str, hint: str, color: str) -> QLabel:
        lab = QLabel(f"<span style='color:{color}; font-weight:bold; letter-spacing:1px'>"
                     f"{name}</span>  <span style='color:{COLORS['text_dim']}'>– {hint}</span>")
        lab.setTextFormat(Qt.RichText)
        lab.setContentsMargins(0, 10, 0, 2)
        return lab

    def _grid(self, cards, accent) -> QGridLayout:
        g = QGridLayout()
        g.setSpacing(10)
        for i, (label, desc) in enumerate(cards):
            g.addWidget(_Card(label, desc, accent, lambda l=label: self._goto(l)), i // 3, i % 3)
        for c in range(3):
            g.setColumnStretch(c, 1)
        return g

    def _on_start_toggled(self, on: bool) -> None:
        self._config["home_at_start"] = bool(on)
        if self._save_config:
            try:
                self._save_config()
            except Exception:  # noqa: BLE001
                pass

    def refresh(self) -> None:
        ok, warn = COLORS.get("success", "#3fb950"), COLORS.get("warning", "#d29922")
        try:
            game, version, dlc, save = self._status()
        except Exception:  # noqa: BLE001
            game, version, dlc, save = "", "", False, ""
        lines = []
        if game and os.path.isdir(game):
            lines.append(f"<span style='color:{ok}'>✔ Game found"
                         + (f" – version {version}" if version and version != "unknown" else "")
                         + "</span>")
            lines.append(f"<span style='color:{ok}'>✔ DLC \"Charting the Unknown\" installed</span>"
                         if dlc else
                         f"<span style='color:{COLORS['text_dim']}'>– DLC not installed "
                         "([DLC] entries stay hidden)</span>")
        else:
            lines.append(f"<span style='color:{warn}'>! Game not found – set the game "
                         "folder (File menu)</span>")
        if save:
            lines.append(f"<span style='color:{ok}'>✔ Save loaded: "
                         f"{os.path.basename(os.path.dirname(save)) or os.path.basename(save)}</span>")
        else:
            lines.append(f"<span style='color:{warn}'>! No save loaded – the SAVE FILE "
                         "pages need one (Save Browser)</span>")
        self._status_label.setText("<br>".join(lines))

    def showEvent(self, event):  # noqa: N802
        self.refresh()
        super().showEvent(event)
