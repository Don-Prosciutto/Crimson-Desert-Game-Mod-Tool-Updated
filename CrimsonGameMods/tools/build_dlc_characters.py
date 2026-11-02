"""Add the characters the table does not have yet - base game and DLC - to the characters table of
crimson_data.db (names for Mesh Swap, Mercenary/Pets, Stores ...).

    python tools/build_dlc_characters.py "<game folder>" [--write]

Reads characterinfo.<dlc>.staticinfobody of every DLC and the English names
from character.<dlc>.paloc (name = (character_key << 32) | 0x30). Characters
already in the table are left as they are. Shown names get "[DLC] ".
"""
from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GMT_DIR = os.path.dirname(HERE)
SQLITE_PATH = os.path.join(GMT_DIR, "crimson_data.db")
sys.path.insert(0, GMT_DIR)


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    import dmm_parser as dmm  # noqa: PLC0415
    from item_db import _dlc_tables  # noqa: PLC0415
    game = args[0]
    work = os.path.join(tempfile.gettempdir(), "crimson_data_chars.db")
    shutil.copyfile(SQLITE_PATH, work)
    c = sqlite3.connect(work)
    have = {r[0] for r in c.execute("SELECT character_key FROM characters")}
    # keys of the base game (from the table header: count, then key + offset)
    import struct  # noqa: PLC0415
    h = bytes(dmm.extract_file(game, "0008", "gamedata/binarystaticinfo__/bin", "characterinfo.staticinfoheader"))
    n16 = struct.unpack_from("<H", h, 0)[0]
    start, n = (2, n16) if 2 + n16 * 8 == len(h) else (4, struct.unpack_from("<I", h, 0)[0])
    base_keys = {struct.unpack_from("<I", h, start + i * 8)[0] for i in range(n) if start + i * 8 + 8 <= len(h)}
    print(f"base game characters: {len(base_keys)}")
    rows_new = []
    sources = [(game, "gamedata/binarystaticinfo__/bin", "characterinfo.staticinfobody")]
    sources += list(_dlc_tables(dmm, game, "0008", "characterinfo.", ".staticinfobody"))
    for root, d, bname in sources:
        is_dlc = bname != "characterinfo.staticinfobody"
        tag = bname.split(".")[1]
        names = {}
        try:
            pal = f"character.{tag}.paloc" if is_dlc else "character.paloc"
            b = bytes(dmm.extract_file(root, "0020", "gamedata/stringtable/binary__/eng", pal))
            if dmm.paloc_is_container(b):
                b = bytes(dmm.unwrap_paloc_container(b))
            names = {int(e["string_key"]): e["string_value"] for e in dmm.parse_paloc_bytes(b)
                     if str(e["string_key"]).isdigit()}
        except Exception as e:  # noqa: BLE001
            print(f"{tag}: names not read: {e}")
        rows = dmm.parse_table("character_info", bytes(dmm.extract_file(root, "0008", d, bname)),
                               bytes(dmm.extract_file(root, "0008", d, bname.replace("body", "header"))))
        for r in rows:
            k = int(r["key"])
            if k in have or (is_dlc and k in base_keys):
                continue
            sk = r.get("string_key", "") or ""
            if r.get("vehicle_info") or sk.startswith("Riding_"):
                cat = "Mount"
            elif sk.startswith("MiddleBoss_"):
                cat = "MiddleBoss"
            elif sk.startswith("Boss_"):
                cat = "Boss"
            elif sk.startswith("N") and "_Unique_" in sk:
                cat = "NPC"
            else:
                cat = "Other"
            name = names.get((k << 32) | 0x30) or sk
            rows_new.append((k, sk, ("[DLC] " if is_dlc else "") + name, cat,
                             (k << 32) | 0x30, (k << 32) | 0x31, ""))
            have.add(k)
    print(f"characters: {len(have) - len(rows_new)} in the table, {len(rows_new)} to add "
          f"({sum(1 for r in rows_new if r[2].startswith('[DLC] '))} of them only in a DLC)")
    print("sample:", rows_new[:5])
    if "--write" not in argv:
        print("(dry run - add --write)")
        return 0
    cols = [r[1] for r in c.execute("pragma table_info(characters)")]
    c.executemany(f"INSERT INTO characters({', '.join(cols[:7])}) VALUES (?,?,?,?,?,?,?)", rows_new)
    c.commit()
    print("characters now:", c.execute("SELECT count(*) FROM characters").fetchone()[0])
    c.close()
    shutil.copyfile(work, SQLITE_PATH)
    with open(SQLITE_PATH, "rb") as f, gzip.open(SQLITE_PATH + ".gz", "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)
    print("written:", SQLITE_PATH, "(+ .gz)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
