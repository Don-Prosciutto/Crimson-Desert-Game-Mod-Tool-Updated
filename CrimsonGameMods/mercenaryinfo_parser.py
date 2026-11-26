"""mercenaryinfo.pabgb parser / serializer.

Crimson Desert's "mercenary" system is the umbrella for everything you can
summon with a cap: Pets, Vehicles (mounts), and traditional Mercenaries.
UI strings confirm three type names: UI_MercenaryTypeName_Mercenary / _Pet
/ _Vehicle. Each row in mercenaryinfo.pabgb is a category config with
active/owned/max caps + behavior flags.

dmm_parser: mercenary_info — 24 fields, 100% round-trip.

Binary layout (from IDA decompile of sub_143A533C0_0_72):
    u8  _key
    u32 _stringKey.size  + _stringKey.bytes[size]
    u8  _isBlocked
    u32 _defaultLimitSummonCount   (active deployed count)
    u32 _defaultLimitHireCount     (owned-inventory cap)
    u32 _maxLimitHireCount         (absolute cap, -1 = unlimited)
    u8  _farFromLeaderOption
    u8  _isControllable
    u8  _setNewMercenaryIsMain
    u8  _mainMercenaryPerTribe
    u8  _isForceStackable
    u8  _isSellable
    u8  _useCampLevel
    u8  _applyEquipItemStat
    u8  _spawnPositionType

Fixed 27 bytes per record when _stringKey is empty (which it is on every
vanilla entry). If a future patch introduces non-empty names, the blob
prefix grows the record by 4 + len bytes.

pabgh is `u16 count + N × (u8 key + u32 offset)` — 5 bytes per entry.
"""

from __future__ import annotations
import struct
import logging

DMM_TABLE_NAME = 'mercenary_info'


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
from typing import Optional

log = logging.getLogger(__name__)


def parse_pabgh(pabgh: bytes) -> list[tuple[int, int]]:
    from table_index import legacy_index
    return [(e.key, e.offset) for e in legacy_index(pabgh).entries]


def serialize_pabgh(entries: list[tuple[int, int]]) -> bytes:
    out = struct.pack('<H', len(entries))
    for k, o in entries:
        out += struct.pack('<BI', k, o)
    return out


class MercenaryRecord:
    __slots__ = (
        'key', 'string_key',
        'is_blocked',
        'default_summon_count', 'default_hire_count', 'max_hire_count',
        'far_from_leader_option', 'is_controllable',
        'set_new_mercenary_is_main', 'main_mercenary_per_tribe',
        'is_force_stackable', 'is_sellable', 'use_camp_level',
        'apply_equip_item_stat', 'spawn_position_type',
    )

    def __init__(self):
        self.key: int = 0
        self.string_key: bytes = b''
        self.is_blocked: int = 0
        self.default_summon_count: int = 0
        self.default_hire_count: int = 0
        self.max_hire_count: int = -1
        self.far_from_leader_option: int = 0
        self.is_controllable: int = 0
        self.set_new_mercenary_is_main: int = 0
        self.main_mercenary_per_tribe: int = 0
        self.is_force_stackable: int = 0
        self.is_sellable: int = 0
        self.use_camp_level: int = 0
        self.apply_equip_item_stat: int = 0
        self.spawn_position_type: int = 0

    @staticmethod
    def from_stream(data: bytes, pos: int) -> tuple['MercenaryRecord', int]:
        r = MercenaryRecord()
        r.key = data[pos]; pos += 1
        sk_len = struct.unpack_from('<I', data, pos)[0]; pos += 4
        r.string_key = data[pos:pos + sk_len]; pos += sk_len
        r.is_blocked = data[pos]; pos += 1
        r.default_summon_count = struct.unpack_from('<i', data, pos)[0]; pos += 4
        r.default_hire_count = struct.unpack_from('<i', data, pos)[0]; pos += 4
        r.max_hire_count = struct.unpack_from('<i', data, pos)[0]; pos += 4
        r.far_from_leader_option = data[pos]; pos += 1
        r.is_controllable = data[pos]; pos += 1
        r.set_new_mercenary_is_main = data[pos]; pos += 1
        r.main_mercenary_per_tribe = data[pos]; pos += 1
        r.is_force_stackable = data[pos]; pos += 1
        r.is_sellable = data[pos]; pos += 1
        r.use_camp_level = data[pos]; pos += 1
        r.apply_equip_item_stat = data[pos]; pos += 1
        r.spawn_position_type = data[pos]; pos += 1
        return r, pos

    def to_bytes(self) -> bytes:
        out = bytes([self.key])
        out += struct.pack('<I', len(self.string_key))
        out += self.string_key
        out += bytes([self.is_blocked])
        out += struct.pack('<i', self.default_summon_count)
        out += struct.pack('<i', self.default_hire_count)
        out += struct.pack('<i', self.max_hire_count)
        out += bytes([
            self.far_from_leader_option, self.is_controllable,
            self.set_new_mercenary_is_main, self.main_mercenary_per_tribe,
            self.is_force_stackable, self.is_sellable, self.use_camp_level,
            self.apply_equip_item_stat, self.spawn_position_type,
        ])
        return out


def parse_all(pabgh: bytes, pabgb: bytes) -> list[MercenaryRecord]:
    entries = parse_pabgh(pabgh)
    sorted_entries = sorted(entries, key=lambda e: e[1])
    records = []
    for i, (k, o) in enumerate(sorted_entries):
        end = sorted_entries[i + 1][1] if i + 1 < len(sorted_entries) else len(pabgb)
        rec, _ = MercenaryRecord.from_stream(pabgb, o)
        if rec.key != k:
            log.warning("mercenaryinfo: pabgh key %d != record key %d at offset %d",
                        k, rec.key, o)
        records.append(rec)
    return records


def serialize_all(records: list[MercenaryRecord]) -> tuple[bytes, bytes]:
    pabgb = bytearray()
    offsets: list[tuple[int, int]] = []
    for rec in records:
        offsets.append((rec.key, len(pabgb)))
        pabgb.extend(rec.to_bytes())
    pabgh = serialize_pabgh(offsets)
    return bytes(pabgh), bytes(pabgb)


def roundtrip_test(pabgh: bytes, pabgb: bytes) -> bool:
    records = parse_all(pabgh, pabgb)
    new_pabgh, new_pabgb = serialize_all(records)
    if new_pabgh != pabgh:
        log.error("pabgh mismatch: orig=%d new=%d", len(pabgh), len(new_pabgh))
        return False
    if new_pabgb != pabgb:
        for i in range(min(len(new_pabgb), len(pabgb))):
            if new_pabgb[i] != pabgb[i]:
                log.error("pabgb first diff at 0x%X: orig=0x%02X new=0x%02X",
                          i, pabgb[i], new_pabgb[i])
                break
        return False
    return True


# Category labels & descriptions. Three are confirmed from the game's own UI
# strings (UI_MercenaryTypeName_Mercenary / _Pet / _Vehicle). The rest are
# best-guess labels based on their vanilla cap fingerprint + the game's
# known subsystems; treat them as educated guesses, not hard confirmations.
#
# Each entry: (short_label, full_description)
CATEGORY_INFO: dict[int, tuple[str, str]] = {
    1:  ("Mercenary (Main)",
         "Confirmed via UI_MercenaryTypeName_Mercenary. Primary hireable\n"
         "mercenary pool. Vanilla: 50 active, 50 owned cap."),
    2:  ("Trade Mercenary / Stack A",
         "Stackable + sellable, 10 active, unlimited owned. Likely trader\n"
         "NPC inventory entries or a shopkeeper summon pool."),
    3:  ("Trade Mercenary / Stack B",
         "Stackable + sellable, 1 active, unlimited owned. Smaller sibling\n"
         "of slot 2 — possibly unique/named traders."),
    4:  ("Pet",
         "Confirmed via UI_MercenaryTypeName_Pet. Cats/dogs/small pets.\n"
         "Vanilla: 3 active deployed, 30 owned cap — the famous '30 pet'\n"
         "limit the 999-Pet-Cap community mod raises."),
    5:  ("Bulk Tradables (Knowledge?)",
         "Sellable, high-count (200 active / 200 owned). Likely knowledge\n"
         "cards, collectibles, or a tradable-item pool."),
    6:  ("Faction Squad A",
         "Non-controllable, non-sellable, 50/50. Likely a faction-spawned\n"
         "squad or event-summoned unit pool."),
    7:  ("Faction Squad B",
         "Same shape as slot 6 (50/50). Likely a parallel squad pool —\n"
         "probably a different faction or event type."),
    8:  ("Royal Supply / Stable",
         "Non-controllable, 50 active, 1000 owned. Very large ownership\n"
         "cap — likely Royal Supply entries, stable horses, or quest\n"
         "rewards pool."),
    9:  ("Faction Squad C",
         "Same shape as slots 6 and 7 (50/50). Third squad pool."),
    10: ("Vehicle / Mount",
         "Confirmed via UI_MercenaryTypeName_Vehicle. Rideable mounts.\n"
         "Vanilla: 1 active, 2 owned — explains why you can only summon\n"
         "one mount at a time."),
    11: ("Singleton (Unique)",
         "1 active / 1 owned. Single-instance slot — likely a main-hero\n"
         "NPC or unique quest summon."),
}


def category_label(key: int) -> str:
    info = CATEGORY_INFO.get(key)
    return info[0] if info else f"Slot #{key}"


def category_description(key: int) -> str:
    info = CATEGORY_INFO.get(key)
    return info[1] if info else "(no metadata — please report if you identify it)"
