import logging
import struct
import sys

log = logging.getLogger(__name__)

DMM_TABLE_NAME = 'gimmick_info'


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


def _u64(D, p):
    return struct.unpack_from('<Q', D, p)[0], p + 8

def _u32(D, p):
    return struct.unpack_from('<I', D, p)[0], p + 4

def _u16(D, p):
    return struct.unpack_from('<H', D, p)[0], p + 2

def _u8(D, p):
    return D[p], p + 1

def _f32(D, p):
    return struct.unpack_from('<f', D, p)[0], p + 4

def _vec3(D, p):
    x, y, z = struct.unpack_from('<fff', D, p)
    return (x, y, z), p + 12


def _skip_cstring(D, p):
    slen, p = _u32(D, p)
    if slen > 500000:
        return -1
    return p + slen

def _read_cstring(D, p):
    slen, p2 = _u32(D, p)
    if slen > 500000:
        return None, -1
    try:
        s = D[p2:p2+slen].decode('utf-8', errors='replace')
    except:
        s = ''
    return s, p2 + slen

def _skip_locstr(D, p):
    p += 1 + 8
    return _skip_cstring(D, p)

def _skip_cstring_hash(D, p):
    slen, p = _u32(D, p)
    if slen > 500000:
        return -1
    return p + slen

def _skip_u32_key_array(D, p):
    count, p = _u32(D, p)
    if count > 500000:
        return -1
    return p + count * 4

def _skip_u16_key_array(D, p):
    count, p = _u32(D, p)
    if count > 500000:
        return -1
    return p + count * 2


def _skip_sub_141063510(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        p = _skip_cstring_hash(D, p)
        if p < 0: return -1
        p = _skip_cstring_hash(D, p)
        if p < 0: return -1
    return p

def _skip_sub_1410615F0(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        p = _skip_cstring_hash(D, p)
        if p < 0: return -1
    return p

def _skip_polymorphic_C89080(D, p):
    type_byte = D[p]; p += 1
    if type_byte in (1, 4, 6, 7):
        return p
    elif type_byte == 0:
        return p + 69
    elif type_byte == 2:
        return p + 8
    elif type_byte == 5:
        return _skip_cstring(D, p)
    elif type_byte == 3:
        p += 13
        p += 11
        count, p = _u32(D, p)
        if count > 100000: return -1
        p += count * 4
        return -1
    elif type_byte == 8:
        return -1
    return -1

def _skip_D77130_case4(D, p):
    st = D[p]; p += 1
    _case4_fixed = {
        0: 1, 1: 8, 2: 4, 3: 8, 4: 4, 5: 8, 6: 12, 7: 4,
        8: 1, 9: 2, 10: 1, 11: 1, 13: 5
    }
    if st in _case4_fixed:
        return p + _case4_fixed[st]
    elif st == 12:
        p += 4
        return _skip_cstring(D, p)
    return -1

def _skip_D77130_case3(D, p):
    st = struct.unpack_from('<H', D, p)[0]; p += 2
    _v16_fixed = {222: 4, 99: 4, 245: 0, 203: 0, 175: 9, 254: 4, 31: 17, 317: 10, 125: 4}
    _v16_cstring = {114, 209}
    if st in _v16_fixed:
        p += _v16_fixed[st]
    elif st in _v16_cstring:
        p = _skip_cstring(D, p)
        if p < 0: return -1
    else:
        pass
    flag = D[p]; p += 1
    if flag:
        p = _skip_cstring(D, p)
        if p < 0: return -1
        p += 11
    return p

def _skip_D77130(D, p, depth=0):
    if depth > 30: return -1
    t = D[p]; p += 1
    if t == 0 or t == 1:
        p = _skip_D77130(D, p, depth + 1)
        if p < 0: return -1
        return _skip_D77130(D, p, depth + 1)
    elif t == 2:
        return _skip_D77130(D, p, depth + 1)
    elif t == 3:
        return _skip_D77130_case3(D, p)
    elif t == 4:
        return _skip_D77130_case4(D, p)
    elif t == 5:
        p += 1
        p = _skip_cstring(D, p)
        if p < 0: return -1
        p += 1 + 8 + 1 + 1
        return p
    elif t == 6:
        return p + 4
    elif t == 7:
        flag = D[p]; p += 1
        if flag:
            p = _skip_cstring(D, p)
            if p < 0: return -1
            p += 1 + 8
            flag2 = D[p]; p += 1
            if not flag2:
                return p
            return -1
        else:
            return -1
    elif t == 8:
        return p + 6
    return -1

def _skip_optional_virtual_object(D, p):
    flag = D[p]; p += 1
    if not flag:
        return p
    return _skip_D77130(D, p)

def _skip_cstring_array(D, p):
    count, p = _u32(D, p)
    if count > 100000: return -1
    for _ in range(count):
        p = _skip_cstring(D, p)
        if p < 0: return -1
    return p

def _skip_sub_1410104C0(D, p):
    return p + 40

def _skip_sub_141C90490_element(D, p):
    p += 1
    p = _skip_sub_1410104C0(D, p)
    if p < 0: return -1
    p = _skip_cstring_hash(D, p)
    if p < 0: return -1
    p = _skip_cstring(D, p)
    if p < 0: return -1
    p += 1
    p += 12
    p += 12
    p += 1
    p += 1
    return p

def _skip_sub_141C90490(D, p):
    count, p = _u32(D, p)
    if count > 100000: return -1
    for _ in range(count):
        p = _skip_sub_141C90490_element(D, p)
        if p < 0: return -1
    return p

def _skip_sub_141C90C40(D, p):
    flag = D[p]; p += 1
    if not flag:
        return p
    p = _skip_cstring_array(D, p)
    if p < 0: return -1
    p += 1
    flag2 = D[p]; p += 1
    if flag2:
        p = _skip_polymorphic_C89080(D, p)
        if p < 0: return -1
    p += 8
    return p

def _skip_sub_141C88550(D, p):
    p = _skip_cstring_hash(D, p)
    if p < 0: return -1
    p = _skip_cstring_array(D, p)
    if p < 0: return -1
    p = _skip_sub_141C90490(D, p)
    if p < 0: return -1
    count, p = _u32(D, p)
    if count > 100000: return -1
    for _ in range(count):
        p = _skip_sub_141C90C40(D, p)
        if p < 0: return -1
    p += 4
    return p

def _skip_sub_141D40F90(D, p):
    count, p = _u32(D, p)
    if count > 100000: return -1
    for _ in range(count):
        p = _skip_optional_virtual_object(D, p)
        if p < 0: return -1
        p = _skip_optional_virtual_object(D, p)
        if p < 0: return -1
        p += 1
        p += 4
        p += 4
        p += 1
        p += 1
    return p

def _skip_sub_1410717B0(D, p):
    count, p = _u32(D, p)
    if count > 100000: return -1
    for _ in range(count):
        p += 8
        p = _skip_cstring(D, p)
        if p < 0: return -1
    return p

def _skip_reward_dropset(D, p):
    count, p = _u32(D, p)
    if count > 100000: return -1
    return p + count * 28

def _skip_sub_141043810(D, p):
    p += 4
    p = _skip_locstr(D, p)
    if p < 0: return -1
    p += 4
    count, p = _u32(D, p)
    if count > 100000: return -1
    for _ in range(count):
        p = _skip_cstring_hash(D, p)
        if p < 0: return -1
        p += 4
    p = _skip_sub_1410717B0(D, p)
    if p < 0: return -1
    p = _skip_sub_141D40F90(D, p)
    if p < 0: return -1
    p = _skip_reward_dropset(D, p)
    if p < 0: return -1
    p += 4
    p += 4
    p += 4
    p += 5
    return p

def _skip_sub_141070A30(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        flag = D[p]
        p += 1
        if flag:
            p = _skip_sub_141C88550(D, p)
            if p < 0: return -1
    return p

def _skip_sub_141B8C800(D, p):
    p = _skip_cstring_hash(D, p)
    if p < 0: return -1
    type_byte = D[p]
    p += 1
    if type_byte in (0, 2, 3, 7):
        p += 4
    elif type_byte in (1, 5, 9):
        p += 2
    elif type_byte in (4, 6, 8):
        p += 4
    p += 1
    return p

def _skip_sub_1419D0610(D, p):
    flag = D[p]; p += 1
    if not flag:
        return p
    count, p = _u32(D, p)
    if count > 100000: return -1
    return p + count * 45

def _skip_sub_141070800(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        p += 4
        inner_count, p = _u32(D, p)
        if inner_count > 100000:
            return -1
        p += inner_count * 16
        p += 1
    return p

def _skip_sub_141063600(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 8

def _skip_sub_141046100(D, p):
    return p + 6

def _skip_sub_1410636F0(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        p += 1 + 1 + 4 + 1
        p = _skip_cstring_hash(D, p)
        if p < 0: return -1
        p += 1 + 16
    return p

def _skip_sub_141063820(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 22


def _skip_sub_141070620(D, p):
    flag = D[p]
    p += 1
    if not flag:
        return p
    p += 40
    p += 1 + 1 + 4 + 1 + 1 + 1
    return p

def _skip_sub_1410453C0(D, p):
    p += 1
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 8

def _skip_sub_141076950(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    if count == 0:
        return p
    return -1

def _skip_sub_141063920(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 8

def _skip_sub_14152EDF0(D, p):
    p += 8
    type_byte = D[p]; p += 1
    p += 4 + 4 + 4 + 8 + 4 + 8 + 8 + 8 + 2
    if type_byte == 0x0B:
        pass
    elif type_byte == 0x0A:
        p += 8
    elif type_byte == 0x0D:
        p += 5
    elif type_byte in (7, 8):
        p += 32
    else:
        p += 4
    return p

def _skip_sub_1410704A0(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        flag = D[p]
        p += 1
        if flag:
            p = _skip_sub_14152EDF0(D, p)
            if p < 0: return -1
        p += 4
    return p

def _skip_sub_141C0DD20(D, p):
    flag = D[p]
    p += 1
    if not flag:
        return p
    return _skip_sub_14152EDF0(D, p)

def _skip_sub_141070300(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    if count == 0:
        return p
    return -1

def _skip_sub_141045580(D, p):
    for _ in range(2):
        p = _skip_sub_1410615F0(D, p)
        if p < 0: return -1
    for _ in range(2):
        p = _skip_cstring(D, p)
        if p < 0: return -1
    p += 1 + 12 + 4 + 4 + 1 + 1
    return p

def _skip_sub_14132ECF0(D, p):
    count, p = _u32(D, p)
    if count > 100000: return -1
    for _ in range(count):
        p = _skip_sub_141045580(D, p)
        if p < 0: return -1
    return p

def _skip_sub_141070120(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        p += 4 + 1 + 1 + 1
        p = _skip_sub_14132ECF0(D, p)
        if p < 0: return -1
        p += 1
    return p

def _skip_sub_14106FF80(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    if count == 0:
        return p
    return -1

def _skip_sub_141B86C10(D, p):
    p = _skip_cstring(D, p)
    if p < 0: return -1
    p = _skip_cstring(D, p)
    if p < 0: return -1
    p += 12
    return p

def _skip_sub_141063A30(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    if count == 0:
        return p
    return -1

def _skip_sub_141063B60(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    if count == 0:
        return p
    return -1

def _skip_sub_141063CB0(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    if count == 0:
        return p
    return -1

def _skip_sub_14106FD90(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    if count == 0:
        return p
    return -1

def _skip_sub_14106FC00(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 260

def _skip_sub_14106FA80(D, p):
    flag = D[p]
    p += 1
    if not flag:
        return p
    count, p = _u32(D, p)
    if count > 100000: return -1
    p += count * 20
    p = _skip_locstr(D, p)
    if p < 0: return -1
    p += 4
    return p

def _skip_sub_14106F8F0(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        inner_count, p = _u32(D, p)
        if inner_count > 100000:
            return -1
        for _j in range(inner_count):
            p += 4
            p = _skip_locstr(D, p)
            if p < 0: return -1
        p += 1
    return p

def _skip_sub_14106F700(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        p = _skip_cstring(D, p)
        if p < 0: return -1
        p = _skip_cstring_hash(D, p)
        if p < 0: return -1
        p += 4 + 4
    return p

def _skip_sub_14106F540(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 48

def _skip_sub_14106F330(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        p += 4
        flag = D[p]
        p += 1
        if flag:
            return -1
    return p

def _skip_sub_141045F50(D, p):
    p = _skip_locstr(D, p)
    if p < 0: return -1
    p = _skip_locstr(D, p)
    if p < 0: return -1
    p = _skip_cstring_hash(D, p)
    if p < 0: return -1
    p += 4
    for _ in range(2):
        p += 4
        inner_count, p = _u32(D, p)
        if inner_count > 100000:
            return -1
        if inner_count > 0:
            return -1
    return p

def _skip_sub_1410605E0(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        p += 4
        p = _skip_cstring_hash(D, p)
        if p < 0: return -1
        p += 12 + 12
    return p

def _skip_sub_141063E00(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 74

def _skip_sub_141060ED0(D, p):
    return p + 2

def _skip_sub_141060CF0(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 2

def _skip_sub_1410609B0(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 8

def _skip_sub_1410377F0(D, p):
    return p + 14

def _skip_sub_141070D80(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    for _ in range(count):
        flag = D[p]
        p += 1
        if flag:
            p += 4
            p = _skip_cstring_hash(D, p)
            if p < 0: return -1
            p += 40
    return p

def _skip_sub_141045D70(D, p):
    p += 4 + 8
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 12

def _skip_sub_143A9D7C0_0_2(D, p):
    count, p = _u32(D, p)
    if count > 100000:
        return -1
    return p + count * 8


def parse_gimmick_entry(D, eoff, end):
    p = eoff
    entry = {}
    entry['_offset'] = eoff

    def _fail(field_name):
        entry['parse_fail_field'] = field_name
        entry['parse_complete'] = False
        return entry

    try:

        entry['key'], p = _u32(D, p)

        slen, _ = _u32(D, p)
        if slen > 5000:
            return None
        entry['name'] = D[p+4:p+4+slen].decode('utf-8', errors='replace')
        p = _skip_cstring(D, p)
        if p < 0: return None

        entry['is_blocked'], p = _u8(D, p)

        entry['prefab_path'], p = _read_cstring(D, p)
        if p < 0: return _fail('_prefabPath')

        p += 4

        p += 2

        count, p = _u32(D, p)
        if count > 100000:
            return _fail('_gimmickInteractionOverrideDataList_count')
        for _ in range(count):
            flag = D[p]; p += 1
            if flag:
                p = _skip_sub_141043810(D, p)
                if p < 0:
                    return _fail('_gimmickInteractionOverrideDataList_element')

        p += 1

        p += 1

        p = _skip_u32_key_array(D, p)
        if p < 0: return _fail('_propertyList')

        entry['gimmick_name_hash'], p = _u32(D, p)

        p = _skip_locstr(D, p)
        if p < 0: return _fail('_gimmickName')

        p = _skip_cstring(D, p)
        if p < 0: return _fail('_emojiTextureID')

        p = _skip_cstring(D, p)
        if p < 0: return _fail('_devMemo')

        p = _skip_sub_141063510(D, p)
        if p < 0:
            return _fail('_gimmickChartParameterList')

        p = _skip_sub_1410615F0(D, p)
        if p < 0:
            return _fail('_triggerVolumeGroupDataList')

        p = _skip_sub_141070A30(D, p)
        if p < 0:
            return _fail('_gimmickTagList')

        count, p = _u32(D, p)
        if count > 100000:
            return _fail('_triggerCheckTargetDataList_count')
        for _ in range(count):
            p = _skip_sub_141B8C800(D, p)
            if p < 0:
                return _fail('_triggerCheckTargetDataList_element')

        count, p = _u32(D, p)
        if count > 100000:
            return _fail('_elementalReceiverColliderGroupDataList_count')
        for _ in range(count):
            p = _skip_sub_1419D0610(D, p)
            if p < 0:
                return _fail('_elementalReceiverColliderGroupDataList')


        p = _skip_sub_141070800(D, p)
        if p < 0:
            return _fail('_gimmickOnTimeGroupDataList')

        p += 1

        p = _skip_u32_key_array(D, p)
        if p < 0: return _fail('_transmutationMaterialItemList')

        p = _skip_u32_key_array(D, p)
        if p < 0: return _fail('_transmutationMaterialGimmickList')

        p = _skip_sub_141063600(D, p)
        if p < 0:
            return _fail('_transmutationMaterialItemGroupList')

        p += 8

        p += 9

        p = _skip_sub_141046100(D, p)

        p = _skip_sub_1410636F0(D, p)
        if p < 0:
            return _fail('_controlMaterialParamValueList')

        p = _skip_sub_141063820(D, p)
        if p < 0:
            return _fail('_growthDataList')

        p += 1

        p += 4

        p += 4

        p += 4

        p += 1

        p += 1

        p += 4

        p = _skip_sub_1410453C0(D, p)
        if p < 0:
            return _fail('_attackImpulseCompleteData')

        p += 8

        p += 8

        p = _skip_sub_141070620(D, p)
        if p < 0:
            return _fail('_collisionBodyData')

        p += 12

        p += 4

        p += 4

        p += 4

        p += 1


        p += 5 * 4 + 12

        p += 4 * 4 + 1

        p += 1

        p += 5 * 4

        p += 1

        p += 1

        p += 1

        p += 4

        p += 12

        p += 4

        p = _skip_cstring_hash(D, p)
        if p < 0: return _fail('_jamReactionType')

        p = _skip_sub_141063920(D, p)
        if p < 0: return _fail('_jammedLogoutEffectName')

        p = _skip_sub_1410704A0(D, p)
        if p < 0:
            return _fail('_collectFilter_Dev')

        p = _skip_sub_141C0DD20(D, p)
        if p < 0:
            return _fail('_housingSupportPlaneScale')

        p = _skip_sub_141070300(D, p)
        if p < 0:
            return _fail('_physicsQualityPreset')

        p = _skip_sub_141070120(D, p)
        if p < 0:
            return _fail('_knowledgeExtractType')

        p = _skip_u32_key_array(D, p)
        if p < 0: return _fail('_equipDockingSpawnDistanceLevel')

        p = _skip_sub_14106FF80(D, p)
        if p < 0:
            return _fail('_spawnDistanceLevel')

        p += 4

        p += 4

        p += 1

        p += 1

        p = _skip_sub_141B86C10(D, p)
        if p < 0:
            return _fail('_miniGameDataList')

        p = _skip_sub_141063A30(D, p)
        if p < 0:
            return _fail('_trafficBoxDataList')

        p = _skip_sub_141063B60(D, p)
        if p < 0:
            return _fail('_factionStructure')

        p = _skip_sub_141063CB0(D, p)
        if p < 0:
            return _fail('_housingItemPlacementTypeFlag')

        p = _skip_sub_14106FD90(D, p)
        if p < 0:
            return _fail('_housingGimmickSpecialType')

        p += 4

        p = _skip_sub_141076950(D, p)
        if p < 0:
            return _fail('_buoyancySubmersionRatio')

        p += 4

        p += 4

        p += 4

        p += 4

        p = _skip_sub_14106FC00(D, p)
        if p < 0:
            return _fail('_breakTypeFromParent')

        p += 1

        p = _skip_sub_1410615F0(D, p)
        if p < 0: return _fail('_weakPointEffectDataList')

        p = _skip_sub_1410615F0(D, p)
        if p < 0: return _fail('_isCollectOnlyGimmick')

        p += 1

        p += 1

        p += 2

        p += 11

        p += 4

        p = _skip_sub_14106FA80(D, p)
        if p < 0:
            return _fail('_attackImpulseCompleteData_2')

        p += 1

        p = _skip_sub_14106F8F0(D, p)
        if p < 0:
            return _fail('_batteryTotalCapacity_2')

        p += 4 + 4 + 4 + 1

        p = _skip_cstring(D, p)
        if p < 0: return _fail('_propertyConditionStringListForDebug')

        p = _skip_sub_1410605E0(D, p)
        if p < 0:
            return _fail('_growthDataList_2')

        p = _skip_sub_141063E00(D, p)
        if p < 0:
            return _fail('_convertItemInfo_2')

        p = _skip_sub_141063E00(D, p)
        if p < 0:
            return _fail('_convertItemInfo_3')

        p = _skip_sub_14106F700(D, p)
        if p < 0:
            return _fail('_isInstallable_2')

        p = _skip_sub_14106F540(D, p)
        if p < 0:
            return _fail('_allyGroupInfo_2')

        p = _skip_sub_14106F330(D, p)
        if p < 0:
            return _fail('_uiMapTextureInfo_2')

        p += 4

        p = _skip_sub_141045F50(D, p)
        if p < 0:
            return _fail('_isTargetable_2')

        p += 4

        p += 1

        entry['knowledge_info'], p = _u32(D, p)

        p += 1

        p += 2

        p += 4

        p += 4

        p += 4

        p += 1

        p += 1

        p += 1

        p += 4

        p = _skip_sub_1410377F0(D, p)

        p += 2

        p = _skip_sub_141060CF0(D, p)
        if p < 0: return _fail('_propagateSkillFromParentActor')

        p += 1

        p += 1

        p = _skip_cstring(D, p)
        if p < 0: return _fail('_cstring_1288')

        p += 7

        p += 8

        p = _skip_sub_1410609B0(D, p)
        if p < 0: return _fail('_isBlockSpawnOnAwayFromOriginTransform')

        p = _skip_sub_143A9D7C0_0_2(D, p)
        if p < 0:
            return _fail('_snowRatio')

        for i in range(2):
            p = _skip_sub_141070D80(D, p)
            if p < 0:
                return _fail(f'_applyGimmickStateToItem_{i}')

        p = _skip_sub_141045D70(D, p)
        if p < 0:
            return _fail('_massLevel')

        p += 4

        p += 4

        p += 4

        p += 1

        entry['respawn_time_seconds'], p = _u32(D, p)

        p += 4

        entry['parse_complete'] = True
        entry['_end_offset'] = p
        return entry

    except (struct.error, IndexError):
        return None


def parse_pabgh_index(G):
    from table_index import legacy_index
    return sorted(((e.key, e.offset) for e in legacy_index(G).entries), key=lambda x: x[1])


def parse_all_gimmicks(D, G):
    idx = parse_pabgh_index(G)

    entries = []
    partial = []
    total_failures = 0

    for i, (key, eoff) in enumerate(idx):
        end = idx[i + 1][1] if i + 1 < len(idx) else len(D)
        entry = parse_gimmick_entry(D, eoff, end)
        if entry is None:
            total_failures += 1
        elif entry.get('parse_complete'):
            entries.append(entry)
        else:
            partial.append(entry)

    return entries, partial, total_failures


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')

    try:
        import crimson_rs
        game_path = 'C:/Program Files (x86)/Steam/steamapps/common/Crimson Desert'
        dp = 'gamedata/binary__/client/bin'
        body = crimson_rs.extract_file(game_path, '0008', dp, 'gimmickinfo.pabgb')
        gh = crimson_rs.extract_file(game_path, '0008', dp, 'gimmickinfo.pabgh')
        print("Loaded via crimson_rs")
    except Exception:
        ext = 'C:/Users/Coding/CrimsonDesertModding/extractedpaz/0008_full'
        with open(f'{ext}/gimmickinfo.pabgb', 'rb') as f:
            body = f.read()
        with open(f'{ext}/gimmickinfo.pabgh', 'rb') as f:
            gh = f.read()
        print(f"Loaded from disk: {len(body)} bytes pabgb, {len(gh)} bytes pabgh")

    idx = parse_pabgh_index(gh)
    print(f"Index entries: {len(idx)}")

    entries, partial, failures = parse_all_gimmicks(body, gh)
    total = len(entries) + len(partial) + failures
    print(f"\n=== Parse Results ===")
    print(f"Total entries:    {total}")
    print(f"Fully parsed:     {len(entries)} ({100*len(entries)/max(total,1):.1f}%)")
    print(f"Partially parsed: {len(partial)} ({100*len(partial)/max(total,1):.1f}%)")
    print(f"Total failures:   {failures} ({100*failures/max(total,1):.1f}%)")

    if partial:
        from collections import Counter
        fail_fields = Counter(e.get('parse_fail_field', 'unknown') for e in partial)
        print(f"\n=== Partial Parse Failure Distribution ===")
        for field, count in fail_fields.most_common(20):
            print(f"  {field}: {count}")

    all_parsed = entries + partial
    if all_parsed:
        print(f"\n=== Sample Entries (first 10 of {len(all_parsed)} parsed) ===")
        for e in all_parsed[:10]:
            name = e.get('name', '?')
            key = e.get('key', 0)
            blocked = e.get('is_blocked', 0)
            complete = e.get('parse_complete', False)
            fail = e.get('parse_fail_field', '-')
            print(f"  key={key:10d}  blocked={blocked}  complete={'Y' if complete else 'N'}  fail={fail:40s}  name={name[:50]}")

    if all_parsed:
        print(f"\n=== Key Statistics (all {len(all_parsed)} parsed entries) ===")
        blocked_count = sum(1 for e in all_parsed if e.get('is_blocked'))
        has_prefab = sum(1 for e in all_parsed if e.get('prefab_path'))
        print(f"  Blocked entries: {blocked_count}")
        print(f"  With prefab path: {has_prefab}")

        from collections import Counter
        prefixes = Counter()
        for e in all_parsed:
            name = e.get('name', '')
            prefix = name.split('_')[0] if '_' in name else name
            prefixes[prefix] += 1
        print(f"\n=== Name Prefix Distribution (top 15) ===")
        for prefix, cnt in prefixes.most_common(15):
            print(f"  {prefix:30s}: {cnt:5d} entries")
