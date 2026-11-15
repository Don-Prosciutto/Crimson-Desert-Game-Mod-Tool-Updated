"""Calm, modern look for the pages that are not redesigned one by one yet
(new look 2.5). Runs once per page, the first time it is shown.

* the "This tab modifies your SAVE FILE / GAME FILES" banners are hidden -
  the top bar shows that for every area now,
* boxed info texts lose their frame and colour and read as quiet hints,
  long how-to texts become a "How it works" hint with the text as tooltip,
* buttons coloured with the old role colours (red / green / yellow / blue)
  become normal buttons; risky ones (red) keep a red outline,
* tables lose row numbers and grid lines and get a little more room,
* the page gets the same outer margins as the redesigned ones.
Nothing changes what a button does; widgets stay where they are.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_BANNER_STARTS = ("This tab modifies", "This tab makes mods", "This tab is READ-ONLY")
_BANNER_TEXTS = (
    "This tab modifies your SAVE FILE", "This tab modifies your SAVE FILE / GAME FILES",
    "This tab modifies GAME FILES (requires admin + restart)",
    "This tab makes mods for the GAME FILES (save as mod, load it in DMM)",
    "This tab is READ-ONLY (browse only)", "This tab is READ-ONLY",
)


def _banner_starts() -> tuple:
    """The banner beginnings in English and in the language in use."""
    try:
        from gui_i18n import tr as _tr
        return _BANNER_STARTS + tuple(t for t in (_tr(b) for b in _BANNER_TEXTS) if t)
    except Exception:  # noqa: BLE001
        return _BANNER_STARTS


def _danger_marks():
    from gui.theme import COLORS
    marks = {"#3b1a22", "#ff5252", "#e53935", "#c62828", "#d32f2f", "#b71c1c", "#f44336"}
    bg = (COLORS.get("btn_danger") or ("",))[0]
    if bg:
        marks.add(bg.lower())
    return marks


def _find_in_layout(lay, widget):
    """(layout, index) of `widget` in `lay` or one of its nested layouts."""
    if lay is None:
        return None, -1
    i = lay.indexOf(widget)
    if i >= 0:
        return lay, i
    for k in range(lay.count()):
        sub = lay.itemAt(k).layout()
        if sub is not None:
            found = _find_in_layout(sub, widget)
            if found[1] >= 0:
                return found
    return None, -1


def polish(page) -> int:
    """Polish `page` once. Returns how many widgets changed."""
    if page is None or getattr(page, "_page_polished", False):
        return 0
    page._page_polished = True
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QPushButton, QTableView, QLayout
    from gui.theme import COLORS
    n = 0
    banner_starts = _banner_starts()
    danger = _danger_marks()
    err = COLORS.get("error", "#f87171")

    for lab in page.findChildren(QLabel):
        t = lab.text() or ""
        if t.startswith(banner_starts):
            lab.setVisible(False)
            n += 1
            continue
        # long how-to texts (several lines): a small "How it works" hint
        # with the text as tooltip instead of a wall of text on the page
        if lab.wordWrap() and t.count("\n") >= 4 and len(t) > 250:
            parent_lay, idx = _find_in_layout(
                lab.parentWidget().layout() if lab.parentWidget() else None, lab)
            if idx >= 0 and hasattr(parent_lay, "insertWidget"):
                hint = QLabel("ⓘ  How it works - point here to read")
                hint.setToolTip(t)
                hint.setCursor(Qt.WhatsThisCursor)
                hint.setStyleSheet(f"color: {COLORS['accent']}; font-weight: 600; padding: 2px 0;")
                parent_lay.insertWidget(idx, hint)
                lab.setVisible(False)
                n += 1
                continue
        ss = (lab.styleSheet() or "").replace(" ", "").lower()
        if lab.wordWrap() and "border:1px" in ss and len(t) > 40:
            lab.setStyleSheet(f"color: {COLORS['text_dim']}; padding: 2px 2px 6px 2px; "
                              f"font-size: 12px; border: none; background: transparent;")
            n += 1

    for btn in page.findChildren(QPushButton):
        ss = btn.styleSheet() or ""
        low = ss.lower()
        if "background-color" not in low or btn.objectName() in ("accentBtn",):
            continue
        if btn.text().strip() in ("?",):
            continue
        if btn.property("swatch"):             # colour buttons (Dye): their colour is the point
            continue
        import re as _re
        _m = _re.search(r"background-color:\s*([^;}]+)", low)
        bg = _m.group(1).strip() if _m else ""
        accents = {(COLORS.get("accent") or "").lower(), (COLORS.get("btn_primary") or ("",))[0].lower()}
        if bg and bg in accents:
            btn.setObjectName("accentBtn")          # was an accent button: keep it one
            btn.setStyleSheet("")
            n += 1
            continue
        if any(m in low for m in danger):
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {err}; border: 1px solid {err}; "
                f"border-radius: 8px; padding: 5px 12px; font-weight: 600; }}"
                f"QPushButton:hover {{ background: rgba(248,113,113,0.12); }}"
                f"QPushButton:disabled {{ color: {COLORS['text_dim']}; border-color: {COLORS['border']}; }}")
        else:
            btn.setStyleSheet("")
        n += 1

    for tv in page.findChildren(QTableView):
        if tv.objectName() == "navTree":
            continue
        try:
            tv.verticalHeader().setVisible(False)
            tv.setShowGrid(False)
            if tv.verticalHeader().defaultSectionSize() < 28:
                tv.verticalHeader().setDefaultSectionSize(28)
            n += 1
        except Exception:  # noqa: BLE001
            pass

    lay = page.layout()
    if isinstance(lay, QLayout):
        m = lay.contentsMargins()
        if m.left() < 12:
            lay.setContentsMargins(14, max(m.top(), 10), 14, max(m.bottom(), 8))
    return n


def polish_safe(page) -> None:
    try:
        polish(page)
    except Exception:  # noqa: BLE001 - looks only
        log.exception("page polish")
