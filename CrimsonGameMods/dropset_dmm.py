"""DropSets on dmm_parser: the same interface as dropset_editor.DropsetEditor,
but reading and writing dropsetinfo through dmm_parser.

Why: dropset_editor.py decodes the table by fixed byte positions from an
older game version. On 2.03.02 it writes 254 of 14747 drop sets back
differently (the Game Check blocked the page for that). dmm_parser reads
and writes every set byte for byte.

The DropSets page and its presets keep working with DropSet / ItemDrop
objects. Each ItemDrop here carries the dmm_parser record of that drop
(`raw`); only the fields the page edits are written back into it:

    ItemDrop.item_key  -> raw_at_120 and variant.lookup (the dropped item)
    ItemDrop.rates     -> raw_16   (1,000,000 = 100 %)
    ItemDrop.max_amt   -> raw_40   (the smaller amount - the old reader had
    ItemDrop.min_amt   -> raw_48    the two names the wrong way round and the
                                    page shows them accordingly)

Everything else in a drop (condition data, dispatch tags, ...) is left
exactly as the game has it. No Qt in here.
"""

from __future__ import annotations

import copy
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from dropset_editor import DropSet, DropsetEditor, ItemDrop

TABLE = "dropsetinfo"


@dataclass
class DmmItemDrop(ItemDrop):
    raw: dict = field(default_factory=dict)


def _new_raw(item_key: int, rate: int, low: int, high: int) -> dict:
    """A plain drop entry, as the game writes one for a simple item drop."""
    return {"dispatch_tag": 0, "lookup_4": 0, "lookup_6": 0, "lookup_8": 0,
            "raw_12": 0, "raw_16": int(rate), "raw_32": 0, "raw_40": int(low),
            "raw_48": int(high), "raw_56": 65535, "raw_at_120": int(item_key),
            "variant": {"lookup": int(item_key), "tag": 0}}


class DmmDropsetEditor(DropsetEditor):

    def __init__(self, dmm=None):
        super().__init__()
        if dmm is None:
            import dmm_parser as dmm  # noqa: PLC0415
        self._dmm = dmm
        self._recs: List[dict] = []
        self._by_key: Dict[int, dict] = {}

    # ── loading ──────────────────────────────────────────────────────
    def load(self, pabgh_path: str, pabgb_path: str):
        with open(pabgh_path, "rb") as f:
            head = f.read()
        with open(pabgb_path, "rb") as f:
            body = f.read()
        self.load_bytes(head, body)

    def load_bytes(self, pabgh: bytes, pabgb: bytes):
        self.header_bytes = bytes(pabgh)
        self.body_bytes = bytearray(pabgb)
        self._recs = list(self._dmm.parse_table(TABLE, bytes(pabgb), bytes(pabgh)))
        self._by_key = {int(r["key"]): r for r in self._recs}
        self._read_index()
        self._parsed_sets.clear()

    def _read_index(self):
        self.record_count = struct.unpack_from("<H", self.header_bytes, 0)[0]
        self.records = [struct.unpack_from("<II", self.header_bytes, 2 + i * 8)
                        for i in range(self.record_count)]
        self._offsets = dict(self.records)
        ends = sorted(o for _, o in self.records) + [len(self.body_bytes)]
        self._next = {o: ends[i + 1] for i, o in enumerate(ends[:-1])}

    # ── records <-> DropSet objects ──────────────────────────────────
    def parse_dropset(self, key: int) -> Optional[DropSet]:
        key = int(key)
        if key in self._parsed_sets:
            return self._parsed_sets[key]
        rec = self._by_key.get(key)
        if rec is None:
            return None
        drops = []
        for raw in rec.get("list") or []:
            item = int(raw.get("raw_at_120", 0) or 0)
            rate = int(raw.get("raw_16", 0) or 0)
            drops.append(DmmItemDrop(
                flag=0, item_key=item, unk4=int(raw.get("dispatch_tag", 0) or 0),
                rates=rate, rates_100=rate // 10000,
                max_amt=int(raw.get("raw_40", 0) or 0),
                min_amt=int(raw.get("raw_48", 0) or 0),
                unk3_flags=int(raw.get("raw_56", 0xFFFF) or 0),
                item_key_dup=item, raw=raw))
        off = self._offsets.get(key, 0)
        ds = DropSet(
            key=key, name=rec.get("string_key", "") or "",
            is_blocked=int(rec.get("is_blocked", 0) or 0),
            drop_roll_type=int(rec.get("drop_roll_type", 0) or 0),
            drop_roll_count=int(rec.get("drop_roll_count", 0) or 0),
            drop_condition_string=rec.get("drop_condition_string", "") or "",
            drop_tag_name_hash=int(rec.get("drop_tag_name_hash", 0) or 0),
            drops=drops,
            nee_slot_count=int(rec.get("nee_slot_count", 0) or 0),
            need_weight=int(rec.get("need_weight", 0) or 0),
            total_drop_rate=int(rec.get("total_drop_rate", 0) or 0),
            original_string=rec.get("original_string", "") or "",
            header_offset=off, body_offset=off,
            total_size=self._next.get(off, len(self.body_bytes)) - off)
        self._parsed_sets[key] = ds
        return ds

    def _record_for(self, ds: DropSet) -> dict:
        """A copy of the set's record with the page's edits written in."""
        rec = copy.deepcopy(self._by_key[int(ds.key)])
        new_list = []
        for d in ds.drops:
            raw = copy.deepcopy(getattr(d, "raw", None) or {}) or _new_raw(
                d.item_key, d.rates, d.max_amt, d.min_amt)
            raw["raw_16"] = int(d.rates)
            raw["raw_40"] = max(0, int(d.max_amt))
            raw["raw_48"] = max(0, int(d.min_amt))
            raw["raw_at_120"] = int(d.item_key)
            var = raw.get("variant")
            if isinstance(var, dict) and "lookup" in var:
                var["lookup"] = int(d.item_key)
            new_list.append(raw)
        rec["list"] = new_list
        for f in ("is_blocked", "drop_roll_type", "drop_roll_count"):
            if f in rec:
                rec[f] = int(getattr(ds, f))
        return rec

    # ── Field JSON ───────────────────────────────────────────────────
    def record(self, key: int) -> Optional[dict]:
        return self._by_key.get(int(key))

    def diff_intents(self, vanilla_recs: List[dict]) -> List[dict]:
        """Field JSON v3 intents for every set that differs from vanilla,
        with the table's own field names (a changed drop list is set whole)."""
        van = {int(r["key"]): r for r in vanilla_recs}
        out = []
        for rec in self._recs:
            v = van.get(int(rec["key"]))
            if v is None:
                continue
            for f, val in rec.items():
                if f in ("key", "string_key") or v.get(f) == val:
                    continue
                out.append({"entry": rec.get("string_key", ""), "key": int(rec["key"]),
                            "field": f, "op": "set", "new": copy.deepcopy(val)})
        return out

    def apply_field_intents(self, intents: List[dict]) -> tuple:
        """Apply Field JSON intents to the records, then rebuild the table.
        Accepts the table's field names and the old export's `drops` lists."""
        by_name = {r.get("string_key"): r for r in self._recs if r.get("string_key")}
        applied = skipped = 0
        for it in intents:
            rec = by_name.get(it.get("entry")) or self._by_key.get(int(it.get("key") or -1))
            field_name = it.get("field", "")
            if rec is None or it.get("op") != "set":
                skipped += 1
                continue
            if field_name == "drops":             # old DropSets export format
                old = rec.get("list") or []
                new = []
                for i, d in enumerate(it.get("new") or []):
                    base = copy.deepcopy(old[i]) if i < len(old) else _new_raw(0, 0, 1, 1)
                    k = int(d.get("item_key", 0))
                    base["raw_at_120"] = k
                    if isinstance(base.get("variant"), dict) and "lookup" in base["variant"]:
                        base["variant"]["lookup"] = k
                    base["raw_16"] = int(d.get("rates", 0))
                    base["raw_40"] = int(d.get("max_amt", 0))
                    base["raw_48"] = int(d.get("min_amt", 0))
                    new.append(base)
                rec["list"] = new
            elif field_name in rec:
                rec[field_name] = copy.deepcopy(it.get("new"))
            else:
                skipped += 1
                continue
            applied += 1
        if applied:
            self.apply_modifications([])
        return applied, skipped

    def _serialize_dropset(self, ds: DropSet) -> bytes:
        out = self._dmm.serialize_table(TABLE, [self._record_for(ds)])
        return bytes(out[0] if isinstance(out, tuple) else out)

    # ── editing ──────────────────────────────────────────────────────
    def add_item(self, ds: DropSet, item_key: int, rate: int = DropsetEditor.MAX_RATE,
                 min_qty: int = 1, max_qty: int = 1,
                 template_drop: Optional[ItemDrop] = None) -> ItemDrop:
        # A plain drop entry; a template may carry condition data for its own
        # item, so it is not copied (the old reader copied some of it).
        d = DmmItemDrop(flag=0, item_key=int(item_key), rates=int(rate),
                        rates_100=int(rate) // 10000, max_amt=int(min_qty),
                        min_amt=int(max_qty), item_key_dup=int(item_key),
                        raw=_new_raw(item_key, rate, min_qty, max_qty))
        ds.drops.append(d)
        return d

    def apply_modifications(self, modified_sets: List[DropSet]):
        if isinstance(modified_sets, dict):
            modified_sets = list(modified_sets.values())
        for ds in modified_sets:
            rec = self._record_for(ds)
            self._by_key[int(ds.key)].clear()
            self._by_key[int(ds.key)].update(rec)
        out = self._dmm.serialize_table(TABLE, self._recs)
        body = bytes(out[0] if isinstance(out, tuple) else out)
        # dmm_parser reads this table without the index, but the game uses
        # the offsets in it; sets that got longer or shorter move the rest.
        from pabgh_index import rebuild_index
        head = rebuild_index(TABLE, body, bytes(self.header_bytes), self._dmm, recs=self._recs)
        if head is None:
            raise RuntimeError("dropsetinfo: the index could not be rebuilt - not applied.")
        check = self._dmm.parse_table(TABLE, body, head)
        if len(check) != len(self._recs):
            raise RuntimeError("dropsetinfo did not read back after the change - not applied.")
        self.body_bytes = bytearray(body)
        self.header_bytes = head
        self._read_index()
        self._parsed_sets.clear()

    # ── overview ─────────────────────────────────────────────────────
    def get_all_sets_summary(self, named_only: bool = True) -> List[dict]:
        result = []
        for rec in self._recs:
            name = rec.get("string_key", "") or ""
            if named_only and not name:
                continue
            key = int(rec["key"])
            result.append({"key": key, "name": name,
                           "drop_count": len(rec.get("list") or []),
                           "category": self.categorize_by_name(name),
                           "offset": self._offsets.get(key, 0)})
        result.sort(key=lambda r: (0 if r["name"] else 1, r["name"] or "", r["key"]))
        return result
