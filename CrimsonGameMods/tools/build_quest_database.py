"""Rebuild the Save Editor's quest and knowledge lists from the installed game,
base game and DLC.

    python tools/build_quest_database.py "<game folder>" [--write]

Reads (via dmm_parser, game 2.04+):
  questinfo, questgroupinfo, missioninfo, knowledgeinfo  (+ *.dlc_01 of every DLC)
  quest.paloc, knowledge.paloc                          (+ *.dlc_01.paloc, English)

Writes into CrimsonSaveEditor/:
  quest_database.json, quest_names.json, quest_groups.json, mission_names.json  - rebuilt
  (and the same files in CrimsonGameMods/data/ if they are there)
  knowledge_keys_all.json  - the existing base list is kept; knowledge that only
                             a DLC has is added with "dlc": true
and the quests / missions tables of CrimsonGameMods/crimson_data.db (+ .gz).

Entries that only a DLC has get "dlc": true and "[DLC] " in front of the shown
name. "Inject all knowledge" leaves DLC knowledge out (a save without the DLC
must not get it); it can still be picked by hand in the Knowledge tab.

Without --write it only prints a comparison with the current files. With
--write it replaces them - but only if every record parsed and no main-story
quest went missing.

(2.04: the old byte parser questinfo_parser.py no longer reads questinfo -
0 of 1173 records - so this script uses dmm_parser.)
"""
from __future__ import annotations

import collections
import gzip
import json
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GMT_DIR = os.path.dirname(HERE)
SE_DIR = os.path.join(os.path.dirname(GMT_DIR), "CrimsonSaveEditor")
DB_PATH = os.path.join(SE_DIR, "quest_database.json")
GROUPS_PATH = os.path.join(SE_DIR, "quest_groups.json")
MISSIONS_PATH = os.path.join(SE_DIR, "mission_names.json")
KNOW_PATH = os.path.join(SE_DIR, "knowledge_keys_all.json")
SQLITE_PATH = os.path.join(GMT_DIR, "crimson_data.db")
BIN = "gamedata/binarystaticinfo__/bin"
LOC = "gamedata/stringtable/binary__/eng"
DLC_TAG = "[DLC] "

sys.path.insert(0, GMT_DIR)        # the Game Mod Tool's dmm_parser / item_db

_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII",
          "XIII", "XIV", "XV"]
CATEGORY_NAMES = {0: "Side", 12: "Regional", 13: "Main Story"}


def _table(dmm, root, stem_file, table):
    body = bytes(dmm.extract_file(root, "0008", BIN, stem_file + ".staticinfobody"))
    head = bytes(dmm.extract_file(root, "0008", BIN, stem_file + ".staticinfoheader"))
    rows = dmm.parse_table(table, body, head)
    if isinstance(rows, dict):
        rows = rows.get("records", [])
    bad = sum(1 for r in rows if r.get("_blob_fallback"))
    return [r for r in rows if not r.get("_blob_fallback")], bad


def _paloc(dmm, root, group, name):
    try:
        b = bytes(dmm.extract_file(root, group, LOC, name))
    except Exception:  # noqa: BLE001
        return {}
    if hasattr(dmm, "paloc_is_container") and dmm.paloc_is_container(b):
        b = bytes(dmm.unwrap_paloc_container(b))
    return {int(e["string_key"]): e["string_value"] for e in dmm.parse_paloc_bytes(b)
            if str(e["string_key"]).isdigit()}


def _read(game):
    import dmm_parser as dmm  # noqa: PLC0415
    from item_db import ItemNameDB, _dlc_tables  # noqa: PLC0415
    grp = ItemNameDB._find_language_group(dmm, game, "eng") or "0020"
    out = {"base": {}, "dlc": []}
    bad = 0
    for stem, table in (("questinfo", "quest_info"), ("questgroupinfo", "questgroupinfo"),
                        ("missioninfo", "mission_info"), ("knowledgeinfo", "knowledge_info")):
        rows, b = _table(dmm, game, stem, table)
        out["base"][stem] = rows
        bad += b
    out["base"]["loc"] = {**_paloc(dmm, game, grp, "quest.paloc"),
                          **_paloc(dmm, game, grp, "knowledge.paloc")}
    roots = sorted({r for r, _d, _n in _dlc_tables(dmm, game, "0008", "questinfo.", ".staticinfobody")})
    for root in roots:
        tag = os.path.basename(root.rstrip("/\\"))            # dlc_01
        part = {"tag": tag}
        for stem, table in (("questinfo", "quest_info"), ("questgroupinfo", "questgroupinfo"),
                            ("missioninfo", "mission_info"), ("knowledgeinfo", "knowledge_info")):
            try:
                rows, b = _table(dmm, root, f"{stem}.{tag}", table)
            except Exception as e:  # noqa: BLE001
                print(f"{tag}: {stem} not read: {e}")
                rows, b = [], 0
            part[stem] = rows
            bad += b
        part["loc"] = {**_paloc(dmm, root, "0020", f"quest.{tag}.paloc"),
                       **_paloc(dmm, root, "0020", f"knowledge.{tag}.paloc")}
        out["dlc"].append(part)
    out["bad"] = bad
    return out


def _idx(loc_obj):
    return loc_obj.get("index") if isinstance(loc_obj, dict) else None


def _quests(rows, loc, old_disp, dlc_keys):
    out = []
    for r in rows:
        key = r["key"]
        disp = loc.get(_idx(r.get("name"))) or old_disp.get(key) or r.get("string_key", "")
        e = {"key": key, "name": r.get("string_key", ""),
             "display": (DLC_TAG + disp) if key in dlc_keys else disp,
             "category": r.get("quest_category", 0),
             "category_name": CATEGORY_NAMES.get(r.get("quest_category", 0), f"Cat_{r.get('quest_category', 0)}"),
             "quest_type": r.get("quest_type", 0), "quest_group": r.get("quest_group_info", 0),
             "missions": list(r.get("mission_list") or []), "stages": list(r.get("stage_list") or []),
             "gauges": list(r.get("gauge_list") or [])}
        if key in dlc_keys:
            e["dlc"] = True
        out.append(e)
    return out


def _groups(rows, loc, dlc_keys):
    groups = []
    for r in rows:
        key = r.get("key")
        title = loc.get(_idx(r.get("name")), "")
        skey = r.get("string_key", "") or ""
        if key == 1000:
            display = f"Prologue. {title}" if title else "Prologue"
        elif key == 1013:
            display = f"Epilogue. {title}" if title else "Epilogue"
        elif isinstance(key, int) and 1001 <= key <= 1012:
            n = key - 1000
            display = f"{_ROMAN[n]}. {title}" if title else f"Chapter {n}"
        else:
            display = title or skey
        g = {"key": key, "name": skey, "display": (DLC_TAG + display) if key in dlc_keys else display,
             "is_dev": bool(r.get("is_dev")), "is_blocked": bool(r.get("is_blocked")),
             "quests": [int(q) for q in (r.get("quest_list") or [])]}
        if key in dlc_keys:
            g["dlc"] = True
        groups.append(g)
    return groups


def _knowledge_name(r, loc):
    for lv in r.get("knowledge_level_data_list") or []:
        for obj in (lv.get("tail_localizable_a"), (lv.get("learn_dialog_list") or [{}])[0].get("text_a")
                    if lv.get("learn_dialog_list") else None):
            n = loc.get(_idx(obj))
            if n:
                return n
    return ""


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    write = "--write" in argv
    if not args:
        print(__doc__)
        return 2
    data = _read(args[0])
    base, dlcs = data["base"], data["dlc"]
    loc = dict(base["loc"])
    for p in dlcs:
        loc.update(p["loc"])
    print(f"texts: {len(base['loc'])} base, {sum(len(p['loc']) for p in dlcs)} DLC; "
          f"records not decoded: {data['bad']}")

    # ── quests ──
    old_db = _load(DB_PATH, [])
    old_disp = {e["key"]: e["display"] for e in old_db if e.get("display") and e.get("display") != e.get("name")}
    base_q = {r["key"]: r for r in base["questinfo"]}
    q_rows = list(base["questinfo"])
    dlc_q = set()
    for p in dlcs:
        for r in p["questinfo"]:
            if r["key"] not in base_q:
                dlc_q.add(r["key"])
                q_rows.append(r)
                base_q[r["key"]] = r
    new = _quests(q_rows, loc, old_disp, dlc_q)
    gone = [e for e in old_db if e["key"] not in base_q]
    new += gone                          # quests the game no longer has: kept, like missions
    if gone:
        print(f"quests: {len(gone)} of the old file are not in the game any more - kept")
    main_old = {e["key"] for e in old_db if e.get("category_name") == "Main Story"}
    main_new = {e["key"] for e in new if e["category_name"] == "Main Story"}
    lost = main_old - main_new
    print(f"quests: old file {len(old_db)} ({len(main_old)} main story) -> game {len(new)} "
          f"({len(main_new)} main story, {len(dlc_q)} only in a DLC)")
    if lost:
        print("main-story quests missing now:", sorted(lost))

    # ── groups ──
    g_rows = list(base["questgroupinfo"])
    known_g = {r["key"]: r for r in g_rows}
    dlc_g = set()
    for p in dlcs:
        for r in p["questgroupinfo"]:
            if r["key"] in known_g:     # a DLC version of a base group: add its quests
                ql = known_g[r["key"]].setdefault("quest_list", [])
                for q in r.get("quest_list") or []:
                    if q not in ql:
                        ql.append(q)
            else:
                dlc_g.add(r["key"])
                g_rows.append(r)
                known_g[r["key"]] = r
    groups = _groups(g_rows, loc, dlc_g)
    print(f"groups: {len(groups)} ({len(dlc_g)} only in a DLC):",
          ", ".join(g["display"] for g in groups if g.get("dlc")))

    # ── missions ──
    m_rows = {r["key"]: r for r in base["missioninfo"]}
    dlc_m = set()
    for p in dlcs:
        for r in p["missioninfo"]:
            if r["key"] not in m_rows:
                dlc_m.add(r["key"])
                m_rows[r["key"]] = r
    old_m = {e["key"]: e for e in _load(MISSIONS_PATH, [])}
    missions = []
    for k, r in m_rows.items():
        disp = loc.get(_idx(r.get("label_a"))) or (old_m.get(k) or {}).get("display") or r.get("string_key", "")
        e = {"key": k, "name": r.get("string_key", ""), "display": (DLC_TAG + disp) if k in dlc_m else disp}
        if k in dlc_m:
            e["dlc"] = True
        missions.append(e)
    for k, e in old_m.items():          # missions the game no longer has: kept
        if k not in m_rows:
            missions.append(e)
    print(f"missions: old file {len(old_m)} -> {len(missions)} ({len(dlc_m)} only in a DLC)")

    # ── knowledge: keep the base list, add DLC-only entries ──
    know = _load(KNOW_PATH, [])
    have = {e["key"] for e in know}
    base_k = {r["key"] for r in base["knowledgeinfo"]}
    added = 0
    for p in dlcs:
        for r in p["knowledgeinfo"]:
            k = r["key"]
            if k in base_k or k in have:
                continue
            name = _knowledge_name(r, loc) or r.get("string_key", "")
            know.append({"key": k, "name": r.get("string_key", ""), "display_name": DLC_TAG + name, "dlc": True})
            have.add(k)
            added += 1
    print(f"knowledge: {len(know) - added} in the list, {added} DLC entries added")

    if not write:
        print("(dry run - add --write to replace the files)")
        return 0
    if data["bad"] or not new or lost:
        print("NOT written: records not decoded or main-story quests missing.")
        return 1
    names = [{"key": e["key"], "name": e["name"], "display": e["display"]} for e in new]
    outputs = ((DB_PATH, new), (GROUPS_PATH, groups), (MISSIONS_PATH, missions), (KNOW_PATH, know),
               (os.path.join(SE_DIR, "quest_names.json"), names))
    for path, obj in outputs:
        targets = [path]
        mirror = os.path.join(GMT_DIR, "data", os.path.basename(path))   # fallback copies
        if os.path.isfile(mirror):
            targets.append(mirror)
        for t in targets:
            with open(t, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=1)
            print("written:", t)
    # quest / mission names in the Game Mod Tool's database
    work = os.path.join(tempfile.gettempdir(), "crimson_data_lists.db")
    shutil.copyfile(SQLITE_PATH, work)
    c = sqlite3.connect(work)
    c.executemany("INSERT OR REPLACE INTO quests(key, name) VALUES (?, ?)",
                  [(e["key"], e["display"]) for e in new])
    c.executemany("INSERT OR REPLACE INTO missions(key, name) VALUES (?, ?)",
                  [(e["key"], e["display"]) for e in missions])
    c.commit()
    print("database: quests", c.execute("select count(*) from quests").fetchone()[0],
          "missions", c.execute("select count(*) from missions").fetchone()[0])
    c.close()
    shutil.copyfile(work, SQLITE_PATH)
    with open(SQLITE_PATH, "rb") as f, gzip.open(SQLITE_PATH + ".gz", "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)
    print("written:", SQLITE_PATH, "(+ .gz)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
