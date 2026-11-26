"""equipslotinfo.pabgb parser / serializer.

Binary format (from IDA decompilation of sub_141048F10 + sub_141048B40):

Record (one per pabgh key):
  header:
    key         u32
    blob_size   u32       (then blob_size bytes of blob data)
    flag_u8     u8
    flag_u16    u16
    list_count  u32
  body:
    EquipInfoData[list_count]   (variable-length per entry)
  footer:
    remaining bytes copied verbatim (sub_1410830B0 + string)

EquipInfoData (sub_141048B40):
    etl_count       u32
    etl_hashes      u32[etl_count]    ← equip_type_info hashes (target for mods)
    category_a      u32
    category_b      u32
    name_hash       u32
    slot_index      u16
    field_u64       u64
    name_hash_2     u32
    fields_u32      u32[4]
    complex_u8      u8
    complex_u64     u64
    complex_blob    u32 size + bytes[size]
    tail            u8 + u8 + u32 + u8[5]   (11 bytes)
"""

from __future__ import annotations
import struct
import logging
from typing import Optional

log = logging.getLogger(__name__)


def parse_pabgh(pabgh: bytes) -> list[tuple[int, int]]:
    from table_index import legacy_index
    return [(e.key, e.offset) for e in legacy_index(pabgh).entries]


def serialize_pabgh(entries: list[tuple[int, int]], key_u32: bool = True) -> bytes:
    out = struct.pack('<H', len(entries))
    for k, o in entries:
        if key_u32:
            out += struct.pack('<II', k, o)
        else:
            out += struct.pack('<HI', k, o)
    return out


class EquipInfoData:
    __slots__ = (
        'etl_hashes', 'category_a', 'category_b', 'name_hash',
        'slot_index', 'field_u64', 'name_hash_2', 'fields_u32',
        'complex_u8', 'complex_u64', 'complex_blob',
        'tail_bytes',
    )

    def __init__(self):
        self.etl_hashes: list[int] = []
        self.category_a: int = 0
        self.category_b: int = 0
        self.name_hash: int = 0
        self.slot_index: int = 0
        self.field_u64: int = 0
        self.name_hash_2: int = 0
        self.fields_u32: list[int] = [0, 0, 0, 0]
        self.complex_u8: int = 0
        self.complex_u64: int = 0
        self.complex_blob: bytes = b''
        self.tail_bytes: bytes = b'\x00' * 11

    @staticmethod
    def from_stream(data: bytes, pos: int) -> tuple['EquipInfoData', int]:
        e = EquipInfoData()
        etl_count = struct.unpack_from('<I', data, pos)[0]; pos += 4
        e.etl_hashes = list(struct.unpack_from(f'<{etl_count}I', data, pos))
        pos += etl_count * 4
        e.category_a = struct.unpack_from('<I', data, pos)[0]; pos += 4
        e.category_b = struct.unpack_from('<I', data, pos)[0]; pos += 4
        e.name_hash = struct.unpack_from('<I', data, pos)[0]; pos += 4
        e.slot_index = struct.unpack_from('<H', data, pos)[0]; pos += 2
        e.field_u64 = struct.unpack_from('<Q', data, pos)[0]; pos += 8
        e.name_hash_2 = struct.unpack_from('<I', data, pos)[0]; pos += 4
        e.fields_u32 = list(struct.unpack_from('<4I', data, pos))
        pos += 16
        e.complex_u8 = data[pos]; pos += 1
        e.complex_u64 = struct.unpack_from('<Q', data, pos)[0]; pos += 8
        blob_size = struct.unpack_from('<I', data, pos)[0]; pos += 4
        e.complex_blob = data[pos:pos + blob_size]; pos += blob_size
        e.tail_bytes = data[pos:pos + 11]; pos += 11
        return e, pos

    def to_bytes(self) -> bytes:
        out = struct.pack('<I', len(self.etl_hashes))
        if self.etl_hashes:
            out += struct.pack(f'<{len(self.etl_hashes)}I', *self.etl_hashes)
        out += struct.pack('<I', self.category_a)
        out += struct.pack('<I', self.category_b)
        out += struct.pack('<I', self.name_hash)
        out += struct.pack('<H', self.slot_index)
        out += struct.pack('<Q', self.field_u64)
        out += struct.pack('<I', self.name_hash_2)
        out += struct.pack('<4I', *self.fields_u32)
        out += struct.pack('<B', self.complex_u8)
        out += struct.pack('<Q', self.complex_u64)
        out += struct.pack('<I', len(self.complex_blob))
        out += self.complex_blob
        out += self.tail_bytes
        return out


class EquipSlotRecord:
    __slots__ = (
        'key', 'header_blob', 'flag_u8', 'flag_u16',
        'entries', 'footer',
    )

    def __init__(self):
        self.key: int = 0
        self.header_blob: bytes = b''
        self.flag_u8: int = 0
        self.flag_u16: int = 0
        self.entries: list[EquipInfoData] = []
        self.footer: bytes = b''

    @staticmethod
    def from_bytes(data: bytes, start: int = 0, end: Optional[int] = None) -> 'EquipSlotRecord':
        if end is None:
            end = len(data)
        r = EquipSlotRecord()
        pos = start
        r.key = struct.unpack_from('<I', data, pos)[0]; pos += 4
        blob_size = struct.unpack_from('<I', data, pos)[0]; pos += 4
        r.header_blob = data[pos:pos + blob_size]; pos += blob_size
        r.flag_u8 = data[pos]; pos += 1
        r.flag_u16 = struct.unpack_from('<H', data, pos)[0]; pos += 2
        list_count = struct.unpack_from('<I', data, pos)[0]; pos += 4
        for _ in range(list_count):
            entry, pos = EquipInfoData.from_stream(data, pos)
            r.entries.append(entry)
        r.footer = data[pos:end]
        return r

    def to_bytes(self) -> bytes:
        out = struct.pack('<I', self.key)
        out += struct.pack('<I', len(self.header_blob))
        out += self.header_blob
        out += struct.pack('<B', self.flag_u8)
        out += struct.pack('<H', self.flag_u16)
        out += struct.pack('<I', len(self.entries))
        for e in self.entries:
            out += e.to_bytes()
        out += self.footer
        return out


def parse_all(pabgh: bytes, pabgb: bytes) -> list[EquipSlotRecord]:
    entries = parse_pabgh(pabgh)
    sorted_entries = sorted(entries, key=lambda e: e[1])
    records = []
    for i, (k, o) in enumerate(sorted_entries):
        end = sorted_entries[i + 1][1] if i + 1 < len(sorted_entries) else len(pabgb)
        rec = EquipSlotRecord.from_bytes(pabgb, o, end)
        records.append(rec)
    return records


def serialize_all(records: list[EquipSlotRecord]) -> tuple[bytes, bytes]:
    pabgb = bytearray()
    offsets: list[tuple[int, int]] = []
    for rec in records:
        offsets.append((rec.key, len(pabgb)))
        pabgb.extend(rec.to_bytes())
    pabgh = serialize_pabgh(offsets, key_u32=True)
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
        log.error("pabgb mismatch: orig=%d new=%d", len(pabgb), len(new_pabgb))
        return False
    return True
