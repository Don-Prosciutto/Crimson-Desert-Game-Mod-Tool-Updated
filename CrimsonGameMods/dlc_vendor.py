"""Groups of the items only a DLC has, for the Stores tab's "DLC Vendor".

The groups come from each item's category_info / item_type in the DLC's
iteminfo table (2.04.05, "Charting the Unknown"). Quest papers, letters,
posters, maps, survey records, trade cargo, furniture and food are left out.
No Qt in here.
"""

from __future__ import annotations

import copy
import logging
from typing import Dict, List

log = logging.getLogger(__name__)

SILVER = 1  # currency item key of Silver

# (id, label) in the order the dialog shows them
GROUPS = [
    ("weapons", "Weapons"),
    ("armor", "Armor & accessories"),
    ("resources", "Crafting & refining materials"),
    ("blueprints", "Blueprints"),
    ("abyss", "Abyss gears"),
    ("recipes", "Cooking recipes"),
    ("sealed", "Sealed abyss artifacts"),
    ("ship", "Ship & mount parts"),
]

_MATERIAL_KEYS_4001 = ("snakerelic_", "Leviathan_Scale", "Destroyed_Mechanism",
                       "Enhanced_HandCannon_")


def group_of(item: dict) -> str:
    """Group id of an item, or "" when it belongs to none."""
    c = int(item.get("category_info") or 0)
    t = int(item.get("item_type") or 0)
    sk = str(item.get("string_key") or "")
    if 100 <= c < 400:
        return "weapons"
    if 400 <= c < 700 or c in (1112, 1113, 1114, 1201):
        return "armor"
    if c == 2501:
        return "abyss"
    if c == 12001:
        return "recipes"
    if c == 3201 and t == 4:
        return "sealed"
    if c == 1102:
        return "ship"
    if (c == 3201 and t == 31) or c in (3601, 3701, 60002, 60007):
        return "resources"
    if c == 4001 and t == 42:
        if sk.startswith(_MATERIAL_KEYS_4001):
            return "resources"
        if sk.startswith(("Recipe_", "Paper_Enhanced")):
            return "blueprints"
        return ""
    if c == 4001 and t == 43:
        return "blueprints"
    if c == 28001 and t == 54 and "Recipe" in sk:
        return "blueprints"
    return ""


def dlc_items(game_path: str) -> List[dict]:
    """The iteminfo records only an installed DLC has."""
    import dmm_parser
    from item_db import _dlc_tables, dlc_only_item_keys
    only = dlc_only_item_keys(game_path)
    out, seen = [], set()
    for root, d, name in _dlc_tables(dmm_parser, game_path, "0008",
                                     "iteminfo.", ".staticinfobody"):
        try:
            recs = dmm_parser.parse_iteminfo_from_bytes(
                bytes(dmm_parser.extract_file(root, "0008", d, name)))
        except Exception as exc:  # noqa: BLE001
            log.warning("DLC iteminfo %s not readable: %s", root, exc)
            continue
        for r in recs:
            k = int(r.get("key") or 0)
            if k in only and k not in seen:
                seen.add(k)
                out.append(r)
    return out


def grouped(items: List[dict]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {g: [] for g, _ in GROUPS}
    for it in items:
        g = group_of(it)
        if g:
            out[g].append(it)
    return out


def price_list_with(item: dict, currency: int, price: int) -> list:
    """The item's price_list with `price` in `currency` (added if missing)."""
    pl = copy.deepcopy(item.get("price_list") or [])
    for p in pl:
        if int(p.get("key") or 0) == currency:
            p.setdefault("price", {})["price"] = int(price)
            return pl
    pl.append({"key": int(currency),
               "price": {"price": int(price), "sym_no": 0, "item_info_wrapper": int(currency)}})
    return pl
