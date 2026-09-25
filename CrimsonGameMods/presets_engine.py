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


PRESETS = [
    {"id": "refine_cost_1", "table": "multichangeinfo", "fn": _refine_cost_1,
     "title": "Refinement Costs 1",
     "desc": "Refining gear needs only 1 of each material, at every refinement level."},
    {"id": "gift_trust", "table": "characterinfo", "fn": _gift_trust,
     "title": "More Trust from Gifts",
     "desc": "Gifts to NPCs give more trust. Talking and quests are not changed.",
     "choices": [2, 5, 10, 20], "default": 5, "choice_label": "x"},
]


def build_targets(game_path: str, chosen: Dict[str, object],
                  progress: Callable[[str], None] = lambda m: None
                  ) -> List[Tuple[str, List[dict], dict]]:
    """[(table stem, intents, apply_intents result)] for the chosen presets
    (id -> parameter). Raises RuntimeError if an intent does not apply."""
    import dmm_parser
    by_table: Dict[str, List[dict]] = {}
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
        out.append((stem, intents, res))
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
