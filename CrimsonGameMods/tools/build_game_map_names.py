"""Add the factions, faction nodes, characters and sublevels the game has now
(main tables + every installed DLC) to game_map.json.

game_map.json was built from game 1.x. The Save Editor takes faction, node,
character and sublevel names from it (Faction tab, quests, friendships).
Entries it already has stay as they are; missing ones are added, the DLC's
with "[DLC] " in front of the name and "dlc": true.

    python tools/build_game_map_names.py <game folder>
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import dmm_parser  # noqa: E402
from item_db import _dlc_tables  # noqa: E402

BIN = "gamedata/binarystaticinfo__/bin"
SECTIONS = [  # (game_map key, table stem, type)
    ("factions", "faction", "faction"),
    ("factionnodes", "factionnode", "factionnode"),
    ("characters", "characterinfo", "character"),
    ("sublevels", "sublevelinfo", "sublevel"),
]
TARGETS = [
    os.path.join(os.path.dirname(ROOT), "CrimsonSaveEditor", "game_map.json"),
    os.path.join(ROOT, "data", "game_map.json"),
]


def _records(game: str, stem: str) -> tuple[list, list]:
    head = bytes(dmm_parser.extract_file(game, "0008", BIN, f"{stem}.staticinfoheader"))
    body = bytes(dmm_parser.extract_file(game, "0008", BIN, f"{stem}.staticinfobody"))
    base = list(dmm_parser.parse_table(stem, body, head))
    keys = {int(r["key"]) for r in base}
    dlc = []
    for root, d, hname in _dlc_tables(dmm_parser, game, "0008", f"{stem}.", ".staticinfoheader"):
        bname = hname[:-len(".staticinfoheader")] + ".staticinfobody"
        recs = dmm_parser.parse_table(stem, bytes(dmm_parser.extract_file(root, "0008", d, bname)),
                                      bytes(dmm_parser.extract_file(root, "0008", d, hname)))
        for r in recs:
            k = int(r["key"])
            if k not in keys:
                keys.add(k)
                dlc.append(r)
    return base, dlc


def main(game: str) -> None:
    gm_path = TARGETS[0]
    with open(gm_path, encoding="utf-8") as f:
        gm = json.load(f)
    for key, stem, typ in SECTIONS:
        sec = gm.setdefault(key, {})
        base, dlc = _records(game, stem)
        added = added_dlc = 0
        for recs, is_dlc in ((base, False), (dlc, True)):
            for r in recs:
                k = str(int(r["key"]))
                if k in sec:
                    continue
                name = str(r.get("string_key") or "")
                entry = {"key": int(r["key"]), "name": f"[DLC] {name}" if is_dlc else name,
                         "type": typ}
                if is_dlc:
                    entry["dlc"] = True
                    added_dlc += 1
                else:
                    added += 1
                sec[k] = entry
        gm.setdefault("counts", {})[key] = len(sec)
        print(f"{key}: +{added} main, +{added_dlc} DLC -> {len(sec)}")
    text = json.dumps(gm, ensure_ascii=False, separators=(",", ":"))
    for path in TARGETS:
        if os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            print("written", path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert")
