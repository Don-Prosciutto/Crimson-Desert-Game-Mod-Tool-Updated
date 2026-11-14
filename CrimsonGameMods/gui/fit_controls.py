"""Give squeezed buttons room (new look 2.5).

Many pages fix their buttons to 20-24 px height or a narrow width - right for
the old, flat style. The new style has more padding, so the text was cut off
at the top and bottom ("Home", "Backup", "…"). Instead of touching ~25 places
one by one, this grows every fixed-size text button that is too small for its
text. It runs again every few seconds, because some pages build their buttons
only when first opened.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MIN_HEIGHT = 28          # fits the theme's 5 px padding + a 10 pt bold label
_QWIDGETSIZE_MAX = 16777215


def fit(root) -> int:
    """Grow too-small fixed buttons and number fields below `root`.
    Returns how many changed."""
    from PySide6.QtWidgets import QDoubleSpinBox, QPushButton, QSpinBox

    changed = 0
    for sb in root.findChildren(QSpinBox) + root.findChildren(QDoubleSpinBox):
        if getattr(sb, "_fit_done", False):
            continue
        sb._fit_done = True
        if not (sb.minimumWidth() == sb.maximumWidth() and sb.maximumWidth() < _QWIDGETSIZE_MAX):
            continue
        widest = max(len(sb.textFromValue(sb.maximum())), len(sb.textFromValue(sb.minimum())), 2)
        need = sb.fontMetrics().horizontalAdvance("8" * widest + sb.suffix() + sb.prefix()) + 52
        if sb.maximumWidth() < need:
            sb.setFixedWidth(need)
            changed += 1
    for btn in root.findChildren(QPushButton):
        if getattr(btn, "_fit_done", False):
            continue
        text = (btn.text() or "").replace("&&", "&").strip()
        if not text:
            continue                       # icon-only buttons keep their size
        btn._fit_done = True
        fixed_w = btn.minimumWidth() == btn.maximumWidth() and btn.maximumWidth() < _QWIDGETSIZE_MAX
        fixed_h = btn.minimumHeight() == btn.maximumHeight() and btn.maximumHeight() < _QWIDGETSIZE_MAX
        if fixed_w and fixed_h:
            continue                       # small square arrow buttons (◀ ▲): leave them
        if fixed_h and btn.maximumHeight() < MIN_HEIGHT:
            btn.setFixedHeight(MIN_HEIGHT)
            changed += 1
        if fixed_w:
            need = btn.fontMetrics().horizontalAdvance(text) + 26
            if btn.maximumWidth() < need:
                btn.setFixedWidth(need)
                changed += 1
    return changed


def attach(window) -> None:
    try:
        from PySide6.QtCore import QTimer
    except Exception:  # noqa: BLE001
        return
    n = fit(window)
    log.info("fit_controls: %d squeezed button size(s) fixed", n)
    timer = QTimer(window)
    timer.setInterval(3000)
    timer.timeout.connect(lambda: fit(window))
    timer.start()
    window._fit_controls_timer = timer
