"""Live-derived analytics over Potter's parsed iteminfo dicts.

Built from the in-memory `_buff_rust_items` list, so no external dump file
required — the index is just a cached set of lookups computed once after
each iteminfo extraction.

Used by the ItemBuffs tab for: category filters, "find similar items",
gimmick-user preview, imbue-coverage report, data-driven stat presets,
JSON-edit validation, and item diff.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Any, Iterable, Optional

log = logging.getLogger(__name__)


CATEGORY_LABEL_OVERRIDES: dict[int, str] = {
    202: "TwoHandSword",
    205: "TwoHandSpear",
    304: "OneHandBow",
}


_USELESS_SUFFIXES = {
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "Item", "Items", "Mat", "Material",
}


def _common_suffix(string_keys: Iterable[str]) -> str:
    """Return the most common meaningful suffix for a category.

    Walks string_key parts right-to-left, skipping pure digits, roman
    numerals, and other useless tail tokens, until it finds something
    descriptive (Sword, Bow, Necklace, etc.).
    """
    suffixes: Counter = Counter()
    for sk in string_keys:
        parts = [p for p in (sk or "").split("_") if p]
        for part in reversed(parts):
            if part.isdigit():
                continue
            if part in _USELESS_SUFFIXES:
                continue
            if len(part) <= 1:
                continue
            suffixes[part] += 1
            break
    if not suffixes:
        return ""
    top, _ = suffixes.most_common(1)[0]
    return top


class IteminfoIndex:
    """Cached lookups over a list of parsed iteminfo dicts.

    Pass the live list in once after extraction; re-create when the user
    re-extracts. All queries are O(1) on prebuilt dicts.
    """

    def __init__(self, items: list[dict]):
        self.items = items
        self.by_key: dict[int, dict] = {it["key"]: it for it in items}

        self.category_counts: Counter = Counter()
        self.item_type_counts: Counter = Counter()
        self.tier_counts: Counter = Counter()
        self.equip_type_counts: Counter = Counter()

        # gimmick_info → [item dicts using it as their gimmick]
        self.gimmick_to_items: dict[int, list[dict]] = defaultdict(list)
        # passive skill id → [item dicts that have it in equip_passive_skill_list]
        self.passive_to_items: dict[int, list[dict]] = defaultdict(list)
        # buff id → [item dicts that have it in equip_buffs]
        self.buff_to_items: dict[int, list[dict]] = defaultdict(list)
        # equip_type_info → [item dicts] (weapon class hash → users)
        self.equip_type_to_items: dict[int, list[dict]] = defaultdict(list)
        # category_info → [item dicts]
        self.category_to_items: dict[int, list[dict]] = defaultdict(list)
        # item_type → [item dicts]
        self.item_type_to_items: dict[int, list[dict]] = defaultdict(list)

        # category_info → friendly label (derived from common suffix)
        self._category_labels: dict[int, str] = {}

        for it in items:
            cat = it.get("category_info") or 0
            it_type = it.get("item_type") or 0
            tier = it.get("item_tier") or 0
            eti = it.get("equip_type_info") or 0
            gi = it.get("gimmick_info") or 0

            self.category_counts[cat] += 1
            self.item_type_counts[it_type] += 1
            self.tier_counts[tier] += 1
            if eti:
                self.equip_type_counts[eti] += 1
                self.equip_type_to_items[eti].append(it)
            if gi:
                self.gimmick_to_items[gi].append(it)
            for p in (it.get("equip_passive_skill_list") or []):
                sid = p.get("skill")
                if sid:
                    self.passive_to_items[int(sid)].append(it)
            bl = set()
            for ed in it.get("enchant_data_list", []):
                for eb in ed.get("equip_buffs", []):
                    bid = eb.get("buff")
                    if bid:
                        bl.add(bid)
            for bid in bl:
                self.buff_to_items[bid].append(it)
            self.category_to_items[cat].append(it)
            self.item_type_to_items[it_type].append(it)

        log.info("Index built: %d items, %d passives, %d buffs",
                 len(items), len(self.passive_to_items), len(self.buff_to_items))

        # Derive friendly category labels from common string_key suffixes.
        for cat, group in self.category_to_items.items():
            if cat in CATEGORY_LABEL_OVERRIDES:
                self._category_labels[cat] = CATEGORY_LABEL_OVERRIDES[cat]
                continue
            label = _common_suffix(g.get("string_key", "") for g in group)
            self._category_labels[cat] = label or f"category_{cat}"

    # ── Lookups ─────────────────────────────────────────────────────────────

    def category_label(self, cat: int) -> str:
        return self._category_labels.get(cat, f"category_{cat}")

    def category_choices(self) -> list[tuple[int, str, int]]:
        """Sorted list of (category_id, label, count) for filter dropdowns."""
        out = []
        for cat, count in self.category_counts.most_common():
            out.append((cat, self.category_label(cat), count))
        return out

    def gimmick_users(self, gimmick_info: int, limit: int = 0) -> list[dict]:
        """Items that have this gimmick_info set."""
        users = self.gimmick_to_items.get(int(gimmick_info), [])
        return users[:limit] if limit else users

    def find_similar(self, item: dict, mode: str = "category") -> list[dict]:
        """Items 'similar' to the given one.

        mode in {category, equip_type, item_type, passives, buffs}.
        Excludes the input item itself.
        """
        key = item.get("key")
        if mode == "equip_type":
            eti = item.get("equip_type_info") or 0
            pool = self.equip_type_to_items.get(eti, []) if eti else []
        elif mode == "item_type":
            it_type = item.get("item_type") or 0
            pool = self.item_type_to_items.get(it_type, [])
        elif mode == "passives":
            psl = (item.get("equip_passive_skill_list") if item.get("equip_passive_skill_list") is not None else [])
            if not psl:
                return []
            seen: set[int] = set()
            pool = []
            for p in psl:
                pid = p.get("skill")
                if pid:
                    for it in self.passive_to_items.get(int(pid), []):
                        k = it.get("key")
                        if k and k not in seen:
                            seen.add(k)
                            pool.append(it)
        elif mode == "buffs":
            edl = item.get("enchant_data_list", [])
            if not edl:
                return []
            seen_b: set[int] = set()
            pool = []
            for b in edl[0].get("equip_buffs", []):
                bid = b.get("buff")
                if bid:
                    for it in self.buff_to_items.get(bid, []):
                        k = it.get("key")
                        if k and k not in seen_b:
                            seen_b.add(k)
                            pool.append(it)
        else:  # category
            cat = item.get("category_info") or 0
            pool = self.category_to_items.get(cat, [])
        return [it for it in pool if it.get("key") != key]

    # ── Imbue coverage ──────────────────────────────────────────────────────

    def imbue_coverage(
        self,
        skill_id: int,
        allowed_class_hashes: set[int],
        weapons: list[dict],
    ) -> dict[str, Any]:
        """Compute current vs after-imbue coverage for a skill across weapons.

        ``allowed_class_hashes`` = the class hashes the skill currently allows
        (extracted from skill.pabgb by the caller).

        Returns a dict with: weapon_count, weapons_with_passive,
        weapons_in_filter_now, weapons_in_filter_after, missing_class_hashes,
        and per-class breakdowns.
        """
        passive_keys = {
            it.get("key") for it in self.passive_to_items.get(int(skill_id), [])
        }
        weapon_count = len(weapons)
        with_passive = sum(1 for w in weapons if w.get("key") in passive_keys)
        in_filter_now = 0
        needed_classes: set[int] = set()
        for w in weapons:
            ch = int(w.get("equip_type_info") or 0)
            if ch and ch in allowed_class_hashes:
                in_filter_now += 1
            elif ch:
                needed_classes.add(ch)

        all_classes_after = allowed_class_hashes | needed_classes
        in_filter_after = sum(
            1 for w in weapons
            if int(w.get("equip_type_info") or 0) in all_classes_after
        )

        # Per-class breakdown — what classes are involved and how many items each
        per_class: dict[int, dict[str, Any]] = {}
        for w in weapons:
            ch = int(w.get("equip_type_info") or 0)
            if not ch:
                continue
            slot = per_class.setdefault(ch, {
                "count": 0,
                "currently_allowed": ch in allowed_class_hashes,
                "sample_string_key": w.get("string_key", ""),
            })
            slot["count"] += 1

        return {
            "weapon_count": weapon_count,
            "weapons_with_passive": with_passive,
            "weapons_in_filter_now": in_filter_now,
            "weapons_in_filter_after": in_filter_after,
            "missing_class_hashes": sorted(needed_classes),
            "per_class": per_class,
        }

    # ── Stat preset library ─────────────────────────────────────────────────

    def stat_template_for(
        self, item_type: int, item_tier: int,
    ) -> Optional[dict[str, Any]]:
        """Return a representative stat block (modal across cluster) for the
        given (item_type, item_tier) pair, or None if the cluster is empty.
        """
        cluster = [
            it for it in self.item_type_to_items.get(item_type, [])
            if (it.get("item_tier") or 0) == item_tier
        ]
        if not cluster:
            return None

        # Aggregate stat ids across the cluster's enchant data, count occurrences
        stat_static_counts: Counter = Counter()
        stat_level_counts: Counter = Counter()
        regen_counts: Counter = Counter()
        max_counts: Counter = Counter()
        buff_counts: Counter = Counter()
        n_with_enchants = 0
        for it in cluster:
            edl = it.get("enchant_data_list") or []
            if not edl:
                continue
            n_with_enchants += 1
            ed0 = edl[0]
            esd = ed0.get("enchant_stat_data") or {}
            for s in (esd.get("stat_list_static") or []):
                stat_static_counts[s.get("stat")] += 1
            for s in (esd.get("stat_list_static_level") or []):
                stat_level_counts[s.get("stat")] += 1
            for s in (esd.get("regen_stat_list") or []):
                regen_counts[s.get("stat")] += 1
            for s in (esd.get("max_stat_list") or []):
                max_counts[s.get("stat")] += 1
            for b in (ed0.get("equip_buffs") or []):
                buff_counts[b.get("buff")] += 1

        return {
            "cluster_size": len(cluster),
            "with_enchants": n_with_enchants,
            "common_stats_static": stat_static_counts.most_common(10),
            "common_stats_level": stat_level_counts.most_common(10),
            "common_regen_stats": regen_counts.most_common(10),
            "common_max_stats": max_counts.most_common(10),
            "common_buffs": buff_counts.most_common(20),
        }

    # ── Validation (for JSON Edit) ──────────────────────────────────────────

    def validate_edit(self, edit_data: dict) -> list[str]:
        """Sanity-check a JSON-edit payload against known-good values.

        Returns a list of warning strings. Empty list = no warnings.
        Never raises — purely advisory. Warnings include things like
        "gimmick_info=12345 is not used by any vanilla item".
        """
        warnings: list[str] = []

        gi = edit_data.get("gimmick_info")
        if isinstance(gi, int) and gi != 0 and gi not in self.gimmick_to_items:
            warnings.append(
                f"gimmick_info={gi} is not used by any vanilla item — "
                f"it may be unknown to the game and crash on equip."
            )

        ct = edit_data.get("cooltime")
        if isinstance(ct, int) and ct == 0:
            warnings.append(
                "cooltime=0 is known to crash the game for activated items "
                "(item_charge_type=0). Use 1 if you want effectively no cooldown."
            )

        ict = edit_data.get("item_charge_type")
        if isinstance(ict, int) and ict not in (0, 1, 2):
            warnings.append(
                f"item_charge_type={ict} is unusual (vanilla uses 0=activated, "
                f"1=consumable, 2=passive)."
            )

        dcd = edit_data.get("docking_child_data")
        if isinstance(dcd, dict):
            dcd_gi = dcd.get("gimmick_info_key")
            if isinstance(dcd_gi, int) and dcd_gi == 0 and isinstance(gi, int) and gi != 0:
                warnings.append(
                    "docking_child_data.gimmick_info_key=0 but gimmick_info is set — "
                    "the gimmick will not actually attach. They must match."
                )
            elif (isinstance(dcd_gi, int) and isinstance(gi, int)
                  and dcd_gi != gi and dcd_gi != 0 and gi != 0):
                warnings.append(
                    f"gimmick_info ({gi}) != docking_child_data.gimmick_info_key "
                    f"({dcd_gi}). Potter's rule: they must be the same value."
                )

        edl = edit_data.get("enchant_stat_data") or {}
        for level_stat in (edl.get("stat_list_static_level") or []):
            v = level_stat.get("change_mb")
            if isinstance(v, int) and not (-128 <= v <= 127):
                warnings.append(
                    f"stat_list_static_level entry change_mb={v} is outside i8 "
                    f"range (-128..127); the serializer may truncate or fail."
                )

        return warnings

    # ── Diff helper ─────────────────────────────────────────────────────────

    def diff_items(self, key_a: int, key_b: int) -> list[dict]:
        """Field-by-field diff between two items. Returns a list of
        {field, value_a, value_b} dicts for fields that differ.
        """
        a = self.by_key.get(key_a)
        b = self.by_key.get(key_b)
        if not a or not b:
            return []
        all_fields = sorted(set(a.keys()) | set(b.keys()))
        diffs = []
        for f in all_fields:
            va = a.get(f)
            vb = b.get(f)
            if va != vb:
                diffs.append({"field": f, "value_a": va, "value_b": vb})
        return diffs
