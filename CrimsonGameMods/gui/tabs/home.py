"""Home: the start page of the Game Mod Tool (new layout, 2.5).

Status tiles (game, DLC, save, tool), the pages as cards with an icon, and
on the right what is new, quick actions and how a mod gets into the game.
The page only reads; it changes nothing. The main window passes in callbacks
so this file stays free of main-window internals.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from gui.theme import COLORS

RELEASES_URL = "https://github.com/Don-Prosciutto/Crimson-Desert-Game-Mod-Tool-Updated/releases"

# Shown under "New in this version". Keep it to a few lines.
WHATS_NEW = [
    "Save Editor: add pets - 84 kinds, 101 more looks, full trust",
    "Map Colors: 25 world map colour schemes or your own",
    "Stores: DLC items in every shop, DLC Vendor with clean prices",
    "From 2.4.8: game 2.05.00, add any of the 57 mounts",
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
    ("Map Colors", "Colour schemes for the world map - presets or your own."),
    ("DropSets", "What enemies, chests and gathering drop."),
    ("SpawnEdit", "How many creatures spawn and how fast they come back."),
    ("SkillTree", "Swap move sets, skill cooldowns and costs."),
    ("MercPets", "Mercenaries and pets in the game files."),
    ("Game Browser", "Look into any game table (for tinkerers)."),
]
SAVE_CARDS = [
    ("Inventory", "Items, stacks, give and delete items."),
    ("Equipment", "Your gear, sockets, refining and dyes."),
    ("Mercenary/Pets", "Add mounts and pets, rename companions."),
    ("Quest Editor", "Complete or reset quests, story chapters."),
    ("Knowledge", "Unlock knowledge, recipes and abyss gates."),
    ("Backup", "Backups of your save files."),
]
MORE_CARDS = [
    ("Item Database", "Every item with icon, key and category."),
    ("Item Packs", "Ready-made item lists to add to a save."),
]


def _strong() -> str:
    return COLORS.get("text_strong", COLORS["text"])


def _soft() -> str:
    return COLORS.get("border_soft", COLORS["border"])


class _Chip(QLabel):
    """A tab of an area on its Home card; a click opens that tab."""

    def __init__(self, text: str, on_click: Callable[[], None]):
        super().__init__(text)
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("homeChip")
        self.setStyleSheet(
            f"QLabel#homeChip {{ background: {COLORS['selected']}; color: {COLORS['text']}; "
            f"border: 1px solid {_soft()}; border-radius: 10px; padding: 2px 9px; font-size: 11px; }}"
            f"QLabel#homeChip:hover {{ border-color: {COLORS['accent']}; color: {_strong()}; }}")

    def mousePressEvent(self, event):  # noqa: N802
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._on_click()
        event.accept()


class _Card(QFrame):
    def __init__(self, title: str, desc: str, accent: str, on_click: Callable[[], None],
                 icon_name: str = "", chips=None):
        super().__init__()
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("homeCard")
        self.setStyleSheet(
            f"QFrame#homeCard {{ background: {COLORS['panel']}; border: 1px solid "
            f"{_soft()}; border-radius: 12px; }}"
            f"QFrame#homeCard:hover {{ border: 1px solid {COLORS['accent']}; }}"
            f"QFrame#homeCard QLabel {{ background: transparent; border: none; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        tile = QLabel()
        tile.setFixedSize(36, 36)
        tile.setAlignment(Qt.AlignCenter)
        tile.setStyleSheet(f"QLabel {{ background: {COLORS['selected']}; border-radius: 9px; }}")
        try:
            from gui.icons import icon, icon_name_for
            tile.setPixmap(icon(icon_name or icon_name_for(title), accent, 18).pixmap(18, 18))
        except Exception:  # noqa: BLE001
            pass
        t = QLabel(title)
        t.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {_strong()};")
        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px;")
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(tile)
        head.addWidget(t, 1)
        lay.addLayout(head)
        lay.addWidget(d)
        if chips:
            from gui.flow_layout import FlowLayout
            fw = QWidget()
            fw.setStyleSheet("background: transparent;")
            fl = FlowLayout(fw)
            try:
                fl.setContentsMargins(0, 2, 0, 0)
            except Exception:  # noqa: BLE001
                pass
            for text, cb in chips:
                fl.addWidget(_Chip(text, cb))
            lay.addWidget(fw)
        lay.addStretch()
        self.setMinimumHeight(124)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(event)


class _Tile(QFrame):
    """A status tile: small label, big value, coloured note with a dot."""

    def __init__(self, label: str):
        super().__init__()
        self.setObjectName("homeTile")
        self.setStyleSheet(
            f"QFrame#homeTile {{ background: {COLORS['panel']}; border: 1px solid {_soft()}; "
            f"border-radius: 12px; }} QFrame#homeTile QLabel {{ background: transparent; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        cap = QLabel(label)
        cap.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 12px; font-weight: 600;")
        self.value = QLabel("–")
        self.value.setStyleSheet(f"color: {_strong()}; font-size: 19px; font-weight: 700;")
        self.note = QLabel("")
        self.note.setTextFormat(Qt.RichText)
        lay.addWidget(cap)
        lay.addWidget(self.value)
        lay.addWidget(self.note)

    def set(self, value: str, note: str, color: str) -> None:
        self.value.setText(value)
        self.note.setText(f"<span style='color:{color}'>●&nbsp; {note}</span>")


def _box(title: str) -> tuple:
    f = QFrame()
    f.setObjectName("homeBox")
    f.setStyleSheet(
        f"QFrame#homeBox {{ background: {COLORS['panel']}; border: 1px solid "
        f"{_soft()}; border-radius: 12px; }}"
        f"QFrame#homeBox QLabel {{ background: transparent; border: none; }}")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    h = QLabel(title)
    h.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {_strong()};")
    lay.addWidget(h)
    return f, lay


class HomePage(QWidget):
    """goto(label) opens a page; status() returns
    (game_path, game_version, dlc_installed, save_path or "");
    the show-at-start setting lives in config['home_at_start'].
    check_mods / support are optional quick actions."""

    def __init__(self, version: str, goto: Callable[[str], None],
                 status: Callable[[], tuple], config: dict,
                 save_config: Optional[Callable[[], None]] = None,
                 support: Optional[Callable[[], None]] = None,
                 check_mods: Optional[Callable[[], None]] = None, parent=None):
        super().__init__(parent)
        self._support = support
        self._goto = goto
        self._status = status
        self._config = config
        self._save_config = save_config
        self._version = version

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(32, 26, 32, 26)
        v.setSpacing(18)

        head = QVBoxLayout()
        head.setSpacing(4)
        title = QLabel("Welcome back")
        title.setStyleSheet(f"font-size: 28px; font-weight: 700; color: {_strong()};")
        sub = QLabel("Make mods for DMM and edit your save – pick an area on the left or a card below.")
        sub.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 14px;")
        head.addWidget(title)
        head.addWidget(sub)
        v.addLayout(head)

        tiles = QGridLayout()
        tiles.setSpacing(12)
        self._t_game = _Tile("Game version")
        self._t_dlc = _Tile("DLC")
        self._t_save = _Tile("Loaded save")
        self._t_tool = _Tile("Tool")
        for i, t in enumerate((self._t_game, self._t_dlc, self._t_save, self._t_tool)):
            tiles.addWidget(t, 0, i)
            tiles.setColumnStretch(i, 1)
        v.addLayout(tiles)

        cols = QHBoxLayout()
        cols.setSpacing(24)
        left = QVBoxLayout()
        left.setSpacing(12)
        try:
            from gui.area_nav import SECTIONS
        except Exception:  # noqa: BLE001
            SECTIONS = []
        heads = {
            "MOD THE GAME": ("Mod the game", "export a mod, load it in DMM", COLORS["scope_game"],
                             COLORS["accent"]),
            "MY SAVE": ("My save", "changes your loaded save – back it up first",
                        COLORS["scope_save"], COLORS["scope_save"]),
            "LIBRARY": ("Library", "reference", COLORS["text_dim"], COLORS["text_dim"]),
        }
        for group, _gcolor, areas in SECTIONS:
            if group not in heads:
                continue                         # START = this page
            name, hint, hcolor, accent = heads[group]
            left.addWidget(self._section(name, hint, hcolor))
            left.addLayout(self._area_grid(areas, accent))
        if not SECTIONS:                         # fallback: the old page cards
            left.addWidget(self._section("Game mods", "export a mod, load it in DMM", COLORS["scope_game"]))
            left.addLayout(self._grid(GAME_CARDS, COLORS["accent"]))
            left.addWidget(self._section("Save editor", "changes your loaded save – back it up first",
                                         COLORS["scope_save"]))
            left.addLayout(self._grid(SAVE_CARDS, COLORS["scope_save"]))
        left.addStretch()
        cols.addLayout(left, 1)

        right_w = QWidget()
        right_w.setFixedWidth(330)
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(16)

        new_box, new_lay = _box(f"New in v{version}")
        for x in WHATS_NEW:
            lab = QLabel(f"<span style='color:{COLORS['accent']}'>●</span>&nbsp; {x}")
            lab.setTextFormat(Qt.RichText)
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color: {COLORS['text']};")
            new_lay.addWidget(lab)
        more = QLabel(f"<a href='{RELEASES_URL}' style='color:{COLORS['accent']}'>Full changelog…</a>")
        more.setTextFormat(Qt.RichText)
        more.setOpenExternalLinks(True)
        new_lay.addWidget(more)
        right.addWidget(new_box)

        act_box, act_lay = _box("Quick actions")
        if check_mods is not None:
            b = QPushButton("Check my mods against this game")
            b.setObjectName("accentBtn")
            b.setMinimumHeight(40)
            b.clicked.connect(lambda: check_mods())
            act_lay.addWidget(b)
        b = QPushButton("Back up my saves")
        b.setMinimumHeight(40)
        b.clicked.connect(lambda: self._goto("Backup"))
        act_lay.addWidget(b)
        if support is not None:
            b = QPushButton("Create a support package")
            b.setMinimumHeight(40)
            b.setToolTip("A zip with versions, the tool's and DMM's log, the settings and\n"
                         "(if you want) the mod with the problem - to send when something\n"
                         "goes wrong. No save files, no game files.")
            b.clicked.connect(lambda: self._support())
            act_lay.addWidget(b)
        right.addWidget(act_box)

        how_box, how_lay = _box("How a mod gets into the game")
        how = QLabel(
            f"<b style='color:{COLORS['accent']}'>1</b>&nbsp; Change something on a game mods page<br>"
            f"<b style='color:{COLORS['accent']}'>2</b>&nbsp; Click Save as mod / Export Field JSON<br>"
            f"<b style='color:{COLORS['accent']}'>3</b>&nbsp; Load the file in DMM and mount – disable it there to undo"
            f"<br><br><span style='color:{COLORS['text_dim']}'>[DLC] = needs the DLC. DMM skips "
            "such a mod without it.</span>")
        how.setTextFormat(Qt.RichText)
        how.setWordWrap(True)
        how_lay.addWidget(how)
        right.addWidget(how_box)

        self._start_cb = QCheckBox("Show this page at start")
        self._start_cb.setToolTip("Otherwise the tool opens on the page used last.")
        self._start_cb.setChecked(bool(self._config.get("home_at_start", True)))
        self._start_cb.toggled.connect(self._on_start_toggled)
        right.addWidget(self._start_cb)
        credit = QLabel("Credits: RicePaddySoftware / NattKh, AerowynX, exodiaprivate-eng (parser).")
        credit.setWordWrap(True)
        credit.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 11px;")
        right.addWidget(credit)
        right.addStretch()
        cols.addWidget(right_w, 0, Qt.AlignTop)
        v.addLayout(cols, 1)

    def _section(self, name: str, hint: str, color: str) -> QLabel:
        lab = QLabel(f"<span style='color:{_strong()}; font-size:17px; font-weight:700'>{name}</span>"
                     f"&nbsp;&nbsp;<span style='color:{color}; font-size:12px'>{hint}</span>")
        lab.setTextFormat(Qt.RichText)
        lab.setContentsMargins(0, 6, 0, 0)
        return lab

    def _grid(self, cards, accent) -> QGridLayout:
        g = QGridLayout()
        g.setSpacing(12)
        for i, (label, desc) in enumerate(cards):
            g.addWidget(_Card(label, desc, accent, lambda l=label: self._goto(l)), i // 3, i % 3)
        for c in range(3):
            g.setColumnStretch(c, 1)
        return g

    def _area_grid(self, areas, accent) -> QGridLayout:
        """One card per area: click = its first tab, chips = its tabs."""
        g = QGridLayout()
        g.setSpacing(12)
        for i, (name, icon_name, _scope, desc, tabs) in enumerate(areas):
            pages = [(tab, page) for tab, page, _note in tabs]
            first = pages[0][1] if pages else name
            chips = ([(tab, (lambda pg=page: self._goto(pg))) for tab, page in pages]
                     if len(pages) > 1 else None)
            g.addWidget(_Card(name, desc, accent, lambda pg=first: self._goto(pg),
                              icon_name=icon_name, chips=chips), i // 2, i % 2)
        for c in range(2):
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
        ok = COLORS.get("success", "#3fb950")
        warn = COLORS.get("warning", "#d29922")
        dim = COLORS["text_dim"]
        info = COLORS.get("scope_save", COLORS["accent"])
        try:
            game, version, dlc, save = self._status()
        except Exception:  # noqa: BLE001
            game, version, dlc, save = "", "", False, ""
        if game and os.path.isdir(game):
            shown = version if version and version != "unknown" else "found"
            self._t_game.set(shown, "Game folder found", ok)
            if dlc:
                self._t_dlc.set("Installed", "Charting the Unknown", ok)
            else:
                self._t_dlc.set("Not installed", "[DLC] entries stay hidden", dim)
        else:
            self._t_game.set("Not found", "Set the game folder (File menu)", warn)
            self._t_dlc.set("–", "needs the game folder", dim)
        if save:
            name = os.path.basename(os.path.dirname(save)) or os.path.basename(save)
            self._t_save.set(name, "Loaded", info)
        else:
            self._t_save.set("None", "Open one in the Save Browser", warn)
        self._t_tool.set(f"v{self._version}", "Game Mod Tool + Save Editor", dim)

    def showEvent(self, event):  # noqa: N802
        self.refresh()
        super().showEvent(event)
