"""Read item records through the save file's own schema.

This module has two jobs.

**1. Recognise false hits of the byte-pattern scan.**
`scan_items` finds items with a byte-pattern scan and accepts stacks up to
9*10^18 and arbitrary slot numbers. That makes it report random byte sequences
as items - in a freshly started, unmodded game 126 of them, with stacks of
72 quadrillion on slot 256.

A simple plausibility limit is not enough here: the largest REAL stack in the
measured saves is 88,888,888 (stack mods), and 50 real items sit on slots above
255 (expanded bags). A threshold alone would throw away real items. Hence the
detour through the schema the save brings along itself: whatever is listed there
as an item record is real. Whatever is NOT listed there AND has implausible
values is a false hit.

**2. Fill in items that `enrich_items_with_parc` never reaches.**
The author's PARC path only reads fields of kind `object_list`
(`_find_item_fields_in_parsed`: `if kind != "object_list": continue`). Items
behind a pointer - which is how equipment hangs off its slot - are out of its
reach. In the measured saves this affects slot104: 243 of 597 items. For those
the tool displayed the packed socket counts as "endurance" (5 instead of 0, 773
instead of 0), and **nothing about them could be edited at all**, because
`_require_parc_field_offset` rightly refuses without a field offset.

This module walks the same records through the schema and returns values
**together with their byte offsets**. That makes the displayed values correct,
and the write path hits the right spot.

Verified: across 5087 fields both paths reach, the byte offsets agree. The only
24 deviations concerned 8 items that appear twice in the save - there
`enrich_items_with_parc` matched the wrong one of the two records, because it
only matches on `_itemNo`. That has been fixed on its side.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, NamedTuple, Optional, Tuple

log = logging.getLogger(__name__)

# Block classes that can carry items. Matched as word stems, not as exact
# names: depending on the save the inventory block is called InventorySaveData
# or InventoryItemContentsSaveData. A freshly started game only has the second
# one - a list of exact names would miss half the inventory there.
ITEM_BEARING_CLASS_STEMS = ("Inventory", "Equipment", "Store", "Mercenary")


def _bears_items(class_name: str) -> bool:
    return any(stem in (class_name or "") for stem in ITEM_BEARING_CLASS_STEMS)

# In these records 0xFFFF means "not set", not 65535.
UNSET_U16 = 0xFFFF


class Field(NamedTuple):
    """One field value together with its offset in the decompressed save."""
    value: Optional[int]
    start: int
    end: int
    trusted: bool = True

    @property
    def usable(self) -> bool:
        """May this offset be used for reading or writing?

        Behind the list fields this index runs two bytes behind the PARC path -
        measured on slot100: _transferredItemKey sits at 34110 according to
        PARC (value 1163042, plausible) and at 34108 according to this index
        (value 3206676737, nonsense). Apparently a missing list field still
        occupies two bytes that this walk does not count.

        The fields BEFORE the lists are not affected - there both paths agree
        in 15,635 places, and those are exactly the ones the tool reads and
        writes. So that nobody builds on the untrusted ones by accident, they
        report themselves as unusable here.
        """
        return self.present and self.trusted

    @property
    def present(self) -> bool:
        """Is this field in the record at all?

        This is decided by the byte offset, NOT by the value. A list field like
        _socketSaveDataList has no numeric value, but it very much has an
        offset - previously it therefore counted as absent here, and the index
        withheld exactly the field the socket tab is built on. Missing fields
        have start == end == 0.
        """
        return self.end > self.start

    @property
    def is_set(self) -> bool:
        """Present, with a numeric value, and not the "no value" sentinel."""
        return (self.present and self.value is not None
                and self.value != UNSET_U16)


def _as_int(text: str) -> Optional[int]:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _collect_items(field, hits: list) -> None:
    """Collect every ItemSaveData node below a field.

    Items sit in two places: as list elements (inventory) and behind a pointer
    (`object_locator`, which is how equipment hangs off its slot). Both cases
    have to be checked - looking only at list elements misses all equipment.
    """
    if getattr(field, "child_type_name", "") == "ItemSaveData" and field.child_fields:
        hits.append(field)
    for element in (getattr(field, "list_elements", None) or []):
        kind = getattr(element, "child_type_name", "") or getattr(element, "type_name", "")
        if kind == "ItemSaveData" and element.child_fields:
            hits.append(element)
        for child in (element.child_fields or []):
            _collect_items(child, hits)
    for child in (getattr(field, "child_fields", None) or []):
        _collect_items(child, hits)


# The byte-pattern scan reports as `offset` the position four bytes before
# `_itemNo`. Measured on slot104: for all 340 unique items this value matches
# exactly the `offset` the PARC path reports. That makes it possible to map an
# item to one specific record even when the same itemNo appears several times
# in the save.
ANCHOR_OFFSET = 4


def _read_records(blob) -> list:
    """All item records as {field name: Field} - one pass over the save.

    Returns an empty list on any error. The caller then falls back to the
    values it already had; a failure here must never stop a save from loading.
    """
    try:
        import save_parser
    except ImportError:
        log.warning("save_parser unavailable - skipping the schema index")
        return []

    blob = bytes(blob)
    try:
        schema = save_parser.parse_schema(blob)
        type_names = [t.name for t in schema["types"]]
        toc = save_parser.parse_toc(blob, schema["schema_end"], type_names)
        entries = [e for e in toc["entries"] if _bears_items(e.class_name)]
        if not entries:
            log.info("No item-bearing blocks found in this save")
            return []
        blocks = save_parser.decode_object_blocks(blob, entries, schema["types"])
    except Exception as e:  # noqa: BLE001 - diagnostics must never break loading
        log.warning("Could not build the schema index: %s", e)
        return []

    nodes: list = []
    for block in blocks:
        for field in block.fields:
            _collect_items(field, nodes)

    records = []
    for node in nodes:
        fields: Dict[str, Field] = {}
        # From the first list field onwards the offsets count as untrusted, see
        # Field.usable. The list itself is still fine - measured across 1,895
        # items _socketSaveDataList agrees with the PARC path - only what comes
        # AFTER it drifts.
        behind_list = False
        for cf in (node.child_fields or []):
            fields[cf.name] = Field(
                value=_as_int(cf.value_repr) if cf.value_repr else None,
                start=cf.start_offset,
                end=cf.end_offset,
                trusted=not behind_list,
            )
            if cf.name.endswith("List") or cf.name.endswith("Data"):
                behind_list = True
        if fields.get("_itemKey") and fields.get("_itemNo"):
            records.append(fields)

    log.info("Schema: %d item records from %d blocks",
             len(records), len(blocks))
    return records


# Loading a save needs the index twice: once for false-hit detection in
# scan_items, once for the fill-in in enrich_items_with_parc. The pass costs
# about a second on a 6.7 MB save - so compute it once, not twice. Only the
# most recently read save is cached; more than one is never needed at a time.
_CACHE_KEY = None
_CACHE_RESULT = None


def _blob_key(blob) -> str:
    import hashlib
    return f"{len(blob)}:{hashlib.md5(bytes(blob)).hexdigest()}"


def build_indexes(blob) -> Tuple[Dict[Tuple[int, int], Dict[str, Field]],
                                 Dict[int, Dict[str, Field]]]:
    """Both mappings in a single pass.

    - by (itemKey, itemNo): for false-hit detection. There the only question is
      "does this key appear in the schema at all", so duplicates do no harm.
    - by anchor (byte offset): maps a single item to exactly ONE record, even
      when the same itemNo appears several times. Only this mapping may be the
      basis for writes.
    """
    global _CACHE_KEY, _CACHE_RESULT
    try:
        cache_key = _blob_key(blob)
    except Exception:  # noqa: BLE001
        cache_key = None
    if cache_key is not None and cache_key == _CACHE_KEY:
        return _CACHE_RESULT

    by_key: Dict[Tuple[int, int], Dict[str, Field]] = {}
    by_anchor: Dict[int, Dict[str, Field]] = {}
    for fields in _read_records(blob):
        # Do NOT name this 'cache_key' - that is the name of the cache's own
        # key above, and the loop used to overwrite it. What got cached was
        # then the itemNo of the last record instead of the save's checksum,
        # and the cache never hit.
        item_key = (fields["_itemKey"].value, fields["_itemNo"].value)
        if None not in item_key:
            by_key[item_key] = fields
        item_no = fields["_itemNo"]
        if item_no.present:
            by_anchor[item_no.start - ANCHOR_OFFSET] = fields

    if cache_key is not None:
        _CACHE_KEY, _CACHE_RESULT = cache_key, (by_key, by_anchor)
    return by_key, by_anchor


def build_index(blob: bytes | bytearray) -> Dict[Tuple[int, int], Dict[str, Field]]:
    """Only the mapping by (itemKey, itemNo) - for false-hit detection."""
    return build_indexes(blob)[0]


def field_position(index, item_key: int, item_no: int, field_name: str) -> Optional[Tuple[int, int]]:
    """Byte offset of a field, or None when the record does not have it.

    The write path asks here before it changes anything. If None comes back,
    the field does not exist in this record - then nothing may be written, or
    the value would land in a different field.
    """
    fields = index.get((item_key, item_no))
    if not fields:
        return None
    field = fields.get(field_name)
    if field is None or not field.usable:
        return None
    return (field.start, field.end)


# -- Sorting out false hits --------------------------------------------------
#
# The byte-pattern scan accepts stacks up to 9*10^18 and arbitrary slot
# numbers. That makes it find random byte sequences matching its pattern and
# report them as items. Measured across seven saves:
#
#   not in the schema index: 114 / 115 / 126 / 2 of them
#   of those, stack above 10 million: ALL
#   in the schema index, stack above 10 million: NONE
#   largest real stack: 8,951,308 (with stack mods)
#
# The separation is therefore complete. Even so, only what is BOTH - absent
# from the schema AND obviously implausible - is sorted out here. A real item
# the schema pass fails to reach for whatever reason stays visible. Better one
# false hit too many than one real item too few.

PLAUSIBLE_STACK = 9_999_999
PLAUSIBLE_SLOT_NO = 255


def is_false_hit(item, index) -> bool:
    """False hit of the byte-pattern scan: absent from the schema AND implausible."""
    if (item.item_key, item.item_no) in index:
        return False
    return (item.stack_count > PLAUSIBLE_STACK
            or item.slot_no > PLAUSIBLE_SLOT_NO)


def drop_false_hits(items, index) -> Tuple[list, list]:
    """Split the item list into real items and false hits.

    Without a schema index nothing is sorted out - the basis for the decision
    is missing then, and a guess is no reason to hide anything.
    """
    if not index:
        return list(items), []
    real, false_hits = [], []
    for it in items:
        (false_hits if is_false_hit(it, index) else real).append(it)
    if false_hits:
        log.info("Dropped %d false hits of the byte-pattern scan (of %d)",
                 len(false_hits), len(items))
    return real, false_hits


# -- Filling in items the PARC path never reaches ---------------------------

# Fields the write path can change. The size is listed because
# `_require_parc_field_offset` checks it - a field whose schema entry has a
# different size is not taken over.
WRITABLE_FIELDS = {
    "_stackCount": 8,
    "_itemNo": 8,
    "_enchantLevel": 2,
    "_endurance": 2,
    "_sharpness": 2,
}


def _value_of(fields, name: str) -> int:
    field = fields.get(name)
    return field.value if (field and field.is_set) else 0


def fill_in_without_parc(items, by_anchor) -> Dict[str, int]:
    """Fill items `enrich_items_with_parc` never reached from the schema.

    Affects items behind a pointer - equipment above all. For those the tool
    used to display the packed socket counts as "endurance", and nothing about
    them could be edited.

    Only what the PARC path did NOT reach is touched. Whatever it delivered
    stays unchanged - the two paths demonstrably agree there, and two sources
    for the same value is one more source of error.

    The mapping runs over the byte offset, not over the itemNo. If no record is
    found there, the item stays as it was: better an item without write access
    than a change in the wrong place.
    """
    stats = {"filled": 0, "no_record": 0, "values_corrected": 0,
             "now_editable": 0}
    if not by_anchor:
        return stats

    for it in items:
        if getattr(it, "parc_parsed", False) and it.field_offsets:
            continue
        fields = by_anchor.get(it.offset)
        if fields is None:
            stats["no_record"] += 1
            continue
        stats["filled"] += 1

        new_sharpness = _value_of(fields, "_sharpness")
        new_endurance = _value_of(fields, "_endurance")
        if new_sharpness != it.sharpness or new_endurance != it.endurance:
            stats["values_corrected"] += 1
        it.sharpness = new_sharpness
        it.endurance = new_endurance

        # Pass the socket counts along separately, instead of packing them into
        # the endurance the way the byte-pattern scan does.
        setattr(it, "max_socket_count", _value_of(fields, "_maxSocketCount"))
        setattr(it, "valid_socket_count", _value_of(fields, "_validSocketCount"))

        enchant = fields.get("_enchantLevel")
        if enchant and enchant.present:
            it.enchant_level = enchant.value
            it.has_enchant = enchant.value != UNSET_U16

        offsets = {}
        for name, size in WRITABLE_FIELDS.items():
            field = fields.get(name)
            if field and field.usable and field.end - field.start == size:
                offsets[name] = field.start
        if offsets:
            ends = [f.end for f in fields.values() if f.usable]
            offsets["_record_end"] = max(ends) if ends else 0
            it.field_offsets = offsets
            # These offsets come from the save's own schema - exactly the
            # condition `_require_parc_field_offset` is meant to guarantee.
            it.parc_parsed = True
            setattr(it, "offset_source", "schema_index")
            stats["now_editable"] += 1

    if stats["filled"]:
        log.info("Filled in %d items from the schema (%d values corrected, "
                 "%d of them now editable), %d without a matching record",
                 stats["filled"], stats["values_corrected"],
                 stats["now_editable"], stats["no_record"])
    return stats
