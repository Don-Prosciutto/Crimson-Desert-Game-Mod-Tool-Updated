"""Read the installed game version and hold it against the parser's target.

Why this is needed: the parser knows exactly one field layout. If a game
update inserts a field somewhere, everything behind it moves, and from that
point on the parser reads at the wrong positions. Sometimes it aborts - then
you see it. Sometimes it runs through and delivers nonsense, or writes tables
back truncated without a warning. That is exactly what went unnoticed for
months in the summer of 2026.

This check makes the case visible when the game path is set, instead of
letting it surface at the third damaged mod.

Experience from the 2.03.00 -> 2.03.01 update: a hotfix that moves only the
third number brought content growth in five tables, but no layout change.
That is why this check only warns on a differing major or minor version and
merely mentions a differing hotfix.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

# The game version the bundled parser was built for.
# Raise this together with a parser update.
PARSER_TARGET = "2.03.02"


def read_game_version(game_path: str) -> str | None:
    """Read meta/0.paver. Three u16 little-endian give major.minor.patch."""
    path = os.path.join(game_path or "", "meta", "0.paver")
    try:
        with open(path, "rb") as f:
            raw = f.read(6)
    except OSError as e:
        log.info("Game version not readable (%s): %s", path, e)
        return None
    if len(raw) < 6:
        return None
    parts = [int.from_bytes(raw[i:i + 2], "little") for i in (0, 2, 4)]
    return f"{parts[0]}.{parts[1]:02d}.{parts[2]:02d}"


def _three_parts(version: str) -> tuple[int, int, int]:
    try:
        parts = [int(t) for t in version.split(".")]
    except (ValueError, AttributeError):
        return (0, 0, 0)
    parts += [0, 0, 0]
    return tuple(parts[:3])  # type: ignore[return-value]


def check(game_path: str) -> tuple[str, str] | None:
    """Return (title, message) when there is something to report, else None."""
    installed = read_game_version(game_path)
    if not installed:
        return None

    game = _three_parts(installed)
    parser = _three_parts(PARSER_TARGET)

    if game[:2] != parser[:2]:
        direction = "newer" if game[:2] > parser[:2] else "older"
        return (
            "Game version does not match the parser",
            f"Installed game version: {installed}\n"
            f"The bundled parser targets: {PARSER_TARGET}\n\n"
            f"The game is {direction}. Tables may therefore be read "
            f"incorrectly — and worse, silently damaged when written "
            f"back.\n\n"
            f"Until a matching parser is available: do not build mods that "
            f"write to game tables."
        )

    if game[2] != parser[2]:
        return (
            "Different hotfix",
            f"Installed game version: {installed}\n"
            f"The parser targets: {PARSER_TARGET}\n\n"
            f"Only the last number differs. Experience says hotfixes do not "
            f"change the data layout, so the tool should work normally.\n\n"
            f"If tables do stop being read correctly, this is the first place "
            f"to look."
        )

    return None
