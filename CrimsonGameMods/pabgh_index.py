"""Rebuild a table's .pabgh index after records changed size.

A .pabgh holds, for every record, its key and its byte offset in the
.pabgb (since game 2.06 also its name and size - see table_index). dmm_parser reads the
body record by record and does not need correct offsets - the game does.
So when an edit makes a record longer or shorter (a list gets an entry
more, a string gets longer), shipping the game's original .pabgh makes the
game read every later record at the wrong place.

rebuild_index() serializes each record on its own, adds up the sizes and
writes new offsets. It returns None when the layout is not the expected
one, then the caller must not write the table. No Qt in here.
"""

from __future__ import annotations

from typing import Optional


def _serialize_one(dmm, stem: str, rec: dict) -> bytes:
    out = dmm.serialize_table(stem, [rec])
    return bytes(out[0] if isinstance(out, tuple) else out)


def rebuild_index(stem: str, body: bytes, pabgh: bytes, dmm=None,
                  recs: Optional[list] = None) -> Optional[bytes]:
    """New .pabgh for `body`. Pass `recs` (the records `body` was written
    from) for tables that dmm_parser can only read through a fitting index.
    Works with both index layouts (see table_index); the new one also gets
    the record sizes."""
    from table_index import read_index  # noqa: PLC0415
    if dmm is None:
        import dmm_parser as dmm  # noqa: PLC0415
    body, pabgh = bytes(body), bytes(pabgh)
    try:
        idx = read_index(pabgh)
    except ValueError:
        return None
    count = len(idx.entries)
    if count == 0:
        return None
    if recs is None:
        try:
            recs = dmm.parse_table(stem, body, pabgh)
        except Exception:  # noqa: BLE001
            return None
    if len(recs) != count:
        return None
    spans = {}
    pos = 0
    parts = []
    for r in recs:
        try:
            chunk = _serialize_one(dmm, stem, r)
        except Exception:  # noqa: BLE001
            return None
        k = int(r.get("key"))
        if k in spans:                # duplicate keys: offsets not unique
            return None
        spans[k] = (pos, len(chunk))
        parts.append(chunk)
        pos += len(chunk)
    if b"".join(parts) != body:       # records are not simply laid end to end
        return None
    try:
        return idx.with_spans(spans)
    except KeyError:
        return None
