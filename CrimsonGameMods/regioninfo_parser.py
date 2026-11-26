
import struct
import json
import logging
import os
import sys

log = logging.getLogger(__name__)

DMM_TABLE_NAME = 'region_info'


def parse_all_dmm(pabgb: bytes, pabgh: bytes):
    """Parse regioninfo using dmm_parser. Returns list of dicts or None on failure."""
    try:
        import dmm_parser
        return dmm_parser.parse_table(DMM_TABLE_NAME, pabgb, pabgh)
    except Exception as e:
        log.debug("dmm_parser regioninfo failed: %s", e)
        return None


def serialize_all_dmm(items: list) -> bytes | None:
    """Serialize regioninfo using dmm_parser. Returns bytes or None on failure."""
    try:
        import dmm_parser
        return bytes(dmm_parser.serialize_table(DMM_TABLE_NAME, items))
    except Exception as e:
        log.debug("dmm_parser regioninfo serialize failed: %s", e)
        return None


def parse_pabgh_index(pabgh_data):
    from table_index import legacy_index
    return legacy_index(pabgh_data).offsets()

def parse_entry_header(data, off):
    return None, None, off

def parse_region_entry(data, off, end):
    _, _, p = parse_entry_header(data, off)
    result = {}

    try:
        result['_key'] = struct.unpack_from('<H', data, p)[0]; p += 2

        slen = struct.unpack_from('<I', data, p)[0]; p += 4
        if slen > 50000:
            result['_error'] = f'bad stringKey len={slen} at offset {p-4}'
            return result
        result['_stringKey'] = data[p:p+slen].decode('ascii', errors='replace'); p += slen

        result['_isBlocked'] = data[p]; p += 1

        flag = data[p]; p += 1
        hash_val = struct.unpack_from('<Q', data, p)[0]; p += 8
        dslen = struct.unpack_from('<I', data, p)[0]; p += 4
        if dslen > 50000:
            result['_error'] = f'bad displayRegionName len={dslen}'
            return result
        result['_displayRegionName_flag'] = flag
        result['_displayRegionName_hash'] = hash_val
        result['_displayRegionName_str'] = data[p:p+dslen].decode('utf-8', errors='replace'); p += dslen

        result['_knowledgeInfo'] = struct.unpack_from('<I', data, p)[0]; p += 4

        rk_count = struct.unpack_from('<I', data, p)[0]; p += 4
        if rk_count > 50000:
            result['_error'] = f'bad rk_count={rk_count}'
            return result
        rk_list = []
        for _ in range(rk_count):
            rk_key = struct.unpack_from('<I', data, p)[0]; p += 4
            rk_val = struct.unpack_from('<I', data, p)[0]; p += 4
            rk_list.append((rk_key, rk_val))
        result['_regionEnterknowledgeInfoList'] = rk_list

        result['_parentRegionInfo'] = struct.unpack_from('<H', data, p)[0]; p += 2

        cr_count = struct.unpack_from('<I', data, p)[0]; p += 4
        if cr_count > 50000:
            result['_error'] = f'bad cr_count={cr_count}'
            return result
        cr_list = []
        for _ in range(cr_count):
            cr_list.append(struct.unpack_from('<H', data, p)[0]); p += 2
        result['_childRegionInfoList'] = cr_list

        result['_bitmapColor_r'] = data[p]; p += 1

        result['_bitmapColor_g'] = data[p]; p += 1

        result['_overriedMaxHeight_raw'] = struct.unpack_from('<I', data, p)[0]
        result['_overriedMaxHeight_float'] = struct.unpack_from('<f', data, p)[0]
        p += 4

        result['_regionType'] = data[p]; p += 1

        result['_fogClearCondition'] = struct.unpack_from('<I', data, p)[0]; p += 4

        result['_limitVehicleRun'] = data[p]; p += 1

        result['_isTown'] = data[p]; p += 1

        result['_isWild'] = data[p]; p += 1

        result['_isUIMapDisable'] = data[p]; p += 1

        result['_isSaveGimmickRegion'] = data[p]; p += 1

        result['_isNonePlayZone'] = data[p]; p += 1

        result['_vehicleMercenaryAllowType'] = data[p]; p += 1

        result['_isWorldMapRoadPathFindable'] = data[p]; p += 1

        ga_count = struct.unpack_from('<I', data, p)[0]; p += 4
        if ga_count > 50000:
            result['_error'] = f'bad ga_count={ga_count}'
            return result
        ga_list = []
        for _ in range(ga_count):
            ga_key = struct.unpack_from('<I', data, p)[0]; p += 4
            ga_val = struct.unpack_from('<I', data, p)[0]; p += 4
            ga_list.append((ga_key, ga_val))
        result['_gimmickAliasPointerList'] = ga_list

        df_count = struct.unpack_from('<I', data, p)[0]; p += 4
        if df_count > 50000:
            result['_error'] = f'bad df_count={df_count}'
            return result
        df_list = []
        for _ in range(df_count):
            df_cond = struct.unpack_from('<I', data, p)[0]; p += 4
            df_faction = struct.unpack_from('<I', data, p)[0]; p += 4
            df_prison = struct.unpack_from('<I', data, p)[0]; p += 4
            df_list.append({'_condition': df_cond, '_domainFaction': df_faction, '_prisonStage': df_prison})
        result['_domainFactionList'] = df_list

        tl_count = struct.unpack_from('<I', data, p)[0]; p += 4
        if tl_count > 50000:
            result['_error'] = f'bad tl_count={tl_count}'
            return result
        tl_list = []
        for _ in range(tl_count):
            tl_list.append(struct.unpack_from('<I', data, p)[0]); p += 4
        result['_tagList'] = tl_list

        result['_parsed_bytes'] = p - off
        result['_entry_size'] = end - off
        result['_bytes_remaining'] = end - p

    except (struct.error, IndexError) as e:
        result['_error'] = str(e)
        result['_error_at_abs'] = p

    return result


def main():
    base = 'C:/Users/Coding/CrimsonDesertModding/extractedpaz/0008_full'
    with open(os.path.join(base, 'regioninfo.pabgb'), 'rb') as f:
        pabgb = f.read()
    with open(os.path.join(base, 'regioninfo.pabgh'), 'rb') as f:
        pabgh = f.read()

    entries = parse_pabgh_index(pabgh)
    sorted_entries = sorted(entries.items(), key=lambda x: x[1])
    sizes = {}
    for i in range(len(sorted_entries)):
        k, o = sorted_entries[i]
        if i + 1 < len(sorted_entries):
            sizes[k] = sorted_entries[i+1][1] - o
        else:
            sizes[k] = len(pabgb) - o

    success = 0
    fail = 0
    nonzero_remaining = 0
    results = []

    for key, eoff in sorted_entries:
        end = eoff + sizes[key]
        r = parse_region_entry(pabgb, eoff, end)
        results.append(r)
        if '_error' in r:
            fail += 1
            if fail <= 5:
                print(f'FAIL key={key}: {r["_error"]}', file=sys.stderr)
        else:
            success += 1
            rem = r['_bytes_remaining']
            if rem != 0:
                nonzero_remaining += 1
                if nonzero_remaining <= 5:
                    print(f'WARN key={key}: {rem} bytes remaining', file=sys.stderr)

    print(f'=== VALIDATION: {success}/{len(sorted_entries)} parsed OK, {fail} failed, {nonzero_remaining} with leftover bytes ===')

    for r in results[:3]:
        print(json.dumps({k: v for k, v in r.items() if not k.startswith('_displayRegionName_hash')},
                         indent=2, default=str, ensure_ascii=True))

    print('\n=== DISMOUNT/VEHICLE FIELDS ANALYSIS ===')
    towns = []
    vehicle_restricted = []
    for r in results:
        if '_error' in r:
            continue
        if r.get('_isTown', 0):
            towns.append((r['_key'], r['_stringKey']))
        if r.get('_limitVehicleRun', 0):
            vehicle_restricted.append((r['_key'], r['_stringKey'], r['_limitVehicleRun']))

    print(f'Town regions (_isTown=1): {len(towns)}')
    for k, n in towns[:10]:
        print(f'  key={k}: {n}')
    print(f'Vehicle-restricted (_limitVehicleRun>0): {len(vehicle_restricted)}')
    for k, n, v in vehicle_restricted[:10]:
        print(f'  key={k}: {n} (value={v})')

    vtypes = {}
    for r in results:
        if '_error' in r:
            continue
        vt = r.get('_vehicleMercenaryAllowType', 0)
        vtypes[vt] = vtypes.get(vt, 0) + 1
    print(f'\n_vehicleMercenaryAllowType distribution: {vtypes}')


if __name__ == '__main__':
    main()
