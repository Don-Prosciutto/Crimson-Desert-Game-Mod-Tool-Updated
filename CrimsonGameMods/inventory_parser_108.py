"""Byte-level inventory_info parser for bag space mods.
Extracts key, string_key, default_slot_count, max_slot_count with offsets.
Works by using dmm_parser for entries that parse typed, and byte-level
fallback for entries that don't (like Character with complex GameCondition)."""
import struct
import logging

log = logging.getLogger(__name__)


def parse_inventory_entries(pabgb: bytes, pabgh: bytes) -> list[dict]:
    """Parse inventory.pabgb into dicts with slot count fields and offsets.

    Returns list of dicts with:
      key, string_key, default_slot_count, max_slot_count,
      _default_slot_offset, _max_slot_offset, _entry_offset, _entry_size
    """
    # Parse pabgh index
    from table_index import legacy_index
    entries = sorted(((e.key, e.offset) for e in legacy_index(pabgh).entries),
                     key=lambda x: x[1])

    results = []
    for i, (key, off) in enumerate(entries):
        end = entries[i + 1][1] if i + 1 < len(entries) else len(pabgb)
        size = end - off
        try:
            r = _parse_entry(pabgb, off, end)
            if r:
                r['key'] = key
                r['_entry_offset'] = off
                r['_entry_size'] = size
                results.append(r)
        except Exception as e:
            log.debug("inventory entry key=%d parse error: %s", key, e)

    return results


def _parse_entry(data: bytes, offset: int, end: int) -> dict | None:
    """Parse a single inventory entry at byte level."""
    o = offset
    result = {}

    # key: u16
    o += 2

    # string_key: CString (u32 len + bytes)
    slen = struct.unpack_from('<I', data, o)[0]
    o += 4
    if slen > 10000:
        return None
    result['string_key'] = data[o:o + slen].decode('utf-8', errors='replace')
    o += slen

    # is_blocked: u8
    o += 1

    # Skip CArrays: pushable_item_type_list, excluded_item_type_list
    for _ in range(2):
        cnt = struct.unpack_from('<I', data, o)[0]
        o += 4 + cnt * 3  # InventoryPushableData = u16 + u8 = 3B

    # inventory_move_data_list: CArray — complex, need to skip over
    move_cnt = struct.unpack_from('<I', data, o)[0]
    o += 4

    # We can't easily parse InventoryMoveData (has GameCondition trees).
    # Instead, search for default_slot_count by scanning from the end.
    # The last fields are fixed: ...u8, u8, u8, CArray<{u32,u64}=12B>
    # Working backwards from end to find the slot counts.

    # The tail pattern (from end):
    # collection_item_list: CArray count(4B) + N*12B
    # is_pushable_item_only_one: u8
    # need_save_slot_count: u8
    # is_moveable_inventory: u8
    # npc_usable_cooltime_max: u32
    # npc_usable_cooltime_min: u32
    # pushable_check_type: u8
    # key_guide_local_string_info: u32
    # inventory_name_ui_text: LocalizableString (u8 + u64 + CString)
    # push_item_alert_ui_text: LocalizableString (u8 + u64 + CString)
    # max_slot_count: u16  ← TARGET
    # default_slot_count: u16  ← TARGET

    # Parse from the END to find the slot counts
    # Start from the very end and work backwards through known fixed fields
    p = end

    # collection_item_list at the end: u32 count + N * 12B
    # We need to find the count. Scan backwards for a plausible count.
    # Try: the last 4 bytes before any collection data could be a small count
    # Actually, let's try a different approach: scan for the u16 pair (slot counts)
    # by looking for two consecutive u16 values where both are 1-1000.

    # Simpler approach: parse from the start through the move data list
    # by scanning for the end of the move data using entry boundaries.
    # After all moves, the next bytes are default_slot_count (u16) + max_slot_count (u16).

    # We know move_cnt moves start at offset o.
    # Each move has variable length. But we can scan for the slot counts
    # by finding where a valid u16 pair sits followed by LocalizableStrings.

    # Scan from the END backwards to find slot counts.
    # Tail structure (from end): collection_item CArray(4+N*12) + 3*u8(3) + 2*u32(8)
    # + u8(1) + u32(4) + 2*LocalizableString(variable) + max_slot(u16) + default_slot(u16)
    #
    # Try different collection_item counts (0, 1, 2, ..., 20)
    for try_cc in range(0, 30):
        tail_fixed = 4 + try_cc * 12 + 3 + 8 + 1 + 4  # collection + u8s + u32s + u8 + u32
        if tail_fixed >= end - offset:
            break
        # Position of key_guide_local_string_info start
        kg_pos = end - tail_fixed
        # Validate collection count
        cc_pos = end - (4 + try_cc * 12)
        actual_cc = struct.unpack_from('<I', data, cc_pos)[0]
        if actual_cc != try_cc:
            continue
        # Before key_guide: 2 LocalizableStrings (scan backwards)
        # Each LS = u8(1) + u64(8) + CString(4+N)
        # Work backwards from kg_pos through 2 LocalizableStrings
        # This is hard backwards. Instead, try slot count positions.
        # The slot counts are 4 bytes before the first LocalizableString.
        # Scan backwards from kg_pos for valid LS patterns.
        for ls_total_guess in range(26, min(end - offset, 2000)):
            slot_pos = kg_pos - ls_total_guess
            if slot_pos < offset + 20:
                break
            dsc = struct.unpack_from('<H', data, slot_pos)[0]
            msc = struct.unpack_from('<H', data, slot_pos + 2)[0]
            if not (1 <= dsc <= 1000 and 1 <= msc <= 1000):
                continue
            # Validate forward: 2 LocalizableStrings from slot_pos+4
            try:
                p2 = slot_pos + 4
                for _ in range(2):
                    p2 += 1 + 8  # u8 + u64
                    slen = struct.unpack_from('<I', data, p2)[0]
                    if slen > 10000:
                        raise ValueError("bad LS")
                    p2 += 4 + slen
                if p2 == kg_pos:
                    result['default_slot_count'] = dsc
                    result['max_slot_count'] = msc
                    result['_default_slot_offset'] = slot_pos
                    result['_max_slot_offset'] = slot_pos + 2
                    return result
            except (struct.error, IndexError, ValueError):
                continue

    return result if 'default_slot_count' in result else None


def modify_slots(pabgb: bytearray, entries: list[dict],
                 target_name: str, default_slots: int, max_slots: int) -> bool:
    """Modify slot counts for a named inventory entry in-place."""
    for e in entries:
        if e.get('string_key') == target_name:
            off_d = e.get('_default_slot_offset')
            off_m = e.get('_max_slot_offset')
            if off_d is not None and off_m is not None:
                struct.pack_into('<H', pabgb, off_d, min(default_slots, 65535))
                struct.pack_into('<H', pabgb, off_m, min(max_slots, 65535))
                return True
    return False
