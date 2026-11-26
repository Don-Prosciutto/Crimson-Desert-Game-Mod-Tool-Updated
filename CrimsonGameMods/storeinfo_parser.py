
import json
import logging
import os
import struct
from data_db import get_connection

DMM_TABLE_NAME = 'store_info'


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
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

ITEM_ENTRY_SIZE = 113
HEADER_OVERHEAD = 55
TAIL_SIZE = 19
TOTAL_OVERHEAD = HEADER_OVERHEAD + TAIL_SIZE


@dataclass
class StoreItemEntry:
    offset: int
    store_key_ref: int
    buy_price: int
    sell_price: int
    trade_flags: int
    item_key: int
    item_key_dup: int
    extra_field: int
    raw: bytes


@dataclass
class StoreRecord:
    index: int
    key: int
    name: str
    offset: int
    size: int
    name_offset: int
    after_name: int
    format_tag: int
    is_standard: bool
    item_count: int
    items: List[StoreItemEntry] = field(default_factory=list)
    header_raw: bytes = b''
    tail_raw: bytes = b''


class StoreinfoParser:

    def __init__(self):
        self.stores: List[StoreRecord] = []
        self._header_data: bytes = b''
        self._body_data: bytearray = bytearray()
        self._header_entries: List[Tuple[int, int]] = []
        self._name_lookup: Dict[int, str] = {}
        self._loaded = False

    def load_from_files(self, pabgh_path: str, pabgb_path: str) -> bool:
        try:
            with open(pabgh_path, 'rb') as f:
                self._header_data = f.read()
            with open(pabgb_path, 'rb') as f:
                self._body_data = bytearray(f.read())
            self._parse_header()
            self._parse_all_stores()
            self._loaded = True
            return True
        except Exception as e:
            log.error("Failed to load storeinfo: %s", e)
            return False

    def load_from_bytes(self, header_bytes: bytes, body_bytes: bytes) -> bool:
        self._header_data = header_bytes
        self._body_data = bytearray(body_bytes)
        self._parse_header()
        self._parse_all_stores()
        self._loaded = True
        return True

    def load_names(self, names_path: str = '') -> None:
        _db = get_connection()
        for row in _db.execute("SELECT item_key, name FROM items"):
            self._name_lookup[row['item_key']] = row['name']

    def get_item_name(self, key: int) -> str:
        return self._name_lookup.get(key, f"Unknown({key})")

    def _parse_header(self) -> None:
        from table_index import legacy_index
        self._header_entries = [(e.key, e.offset)
                                for e in legacy_index(self._header_data).entries]

    def _parse_all_stores(self) -> None:
        self.stores.clear()
        data = self._body_data
        n = len(self._header_entries)

        for idx, (skey, soff) in enumerate(self._header_entries):
            if idx + 1 < n:
                rec_size = self._header_entries[idx + 1][1] - soff
            else:
                rec_size = len(data) - soff

            name_len = struct.unpack_from('<I', data, soff + 2)[0]
            name = data[soff + 6:soff + 6 + name_len].decode('ascii', errors='replace')
            after_name = soff + 6 + name_len
            remaining = rec_size - 6 - name_len

            fmt_tag = 0
            if after_name + 0x1C <= len(data):
                fmt_tag = struct.unpack_from('<H', data, after_name + 0x1A)[0]

            item_count = 0
            is_standard = False
            if after_name + 0x38 <= len(data):
                for _cnt_off in (0x2F, 0x26, 0x30, 0x2E):
                    if after_name + _cnt_off + 4 > len(data):
                        continue
                    cnt = struct.unpack_from('<I', data, after_name + _cnt_off)[0]
                    if cnt == 0 or cnt >= 10000:
                        continue
                    for _ho_pad in (8, 9, 7, 6, 10, 5, 4, 11):
                        ho_start = _cnt_off + _ho_pad
                        items_bytes = remaining - ho_start
                        if items_bytes <= 0:
                            continue
                        tail = items_bytes - cnt * ITEM_ENTRY_SIZE
                        if 0 <= tail < 25 and items_bytes >= cnt * ITEM_ENTRY_SIZE:
                            is_standard = True
                            item_count = cnt
                            HEADER_OVERHEAD_actual = ho_start
                            TAIL_SIZE_actual = tail
                            break
                    if is_standard:
                        break

            store = StoreRecord(
                index=idx,
                key=skey,
                name=name,
                offset=soff,
                size=rec_size,
                name_offset=soff + 2,
                after_name=after_name,
                format_tag=fmt_tag,
                is_standard=is_standard,
                item_count=item_count,
            )

            if is_standard:
                store.header_raw = bytes(data[after_name:after_name + HEADER_OVERHEAD_actual])
                items_end = after_name + HEADER_OVERHEAD_actual + item_count * ITEM_ENTRY_SIZE
                store.tail_raw = bytes(data[items_end:items_end + TAIL_SIZE_actual])

                for i in range(item_count):
                    entry_off = after_name + HEADER_OVERHEAD_actual + i * ITEM_ENTRY_SIZE
                    raw = bytes(data[entry_off:entry_off + ITEM_ENTRY_SIZE])
                    if len(raw) < ITEM_ENTRY_SIZE:
                        break

                    store_key_ref = struct.unpack_from('<H', raw, 0)[0]
                    buy_price = struct.unpack_from('<Q', raw, 0x06)[0]
                    sell_price = struct.unpack_from('<Q', raw, 0x0E)[0]
                    trade_flags = struct.unpack_from('<I', raw, 0x16)[0]
                    item_key = struct.unpack_from('<I', raw, 0x1E)[0]
                    item_key_dup = struct.unpack_from('<I', raw, 0x5D)[0]
                    extra_field = struct.unpack_from('<I', raw, 0x3A)[0]

                    store.items.append(StoreItemEntry(
                        offset=entry_off,
                        store_key_ref=store_key_ref,
                        buy_price=buy_price,
                        sell_price=sell_price,
                        trade_flags=trade_flags,
                        item_key=item_key,
                        item_key_dup=item_key_dup,
                        extra_field=extra_field,
                        raw=raw,
                    ))
            else:
                rec = data[after_name:soff + rec_size]
                for j in range(len(rec) - 5):
                    if rec[j] == 0x01 and rec[j + 1] == 0x01:
                        ik = struct.unpack_from('<I', rec, j + 2)[0]
                        if 100 < ik < 10000000:
                            store.items.append(StoreItemEntry(
                                offset=after_name + j - 0x20,
                                store_key_ref=skey,
                                buy_price=0,
                                sell_price=0,
                                trade_flags=0,
                                item_key=ik,
                                item_key_dup=ik,
                                extra_field=0,
                                raw=b'',
                            ))
                store.item_count = len(store.items)

            self.stores.append(store)

    def get_store_by_key(self, key: int) -> Optional[StoreRecord]:
        return next((s for s in self.stores if s.key == key), None)

    def get_store_by_name(self, name: str) -> Optional[StoreRecord]:
        name_lower = name.lower()
        return next((s for s in self.stores if name_lower in s.name.lower()), None)

    def swap_item(self, store_key: int, old_item_key: int, new_item_key: int) -> bool:
        store = self.get_store_by_key(store_key)
        if not store or not store.is_standard:
            log.warning("Store %d not found or not standard format", store_key)
            return False

        for item in store.items:
            if item.item_key == old_item_key:
                entry_off = item.offset
                struct.pack_into('<I', self._body_data, entry_off + 0x22, new_item_key)
                struct.pack_into('<I', self._body_data, entry_off + 0x5D, new_item_key)
                item.item_key = new_item_key
                item.item_key_dup = new_item_key
                log.info("Swapped %d -> %d in store %d", old_item_key, new_item_key, store_key)
                return True
        return False

    def add_item(self, store_key: int, donor_item_key: int, new_item_key: int,
                 buy_price: int = -1, sell_price: int = -1) -> bool:
        store = self.get_store_by_key(store_key)
        if not store or not store.is_standard:
            log.warning("Store %d not found or not standard format", store_key)
            return False

        donor = None
        for item in store.items:
            if item.item_key == donor_item_key:
                donor = item
                break
        if not donor or len(donor.raw) < ITEM_ENTRY_SIZE:
            log.warning("Donor %d not found in store %d", donor_item_key, store_key)
            return False

        new_entry = bytearray(donor.raw)
        struct.pack_into('<I', new_entry, 0x22, new_item_key)
        struct.pack_into('<I', new_entry, 0x5D, new_item_key)
        if buy_price >= 0:
            struct.pack_into('<Q', new_entry, 0x06, buy_price)
        if sell_price >= 0:
            struct.pack_into('<Q', new_entry, 0x0E, sell_price)

        items_end = store.after_name + HEADER_OVERHEAD + store.item_count * ITEM_ENTRY_SIZE
        self._body_data[items_end:items_end] = new_entry

        new_count = store.item_count + 1
        struct.pack_into('<I', self._body_data, store.after_name + 0x26, new_count)
        struct.pack_into('<I', self._body_data, store.after_name + 0x2F, new_count)

        self._rebuild_header_offsets(store.index, ITEM_ENTRY_SIZE)

        self._parse_all_stores()

        log.info("Added item %d (from donor %d) to store %d. New count: %d",
                 new_item_key, donor_item_key, store_key, new_count)
        return True

    def remove_item(self, store_key: int, item_key: int) -> bool:
        store = self.get_store_by_key(store_key)
        if not store or not store.is_standard:
            return False

        for i, item in enumerate(store.items):
            if item.item_key == item_key:
                entry_off = item.offset
                self._body_data[entry_off:entry_off + ITEM_ENTRY_SIZE] = b''

                new_count = store.item_count - 1
                struct.pack_into('<I', self._body_data, store.after_name + 0x26, new_count)
                struct.pack_into('<I', self._body_data, store.after_name + 0x2F, new_count)

                self._rebuild_header_offsets(store.index, -ITEM_ENTRY_SIZE)
                self._parse_all_stores()
                return True
        return False

    def _rebuild_header_offsets(self, changed_index: int, size_delta: int) -> None:
        new_entries = list(self._header_entries)
        for i in range(changed_index + 1, len(new_entries)):
            key, off = new_entries[i]
            new_entries[i] = (key, off + size_delta)
        self._header_entries = new_entries

        count = len(new_entries)
        new_hdr = bytearray(struct.pack('<H', count))
        for skey, soff in new_entries:
            new_hdr += struct.pack('<HI', skey, soff)
        self._header_data = bytes(new_hdr)

    def get_header_bytes(self) -> bytes:
        return self._header_data

    def get_body_bytes(self) -> bytes:
        return bytes(self._body_data)

    def get_summary(self) -> str:
        std = sum(1 for s in self.stores if s.is_standard)
        total_items = sum(len(s.items) for s in self.stores)
        return (f"{len(self.stores)} stores ({std} standard, {len(self.stores)-std} special), "
                f"{total_items} total items, body={len(self._body_data):,} bytes")

    def validate(self) -> List[str]:
        issues = []
        for store in self.stores:
            if not store.is_standard:
                continue
            cnt1 = struct.unpack_from('<I', self._body_data, store.after_name + 0x26)[0]
            cnt2 = struct.unpack_from('<I', self._body_data, store.after_name + 0x2F)[0]
            if cnt1 != cnt2:
                issues.append(f"{store.name}: count mismatch +0x26={cnt1} +0x2F={cnt2}")
            if cnt1 != len(store.items):
                issues.append(f"{store.name}: count={cnt1} but {len(store.items)} items parsed")
            for item in store.items:
                if item.item_key != item.item_key_dup:
                    issues.append(f"{store.name}: item {item.item_key} dup mismatch {item.item_key_dup}")
        return issues


def parse_storeinfo(pabgh_path: str, pabgb_path: str) -> StoreinfoParser:
    parser = StoreinfoParser()
    parser.load_from_files(pabgh_path, pabgb_path)
    parser.load_names()
    return parser


if __name__ == '__main__':
    import sys
    pabgh = sys.argv[1] if len(sys.argv) > 1 else 'C:/Users/Coding/CrimsonDesertModding/extractedpaz/0008_full/storeinfo.pabgh'
    pabgb = sys.argv[2] if len(sys.argv) > 2 else 'C:/Users/Coding/CrimsonDesertModding/extractedpaz/0008_full/storeinfo.pabgb'

    parser = parse_storeinfo(pabgh, pabgb)
    print(parser.get_summary())
    print()

    issues = parser.validate()
    if issues:
        print(f"Validation issues ({len(issues)}):")
        for iss in issues:
            print(f"  {iss}")
    else:
        print("Validation: all standard stores OK")

    print()
    print("Standard format stores with items:")
    for s in parser.stores:
        if s.is_standard and s.items:
            items_str = ', '.join(f"{parser.get_item_name(it.item_key)}({it.item_key})"
                                 for it in s.items[:3])
            if len(s.items) > 3:
                items_str += f", ... +{len(s.items)-3} more"
            print(f"  {s.name} (key={s.key}): {len(s.items)} items - {items_str}")
