
import json
import logging
import os
import struct
from data_db import get_connection
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

ITEM_ENTRY_SIZE = 105
ITEM_MARKER = b'\x01\x01'


@dataclass
class StoreItem:
    offset: int
    item_key: int
    item_name: str
    raw_entry: bytes
    price_buy: int = 0
    price_sell: int = 0


@dataclass
class Store:
    key: int
    name: str
    offset: int
    size: int
    items: List[StoreItem] = field(default_factory=list)
    raw_data: bytes = b''


class StoreInfoParser:

    def __init__(self, game_path: str):
        self.game_path = game_path
        self.stores: List[Store] = []
        self._header_data: bytes = b''
        self._body_data: bytearray = bytearray()
        self._header_entries: List[Tuple[int, int]] = []
        self._name_lookup: Dict[int, str] = {}
        self._loaded = False

    def load_names(self) -> None:
        _db = get_connection()
        for row in _db.execute("SELECT item_key, name FROM items"):
            self._name_lookup[row['item_key']] = row['name']

    def extract(self) -> bool:
        import sys
        for d in (os.path.join(os.path.dirname(__file__), 'Communitydump', 'BestCrypto'),
                  os.path.join(os.path.dirname(__file__), 'tools')):
            if os.path.isdir(d) and d not in sys.path:
                sys.path.insert(0, d)

        try:
            from paz_parse import parse_pamt
        except ImportError:
            log.error("paz_parse not found")
            return False

        import lz4.block

        pamt_path = os.path.join(self.game_path, '0008', '0.pamt')
        if not os.path.isfile(pamt_path):
            log.error("PAMT not found: %s", pamt_path)
            return False

        entries = parse_pamt(pamt_path, paz_dir=os.path.join(self.game_path, '0008'))

        header_entry = None
        body_entry = None
        for e in entries:
            _p = e.path.lower()
            if 'storeinfo.pabgh' in _p or 'storeinfo.staticinfoheader' in _p:
                header_entry = e
            elif 'storeinfo.pabgb' in _p or 'storeinfo.staticinfobody' in _p:
                body_entry = e

        if not header_entry or not body_entry:
            log.error("storeinfo not found in PAMT")
            return False

        with open(header_entry.paz_file, 'rb') as f:
            f.seek(header_entry.offset)
            self._header_data = f.read(header_entry.comp_size)

        with open(body_entry.paz_file, 'rb') as f:
            f.seek(body_entry.offset)
            raw = f.read(body_entry.comp_size)

        if body_entry.compressed:
            self._body_data = bytearray(
                lz4.block.decompress(raw, uncompressed_size=body_entry.orig_size))
        else:
            self._body_data = bytearray(raw)

        count = struct.unpack_from('<H', self._header_data, 0)[0]
        self._header_entries = []
        for i in range(count):
            base = 2 + i * 6
            key = struct.unpack_from('<H', self._header_data, base)[0]
            off = struct.unpack_from('<I', self._header_data, base + 2)[0]
            self._header_entries.append((key, off))

        self.load_names()
        self._parse_stores()
        self._loaded = True

        log.info("Loaded %d stores with %d total items from storeinfo",
                 len(self.stores), sum(len(s.items) for s in self.stores))
        return True

    def _parse_stores(self) -> None:
        self.stores.clear()
        data = self._body_data

        for idx, (skey, soff) in enumerate(self._header_entries):
            if idx + 1 < len(self._header_entries):
                rec_size = self._header_entries[idx + 1][1] - soff
            else:
                rec_size = len(data) - soff

            name_len = struct.unpack_from('<I', data, soff + 2)[0]
            store_name = data[soff + 6:soff + 6 + name_len].decode('ascii', errors='replace')

            store = Store(
                key=skey,
                name=store_name,
                offset=soff,
                size=rec_size,
                raw_data=bytes(data[soff:soff + rec_size]),
            )

            rec = data[soff:soff + rec_size]
            for i in range(len(rec) - 5):
                if rec[i] == 0x01 and rec[i + 1] == 0x01:
                    item_key = struct.unpack_from('<I', rec, i + 2)[0]
                    if item_key in self._name_lookup and item_key > 100:
                        entry_start = i - 2
                        entry_end = entry_start + ITEM_ENTRY_SIZE
                        if entry_end <= len(rec):
                            raw_entry = bytes(rec[entry_start:entry_end])
                        else:
                            raw_entry = bytes(rec[entry_start:])

                        price_buy = 0
                        price_sell = 0
                        if i + 82 <= len(rec):
                            price_off = i + 72
                            if price_off + 16 <= soff + rec_size:
                                price_buy = struct.unpack_from('<Q', data, soff + price_off)[0]
                                price_sell = struct.unpack_from('<Q', data, soff + price_off + 8)[0]

                        store.items.append(StoreItem(
                            offset=soff + i,
                            item_key=item_key,
                            item_name=self._name_lookup.get(item_key, f"Unknown ({item_key})"),
                            raw_entry=raw_entry,
                            price_buy=price_buy,
                            price_sell=price_sell,
                        ))

            self.stores.append(store)

    def get_store_by_key(self, key: int) -> Optional[Store]:
        return next((s for s in self.stores if s.key == key), None)

    def get_store_by_name(self, name: str) -> Optional[Store]:
        name_lower = name.lower()
        return next((s for s in self.stores if name_lower in s.name.lower()), None)

    def swap_item(self, store_key: int, old_item_key: int, new_item_key: int) -> bool:
        store = self.get_store_by_key(store_key)
        if not store:
            return False

        for item in store.items:
            if item.item_key == old_item_key:
                struct.pack_into('<I', self._body_data, item.offset + 2, new_item_key)
                second_off = item.offset + 61
                if second_off + 4 <= len(self._body_data):
                    check = struct.unpack_from('<I', self._body_data, second_off)[0]
                    if check == old_item_key:
                        struct.pack_into('<I', self._body_data, second_off, new_item_key)

                item.item_key = new_item_key
                item.item_name = self._name_lookup.get(new_item_key, f"Unknown ({new_item_key})")
                log.info("Swapped item %d -> %d in store %d", old_item_key, new_item_key, store_key)
                return True

        return False

    def add_item_to_store(self, store_key: int, donor_item_key: int,
                          new_item_key: int) -> bool:
        store = self.get_store_by_key(store_key)
        if not store:
            return False

        donor = None
        for item in store.items:
            if item.item_key == donor_item_key:
                donor = item
                break

        if not donor or len(donor.raw_entry) < ITEM_ENTRY_SIZE:
            log.warning("Donor item %d not found in store %d", donor_item_key, store_key)
            return False

        entry_start = donor.offset - 0x20
        if entry_start < 0:
            log.warning("Cannot determine entry start for donor %d", donor_item_key)
            return False
        new_entry = bytearray(self._body_data[entry_start:entry_start + ITEM_ENTRY_SIZE])

        struct.pack_into('<I', new_entry, 0x22, new_item_key)
        struct.pack_into('<I', new_entry, 0x5D, new_item_key)

        name_len = struct.unpack_from('<I', self._body_data, store.offset + 2)[0]
        after_name = store.offset + 6 + name_len
        old_count = struct.unpack_from('<I', self._body_data, after_name + 0x26)[0]
        items_end = after_name + 51 + old_count * ITEM_ENTRY_SIZE
        self._body_data[items_end:items_end] = new_entry

        new_count = old_count + 1
        struct.pack_into('<I', self._body_data, after_name + 0x26, new_count)
        struct.pack_into('<I', self._body_data, after_name + 0x2F, new_count)

        self._rebuild_header_offsets()
        self._parse_stores()

        log.info("Added item %d (cloned from %d) to store %d",
                 new_item_key, donor_item_key, store_key)
        return True

    def _rebuild_header_offsets(self) -> None:
        data = self._body_data
        new_entries = []
        for skey, _ in self._header_entries:
            key_bytes = struct.pack('<H', skey)
            pos = 0
            while pos < len(data) - 10:
                pos = data.find(key_bytes, pos)
                if pos < 0:
                    break
                try:
                    name_len = struct.unpack_from('<I', data, pos + 2)[0]
                    if 1 <= name_len <= 100:
                        test = data[pos + 6:pos + 6 + name_len]
                        if all(32 <= b < 127 or b == 0 for b in test):
                            name = test.decode('ascii', errors='replace')
                            if 'Store_' in name or 'store_' in name.lower():
                                new_entries.append((skey, pos))
                                break
                except (struct.error, IndexError):
                    pass
                pos += 1
            else:
                old_off = next(o for k, o in self._header_entries if k == skey)
                new_entries.append((skey, old_off))

        self._header_entries = new_entries

        count = len(new_entries)
        new_hdr = bytearray(struct.pack('<H', count))
        for skey, soff in new_entries:
            new_hdr += struct.pack('<HI', skey, soff)
        self._header_data = bytes(new_hdr)

    def write_to_paz(self, paz_dir_name: str = "0036") -> Tuple[bool, str]:
        try:
            import crimson_rs
            import shutil

            output_dir = os.path.join(self.game_path, paz_dir_name)

            papgt_path = os.path.join(self.game_path, "meta", "0.papgt")
            papgt_backup = papgt_path + ".sebak"
            if os.path.isfile(papgt_path) and not os.path.isfile(papgt_backup):
                shutil.copy2(papgt_path, papgt_backup)

            if os.path.isdir(output_dir):
                shutil.rmtree(output_dir)
            os.makedirs(output_dir, exist_ok=True)

            builder = crimson_rs.PackGroupBuilder(output_dir, compression=2)
            builder.add_file("gamedata", "storeinfo.pabgh", self._header_data)
            builder.add_file("gamedata", "storeinfo.pabgb", bytes(self._body_data))
            pamt_bytes = builder.finish()

            pamt_checksum = crimson_rs.calculate_checksum(pamt_bytes[12:])
            papgt = crimson_rs.parse_papgt_file(papgt_path)

            papgt['entries'] = [e for e in papgt['entries'] if e['group_name'] != paz_dir_name]
            new_papgt = crimson_rs.add_papgt_entry(papgt, paz_dir_name, pamt_checksum, 0, 0x3FFF)
            crimson_rs.write_papgt_file(new_papgt, papgt_path)

            paz_size = os.path.getsize(os.path.join(output_dir, "0.paz"))
            msg = (f"Packed storeinfo to {paz_dir_name}/ ({paz_size:,} bytes)\n"
                   f"PAPGT updated ({len(new_papgt['entries'])} entries)\n"
                   f"Stores: {len(self.stores)}, Items: {sum(len(s.items) for s in self.stores)}")
            log.info(msg)
            return True, msg

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, str(e)

    def write_inplace(self) -> Tuple[bool, str]:
        try:
            import sys
            import lz4.block
            import shutil

            for d in (os.path.join(os.path.dirname(__file__), 'Communitydump', 'BestCrypto'),
                      os.path.join(os.path.dirname(__file__), 'tools')):
                if os.path.isdir(d) and d not in sys.path:
                    sys.path.insert(0, d)
            from paz_parse import parse_pamt

            pamt_path = os.path.join(self.game_path, '0008', '0.pamt')
            if not os.path.isfile(pamt_path):
                return False, f"PAMT not found: {pamt_path}"

            entries = parse_pamt(pamt_path, paz_dir=os.path.join(self.game_path, '0008'))

            body_entry = None
            for e in entries:
                if 'storeinfo.pabgb' in e.path.lower() or 'storeinfo.staticinfobody' in e.path.lower():
                    body_entry = e

            if not body_entry:
                return False, "storeinfo.pabgb not found in PAMT"

            if not body_entry.compressed:
                paz_path = body_entry.paz_file
                paz_backup = paz_path + ".sebak"
                if not os.path.isfile(paz_backup):
                    shutil.copy2(paz_path, paz_backup)

                with open(paz_path, 'r+b') as f:
                    f.seek(body_entry.offset)
                    f.write(bytes(self._body_data))

                return True, f"Patched {len(self._body_data):,} bytes at offset {body_entry.offset} in {os.path.basename(paz_path)}"

            paz_path = body_entry.paz_file
            orig_comp_size = body_entry.comp_size
            orig_size = body_entry.orig_size

            if len(self._body_data) != orig_size:
                return False, (
                    f"Body size changed ({orig_size} -> {len(self._body_data)}). "
                    f"In-place patching only works for same-size edits (swaps/limits). "
                    f"Use PAZ group override for insertions."
                )

            recompressed = lz4.block.compress(
                bytes(self._body_data), mode='high_compression', store_size=False
            )

            if len(recompressed) > orig_comp_size:
                return False, (
                    f"Recompressed size ({len(recompressed)}) > original ({orig_comp_size}). "
                    f"Cannot patch in-place."
                )

            padded = recompressed + b'\x00' * (orig_comp_size - len(recompressed))

            paz_backup = paz_path + ".sebak"
            if not os.path.isfile(paz_backup):
                shutil.copy2(paz_path, paz_backup)
                log.info("Backed up %s", paz_path)

            with open(paz_path, 'r+b') as f:
                f.seek(body_entry.offset)
                f.write(padded)

            try:
                import crimson_rs
                with open(paz_path, 'rb') as f:
                    chunk_data = f.read()
                new_chunk_checksum = crimson_rs.calculate_checksum(chunk_data)

                with open(pamt_path, 'rb') as f:
                    pamt_data = bytearray(f.read())

                if body_entry.table_offset + 12 <= len(pamt_data):
                    struct.pack_into('<I', pamt_data, body_entry.table_offset + 8,
                                     len(recompressed))
                    log.info("Updated PAMT comp_size: %d -> %d at offset %d",
                             orig_comp_size, len(recompressed), body_entry.table_offset + 8)

                chunk_count = struct.unpack_from('<H', pamt_data, 4)[0]
                struct.pack_into('<I', pamt_data, 12 + 4, new_chunk_checksum)
                chunk_size = len(chunk_data)
                struct.pack_into('<I', pamt_data, 12 + 8, chunk_size)

                pamt_post_header = bytes(pamt_data[4:])
                new_pamt_checksum = crimson_rs.calculate_checksum(bytes(pamt_data[12:]))
                struct.pack_into('<I', pamt_data, 0, new_pamt_checksum)

                pamt_backup = pamt_path + ".sebak"
                if not os.path.isfile(pamt_backup):
                    shutil.copy2(pamt_path, pamt_backup)

                with open(pamt_path, 'wb') as f:
                    f.write(pamt_data)

                papgt_path = os.path.join(self.game_path, "meta", "0.papgt")
                papgt_backup = papgt_path + ".sebak"
                if not os.path.isfile(papgt_backup):
                    shutil.copy2(papgt_path, papgt_backup)

                papgt = crimson_rs.parse_papgt_file(papgt_path)
                for entry in papgt['entries']:
                    if entry['group_name'] == '0008':
                        entry['pack_meta_checksum'] = new_pamt_checksum
                        break
                crimson_rs.write_papgt_file(papgt, papgt_path)

                msg = (
                    f"In-place patch applied to {os.path.basename(paz_path)}\n"
                    f"  Offset: {body_entry.offset}, Size: {orig_comp_size} bytes\n"
                    f"  Recompressed: {len(recompressed)} bytes (padded to {orig_comp_size})\n"
                    f"  Checksums updated: PAMT + PAPGT\n"
                    f"  Backup: {paz_backup}"
                )
            except ImportError:
                msg = (
                    f"In-place patch applied (no checksum update — crimson_rs not available)\n"
                    f"  {os.path.basename(paz_path)} at offset {body_entry.offset}\n"
                    f"  Recompressed: {len(recompressed)} bytes (padded to {orig_comp_size})"
                )

            log.info(msg)
            return True, msg

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, str(e)

    def get_summary(self) -> str:
        if not self._loaded:
            return "Not loaded. Call extract() first."
        total_items = sum(len(s.items) for s in self.stores)
        return (f"{len(self.stores)} stores, {total_items} items total\n"
                f"Body: {len(self._body_data):,} bytes")
