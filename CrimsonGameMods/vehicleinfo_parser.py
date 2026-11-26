import logging
import struct

log = logging.getLogger(__name__)

DMM_TABLE_NAME = 'vehicle_info'


def parse_all_dmm(pabgb: bytes, pabgh: bytes):
    try:
        import dmm_parser
        return dmm_parser.parse_table(DMM_TABLE_NAME, pabgb, pabgh)
    except Exception:
        return None


def serialize_all_dmm(items: list) -> bytes | None:
    try:
        import dmm_parser
        return bytes(dmm_parser.serialize_table(DMM_TABLE_NAME, items))
    except Exception:
        return None


def parse_pabgh_index_u16(G):
    from table_index import legacy_index
    return legacy_index(G).offsets()


def parse_entry(D, eoff, end):
    try:
        p = eoff

        key = struct.unpack_from('<H', D, p)[0]; p += 2

        slen = struct.unpack_from('<I', D, p)[0]; p += 4
        if slen > 200:
            return None
        name = D[p:p + slen].decode('utf-8', errors='replace'); p += slen

        p += 1

        p += 4

        p += 4

        vehicle_type = D[p]; p += 1

        p += 16 * 8

        p += 1

        p += 2 * 8

        p += 12

        p += 1

        pl_count = struct.unpack_from('<I', D, p)[0]; p += 4 + pl_count

        voxel_type = struct.unpack_from('<I', D, p)[0]; p += 4

        f16 = D[p]; p += 1
        f17 = D[p]; p += 1

        vehicle_char_key = struct.unpack_from('<I', D, p)[0]; p += 4

        mount_call_type = D[p]; p += 1
        mount_call_type_offset = p - 1

        can_call_safe_zone = D[p]; p += 1
        can_call_safe_zone_offset = p - 1

        altitude_cap_raw = struct.unpack_from('<I', D, p)[0]
        altitude_cap = struct.unpack_from('<f', D, p)[0]; p += 4

        return {
            'key': key,
            'name': name,
            'vehicle_type': vehicle_type,
            'voxel_type': voxel_type,
            'f16': f16,
            'f17': f17,
            'vehicle_char_key': vehicle_char_key,
            'mount_call_type': mount_call_type,
            'mount_call_type_offset': mount_call_type_offset,
            'can_call_safe_zone': can_call_safe_zone,
            'can_call_safe_zone_offset': can_call_safe_zone_offset,
            'altitude_cap': altitude_cap,
            'altitude_cap_offset': p - 4,
        }

    except (struct.error, IndexError):
        return None


def parse_all_entries(pabgb_path, pabgh_path):
    with open(pabgb_path, 'rb') as f:
        D = f.read()
    with open(pabgh_path, 'rb') as f:
        G = f.read()

    idx = parse_pabgh_index_u16(G)
    sorted_offs = sorted(set(idx.values()))
    entries = []
    failures = 0

    for key, eoff in idx.items():
        bi = sorted_offs.index(eoff)
        end = sorted_offs[bi + 1] if bi + 1 < len(sorted_offs) else len(D)
        entry = parse_entry(D, eoff, end)
        if entry is None:
            failures += 1
        else:
            entries.append(entry)

    return entries, failures
