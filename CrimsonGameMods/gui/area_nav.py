"""Navigation by task (new look 2.5): ten areas instead of thirty pages.

The pages stay where they always were (in ``_real_tabs`` and its group tab
widgets); an area only decides which of them it shows as tabs. Code that
opens a page by its old name (Home cards, last page, Save Editor jumps)
keeps working, and the navigation follows.

Each area item in the tree keeps its pages as hidden child items with the
usual ("page", holder, widget) data, so the game check in selftest_ui can
still find, grey out and disable them.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QTabBar, QTabWidget, QTreeWidgetItem,
                               QTreeWidgetItemIterator, QVBoxLayout, QWidget)

from gui.theme import COLORS

log = logging.getLogger(__name__)

# section, colour key, areas:
#   (area, icon, scope, subtitle, [(tab text, old page name it opens, tooltip)])
SECTIONS = [
    ("START", "text_dim", [
        ("Home", "home", "", "Status, shortcuts and what is new", [
            ("Home", "Home", "")]),
    ]),
    ("MOD THE GAME", "scope_game", [
        ("Items & Gear", "buffs", "game", "Change any item – stats, buffs, sockets, stacks – or apply presets to many items", [
            ("Edit items", "ItemBuffs", "Formerly “ItemBuffs”"),
            ("Quick presets", "Presets", "Formerly “Presets”"),
            ("Combine mods", "Stacker Tool", "Formerly “Stacker Tool”")]),
        ("Shops & Loot", "stores", "game", "What vendors sell and what enemies, chests and gathering drop", [
            ("Shops", "Stores", "Formerly “Stores” – incl. the DLC Vendor"),
            ("Drops", "DropSets", "Formerly “DropSets”")]),
        ("Characters & Mounts", "mounts", "game", "Mount speed and cooldowns, NPC behaviour, looks, move sets and skills", [
            ("Mounts", "Mounts", ""),
            ("Characters", "Characters", ""),
            ("Looks", "Mesh Swap", "Formerly “Mesh Swap” (transmog)"),
            ("Skills & move sets", "SkillTree", "Formerly “SkillTree”"),
            ("Mercenaries", "MercPets", "Formerly “MercPets (game files)”")]),
        ("World", "world", "game", "Creature spawns, world map colours and storage space", [
            ("Spawns", "SpawnEdit", "Formerly “SpawnEdit”"),
            ("Map colours", "Map Colors", ""),
            ("Storage space", "BagSpace", "Formerly “BagSpace”")]),
    ]),
    ("MY SAVE", "scope_save", [
        ("Inventory & Gear", "equip", "save", "The items in your save – stacks, refining, sockets, dyes, swaps and buy-backs", [
            ("Items", "Inventory", "Formerly “Inventory”"),
            ("Equipped", "Equipment", "Formerly “Equipment”"),
            ("Sockets", "Sockets", ""),
            ("Dye", "Dye", ""),
            ("Item swap", "Item Swap", ""),
            ("Buy back", "Repurchase", "Formerly “Repurchase”")]),
        ("Companions", "pets", "save", "Your mounts, pets and mercenaries – add new ones, rename them", [
            ("Companions", "Mercenary/Pets", "Formerly “Mercenary/Pets”")]),
        ("Progress", "quest", "save", "Quests and story chapters, knowledge, abyss gates and factions", [
            ("Quests", "Quest Editor", "Formerly “Quest Editor”"),
            ("Quest database", "Quest Database", ""),
            ("Knowledge", "Knowledge", ""),
            ("Abyss gates", "Abyss Gates", ""),
            ("Factions", "Faction", "")]),
        ("Backups", "backup", "save", "Every change to a save is backed up first – restore any of them here", [
            ("Backups", "Backup", "")]),
    ]),
    ("LIBRARY", "text_dim", [
        ("Item Library", "items", "lib", "Every item in the game with its key, and ready-made item packs", [
            ("All items", "Item Database", "Formerly “Item Database”"),
            ("Item packs", "Item Packs", "")]),
        ("Advanced", "browser", "expert", "Raw game tables and the load order of mounted mods – for experts", [
            ("Game Browser", "Game Browser", ""),
            ("Load Manager", "Load Manager", "")]),
    ]),
]
FALLBACK_AREA = "Advanced"   # pages no area names (new ones, hidden extras) land here

SCOPE_BADGE = {
    "game": ("Makes a mod · load it in DMM", "scope_game"),
    "save": ("Changes your save file", "scope_save"),
    "lib": ("Reference · changes nothing", "text_dim"),
    "expert": ("Expert tools", "text_dim"),
}


def _c(key: str, fallback: str = "#93a4bd") -> str:
    return COLORS.get(key) or fallback


def _strong() -> str:
    return COLORS.get("text_strong", COLORS["text"])


# ── building ─────────────────────────────────────────────────────────────────

def build_tab_row(win) -> QWidget:
    """The row of area tabs under the top bar; returns its container."""
    row = QWidget()
    row.setObjectName("areaTabsRow")
    row.setAttribute(Qt.WA_StyledBackground, True)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(20, 0, 14, 0)
    lay.setSpacing(0)
    bar = QTabBar()
    bar.setObjectName("areaTabs")
    bar.setDrawBase(False)
    bar.setExpanding(False)
    bar.setDocumentMode(True)
    bar.setUsesScrollButtons(True)
    bar.setFocusPolicy(Qt.NoFocus)
    lay.addWidget(bar)
    lay.addStretch(1)
    row.setStyleSheet(
        f"QWidget#areaTabsRow {{ background: {COLORS['bg']}; "
        f"border-bottom: 1px solid {_c('border_soft', COLORS['border'])}; }}"
        f"QTabBar#areaTabs {{ background: transparent; border: none; }}"
        f"QTabBar#areaTabs::tab {{ background: {COLORS['panel']}; "
        f"border: 1px solid {COLORS['border']}; border-radius: 15px; padding: 6px 16px; "
        f"margin: 9px 8px 9px 0px; color: {COLORS['text']}; font-size: 13px; font-weight: 600; }}"
        f"QTabBar#areaTabs::tab:hover {{ border-color: {COLORS['accent']}; color: {_strong()}; }}"
        f"QTabBar#areaTabs::tab:selected {{ background: {COLORS['selected']}; color: {_strong()}; "
        f"border: 1px solid {COLORS['accent']}; }}"
        f"QTabBar#areaTabs::tab:disabled {{ color: {COLORS['text_dim']}; }}")
    bar.currentChanged.connect(lambda i: _tab_changed(win, i))
    win._area_bar = bar
    win._area_row = row
    win._area_current = ""
    win._areas = {}
    return row


def build_scope_badge(win) -> QLabel:
    lab = QLabel("")
    lab.setVisible(False)
    win._page_scope = lab
    return lab


def _pages(win):
    """(holder, widget, name) for every visible page, in tab order."""
    rt = win._real_tabs
    out = []
    for i in range(rt.count()):
        page = rt.widget(i)
        if isinstance(page, QTabWidget):
            if page.count() == 0:
                continue
            page.tabBar().hide()
            page.setDocumentMode(True)
            if id(page) not in win._nav_watched:
                page.currentChanged.connect(lambda _i: win._nav_sync())
                win._nav_watched.add(id(page))
            for j in range(page.count()):
                if hasattr(page, "isTabVisible") and not page.isTabVisible(j):
                    continue
                out.append((page, page.widget(j), page.tabText(j)))
        else:
            out.append((rt, page, rt.tabText(i)))
    return out


def _set_icon(item, name: str, on: bool) -> None:
    try:
        from gui.icons import icon
        item.setIcon(0, icon(name, COLORS["accent"] if on else COLORS["text_dim"], 18))
        item.setData(0, Qt.UserRole + 10, on)
    except Exception:  # noqa: BLE001 - icons are decoration only
        pass


def rebuild(win) -> None:
    nav = win._nav
    pages = _pages(win)
    used: set = set()
    areas: dict = {}
    nav.blockSignals(True)
    nav.clear()
    nav.setItemsExpandable(False)
    for section, ckey, section_areas in SECTIONS:
        sec = QTreeWidgetItem([section])
        f = QFont(nav.font())
        f.setBold(True)
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.8))
        f.setLetterSpacing(QFont.PercentageSpacing, 110)
        sec.setFont(0, f)
        sec.setForeground(0, QColor(_c(ckey, COLORS["text_dim"])))
        sec.setFlags(Qt.ItemIsEnabled)
        sec.setData(0, Qt.UserRole, ("section", section))
        sec.setSizeHint(0, sec.sizeHint(0))
        nav.addTopLevelItem(sec)
        sec.setFirstColumnSpanned(True)
        for name, icon_name, scope, sub, tabs in section_areas:
            entries = []
            for tab, prefix, tip in tabs:
                want = prefix.lower()
                hit = next(((h, w, n) for h, w, n in pages
                            if id(w) not in used and n.lower().startswith(want)), None)
                if hit is None:
                    continue
                used.add(id(hit[1]))
                entries.append({"tab": tab, "holder": hit[0], "widget": hit[1],
                                "tip": tip, "name": hit[2]})
            if name == FALLBACK_AREA:
                for h, w, n in pages:
                    if id(w) not in used:
                        used.add(id(w))
                        entries.append({"tab": n, "holder": h, "widget": w, "tip": "", "name": n})
            if not entries:
                continue
            it = QTreeWidgetItem([name])
            it.setData(0, Qt.UserRole, ("area", name))
            it.setToolTip(0, sub)
            _set_icon(it, icon_name, False)
            nav.addTopLevelItem(it)
            it.setFirstColumnSpanned(True)
            for e in entries:
                ch = QTreeWidgetItem(it, [e["name"]])
                ch.setData(0, Qt.UserRole, ("page", e["holder"], e["widget"]))
                if e["tip"]:
                    ch.setToolTip(0, e["tip"])
                ch.setHidden(True)
                e["item"] = ch
            areas[name] = {"icon": icon_name, "scope": scope, "sub": sub,
                           "tabs": entries, "item": it}
    win._areas = areas
    nav.blockSignals(False)
    win._area_current = ""
    sync(win)
    try:
        win._selftest_apply_to_nav()
    except Exception:  # noqa: BLE001
        log.exception("game check on the navigation")
    _fill_tabs(win, win._area_current)


# ── switching ────────────────────────────────────────────────────────────────

def _show(win, holder, widget) -> None:
    rt = win._real_tabs
    if holder is rt:
        rt.setCurrentWidget(widget)
    else:
        rt.setCurrentWidget(holder)
        holder.setCurrentWidget(widget)


def _remember(win, area: str, page_name: str) -> None:
    try:
        win._config["last_page"] = page_name
        per = dict(win._config.get("area_tab") or {})
        per[area] = page_name
        win._config["area_tab"] = per
    except Exception:  # noqa: BLE001
        pass


def clicked(win, item, _col=0) -> None:
    data = item.data(0, Qt.UserRole)
    if not data:
        return
    if data[0] == "area":
        area = win._areas.get(data[1])
        if not area:
            return
        last = (win._config.get("area_tab") or {}).get(data[1])
        entry = next((e for e in area["tabs"] if e["name"] == last), None)
        if entry is None:
            entry = next((e for e in area["tabs"]
                          if not getattr(e["widget"], "_selftest_blocked", False)), area["tabs"][0])
        _show(win, entry["holder"], entry["widget"])
        _remember(win, data[1], entry["name"])
    elif data[0] == "page":
        _show(win, data[1], data[2])
    else:
        # a section heading: keep the open area selected
        sync(win)


def _tab_changed(win, index: int) -> None:
    area = win._areas.get(win._area_current)
    if not area or not (0 <= index < len(area["tabs"])):
        return
    e = area["tabs"][index]
    _show(win, e["holder"], e["widget"])
    _remember(win, win._area_current, e["name"])


def _fill_tabs(win, area_name: str, current: int = -1) -> None:
    bar = getattr(win, "_area_bar", None)
    if bar is None:
        return
    area = win._areas.get(area_name)
    bar.blockSignals(True)
    while bar.count():
        bar.removeTab(0)
    if area:
        for k, e in enumerate(area["tabs"]):
            blocked = getattr(e["widget"], "_selftest_blocked", False)
            # '&' would turn into a keyboard shortcut and vanish ("Skills  move sets")
            bar.addTab(e["tab"].replace("&", "&&") + ("  (blocked)" if blocked else ""))
            tip = e["tip"]
            if blocked:
                tip = (e["item"].toolTip(0) if e.get("item") is not None else "") or "Blocked by the game check"
            bar.setTabToolTip(k, tip)
        if current >= 0:
            bar.setCurrentIndex(current)
    bar.blockSignals(False)
    win._area_row.setVisible(bool(area) and len(area["tabs"]) > 1)


def _header(win, area_name: str) -> None:
    area = win._areas.get(area_name)
    if not area or not hasattr(win, "_page_title"):
        return
    win._page_title.setText(area_name)
    win._page_sub.setText(area["sub"])
    win._page_sub.setVisible(bool(area["sub"]))
    lab = getattr(win, "_page_scope", None)
    if lab is not None:
        badge = SCOPE_BADGE.get(area["scope"])
        if badge:
            color = _c(badge[1], COLORS["text_dim"])
            q = QColor(color)
            lab.setText(badge[0])
            lab.setStyleSheet(
                f"QLabel {{ color: {color}; background: rgba({q.red()},{q.green()},{q.blue()},38); "
                f"border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; }}")
        lab.setVisible(bool(badge))
    try:
        win._refresh_top_pills()
    except Exception:  # noqa: BLE001
        pass


def sync(win) -> None:
    """Select the area of the open page, fill its tabs and the header."""
    nav = getattr(win, "_nav", None)
    if nav is None or not getattr(win, "_areas", None):
        return
    rt = win._real_tabs
    page = rt.currentWidget()
    target = page.currentWidget() if isinstance(page, QTabWidget) and page.count() else page
    found, index = "", -1
    for name, area in win._areas.items():
        for k, e in enumerate(area["tabs"]):
            if e["widget"] is target:
                found, index = name, k
                break
        if found:
            break
    if not found:
        return
    for name, area in win._areas.items():
        on = name == found
        if area["item"].data(0, Qt.UserRole + 10) != on:
            _set_icon(area["item"], area["icon"], on)
    nav.blockSignals(True)
    nav.setCurrentItem(win._areas[found]["item"])
    nav.blockSignals(False)
    if found != "Home":
        from gui.page_polish import polish_safe
        polish_safe(target)
    if found != win._area_current:
        win._area_current = found
        _fill_tabs(win, found, index)
        _header(win, found)
    else:
        bar = win._area_bar
        # labels may have changed after the game check
        _fill_tabs(win, found, index)
        if bar.currentIndex() != index:
            bar.blockSignals(True)
            bar.setCurrentIndex(index)
            bar.blockSignals(False)
