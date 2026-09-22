"""Check whether an edited save is still sound - BEFORE writing it.

Why this is needed
------------------
On 2026-09-22 a save that had been given an Abyss gem in an empty socket
through the editor made the game crash on startup - before the main menu, so
no save could be loaded at all any more. The file looked perfectly fine:

  - the schema parsed (103 types)
  - all 1211 blocks present, sizes consistent
  - item count unchanged
  - the C++ validation during writing reported nothing

The damage only showed up in a single number: the collector that gathers the
internal offsets found 1,832 offsets FEWER than before - even though it walked
the save all the way to the end. So one region was no longer walkable, and the
game stumbled over it.

That number is exactly what this module checks.

What it costs
-------------
The collector needs about six seconds on a 6.7 MB save. That is why the full
check only runs when the save has changed its SIZE - that is, for changes that
insert or remove something. Whoever only overwrites a value (stack, enchant,
swapping a gem) changes no length, moves no offsets, and gets the quick check.
"""

from __future__ import annotations

import logging
from typing import NamedTuple, Optional

log = logging.getLogger(__name__)


class Verdict(NamedTuple):
    ok: bool
    title: str
    text: str
    detail: str = ""

    @property
    def checked(self) -> bool:
        """Could anything be checked at all?"""
        return self.title != "not checkable"


def _blocks(blob: bytes):
    """Read schema and block table. Raises when the structure is broken."""
    import save_parser
    schema = save_parser.parse_schema(blob)
    type_names = [t.name for t in schema["types"]]
    toc = save_parser.parse_toc(blob, schema["schema_end"], type_names)
    return schema, toc


def _count_offsets(blob: bytes) -> int:
    from parc_inserter2 import parse_and_collect
    _result, offsets, _sizes = parse_and_collect(blob)
    return len(offsets)


def quick_check(edited: bytes) -> Verdict:
    """Can the save still be read at all?

    Catches gross damage and costs less than a second. It does NOT catch fine
    damage to the internal offsets - that is what the full check is for.
    """
    try:
        schema, toc = _blocks(edited)
    except Exception as e:  # noqa: BLE001
        return Verdict(False, "save no longer readable",
                       f"The edited save can no longer be parsed:\n\n{e}", "")
    entries = toc["entries"]
    for e in entries:
        if e.data_offset < 0 or e.data_offset + e.data_size > len(edited):
            return Verdict(False, "block extends past the end of the file",
                           f"Block #{e.index} ({e.class_name}) reaches beyond the end "
                           f"of the save.", "")
    return Verdict(True, "ok",
                   f"{len(schema['types'])} types, {len(entries)} blocks read.")


def full_check(original: bytes, edited: bytes,
               offsets_before: Optional[int] = None) -> Verdict:
    """After a size change, are all internal offsets still walkable?

    `offsets_before` can be passed in when the number is already known - that
    saves half the runtime.
    """
    quick = quick_check(edited)
    if not quick.ok:
        return quick

    try:
        before = offsets_before if offsets_before is not None else _count_offsets(original)
        after = _count_offsets(edited)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not count internal offsets: %s", e)
        return Verdict(True, "not checkable",
                       f"The internal offsets could not be counted ({e}). "
                       f"The save is readable; nothing more can be said here.")

    lost = before - after
    log.info("Offset check: before %d, after %d (%+d)", before, after, -lost)
    if lost > 0:
        return Verdict(
            False, "internal offsets lost",
            f"After this change, {lost} internal offsets can no longer be "
            f"found ({before} → {after}).\n\n"
            f"The save still parses, but one region is no longer walkable end "
            f"to end. That is exactly how the save looked that stopped the game "
            f"from starting.\n\n"
            f"This change should not be written.",
            f"offsets before {before}, after {after}, difference {-lost}")
    return Verdict(True, "ok",
                   f"offsets complete ({before} → {after}), {quick.text}")


def check(original: bytes, edited: bytes,
          offsets_before: Optional[int] = None) -> Verdict:
    """Pick the right check: quick when the size is unchanged, full otherwise."""
    if original is not None and len(original) == len(edited):
        verdict = quick_check(edited)
        log.info("Save size unchanged (%d bytes) - quick check: %s",
                 len(edited), verdict.title)
        return verdict
    log.info("Save size changed (%d -> %d bytes) - running the full check",
             len(original) if original is not None else -1, len(edited))
    return full_check(original, edited, offsets_before)
