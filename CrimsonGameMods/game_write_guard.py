"""Writing into the game is switched off.

Since game 2.04.00 the game signs its pack list (meta/0.papgt). If that file or
a pack index (<group>/0.pamt) changes, the game refuses to start. Every
"Apply to Game" path of this tool works by writing exactly those files, so on
2.04 it can only break the installation. The tool therefore never writes into
the game folder any more; changes leave it as Field JSON files.

Two layers:
  * install() wraps the parser's write_papgt_file / write_pamt_file. A write
    whose target lies in a game installation raises GameWriteBlocked, so no
    code path can reach the game files, buttons or not.
  * attach(window) disables every "Apply to Game" style button and explains
    why in its tooltip. It re-checks every few seconds, because some pages
    build their buttons only when first opened.

No Qt at import time; Qt is only touched inside attach().
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

MESSAGE = (
    "Writing to the game is switched off.\n\n"
    "Since game 2.04 the game signs its pack list (meta/0.papgt) and will not "
    "start if that file or a pack index changes. Use Export Field JSON instead."
)

# Button texts that write into the game (compared case-insensitively, without
# '&' and check marks).
_BUTTON_TEXTS = ("apply to game", "apply stack", "apply single")


class GameWriteBlocked(RuntimeError):
    """Raised instead of writing into a game installation."""


def _is_game_dir(path: str) -> bool:
    return bool(path) and os.path.isdir(os.path.join(path, "bin64")) and os.path.isdir(os.path.join(path, "meta"))


def targets_game(path) -> bool:
    """Does this file path point into a Crimson Desert installation?

    meta/0.papgt and <group>/0.pamt both sit one folder below the game root.
    """
    try:
        p = os.path.abspath(os.fspath(path))
    except TypeError:
        return False
    return _is_game_dir(os.path.dirname(os.path.dirname(p)))


def _wrap(module, name: str) -> None:
    original = getattr(module, name, None)
    if original is None or getattr(original, "_game_write_guard", False):
        return

    def guarded(data, path, *args, **kwargs):
        if targets_game(path):
            log.warning("Blocked %s.%s into the game: %s", module.__name__, name, path)
            raise GameWriteBlocked(MESSAGE)
        return original(data, path, *args, **kwargs)

    guarded._game_write_guard = True
    guarded.__wrapped__ = original
    setattr(module, name, guarded)


def install() -> None:
    """Wrap the parser write functions of both bundled parsers."""
    for mod_name in ("crimson_rs", "dmm_parser"):
        try:
            module = __import__(mod_name)
        except Exception as e:  # noqa: BLE001 - a missing parser must not stop the tool
            log.info("game_write_guard: %s not importable (%s)", mod_name, e)
            continue
        for fn in ("write_papgt_file", "write_pamt_file"):
            _wrap(module, fn)
    log.info("game_write_guard: writes into the game folder are blocked")


def _norm(text: str) -> str:
    return " ".join(text.replace("&", "").replace("✔", "").split()).lower()


def switch_off(btn) -> None:
    """Disable one button for good and say why."""
    if getattr(btn, "_game_write_off", False):
        return
    btn.setEnabled(False)
    btn.setToolTip(MESSAGE)
    # Pages enable their buttons again after loading data; keep this one off.
    btn.setEnabled = lambda *_a, _b=btn: type(_b).setEnabled(_b, False)
    btn._game_write_off = True


def disable_buttons(root) -> int:
    """Disable every button that writes into the game. Returns how many."""
    from PySide6.QtWidgets import QAbstractButton

    count = 0
    for btn in root.findChildren(QAbstractButton):
        if getattr(btn, "_game_write_off", False):
            continue
        if _norm(btn.text()) not in _BUTTON_TEXTS:
            continue
        switch_off(btn)
        count += 1
    return count


def attach(window) -> None:
    """Disable the buttons now and keep them disabled."""
    try:
        from PySide6.QtCore import QTimer
    except Exception:  # noqa: BLE001
        return
    n = disable_buttons(window)
    log.info("game_write_guard: %d write button(s) disabled", n)
    timer = QTimer(window)
    timer.setInterval(3000)
    timer.timeout.connect(lambda: disable_buttons(window))
    timer.start()
    window._game_write_guard_timer = timer
