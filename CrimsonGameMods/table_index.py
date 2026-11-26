"""Read and rebuild the index (.pabgh) of a game table, in both layouts.

A table is a body (.pabgb, the records end to end) plus an index (.pabgh)
that says where each record starts. The index exists in two layouts:

  up to game 2.05:  count, then per record  key + offset
                    (count u16 or u32, key u8/u16/u32, some tables carry
                    4 or 12 more bytes beside the key)
  since game 2.06:  count, then per record  key + u32 length + name
                    + u32 offset + u32 size
                    (the record's name moved from the body into the index)

This module only reads and writes the index. It does not decode records -
that stays the job of dmm_parser. It exists because several places in the
tool read the index on their own (item keys for the "new in game data"
badge, the stacker, Edit items, index rebuilds after an edit) and those
must work with both layouts. No Qt in here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterable, Optional

OLD = "old"      # up to 2.05: key + offset
NEW = "new"      # since 2.06: key + name + offset + size

_MAX_NAME = 4096


@dataclass
class IndexEntry:
    key: int                 # the lookup key (see _key_value)
    offset: int              # where the record starts in the body
    size: Optional[int]      # record length; NEW only (OLD: from offsets)
    name: Optional[str]      # the record's name; NEW only
    raw_key: bytes           # the key bytes exactly as on disk
    name_raw: bytes = b""    # the name bytes exactly as on disk (NEW)


@dataclass
class TableIndex:
    layout: str              # OLD or NEW ("" for an empty index)
    count_size: int          # bytes of the leading count (1, 2 or 4)
    key_size: int            # bytes of the key part per entry
    entries: list = field(default_factory=list)

    # -- reading -----------------------------------------------------------
    def keys(self) -> list:
        return [e.key for e in self.entries]

    def offsets(self) -> dict:
        """key -> offset (last one wins on duplicate keys)."""
        return {e.key: e.offset for e in self.entries}

    def sizes(self, body_len: int) -> dict:
        """key -> record length. OLD has no sizes on disk, so each record
        runs to the next higher offset (or the end of the body)."""
        if self.layout == NEW:
            return {e.key: e.size for e in self.entries}
        starts = sorted({e.offset for e in self.entries}) + [body_len]
        nxt = {starts[i]: starts[i + 1] for i in range(len(starts) - 1)}
        return {e.key: nxt[e.offset] - e.offset for e in self.entries}

    def spans(self, body_len: int) -> list:
        """(entry, start, end) in index order."""
        if self.layout == NEW:
            return [(e, e.offset, e.offset + e.size) for e in self.entries]
        starts = sorted({e.offset for e in self.entries}) + [body_len]
        nxt = {starts[i]: starts[i + 1] for i in range(len(starts) - 1)}
        return [(e, e.offset, nxt[e.offset]) for e in self.entries]

    def records(self, body: bytes) -> dict:
        """key -> the record's bytes."""
        return {e.key: bytes(body[a:b]) for e, a, b in self.spans(len(body))}

    # -- writing -----------------------------------------------------------
    def to_bytes(self) -> bytes:
        out = bytearray(len(self.entries).to_bytes(self.count_size, "little"))
        for e in self.entries:
            out += e.raw_key
            if self.layout == NEW:
                out += struct.pack("<I", len(e.name_raw)) + e.name_raw
                out += struct.pack("<II", e.offset, e.size)
            else:
                out += struct.pack("<I", e.offset)
        return bytes(out)

    def with_spans(self, spans: dict) -> bytes:
        """The index with new places for the records: `spans` maps
        key -> (offset, size). Raises KeyError for a key it lacks."""
        return self.with_span_list([spans[e.key] for e in self.entries])

    def with_span_list(self, spans: list) -> bytes:
        """Like with_spans, but `spans` is a list of (offset, size) in index
        order - for tables whose keys are not unique."""
        if len(spans) != len(self.entries):
            raise ValueError(f"{len(spans)} places for {len(self.entries)} records")
        out = TableIndex(self.layout, self.count_size, self.key_size)
        for e, (off, size) in zip(self.entries, spans):
            out.entries.append(IndexEntry(e.key, off, size if self.layout == NEW else None,
                                          e.name, e.raw_key, e.name_raw))
        return out.to_bytes()


def _key_value(raw: bytes) -> int:
    # 12-byte keys (aieventtableinfo): u16 FFFF, u16 0, u32 hash, u32 c -
    # the hash is the lookup key. 8-byte keys (characterappearanceindexinfo):
    # u32 key + i32 parent. Everything else: the whole key, little endian.
    if len(raw) == 12:
        return int.from_bytes(raw[4:8], "little")
    if len(raw) == 8:
        return int.from_bytes(raw[:4], "little")
    return int.from_bytes(raw, "little")


# (count size, key size) as seen up to 2.05 - order matters for ambiguous sizes
_OLD_SHAPES = ((2, 4), (2, 2), (4, 4), (2, 1), (4, 8), (2, 12), (1, 1))
_NEW_COUNT = (2, 4, 1)
_NEW_KEY = (4, 2, 1, 8, 12)


def _try_new(h: bytes, cs: int, ks: int) -> Optional[TableIndex]:
    n = int.from_bytes(h[:cs], "little")
    p = cs
    idx = TableIndex(NEW, cs, ks)
    end = len(h)
    for _ in range(n):
        if p + ks + 4 > end:
            return None
        raw = h[p:p + ks]
        p += ks
        ln = struct.unpack_from("<I", h, p)[0]
        p += 4
        if ln > _MAX_NAME or p + ln + 8 > end:
            return None
        name_raw = h[p:p + ln]
        p += ln
        off, size = struct.unpack_from("<II", h, p)
        p += 8
        try:
            name = name_raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
        idx.entries.append(IndexEntry(_key_value(raw), off, size, name, raw, name_raw))
    return idx if p == end else None


def _try_old(h: bytes, cs: int, ks: int) -> Optional[TableIndex]:
    n = int.from_bytes(h[:cs], "little")
    step = ks + 4
    if cs + n * step != len(h):
        return None
    idx = TableIndex(OLD, cs, ks)
    for i in range(n):
        b = cs + i * step
        raw = h[b:b + ks]
        off = struct.unpack_from("<I", h, b + ks)[0]
        idx.entries.append(IndexEntry(_key_value(raw), off, None, None, raw))
    return idx


def read_index(pabgh: bytes, layout: Optional[str] = None) -> TableIndex:
    """Parse an index in either layout. `layout` forces OLD or NEW.
    Raises ValueError when it fits neither."""
    h = bytes(pabgh)
    if len(h) < 1:
        raise ValueError("empty index")
    # an index with no records
    for cs in (4, 2, 1):
        if len(h) == cs and int.from_bytes(h, "little") == 0:
            return TableIndex(layout or "", cs, 0)
    if layout in (None, NEW):
        # NEW first: its walk is strict (lengths, names, exact end), so an
        # OLD index practically never passes it; the reverse is not true.
        for cs in _NEW_COUNT:
            if len(h) < cs:
                continue
            for ks in _NEW_KEY:
                idx = _try_new(h, cs, ks)
                if idx is not None and idx.entries:
                    return idx
    if layout in (None, OLD):
        for cs, ks in _OLD_SHAPES:
            if len(h) < cs:
                continue
            idx = _try_old(h, cs, ks)
            if idx is not None:
                return idx
    raise ValueError(f"unknown index layout ({len(h)} bytes)")


class NewLayoutError(ValueError):
    """A reader that walks the record bytes itself only knows the layout up
    to game 2.05 (name at the start of each record)."""


def legacy_index(pabgh: bytes) -> TableIndex:
    """read_index for the old record readers: raises NewLayoutError for a
    game 2.06 table, so they fail loudly instead of misreading records."""
    idx = read_index(pabgh)
    if idx.layout == NEW:
        raise NewLayoutError("table uses the game 2.06 layout; this reader only "
                             "knows the layout up to 2.05")
    return idx


def index_layout(pabgh: bytes) -> str:
    """OLD, NEW, or "" when the index is empty or unknown."""
    try:
        return read_index(pabgh).layout
    except ValueError:
        return ""


def index_keys(pabgh: bytes) -> list:
    return read_index(pabgh).keys()


def index_offsets(pabgh: bytes) -> dict:
    return read_index(pabgh).offsets()


def record_spans(pabgh: bytes, body_len: int) -> list:
    """[(key, start, end)] in index order."""
    return [(e.key, a, b) for e, a, b in read_index(pabgh).spans(body_len)]
