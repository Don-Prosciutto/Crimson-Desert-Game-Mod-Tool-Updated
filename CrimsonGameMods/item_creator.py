"""Custom item creator — clone existing items under new keys.

Pipeline:
  1. clone_item()     — copy donor binary, patch key + name + echo keys
  2. inject_to_store() — add item key to a vendor's item list
  3. Deploy via overlay (iteminfo → 0058, storeinfo → 0060)

Ported from Benreuveni's crimson-desert-add-item with adaptations for
our crimson_rs + overlay pipeline.
"""

from __future__ import annotations

import struct
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── Paloc ID formula (game's runtime name lookup) ────────────────────

def compute_paloc_ids(item_key: int) -> tuple[int, int]:
    """Return (name_id, description_id) for localization lookup.

    The game computes: name = (item_key << 32) | 0x70
                       desc = (item_key << 32) | 0x71
    """
    return (item_key << 32) | 0x70, (item_key << 32) | 0x71


# ── Key validation ───────────────────────────────────────────────────

CUSTOM_KEY_START = 999001

def find_next_free_key(existing_keys: set[int],
                       start: int = CUSTOM_KEY_START) -> int:
    """Find the next available item key that doesn't conflict."""
    key = start
    while key in existing_keys:
        key += 1
    return key


def validate_key(key: int, existing_keys: set[int]) -> tuple[bool, str]:
    """Check if a key is valid for a new custom item."""
    if key <= 0:
        return False, "Key must be positive"
    if key in existing_keys:
        return False, f"Key {key} already exists in iteminfo"
    if key < CUSTOM_KEY_START:
        return False, f"Key should be >= {CUSTOM_KEY_START} to avoid vanilla collisions"
    return True, "Available"


# ── Item cloning ─────────────────────────────────────────────────────

def clone_item_bytes(
    donor_bytes: bytes,
    donor_key: int,
    new_key: int,
    new_internal_name: str,
) -> bytes:
    """Clone a donor item's raw binary bytes under a new key and name.

    Modifies:
      - Leading u32 key
      - String key (internal name after u32 name_len)
      - All 0x07 0x70/0x71 echo-key references (for localization lookup)

    Args:
        donor_bytes: the complete binary blob of the donor item
        donor_key: the donor's original item key
        new_key: the new key to assign
        new_internal_name: new ASCII internal name (e.g. "Custom_Sword_999001")

    Returns:
        New item bytes with patched key, name, and echo keys.
    """
    if not new_internal_name or not all(
        c.isalnum() or c == "_" for c in new_internal_name
    ):
        raise ValueError(
            f"Internal name must be ASCII alphanumeric/underscore: "
            f"{new_internal_name!r}"
        )

    # Parse donor header: u32 key + u32 name_len + name + u8 null
    old_name_len = struct.unpack_from("<I", donor_bytes, 4)[0]
    if donor_bytes[8 + old_name_len] != 0:
        raise ValueError("Donor header malformed (missing null terminator)")

    # Rebuild header with new key and name
    rest = donor_bytes[8 + old_name_len + 1:]  # everything after null terminator
    name_bytes = new_internal_name.encode("ascii")
    clone = bytearray(
        struct.pack("<II", new_key, len(name_bytes))
        + name_bytes
        + b"\x00"
        + rest
    )

    # Patch echo keys: 0x07 + u32(0x70 or 0x71) + u32(old_key) → new_key
    echo_count = _patch_echo_keys(clone, donor_key, new_key)
    log.info(
        "Cloned %s (key %d -> %d): %d echo keys patched, "
        "size %d -> %d (delta %+d)",
        new_internal_name, donor_key, new_key, echo_count,
        len(donor_bytes), len(clone),
        len(clone) - len(donor_bytes),
    )
    return bytes(clone)


def _patch_echo_keys(data: bytearray, old_key: int, new_key: int) -> int:
    """Patch 0x07 + u32(0x70|0x71) + u32(old_key) echo markers.

    These tagged blocks are how the game resolves item names at runtime.
    Returns count of patches applied.
    """
    count = 0
    pos = 0
    while pos < len(data) - 9:
        if data[pos] == 0x07:
            marker = struct.unpack_from("<I", data, pos + 1)[0]
            if marker in (0x70, 0x71):
                echo_off = pos + 5
                echo_val = struct.unpack_from("<I", data, echo_off)[0]
                if echo_val == old_key:
                    struct.pack_into("<I", data, echo_off, new_key)
                    count += 1
                    pos = echo_off + 4
                    continue
        pos += 1
    return count


# ── Iteminfo pabgb/pabgh rebuild ─────────────────────────────────────

def build_iteminfo_pabgh(pabgb_bytes: bytes, extra_entries: list = None) -> bytes:
    """Rebuild iteminfo.pabgh (key -> offset index) from pabgb bytes.

    The game uses pabgh to look items up by key during equip / inventory
    operations. Vanilla pabgh encodes offsets into the vanilla pabgb; when
    we ship a modified (usually larger) pabgb without a matching pabgh,
    vanilla offsets land mid-entry and items after the first size change
    become unreachable — rings / cloaks / etc. appear in inventory but lose
    sockets, buffs, and other mutated fields.

    Format: u16 count + N * (u32 key, u32 offset_into_pabgb). Offsets are
    absolute byte offsets, same as what parse_iteminfo_tracked returns via
    spans[i]['start']. Verified to round-trip bit-exact against vanilla.
    """
    import crimson_rs

    # Scan pabgb sequentially: each entry starts with key(u32) + name_len(u32) + name.
    # We parse each item to find its size, building a key→offset index.
    entry_list = []
    _off = 0
    while _off + 8 < len(pabgb_bytes):
        _key = struct.unpack_from('<I', pabgb_bytes, _off)[0]
        if _key == 0 or _key > 0x10000000:
            break
        entry_list.append((_key, _off))
        # Try parsing to find item size
        try:
            _slice = pabgb_bytes[_off:min(_off + 20000, len(pabgb_bytes))]
            _parsed = crimson_rs.parse_iteminfo_from_bytes(_slice)
            if _parsed:
                _ser = crimson_rs.serialize_iteminfo([_parsed[0]])
                _off += len(_ser)
                continue
        except Exception:
            pass
        # Parse failed — try reading name_len to skip past header, then scan
        # for next valid entry
        _nl = struct.unpack_from('<I', pabgb_bytes, _off + 4)[0]
        if 0 < _nl <= 512:
            _off += 8 + _nl  # skip past header
        else:
            break
        # Scan for next item key
        _found_next = False
        while _off + 8 < len(pabgb_bytes):
            _nk = struct.unpack_from('<I', pabgb_bytes, _off)[0]
            _nnl = struct.unpack_from('<I', pabgb_bytes, _off + 4)[0]
            if 0 < _nk < 0x10000000 and 0 < _nnl <= 512:
                try:
                    pabgb_bytes[_off + 8:_off + 8 + _nnl].decode('ascii')
                    _found_next = True
                    break
                except Exception:
                    pass
            _off += 1
        if not _found_next:
            break

    if extra_entries:
        entry_list.extend(extra_entries)

    out = bytearray(struct.pack("<H", len(entry_list)))
    for _key, _start in entry_list:
        out += struct.pack("<II", _key, _start)
    return bytes(out)


def append_items_to_iteminfo(
    vanilla_body: bytes,
    vanilla_head: bytes,
    new_items: list[tuple[int, bytes]],
) -> tuple[bytes, bytes]:
    """Append new items to iteminfo.pabgb and register in pabgh.

    Args:
        vanilla_body: decompressed iteminfo.pabgb
        vanilla_head: decompressed iteminfo.pabgh
        new_items: list of (new_key, new_item_bytes) to append

    Returns:
        (new_body, new_head) ready for overlay deployment.
    """
    # Parse existing pabgh
    # The appended records carry their name in the body - the layout up to
    # game 2.05. A 2.06 table (name in the index) stops here.
    from table_index import legacy_index
    entries: list[tuple[int, int]] = [(e.key, e.offset)
                                      for e in legacy_index(vanilla_head).entries]

    existing_keys = {k for k, _ in entries}

    new_body = bytearray(vanilla_body)
    new_entries = list(entries)

    for key, item_bytes in new_items:
        if key in existing_keys:
            raise ValueError(f"Key {key} already in iteminfo")
        new_entries.append((key, len(new_body)))
        new_body += item_bytes
        existing_keys.add(key)

    # Rebuild pabgh
    new_head = struct.pack("<H", len(new_entries))
    for k, o in new_entries:
        new_head += struct.pack("<II", k, o)

    return bytes(new_body), bytes(new_head)


# ── Store injection ──────────────────────────────────────────────────

def add_item_to_store(
    store_parser,
    store_key: int,
    item_key: int,
    buy_price: int = 1,
    sell_price: int = 0,
) -> bool:
    """Add a custom item to a store's item list.

    Uses the existing StoreinfoParser instance to modify a store record.
    Returns True if successful.
    """
    store = None
    for s in store_parser.stores:
        if s.key == store_key:
            store = s
            break
    if store is None:
        log.error("Store key %d not found", store_key)
        return False

    # Check if item already in store
    for it in store.items:
        if it.item_key == item_key:
            log.info("Item %d already in store %d", item_key, store_key)
            return True

    # Clone the last item's raw bytes as a template, patch the key
    if not store.items:
        log.error("Store %d has no items to use as template", store_key)
        return False

    template = store.items[-1]
    from storeinfo_parser import StoreItemEntry
    new_entry = StoreItemEntry(
        offset=0,  # will be recalculated on serialize
        store_key_ref=template.store_key_ref,
        buy_price=buy_price,
        sell_price=sell_price,
        trade_flags=template.trade_flags,
        item_key=item_key,
        item_key_dup=item_key,
        extra_field=template.extra_field,
        raw=b'',  # will be rebuilt
    )
    store.items.append(new_entry)
    store.item_count = len(store.items)

    log.info(
        "Added item %d to store %s (key %d), price=%d",
        item_key, store.name, store_key, buy_price,
    )
    return True
