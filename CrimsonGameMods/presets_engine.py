"""Presets engine - one-click value mods as Field JSON intents (no Qt).

Each preset turns into intents on the unmodded game table (group 0008).
build_targets() checks every intent with DMM's own apply_intents; the
results are used for Export Field JSON and for Apply to Game.
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Tuple

TABLE_DIR = "gamedata/binary__/client/bin"
DEFAULT_GROUP = 74
MARKER = ".cgm_presets"
REFINE_TOOL = 28001            # crafttoolinfo CraftTool_Enchant = refinement


# ── presets: vanilla records -> intents ─────────────────────────────────

def _refine_cost_1(recs: list, _param) -> List[dict]:
    out = []
    for r in recs:
        if r.get("craft_tool_info") != REFINE_TOOL:
            continue
        for i, m in enumerate(r.get("fixed_material_data_list") or []):
            if isinstance(m.get("count"), int) and m["count"] > 1:
                out.append({"entry": r.get("string_key", ""), "key": r.get("key", 0),
                            "field": f"fixed_material_data_list[{i}].count",
                            "op": "set", "new": 1})
        for i, m in enumerate(r.get("recipe_item_group_info_list") or []):
            if isinstance(m.get("count"), int) and m["count"] > 1:
                out.append({"entry": r.get("string_key", ""), "key": r.get("key", 0),
                            "field": f"recipe_item_group_info_list[{i}].count",
                            "op": "set", "new": 1})
    return out


def _gift_trust(recs: list, factor) -> List[dict]:
    factor = int(factor or 5)
    out = []
    for r in recs:
        for i, g in enumerate(r.get("character_friendly_item_data_list") or []):
            v = g.get("reward_friendly")
            if isinstance(v, int) and 0 < v < 2 ** 40:
                out.append({"entry": r.get("string_key", ""), "key": r.get("key", 0),
                            "field": f"character_friendly_item_data_list[{i}].reward_friendly",
                            "op": "set", "new": v * factor})
    return out


# Rarity Matters: item_tier 1 Common ... 5 Legendary -> factor on attack/defense.
# Level 1-10: Legendary +5 % per level, the other tiers get a share of that
# (level 10 = Uncommon +10 %, Rare +20 %, Epic +35 %, Legendary +50 %).
RARITY_SHARES = {2: 0.2, 3: 0.4, 4: 0.7, 5: 1.0}
RARITY_LEVELS = list(range(1, 11))
RARITY_STEP = 5                                                  # % for Legendary per level
RARITY_OLD_NAMES = {"Mild": 25, "Normal": 50, "Strong": 100}     # earlier versions: % for Legendary


RARITY_MODES = ("stronger", "harder")


def rarity_param(param):
    """(mode, level) from what a preset/page passes: a level (1-10), an old
    name, ("harder", 5) or {"mode": .., "level": ..}."""
    if isinstance(param, dict):
        return (param.get("mode") or "stronger"), param.get("level", 5)
    if isinstance(param, (tuple, list)) and len(param) == 2:
        return (param[0] or "stronger"), param[1]
    return "stronger", (5 if param is None else param)


def rarity_factors(level, mode: str = "stronger") -> Dict[int, float]:
    """item_tier -> factor on attack/defense.
    stronger: Legendary +p %, Epic/Rare/Uncommon 70/40/20 % of that, Common stays.
    harder:   the same gaps, but Legendary stays vanilla and the rest goes down
              (Common too, else it would end up above Uncommon)."""
    if level in RARITY_OLD_NAMES:
        pct = float(RARITY_OLD_NAMES[level])
    else:
        try:
            lv = float(level)
        except (TypeError, ValueError):
            lv = 5.0
        pct = min(10.0, max(1.0, lv)) * RARITY_STEP
    up = {t: 1.0 + sh * pct / 100.0 for t, sh in RARITY_SHARES.items()}
    if mode != "harder":
        return up
    top = up[5]
    down = {1: 1.0 / top}
    down.update({t: f / top for t, f in up.items() if t != 5})
    return down


RARITY_STATS = (1000002, 1000003)        # DDD attack, DPV defense (statusinfo)


def _rarity_matters(recs: list, param) -> List[dict]:
    mode, level = rarity_param(param)
    factors = rarity_factors(level, mode)
    out = []
    for r in recs:
        f = factors.get(r.get("item_tier") or 0)
        if not f:
            continue
        for i, e in enumerate(r.get("enchant_data_list") or []):
            statics = (e.get("enchant_stat_data") or {}).get("stat_list_static") or []
            for j, s in enumerate(statics):
                v = s.get("change_mb")
                if s.get("stat") in RARITY_STATS and isinstance(v, int) and v > 0:
                    out.append({"entry": r.get("string_key", ""), "key": r.get("key", 0),
                                "field": f"enchant_data_list[{i}].enchant_stat_data."
                                         f"stat_list_static[{j}].change_mb",
                                "op": "set", "new": int(round(v * f))})
    return out


PRESETS = [
    {"id": "refine_cost_1", "table": "multichangeinfo", "fn": _refine_cost_1,
     "title": "Refinement Costs 1",
     "desc": "Refining gear needs only 1 of each material, at every refinement level."},
    {"id": "gift_trust", "table": "characterinfo", "fn": _gift_trust,
     "title": "More Trust from Gifts",
     "desc": "Gifts to NPCs give more trust. Talking and quests are not changed.",
     "choices": [2, 5, 10, 20], "default": 5, "choice_label": "x"},
    {"id": "rarity_matters", "table": "iteminfo", "fn": _rarity_matters,
     "title": "Rarity Matters",
     "desc": "Rarer gear has more attack and defense at every refinement level, so a "
             "Legendary +10 beats a Common +10. Every rarity above Common gets stronger "
             "than vanilla: each level adds +5 % for Legendary and 70 % / 40 % / 20 % of "
             "that for Epic / Rare / Uncommon. Level 10: Uncommon +10 %, Rare +20 %, "
             "Epic +35 %, Legendary +50 %. Common stays. "
             "Includes the DLC items (skipped by DMM without the DLC).",
     "choices": RARITY_LEVELS, "default": 5,
     "choice_names": [f"Level {n} - up to +{n * RARITY_STEP} % over vanilla" for n in RARITY_LEVELS],
     "dlc_too": True, "hidden": True},          # has its own page (gui/tabs/rarity.py)
]


def build_targets(game_path: str, chosen: Dict[str, object],
                  progress: Callable[[str], None] = lambda m: None
                  ) -> List[Tuple[str, List[dict], dict]]:
    """[(table stem, intents, apply_intents result)] for the chosen presets
    (id -> parameter). Raises RuntimeError if an intent does not apply."""
    import dmm_parser
    by_table: Dict[str, List[dict]] = {}
    dlc_by_table: Dict[str, List[dict]] = {}
    cache: Dict[str, Tuple[bytes, Optional[bytes], list]] = {}
    for p in PRESETS:
        if p["id"] not in chosen:
            continue
        stem = p["table"]
        if stem not in cache:
            progress(f"Reading {stem}...")
            body = bytes(dmm_parser.extract_file(game_path, "0008", TABLE_DIR, f"{stem}.pabgb"))
            head = bytes(dmm_parser.extract_file(game_path, "0008", TABLE_DIR, f"{stem}.pabgh"))
            cache[stem] = (body, head, dmm_parser.parse_table(stem, body, head))
        by_table.setdefault(stem, []).extend(p["fn"](cache[stem][2], chosen[p["id"]]))
        if p.get("dlc_too"):
            dlc_by_table.setdefault(stem, []).extend(
                _dlc_only_intents(game_path, stem, cache[stem][2], p["fn"], chosen[p["id"]],
                                  progress))
    out = []
    for stem, intents in by_table.items():
        if not intents:
            continue
        progress(f"Checking {len(intents)} changes to {stem}...")
        body, head, _ = cache[stem]
        res = dmm_parser.apply_intents(stem, body, head, intents)
        bad = [o for o in res.get("outcomes") or [] if o.get("status") != "applied"]
        if bad:
            reason = bad[0].get("reason") or "unknown reason"
            raise RuntimeError(f"{stem}: {len(bad)} of {len(intents)} changes do not apply "
                               f"({reason}). Nothing was written.")
        # DLC-only records (already checked against the DLC table) ride in the
        # same target, as Edit items does; Apply to Game writes the base table.
        out.append((stem, intents + dlc_by_table.get(stem, []), res))
    return out


def _dlc_only_intents(game_path: str, stem: str, base_recs: list, fn, param,
                      progress: Callable[[str], None]) -> List[dict]:
    """The preset on the records only an installed DLC has, checked with
    apply_intents on the DLC's own table. Empty without a DLC."""
    import dmm_parser
    from item_db import _dlc_tables
    base_keys = {r.get("key") for r in base_recs}
    out: List[dict] = []
    for root, d, hname in _dlc_tables(dmm_parser, game_path, "0008", f"{stem}.",
                                      ".staticinfoheader"):
        bname = hname[:-len(".staticinfoheader")] + ".staticinfobody"
        progress(f"Reading {hname[:-len('.staticinfoheader')]}...")
        head = bytes(dmm_parser.extract_file(root, "0008", d, hname))
        body = bytes(dmm_parser.extract_file(root, "0008", d, bname))
        recs = [r for r in dmm_parser.parse_table(stem, body, head)
                if r.get("key") not in base_keys]
        intents = fn(recs, param)
        if not intents:
            continue
        progress(f"Checking {len(intents)} changes to DLC items...")
        res = dmm_parser.apply_intents(stem, body, head, intents)
        bad = [o for o in res.get("outcomes") or [] if o.get("status") != "applied"]
        if bad:
            reason = bad[0].get("reason") or "unknown reason"
            raise RuntimeError(f"{stem} (DLC): {len(bad)} of {len(intents)} changes do not "
                               f"apply ({reason}). Nothing was written.")
        out.extend(intents)
        base_keys |= {r.get("key") for r in recs}
    return out


def other_overlays_with(game_path: str, stems, our_group: str) -> Dict[str, List[str]]:
    """table -> overlay groups (DMM, other tools) that also carry it."""
    from overlay_coordinator import is_game_data_group, _pamt_contains_file
    import dmm_parser
    found: Dict[str, List[str]] = {}
    try:
        entries = dmm_parser.parse_papgt_file(os.path.join(game_path, "meta", "0.papgt"))["entries"]
    except Exception:  # noqa: BLE001
        return found
    for e in entries:
        g = e.get("group_name", "")
        if g == our_group or is_game_data_group(game_path, g):
            continue
        pamt = os.path.join(game_path, g, "0.pamt")
        for stem in stems:
            if os.path.isfile(pamt) and _pamt_contains_file(pamt, f"{stem}."):
                found.setdefault(stem, []).append(g)
    return found
