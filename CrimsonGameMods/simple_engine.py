"""CrimsonGameMods Simple - the part that changes the game (no Qt in here).

What it does
------------
Every switch is a small change to one or more game tables (iteminfo,
skill, dropsetinfo ...). "Apply" rebuilds ALL active switches in one go:

  1. read each needed table from the game - from the overlay that is
     currently in effect for that table (for example DMM's), else from the
     unmodded group 0008 - so Simple adds its changes on top instead of
     switching other mods off;
  2. check that the parser reads and writes that table back byte for byte
     (if not, the game was updated and the switch is refused instead of
     writing a damaged table);
  3. apply the switches in memory and write every changed table into ONE
     overlay group, "cgmsimple", next to the game's own groups;
  4. register that group at the front of meta/0.papgt, keeping every other
     entry exactly as it was (vanilla, DMM, anything else).

"Remove" deletes the group and its papgt entry - the papgt is rebuilt
byte for byte without it. Nothing else in the game folder is touched: the
game's own groups are only read.

After a game update Steam replaces 0.papgt; Simple notices that its entry
is gone (or the game version changed) and offers to apply again.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import struct
import tempfile
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

GROUP = "cgmsimple"
MARKER = "cgmsimple.json"
TABLE_DIR = "gamedata/binary__/client/bin"      # mapped to the 2.01+ layout by dmm_parser
PAPGT_BACKUP = "0.papgt.cgmsimple_backup"
ENGINE_VERSION = 2

# serialize_table does not resolve every alias of the parse side
_SERIALIZE_NAME = {"equipslotinfo": "equip_slot_info"}


class RefusedError(RuntimeError):
    """A switch cannot be applied safely (e.g. the parser does not fit)."""


# ── mod definitions ──────────────────────────────────────────────────────
# id -> tables it edits. The functions below do the edits.

MOD_TABLES: Dict[str, Tuple[str, ...]] = {
    "no_cooldown": ("iteminfo",),
    "max_charges": ("iteminfo",),
    "max_stacks": ("iteminfo",),
    "inf_durability": ("iteminfo",),
    "make_dyeable": ("iteminfo",),
    "five_sockets": ("iteminfo",),
    "unlock_abyss": ("iteminfo",),
    "universal_prof": ("iteminfo", "equipslotinfo"),
    "infinite_stamina": ("skill",),
    "mounts_in_towns": ("regioninfo", "characterinfo"),
    "npcs_killable": ("characterinfo",),
    "drop_5x": ("dropsetinfo",),
    "drop_max": ("dropsetinfo",),
    "merc_max": ("mercenaryinfo",),
    "speed_3x": ("statusinfo",),
    "hard_2x_hp": ("buffinfo",),
    "store_max_stock": ("storeinfo",),
    "bagspace_240": ("inventory",),
    "bagspace_700": ("inventory",),
    "refine_cost_1": ("multichangeinfo",),
    "thief_gloves_no_cd": ("iteminfo",),
    "gift_trust_5x": ("characterinfo",),
}

PLAYER_CHAR_KEYS = {1, 4, 6}          # Kliff, Damiane, Oongka in equipslotinfo
SOCKET_COSTS = [500, 1000, 2000, 3000, 4000]


def _iv(v, default=0) -> int:
    """Plain int from a value that may be a {a,b,c} struct in 2.0x tables."""
    if v is None:
        return default
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, dict):
        for k in ("a", "value", "v"):
            if k in v and isinstance(v[k], (int, float)):
                return int(v[k])
        nums = [x for x in v.values() if isinstance(x, (int, float))]
        return int(nums[0]) if nums else default
    return default


def _abc(v: int) -> dict:
    return {"a": v, "b": v, "c": v}


def _m_no_cooldown(t):
    n = 0
    for it in t["iteminfo"]:
        # milliseconds; 0 crashes the game. Only ever lowered.
        target = 8000 if "kuku" in (it.get("string_key") or "").lower() else 1000
        if _iv(it.get("cooltime")) > target:
            it["cooltime"] = _abc(target)
            n += 1
    return n


def _m_max_charges(t):
    n = 0
    for it in t["iteminfo"]:
        if _iv(it.get("item_charge_type")) == 0 and 0 < _iv(it.get("max_charged_useable_count")) != 99:
            it["max_charged_useable_count"] = _abc(99)
            n += 1
    return n


def _m_max_stacks(t):
    n = 0
    for it in t["iteminfo"]:
        if 1 < _iv(it.get("max_stack_count")) != 999999:
            it["max_stack_count"] = 999999
            n += 1
    return n


def _m_inf_durability(t):
    n = 0
    for it in t["iteminfo"]:
        if 0 < _iv(it.get("max_endurance")) != 65535:
            it["max_endurance"] = 65535
            it["is_destroy_when_broken"] = 0
            n += 1
    return n


def _m_make_dyeable(t):
    n = 0
    for it in t["iteminfo"]:
        if it.get("equip_type_info") and not _iv(it.get("is_dyeable")):
            it["is_dyeable"] = 1
            it["is_editable_grime"] = 1
            n += 1
    return n


def _m_five_sockets(t):
    """Extend items that already have sockets to 5 (the path confirmed in game)."""
    n = 0
    for it in t["iteminfo"]:
        ddd = it.get("drop_default_data")
        if not ddd or not ddd.get("use_socket"):
            continue
        cur = list(ddd.get("add_socket_material_item_list") or [])
        if not cur or len(cur) >= 5:
            continue
        while len(cur) < 5:
            cur.append({"item": 1, "value": SOCKET_COSTS[len(cur)]})
        ddd["add_socket_material_item_list"] = cur
        ddd["socket_valid_count"] = 5
        n += 1
    return n


def _m_unlock_abyss(t):
    n = 0
    for it in t["iteminfo"]:
        if "AbyssGear" in (it.get("string_key") or "") and _iv(it.get("equipable_hash")) != 0:
            it["equipable_hash"] = 0
            n += 1
    return n


def _m_universal_prof(t):
    n = 0
    for it in t["iteminfo"]:
        if not it.get("equip_type_info"):
            continue
        for pd in it.get("prefab_data_list") or []:
            if pd.get("tribe_gender_list"):
                pd["tribe_gender_list"] = []
                n += 1
    # equip slots: every player character accepts what any of them accepts
    recs = [r for r in t["equipslotinfo"] if r.get("key") in PLAYER_CHAR_KEYS]
    pool: Dict[int, Set[int]] = {}
    for r in recs:
        for e in r.get("entries") or []:
            pool.setdefault(e["slot_index"], set()).update(e["etl_hashes"])
    for r in recs:
        for e in r.get("entries") or []:
            add = sorted(pool.get(e["slot_index"], set()) - set(e["etl_hashes"]))
            if add:
                e["etl_hashes"].extend(add)
                n += 1
    return n


def _m_infinite_stamina(t):
    n = 0
    for sk in t["skill"]:
        for lk in ("use_resource_stat_list", "use_driver_resource_stat_list"):
            for r in sk.get(lk) or []:
                if isinstance(r, dict) and r.get("d", 0) != 0:
                    r["d"] = 0
                    n += 1
    return n


def _m_mounts_in_towns(t):
    n = 0
    for r in t["regioninfo"]:
        for f in ("is_town", "is_wild", "limit_vehicle_run"):
            if r.get(f):
                r[f] = 0
                n += 1
    for c in t["characterinfo"]:
        if not c.get("vehicle_info"):
            continue
        if 0 < _iv(c.get("call_mercenary_spawn_duration")) != 0x7FFFFFFF:
            c["call_mercenary_spawn_duration"] = 0x7FFFFFFF
            n += 1
        if _iv(c.get("call_mercenary_cool_time")) > 0:
            c["call_mercenary_cool_time"] = 0
            n += 1
    return n


def _m_npcs_killable(t):
    n = 0
    for c in t["characterinfo"]:
        if c.get("vehicle_info") or (c.get("string_key") or "").startswith("Riding_"):
            continue
        if c.get("key") in PLAYER_CHAR_KEYS:
            continue
        if c.get("of_origin_invincibility"):
            c["of_origin_invincibility"] = 0
            n += 1
        if c.get("of_origin_is_attackable") == 0:
            c["of_origin_is_attackable"] = 1
            n += 1
    return n


_DROP_FULL = 1_000_000                # 100 % in 2.0x drop tables


def _drops(t, multiplier: Optional[int]):
    n = 0
    for d in t["dropsetinfo"]:
        for item in d.get("list") or []:
            old = item.get("raw_16", 0)
            if not isinstance(old, int) or not 0 < old < _DROP_FULL:
                continue
            new = _DROP_FULL if multiplier is None else min(old * multiplier, _DROP_FULL)
            if new != old:
                item["raw_16"] = new
                n += 1
    return n


def _m_merc_max(t):
    n = 0
    for r in t["mercenaryinfo"]:
        sc = r.get("default_limit_summon_count")
        if isinstance(sc, int) and 0 < sc < 9999:
            r["default_limit_summon_count"] = 9999
            n += 1
        hc = r.get("default_limit_hire_count")
        if isinstance(hc, int) and 0 < hc < 0xFFFFFFFF:
            r["default_limit_hire_count"] = 0xFFFFFFFF
            n += 1
    return n


def _m_speed_3x(t):
    n = 0
    for r in t["statusinfo"]:
        if r.get("string_key") in ("AttackSpeedRate", "MoveSpeedRate"):
            sdl = r.get("stat_level_data")
            if isinstance(sdl, list):
                for i, v in enumerate(sdl):
                    if isinstance(v, int) and v > 0:
                        sdl[i] = v * 3
                        n += 1
    return n


def _m_hard_2x_hp(t):
    """Hard difficulty adds +15 % HP to enemies and +50 % to bosses; double it."""
    n = 0
    for r in t["buffinfo"]:
        if r.get("string_key") not in ("BuffLevel_Difficulty", "BuffLevel_Difficulty_Boss"):
            continue
        for bd in r.get("buff_data_list") or []:
            var = (bd.get("data") or {}).get("variant") or {}
            body = var.get("body") or {}
            if var.get("type") == "VaryStatMaxValueRateBuffData" and body.get("f00") == 0:
                v = body.get("f01")
                if isinstance(v, int) and 0 < v < 2 ** 31:
                    body["f01"] = v * 2
                    n += 1
    return n


def _m_store_max_stock(t):
    n = 0
    for s in t["storeinfo"]:
        for st in s.get("stock_data_list") or []:
            if isinstance(st.get("raw_c"), int) and st["raw_c"] != 999999:
                st["raw_c"] = 999999
                n += 1
    return n


def _bag(t, character_slots: int):
    n = 0
    for r in t["inventory"]:
        name = r.get("string_key")
        if name == "Character":
            want = (character_slots, max(700, _iv(r.get("max_slot_count"))))
        elif name in ("CampWareHouse", "WareHouse", "Bank"):
            want = (700, max(700, _iv(r.get("max_slot_count"))))
        else:
            continue
        if (r.get("default_slot_count"), r.get("max_slot_count")) != want:
            r["default_slot_count"], r["max_slot_count"] = want
            n += 1
    return n


REFINE_TOOL = 28001                   # crafttoolinfo CraftTool_Enchant = refinement
THIEF_GLOVES = "ThiefGloves"          # iteminfo string_key, 30 min cooldown in vanilla


def _m_refine_cost_1(t):
    """Refinement recipes: every material amount above 1 becomes 1 (all levels)."""
    n = 0
    for r in t["multichangeinfo"]:
        if r.get("craft_tool_info") != REFINE_TOOL:
            continue
        for m in (r.get("fixed_material_data_list") or []) + (r.get("recipe_item_group_info_list") or []):
            if isinstance(m.get("count"), int) and m["count"] > 1:
                m["count"] = 1
                n += 1
    return n


def _m_thief_gloves_no_cd(t):
    n = 0
    for it in t["iteminfo"]:
        if it.get("string_key") == THIEF_GLOVES and _iv(it.get("cooltime")) > 1000:
            it["cooltime"] = _abc(1000)            # 1 s; 0 crashes the game
            n += 1
    return n


def _m_gift_trust_5x(t):
    """Trust an NPC gives for a gift (characterinfo friendly item data) x5."""
    n = 0
    for c in t["characterinfo"]:
        for g in c.get("character_friendly_item_data_list") or []:
            v = g.get("reward_friendly")
            if isinstance(v, int) and 0 < v < 2 ** 40:
                g["reward_friendly"] = v * 5
                n += 1
    return n


MOD_FUNCS: Dict[str, Callable] = {
    "no_cooldown": _m_no_cooldown,
    "max_charges": _m_max_charges,
    "max_stacks": _m_max_stacks,
    "inf_durability": _m_inf_durability,
    "make_dyeable": _m_make_dyeable,
    "five_sockets": _m_five_sockets,
    "unlock_abyss": _m_unlock_abyss,
    "universal_prof": _m_universal_prof,
    "infinite_stamina": _m_infinite_stamina,
    "mounts_in_towns": _m_mounts_in_towns,
    "npcs_killable": _m_npcs_killable,
    "drop_5x": lambda t: _drops(t, 5),
    "drop_max": lambda t: _drops(t, None),
    "merc_max": _m_merc_max,
    "speed_3x": _m_speed_3x,
    "hard_2x_hp": _m_hard_2x_hp,
    "store_max_stock": _m_store_max_stock,
    "bagspace_240": lambda t: _bag(t, 240),
    "bagspace_700": lambda t: _bag(t, 700),
    "refine_cost_1": _m_refine_cost_1,
    "thief_gloves_no_cd": _m_thief_gloves_no_cd,
    "gift_trust_5x": _m_gift_trust_5x,
}


# ── reading and writing tables ───────────────────────────────────────────

def _papgt_path(gp: str) -> str:
    return os.path.join(gp, "meta", "0.papgt")


def _pamt_files(dmm, gp: str, group: str) -> Set[str]:
    try:
        p = dmm.parse_pamt_file(os.path.join(gp, group, "0.pamt"))
    except Exception:  # noqa: BLE001
        return set()
    return {f["name"].lower() for d in p["directories"] for f in d["files"]}


def source_group(dmm, gp: str, stem: str, cache: Optional[dict] = None) -> str:
    """The group the game currently takes this table from: the first entry of
    the papgt that has it. Overlays (DMM, GMT, ...) sit in front of the
    game's own groups; ours is ignored. Unmodded tables live in 0008."""
    body = f"{stem}.staticinfobody"
    cache = {} if cache is None else cache
    try:
        entries = dmm.parse_papgt_file(_papgt_path(gp))["entries"]
    except Exception:  # noqa: BLE001
        return "0008"
    for e in entries:
        g = e["group_name"]
        if g == GROUP:
            continue
        if g.isdigit() and int(g) <= 40:          # the game's own groups
            if g == "0008":
                return "0008"
            continue
        if g not in cache:
            cache[g] = (_pamt_files(dmm, gp, g)
                        if os.path.isfile(os.path.join(gp, g, "0.pamt")) else set())
        if body in cache[g]:
            return g
    return "0008"


def _read(dmm, gp: str, group: str, stem: str):
    body = bytes(dmm.extract_file(gp, group, TABLE_DIR, f"{stem}.pabgb"))
    try:
        head = bytes(dmm.extract_file(gp, group, TABLE_DIR, f"{stem}.pabgh"))
    except Exception:  # noqa: BLE001 - some tables have no index
        head = None
    return body, head


def _serialize(dmm, stem: str, recs: list, head: Optional[bytes]) -> Tuple[bytes, Optional[bytes]]:
    if stem == "iteminfo":
        # iteminfo is not pabgh-bounded for the serializer: build the index
        # (u16 count, then key u32 + offset u32 per record, in index order).
        body = bytearray()
        offs = {}
        for it in recs:
            offs[int(it["key"])] = len(body)
            body += bytes(dmm.serialize_table("iteminfo", [it]))
        count = struct.unpack_from("<H", head, 0)[0]
        keys = [struct.unpack_from("<I", head, 2 + i * 8)[0] for i in range(count)]
        new_head = bytearray(struct.pack("<H", count))
        for k in keys:
            new_head += struct.pack("<II", k, offs[k])
        return bytes(body), bytes(new_head)
    name = _SERIALIZE_NAME.get(stem, stem)
    try:
        out = dmm.serialize_table(name, recs, None, head)
    except ValueError as e:
        if "not pabgh-bounded" not in str(e):
            raise
        return bytes(dmm.serialize_table(name, recs)), head
    if isinstance(out, tuple):
        return bytes(out[0]), bytes(out[1])
    return bytes(out), head


class _Tables(dict):
    """Loads a table on first use, after checking the parser writes it back
    byte for byte."""

    def __init__(self, dmm, gp: str, progress):
        super().__init__()
        self.dmm, self.gp, self.progress = dmm, gp, progress
        self.head: Dict[str, Optional[bytes]] = {}
        self.src: Dict[str, str] = {}
        self._pamt_cache: dict = {}

    def __missing__(self, stem):
        grp = source_group(self.dmm, self.gp, stem, self._pamt_cache)
        log.info("Simple: %s taken from group %s", stem, grp)
        self.progress(f"Reading {stem}" + (f" (from {grp})" if grp != "0008" else "") + "...")
        body, head = _read(self.dmm, self.gp, grp, stem)
        recs = self.dmm.parse_table(stem, body, head)
        b2, h2 = _serialize(self.dmm, stem, recs, head)
        if b2 != body or (head is not None and h2 != head):
            raise RefusedError(
                f"The bundled parser does not read and write '{stem}' back correctly for this "
                f"game version. Changing it could damage the game data, so this switch is "
                f"blocked until the tool is updated.")
        self.head[stem], self.src[stem] = head, grp
        self[stem] = recs
        return recs


# ── papgt ────────────────────────────────────────────────────────────────

def _rebuild_papgt(dmm, template: dict, entries: list) -> dict:
    p = dict(template)
    p["entries"] = []
    for e in reversed(entries):
        p = dmm.add_papgt_entry(p, e["group_name"], e["pack_meta_checksum"],
                                e["is_optional"], e["language"])
    return p


def _write_papgt(dmm, gp: str, entries: list) -> None:
    path = _papgt_path(gp)
    tpl = dmm.parse_papgt_file(path)
    new = _rebuild_papgt(dmm, tpl, entries)
    tmp = path + ".cgms_tmp"
    dmm.write_papgt_file(new, tmp)
    dmm.parse_papgt_file(tmp)            # must read back
    os.replace(tmp, path)


# ── public API ───────────────────────────────────────────────────────────

# Multipliers change the value again every time they run, so "nothing left
# to change" cannot be checked for them.
_NOT_VERIFIABLE = {"drop_5x", "speed_3x", "hard_2x_hp", "gift_trust_5x"}


def verify(gp: str, progress: Callable[[str], None] = lambda m: None, dmm=None) -> Dict[str, str]:
    """Check the installed Simple tables: run every installed switch once more
    on them. A switch that is really in the game files finds nothing left to
    change. Changes nothing on disk. Returns mod id -> short result text."""
    if dmm is None:
        import dmm_parser as dmm  # noqa: PLC0415
    mark = installed(gp) or {}
    out: Dict[str, str] = {}
    tables: Dict[str, list] = {}
    for mid in mark.get("mods", []):
        if mid not in MOD_FUNCS:
            out[mid] = "unknown mod"
            continue
        if mid in _NOT_VERIFIABLE:
            out[mid] = "not checkable (multiplier)"
            continue
        try:
            for stem in MOD_TABLES[mid]:
                if stem not in tables:
                    progress(f"Checking {stem}...")
                    tables[stem] = dmm.parse_table(stem, *_read(dmm, gp, GROUP, stem))
            left = MOD_FUNCS[mid](tables)
            out[mid] = ("OK - in the game files" if left == 0
                        else f"NOT COMPLETE - {left} values still unchanged")
        except Exception as e:  # noqa: BLE001
            out[mid] = f"check failed: {type(e).__name__}: {e}"[:200]
    return out


def installed(gp: str) -> Optional[dict]:
    """Marker of the current install, or None."""
    try:
        with open(os.path.join(gp, GROUP, MARKER), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def health(gp: str, dmm=None) -> Tuple[str, str]:
    """('ok'|'none'|'stale', explanation) - is our install still active?"""
    if dmm is None:
        import dmm_parser as dmm  # noqa: PLC0415
    from game_version import read_game_version  # noqa: PLC0415
    mark = installed(gp)
    in_papgt = False
    try:
        in_papgt = any(e["group_name"] == GROUP
                       for e in dmm.parse_papgt_file(_papgt_path(gp))["entries"])
    except Exception:  # noqa: BLE001
        pass
    if not mark and not in_papgt:
        return "none", "No Simple mods installed."
    if not mark or not in_papgt:
        return "stale", ("Simple's mods are no longer active (the game or another mod manager "
                         "rewrote the pack list). Apply again to restore them.")
    ver = read_game_version(gp) or "?"
    if mark.get("game_version") != ver:
        return "stale", (f"The game was updated ({mark.get('game_version')} -> {ver}). "
                         "Apply again so the mods are rebuilt on the new game files.")
    # Simple copied these tables from other mods (DMM ...) or the game. If one
    # of those changed since, our copy is out of date and hides the change.
    try:
        now = {e["group_name"]: e["pack_meta_checksum"]
               for e in dmm.parse_papgt_file(_papgt_path(gp))["entries"]}
    except Exception:  # noqa: BLE001
        now = {}
    changed = sorted({g for g, c in (mark.get("source_checksums") or {}).items()
                      if now.get(g) != c})
    moved = sorted({t for t, g in (mark.get("sources") or {}).items()
                    if source_group(dmm, gp, t) != g})
    if changed or moved:
        return "stale", ("Your other mods (for example in DMM) changed since Simple was applied. "
                         "Apply again so Simple builds on the current state - until then the "
                         "Simple tables hide those changes.")
    return "ok", f"{len(mark.get('mods', []))} mod(s) active for game {ver}."


def foreign_overlays(gp: str, stems: Set[str], dmm=None) -> Dict[str, List[str]]:
    """Other overlays (DMM etc.) that also change these tables."""
    if dmm is None:
        import dmm_parser as dmm  # noqa: PLC0415
    out: Dict[str, List[str]] = {}
    try:
        entries = dmm.parse_papgt_file(_papgt_path(gp))["entries"]
    except Exception:  # noqa: BLE001
        return out
    for e in entries:
        g = e["group_name"]
        if g == GROUP or (g.isdigit() and int(g) <= 40):
            continue
        files = _pamt_files(dmm, gp, g)
        hit = sorted(s for s in stems if f"{s}.staticinfobody" in files)
        if hit:
            out[g] = hit
    return out


def apply(gp: str, active: Set[str], progress: Callable[[str], None] = lambda m: None,
          dmm=None) -> dict:
    """Build every active switch and install the result. Returns a report."""
    if dmm is None:
        import dmm_parser as dmm  # noqa: PLC0415
    from game_version import read_game_version  # noqa: PLC0415
    active = {m for m in active if m in MOD_FUNCS}
    if not active:
        remove(gp, progress, dmm)
        return {"mods": {}, "tables": [], "removed": True}

    log.info("Simple: apply %s to %s", sorted(active), gp)
    tables = _Tables(dmm, gp, progress)
    counts: Dict[str, int] = {}
    for mid in sorted(active):
        for stem in MOD_TABLES[mid]:
            tables[stem]                    # load + roundtrip check first
        progress(f"Applying {mid}...")
        counts[mid] = MOD_FUNCS[mid](tables)
        log.info("Simple: %s changed %d values", mid, counts[mid])

    files: List[Tuple[str, bytes]] = []
    for stem, recs in tables.items():
        progress(f"Writing {stem}...")
        body, head = _serialize(dmm, stem, recs, tables.head[stem])
        chk = dmm.parse_table(stem, body, head)          # the result must read back
        if len(chk) != len(recs):
            raise RefusedError(f"'{stem}' did not read back after the change - nothing was installed.")
        files.append((f"{stem}.pabgb", body))
        if head is not None:
            files.append((f"{stem}.pabgh", head))

    progress("Installing...")
    papgt_now = {e["group_name"]: e["pack_meta_checksum"]
                 for e in dmm.parse_papgt_file(_papgt_path(gp))["entries"]}
    final = os.path.join(gp, GROUP)
    with tempfile.TemporaryDirectory() as tmp:
        gdir = os.path.join(tmp, GROUP)
        b = dmm.PackGroupBuilder(output_dir=gdir, compression=int(dmm.Compression.LZ4),
                                 crypto=int(dmm.Crypto.NONE), encrypt_info=b"\x00\x00\x00",
                                 max_chunk_size=500_000_000)
        for name, data in files:
            b.add_file(TABLE_DIR, name, data)
        pamt = bytes(b.finish())
        checksum = dmm.calculate_checksum(pamt[12:])

        papgt = _papgt_path(gp)
        backup = os.path.join(gp, "meta", PAPGT_BACKUP)
        if not os.path.isfile(backup):
            shutil.copy2(papgt, backup)

        staging = final + ".new"
        if os.path.isdir(staging):
            shutil.rmtree(staging)
        shutil.copytree(gdir, staging)
        marker = {
            "engine": ENGINE_VERSION,
            "game_version": read_game_version(gp) or "?",
            "mods": sorted(active),
            "tables": sorted(tables.keys()),
            "sources": tables.src,
            "source_checksums": {g: papgt_now.get(g) for g in set(tables.src.values())},
            "changes": counts,
            "when": time.strftime("%Y-%m-%d %H:%M"),
        }
        with open(os.path.join(staging, MARKER), "w", encoding="utf-8") as f:
            json.dump(marker, f, indent=1)
        old = final + ".old"
        if os.path.isdir(old):
            shutil.rmtree(old)
        if os.path.isdir(final):
            os.replace(final, old)
        os.replace(staging, final)
        try:
            entries = [e for e in dmm.parse_papgt_file(papgt)["entries"] if e["group_name"] != GROUP]
            entries.insert(0, {"group_name": GROUP, "pack_meta_checksum": checksum,
                               "is_optional": 0, "language": 0x3FFF})
            _write_papgt(dmm, gp, entries)
        except Exception:
            shutil.rmtree(final, ignore_errors=True)
            if os.path.isdir(old):
                os.replace(old, final)
            raise
        shutil.rmtree(old, ignore_errors=True)
    log.info("Simple: installed %s", marker)
    return {"mods": counts, "tables": sorted(tables.keys()), "sources": tables.src}


def remove(gp: str, progress: Callable[[str], None] = lambda m: None, dmm=None) -> bool:
    """Remove Simple's group and papgt entry. Other entries stay untouched."""
    if dmm is None:
        import dmm_parser as dmm  # noqa: PLC0415
    progress("Removing Simple's mods...")
    log.info("Simple: remove from %s", gp)
    changed = False
    try:
        entries = dmm.parse_papgt_file(_papgt_path(gp))["entries"]
        if any(e["group_name"] == GROUP for e in entries):
            _write_papgt(dmm, gp, [e for e in entries if e["group_name"] != GROUP])
            changed = True
    except FileNotFoundError:
        pass
    d = os.path.join(gp, GROUP)
    if os.path.isdir(d):
        shutil.rmtree(d)
        changed = True
    return changed
