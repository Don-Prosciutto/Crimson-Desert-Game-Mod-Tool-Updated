"""Resolve PA Reflection u32 name-hashes back to their original string identifiers.

stringinfo.pabgb stores 29K hash→string entries in this layout per record:
    [u32 hash] [4B zero] [1B flag] [u32 slen] [N bytes utf-8 string]

The pabgh side is a flat (hash, offset) table — u16 count header, then 8B per entry.

Used by field_edit.py and the Action Chart Browser to translate raw hex hashes
like 0x8bb21489 into readable names like 'Player_Kliff'.
"""
from __future__ import annotations

import logging
import os
import struct
from typing import Optional

log = logging.getLogger(__name__)


class StringResolver:
    def __init__(self) -> None:
        self._hash_to_str: dict[int, str] = {}
        self._loaded = False

    def load_from_pabgb(self, pabgb: bytes, pabgh: bytes) -> int:
        h2s: dict[int, str] = {}
        # Both layouts put the string length 9 bytes into the record:
        # up to 2.05 [u32 0 (empty name)][u32 hash][u8], since 2.06
        # [u32 hash][u32 row number][u8].
        from table_index import read_index
        for _e in read_index(pabgh).entries:
            k, o = _e.key, _e.offset
            if o + 13 > len(pabgb):
                continue
            slen = struct.unpack_from('<I', pabgb, o + 9)[0]
            if slen > 1000 or o + 13 + slen > len(pabgb):
                continue
            try:
                s = pabgb[o + 13:o + 13 + slen].decode('utf-8', errors='replace')
            except Exception:
                continue
            h2s[k] = s
        self._hash_to_str = h2s
        self._loaded = True
        return len(h2s)

    def load_from_game(self, game_path: str) -> int:
        try:
            import crimson_rs
            dp = "gamedata/binary__/client/bin"
            pabgb = bytes(crimson_rs.extract_file(game_path, "0008", dp,
                                                  "stringinfo.pabgb"))
            pabgh = bytes(crimson_rs.extract_file(game_path, "0008", dp,
                                                  "stringinfo.pabgh"))
            n = self.load_from_pabgb(pabgb, pabgh)
            log.info("StringResolver loaded %d hash→string entries from game", n)
            return n
        except Exception:
            log.exception("StringResolver: failed to load stringinfo from game")
            return 0

    def load_from_extracted(self, base_dir: str) -> int:
        try:
            with open(os.path.join(base_dir, 'stringinfo.pabgb'), 'rb') as f:
                pabgb = f.read()
            with open(os.path.join(base_dir, 'stringinfo.pabgh'), 'rb') as f:
                pabgh = f.read()
            return self.load_from_pabgb(pabgb, pabgh)
        except Exception:
            log.exception("StringResolver: failed to load from %s", base_dir)
            return 0

    @property
    def loaded(self) -> bool:
        return self._loaded

    def __len__(self) -> int:
        return len(self._hash_to_str)

    def resolve(self, h: int) -> Optional[str]:
        return self._hash_to_str.get(int(h))

    def label(self, h: int, fmt: str = '{name} (0x{hash:08x})',
              fallback: str = '0x{hash:08x}') -> str:
        s = self.resolve(h)
        if s:
            return fmt.format(name=s, hash=h)
        return fallback.format(hash=h)
