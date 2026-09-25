"""Rebuild a table's .pabgh index after records changed size.

A .pabgh holds, for every record, its key and its byte offset in the
.pabgb (u16 count, then key + u32 offset per record). dmm_parser reads the
body record by record and does not need correct offsets - the game does.
So when an edit makes a record longer or shorter (a list gets an entry
more, a string gets longer), shipping the game's original .pabgh makes the
game read every later record at the wrong place.

rebuild_index() serializes each record on its own, adds up the sizes and
writes new offsets. It returns None when the layout is not the expected
one, then the caller must not write the table. No Qt in here.
"""

from __future__ import annotations

import struct
from typing import Optional


def _serialize_one(dmm, stem: str, rec: dict) -> bytes:
    out = dmm.serialize_table(stem, [rec])
    return bytes(out[0] if isinstance(out, tuple) else out)


def rebuild_index(stem: str, body: bytes, pabgh: bytes, dmm=None) -> Optional[bytes]:
    if dmm is None:
        import dmm_parser as dmm  # noqa: PLC0415
    body, pabgh = bytes(body), bytes(pabgh)
    if len(pabgh) < 2:
        return None
    count = struct.unpack_from("<H", pabgh, 0)[0]
    if count == 0 or (len(pabgh) - 2) % count:
        return None
    step = (len(pabgh) - 2) // count
    if step not in (6, 8):            # u16 or u32 key, then u32 offset
        return None
    key_fmt = "<H" if step == 6 else "<I"
    try:
        recs = dmm.parse_table(stem, body, pabgh)
    except Exception:  # noqa: BLE001
        return None
    if len(recs) != count:
        return None
    offsets = {}
    pos = 0
    parts = []
    for r in recs:
        try:
            chunk = _serialize_one(dmm, stem, r)
        except Exception:  # noqa: BLE001
            return None
        k = int(r.get("key"))
        if k in offsets:              # duplicate keys: offsets not unique
            return None
        offsets[k] = pos
        parts.append(chunk)
        pos += len(chunk)
    if b"".join(parts) != body:       # records are not simply laid end to end
        return None
    out = bytearray(pabgh[:2])
    for i in range(count):
        base = 2 + i * step
        key = struct.unpack_from(key_fmt, pabgh, base)[0]
        if key not in offsets:
            return None
        out += pabgh[base:base + step - 4] + struct.pack("<I", offsets[key])
    return bytes(out)
