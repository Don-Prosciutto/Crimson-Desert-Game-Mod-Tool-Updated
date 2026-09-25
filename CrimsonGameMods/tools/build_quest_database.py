"""Rebuild the Save Editor's quest_database.json and quest_groups.json
from the installed game.

    python tools/build_quest_database.py "<game folder>" [--write]
    python tools/build_quest_database.py --from-dir <folder> [--write]

Reads from the game: questinfo (every quest, its group, missions, stages,
gauges), questgroupinfo (the groups - Prologue, chapters, Exploration, ... -
with their quests in the game's order), missioninfo (mission names) and
quest.paloc (English names). --from-dir takes those files from a folder
instead (questinfo/questgroupinfo/missioninfo .pabgb/.pabgh, quest.paloc).

Writes quest_database.json, quest_groups.json and mission_names.json.

Without --write it only prints a comparison with the current files. With
--write it replaces them - but only if every questinfo record parsed and no
main-story quest went missing.

The Save Editor's "Story & Groups" view uses quest_groups.json; without it
the view falls back to numbered chapters.
"""
from __future__ import annotations

import collections
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GMT_DIR = os.path.dirname(HERE)
SE_DIR = os.path.join(os.path.dirname(GMT_DIR), "CrimsonSaveEditor")
DB_PATH = os.path.join(SE_DIR, "quest_database.json")
GROUPS_PATH = os.path.join(SE_DIR, "quest_groups.json")
MISSIONS_PATH = os.path.join(SE_DIR, "mission_names.json")
BIN_DIR = "gamedata/binary__/client/bin"
LOC_DIR = "gamedata/stringtable/binary__/eng"

sys.path.insert(0, SE_DIR)
sys.path.insert(0, GMT_DIR)        # first: the Game Mod Tool's dmm_parser / crimson_rs

_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII",
          "XIII", "XIV", "XV"]


def _read_game(game: str) -> dict:
    import crimson_rs  # noqa: PLC0415 - the Game Mod Tool's reader
    import dmm_parser  # noqa: PLC0415
    from item_db import ItemNameDB  # noqa: PLC0415
    files = {}
    for stem in ("questinfo", "questgroupinfo", "missioninfo"):
        for ext in ("pabgb", "pabgh"):
            files[f"{stem}.{ext}"] = bytes(crimson_rs.extract_file(game, "0008", BIN_DIR,
                                                                   f"{stem}.{ext}"))
    grp = ItemNameDB._find_language_group(dmm_parser, game, "eng")
    if grp:
        files["quest.paloc"] = bytes(dmm_parser.extract_file(game, grp, LOC_DIR, "quest.paloc"))
    return files


def _read_dir(folder: str) -> dict:
    files = {}
    for name in ("questinfo.pabgb", "questinfo.pabgh", "questgroupinfo.pabgb",
                 "questgroupinfo.pabgh", "missioninfo.pabgb", "missioninfo.pabgh", "quest.paloc"):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                files[name] = f.read()
    return files


def _parse_quests(body: bytes, head: bytes):
    import questinfo_parser as qp  # noqa: PLC0415
    with tempfile.TemporaryDirectory() as d:
        pb, pg = os.path.join(d, "q.pabgb"), os.path.join(d, "q.pabgh")
        with open(pb, "wb") as f:
            f.write(body)
        with open(pg, "wb") as f:
            f.write(head)
        entries, failures = qp.parse_all(pb, pg)
    return entries, failures, len(qp.parse_pabgh(head))


def _paloc(data):
    if not data:
        return {}
    import dmm_parser  # noqa: PLC0415
    out = {}
    for e in dmm_parser.parse_paloc_bytes(data):
        k = str(e.get("string_key") or "")
        if k.isdigit():
            out[int(k)] = str(e.get("string_value") or "")
    return out


def _parse_groups(body: bytes, head: bytes, loc: dict):
    import dmm_parser  # noqa: PLC0415
    parsed = dmm_parser.parse_table("questgroupinfo", body, head)
    records = parsed.get("records", parsed) if isinstance(parsed, dict) else parsed
    groups = []
    for r in records:
        name = r.get("name") or {}
        index = name.get("index") if isinstance(name, dict) else None
        title = loc.get(index, "") if index else ""
        skey = r.get("string_key", "") or ""
        key = r.get("key")
        if key == 1000:
            display = f"Prologue. {title}" if title else "Prologue"
        elif key == 1013:
            display = f"Epilogue. {title}" if title else "Epilogue"
        elif isinstance(key, int) and 1001 <= key <= 1012:
            n = key - 1000
            display = f"{_ROMAN[n]}. {title}" if title else f"Chapter {n}"
        else:
            display = title or skey
        groups.append({
            "key": key, "name": skey, "display": display,
            "is_dev": bool(r.get("is_dev")), "is_blocked": bool(r.get("is_blocked")),
            "quests": [int(q) for q in (r.get("quest_list") or [])],
        })
    return groups


def _mission_names(body: bytes, head: bytes, loc: dict, old: dict):
    """Mission key -> (internal name, display name).

    dmm-parser cannot decode missioninfo in 2.03, so the name is found by
    its shape: a LocalizableString is u8 category, u64 paloc key, then a
    CString that repeats the key as text. The first one in a record is the
    mission's name (the next ones are its descriptions). Missions without
    one keep the name from the old mission_names.json."""
    import struct  # noqa: PLC0415
    import questinfo_parser as qp  # noqa: PLC0415
    idx = qp.parse_pabgh(head)
    offs = sorted(set(idx.values()))
    nxt = {o: (offs[i + 1] if i + 1 < len(offs) else len(body)) for i, o in enumerate(offs)}
    out = {}
    for key, off in idx.items():
        end = nxt[off]
        n = struct.unpack_from("<I", body, off + 4)[0]
        skey = body[off + 8:off + 8 + n].decode("utf-8", "replace") if n < 500 else ""
        label = ""
        i = off + 8 + n
        while i + 13 <= end:
            ix = struct.unpack_from("<Q", body, i + 1)[0]
            if ix in loc:
                ln = struct.unpack_from("<I", body, i + 9)[0]
                if body[i + 13:i + 13 + ln] == str(ix).encode():
                    label = loc[ix]
                    break
            i += 1
        prev = old.get(key) or {}
        display = label or (prev.get("display") if prev.get("display") != prev.get("name") else "") or skey
        out[key] = (skey or prev.get("name", ""), display)
    return out


def _old_displays():
    names = {}
    for fn in ("quest_names.json", "quest_database.json"):
        try:
            with open(os.path.join(SE_DIR, fn), encoding="utf-8") as f:
                for e in json.load(f):
                    if e.get("display") and e.get("display") != e.get("name"):
                        names[e["key"]] = e["display"]
        except (OSError, ValueError):
            pass
    return names


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    write = "--write" in argv
    if "--from-dir" in argv:
        files = _read_dir(args[0]) if args else {}
    elif args:
        files = _read_game(args[0])
    else:
        print(__doc__)
        return 2

    loc = _paloc(files.get("quest.paloc"))
    print(f"quest.paloc: {len(loc)} English strings")

    entries, failures, total = _parse_quests(files["questinfo.pabgb"], files["questinfo.pabgh"])
    print(f"questinfo: {total} records, {len(entries)} parsed, {failures} failed")

    displays = _old_displays()
    new = []
    for e in entries:                     # game order, like the old file
        display = loc.get(e.get("name_index")) or displays.get(e["key"]) or e["name"]
        new.append({
            "key": e["key"], "name": e["name"], "display": display,
            "category": e["quest_category"], "category_name": e["category_name"],
            "quest_type": e["quest_type"], "quest_group": e["quest_group"],
            "missions": e["missions"], "stages": e["stages"], "gauges": e.get("gauges", []),
        })

    with open(DB_PATH, encoding="utf-8") as f:
        old = json.load(f)
    main_old = {e["key"] for e in old if e.get("category_name") == "Main Story"}
    main_new = {e["key"] for e in new if e["category_name"] == "Main Story"}
    print(f"old file: {len(old)} quests, {len(main_old)} main story")
    print(f"game:     {len(new)} quests, {len(main_new)} main story")
    print("main story per group:", sorted(collections.Counter(
        e["quest_group"] for e in new if e["category_name"] == "Main Story").items()))
    lost = main_old - main_new
    if lost:
        print("main-story quests missing now:", sorted(lost))

    groups = None
    try:
        groups = _parse_groups(files["questgroupinfo.pabgb"], files["questgroupinfo.pabgh"], loc)
        print(f"questgroupinfo: {len(groups)} groups")
        for g in groups:
            print(f"    {g['key']:>5} {g['name'][:26]:26} {g['display'][:40]:40} {len(g['quests'])} quests")
    except Exception as e:  # noqa: BLE001
        print(f"questgroupinfo not read: {type(e).__name__}: {e}")

    missions = None
    if "missioninfo.pabgb" in files:
        try:
            with open(MISSIONS_PATH, encoding="utf-8") as f:
                old_m = {e["key"]: e for e in json.load(f)}
        except (OSError, ValueError):
            old_m = {}
        missions = _mission_names(files["missioninfo.pabgb"], files["missioninfo.pabgh"], loc, old_m)
        named = sum(1 for k, (n, d) in missions.items() if d and d != n)
        refs = {m for e in new for m in e["missions"]}
        unnamed = [m for m in refs if m not in missions or missions[m][1] == missions[m][0]]
        print(f"missioninfo: {len(missions)} missions, {named} with a display name "
              f"(old file: {len(old_m)}); missions of quests without a name: {len(unnamed)}")
        if set(old_m) - set(missions):
            print(f"  {len(set(old_m) - set(missions))} missions of the old file are gone - kept")
            for k in set(old_m) - set(missions):
                missions[k] = (old_m[k].get("name", ""), old_m[k].get("display", ""))

    if not write:
        print("(dry run - add --write to replace the files)")
        return 0
    if failures or not new or lost:
        print("NOT written: parse failures or missing main-story quests.")
        return 1
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    print("written:", DB_PATH)
    if groups:
        with open(GROUPS_PATH, "w", encoding="utf-8") as f:
            json.dump(groups, f, ensure_ascii=False, indent=1)
        print("written:", GROUPS_PATH)
    if missions:
        with open(MISSIONS_PATH, "w", encoding="utf-8") as f:
            json.dump([{"key": k, "name": n, "display": d} for k, (n, d) in missions.items()],
                      f, ensure_ascii=False, indent=1)
        print("written:", MISSIONS_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
