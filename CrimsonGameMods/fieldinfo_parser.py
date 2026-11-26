import logging
import struct
import sys
import os

log = logging.getLogger(__name__)

DMM_TABLE_NAME = 'field_info'


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


def _u8(D, p):
    return D[p], p + 1

def _u16(D, p):
    return struct.unpack_from('<H', D, p)[0], p + 2

def _u32(D, p):
    return struct.unpack_from('<I', D, p)[0], p + 4

def _cstring(D, p):
    slen, p = _u32(D, p)
    if slen > 10000:
        return None, -1
    s = D[p:p + slen].decode('utf-8', errors='replace')
    return s, p + slen

def _skip_cstring(D, p):
    slen, p = _u32(D, p)
    if slen > 10000:
        return -1
    return p + slen


def parse_pabgh_index(G):
    from table_index import legacy_index
    return legacy_index(G).offsets()


def parse_entry(D, eoff, end):
    p = eoff
    entry = {}

    try:
        entry['key'], p = _u32(D, p)

        entry['name'], p = _cstring(D, p)
        if p < 0:
            return None

        _, p = _u8(D, p)

        entry['field_type1'], p = _u32(D, p)
        entry['field_type2'], p = _u32(D, p)

        _, p = _u32(D, p)

        entry['flag1'], p = _u8(D, p)
        entry['flag2'], p = _u8(D, p)
        entry['flag3'], p = _u8(D, p)
        entry['flag4'], p = _u8(D, p)

        _, p = _u32(D, p)

        x = struct.unpack_from('<f', D, p)[0]; p += 4
        y = struct.unpack_from('<f', D, p)[0]; p += 4
        z = struct.unpack_from('<f', D, p)[0]; p += 4
        entry['position'] = (round(x, 2), round(y, 2), round(z, 2))

        p += 8
        p += 8

        p += 4 * 4

        entry['zone_type'], p = _u16(D, p)

        entry['can_call_vehicle'], p = _u8(D, p)
        entry['can_call_vehicle_offset'] = p - 1

        _, p = _u8(D, p)


        entry['always_call_vehicle_dev'] = D[end - 1]
        entry['always_call_vehicle_dev_offset'] = end - 1

        if end - 13 > p:
            entry['region_key1'] = struct.unpack_from('<I', D, end - 13)[0]
            entry['region_key2'] = struct.unpack_from('<I', D, end - 9)[0]
            entry['region_key3'] = struct.unpack_from('<I', D, end - 5)[0]

        return entry

    except (struct.error, IndexError):
        return None


def parse_all_entries(pabgb_path, pabgh_path):
    with open(pabgb_path, 'rb') as f:
        D = f.read()
    with open(pabgh_path, 'rb') as f:
        G = f.read()

    idx = parse_pabgh_index(G)
    sorted_offs = sorted(set(idx.values()))
    entries = []
    failures = 0

    for key, eoff in idx.items():
        bi = sorted_offs.index(eoff)
        end = sorted_offs[bi + 1] if bi + 1 < len(sorted_offs) else len(D)

        entry = parse_entry(D, eoff, end)
        if entry is None:
            failures += 1
            continue
        entries.append(entry)

    return entries, failures


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')

    try:
        import crimson_rs
        game_path = 'C:/Program Files (x86)/Steam/steamapps/common/Crimson Desert'
        dp = 'gamedata/binary__/client/bin'
        body = crimson_rs.extract_file(game_path, '0008', dp, 'fieldinfo.pabgb')
        gh = crimson_rs.extract_file(game_path, '0008', dp, 'fieldinfo.pabgh')
        with open('fieldinfo_game.pabgb', 'wb') as f:
            f.write(body)
        with open('fieldinfo_game.pabgh', 'wb') as f:
            f.write(gh)
        pb, pg = 'fieldinfo_game.pabgb', 'fieldinfo_game.pabgh'
        print(f"Extracted fieldinfo: pabgb={len(body)}B pabgh={len(gh)}B")
    except Exception as e:
        print(f"Could not extract from game: {e}")
        EXT = 'C:/Users/Coding/CrimsonDesertModding/extractedpaz/0008_full'
        pb = f'{EXT}/fieldinfo.pabgb'
        pg = f'{EXT}/fieldinfo.pabgh'

    entries, failures = parse_all_entries(pb, pg)
    print(f"Parsed: {len(entries)} entries, {failures} failures")

    from collections import Counter
    acv = Counter()
    ccv = Counter()
    for e in entries:
        acv[e['always_call_vehicle_dev']] += 1
        ccv[e['can_call_vehicle']] += 1

    print(f"\n_alwaysCallVehicle_dev: {dict(acv.most_common())}")
    print(f"_canCallVehicle: {dict(ccv.most_common())}")

    print(f"\nSample entries:")
    for e in sorted(entries, key=lambda x: x['key'])[:20]:
        name = e['name'][:40]
        print(f"  key={e['key']:>8d} {name:40s} canCall={e['can_call_vehicle']} alwaysDev={e['always_call_vehicle_dev']} pos={e['position']}")
