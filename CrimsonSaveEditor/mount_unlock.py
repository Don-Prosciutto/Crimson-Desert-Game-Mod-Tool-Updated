"""Add mounts to a save - by copying an entry of the same save, no foreign templates.

Why this way: the old "Unlock Mounts" inserted hex blocks taken from someone
else's save of an older game version and guessed internal numbers. This copies
the plainest entry of the player's own mercenary list (the layout this game
version writes), changes only which character it is and gives it a new number.
The game fills in the rest itself on the next save (owner, HP, position).

Tested in game 2.05.00 (13.11.2026): first White Bear, Silver Fang, Snowwhite
Deer and Rock Tusk (call, ride, attack, save, restart, load, play on, load
again), then all 57 mounts below in one save.

Every result is checked before it is returned: list count, the new entries,
the old entries, every other block decoded identically and not a single byte
changed outside real payload pointers. Anything else raises and nothing is
changed. No Qt in here.
"""

from __future__ import annotations

import copy
import struct
from typing import Dict, Iterable, List, Tuple

# (characterKey, name, group) - the rideable mounts as listed on
# crimsondesert.gg/mounts (58 incl. DLC), one game record each (the "Riding_"
# record where there is one). Blackstar is left out: the entry is written but
# the game only shows it after its quest. Tested in game 2.05.00, 13.11.2026:
# all in one save (Royler, Camora and Wyvern were owned already) - call,
# ride, animations. Aquatic ones and the Ocean Drifter need the DLC.
MOUNTS: List[Tuple[int, str, str]] = [
    # Horses
    (2002, 'Brianto', 'Horses'),
    (1002441, "Calphadean Scout's Horse", 'Horses'),
    (31379, 'Camora', 'Horses'),
    (2011, 'Elantrima', 'Horses'),
    (1000766, "Hernandian Soldier's Horse", 'Horses'),
    (2000, 'Herspia', 'Horses'),
    (2005, 'Numont', 'Horses'),
    (2001, 'Priden', 'Horses'),
    (1001120, 'Race Horse', 'Horses'),
    (31378, 'Rokade', 'Horses'),
    (31377, 'Royler', 'Horses'),
    # Predators
    (1003769, 'Large White Wolf', 'Predators'),
    (1001009, 'Large Wolf', 'Predators'),
    (1003918, 'Silver Fang', 'Predators'),
    (1000264, 'Swift Wolf', 'Predators'),
    (1002316, 'Circus Lion', 'Predators'),
    (1003792, 'Lion', 'Predators'),
    (1001077, 'Tiger', 'Predators'),
    # Bears
    (30116, 'Bear', 'Bears'),
    (30108, 'Black Bear', 'Bears'),
    (1000022, 'Captured Bear', 'Bears'),
    (1003911, 'Clawed Bear', 'Bears'),
    (30111, 'Grizzly Bear', 'Bears'),
    (1003917, 'White Bear', 'Bears'),
    # Camels
    (1004021, 'Sandwalk Camel', 'Camels'),
    # Boars
    (1003912, 'Rock Tusk Warthog', 'Boars'),
    # Deer
    (1003914, 'Rosehorn Deer', 'Deer'),
    (1003919, 'Snowwhite Deer', 'Deer'),
    # Ibex
    (1002315, 'Ibex', 'Ibex'),
    (1003915, 'Icicle Edge Alpine Ibex', 'Ibex'),
    # Birds
    (1004046, 'Leaping Kuku Bird', 'Birds'),
    (1000265, 'Red-Feathered Raptor', 'Birds'),
    # Reptiles
    (1000254, 'Giant Green Iguana', 'Reptiles'),
    (1000363, 'Giant Red Iguana', 'Reptiles'),
    # Mechanical
    (1004643, 'Ocean Drifter', 'Mechanical'),
    # Aquatic
    (1004531, 'Golden Shark', 'Aquatic'),
    (1004575, 'Hammerhead Shark', 'Aquatic'),
    (1004278, 'Shark', 'Aquatic'),
    (1004280, 'Orca', 'Aquatic'),
    (1004279, 'Sunfish', 'Aquatic'),
    (1004089, 'Spotted Seal', 'Aquatic'),
    (1004224, 'Green Sea Turtle', 'Aquatic'),
    (1004226, 'Hawksbill Sea Turtle', 'Aquatic'),
    (1004561, 'Hydrothermal Turtle', 'Aquatic'),
    (32300, 'Loggerhead Sea Turtle', 'Aquatic'),
    (1004225, 'Olive Ridley Sea Turtle', 'Aquatic'),
    (1004574, 'Eagle Ray', 'Aquatic'),
    (1004563, 'Electric Ray', 'Aquatic'),
    (1004626, 'Giant Manta Ray', 'Aquatic'),
    (1004277, 'Manta Ray', 'Aquatic'),
    (1004530, 'Pink Manta Ray', 'Aquatic'),
    (1004535, 'Dolphin', 'Aquatic'),
    (1004536, 'Pink Dolphin', 'Aquatic'),
    # Flying
    (1004233, 'Wyvern', 'Flying'),
    (1002041, 'Cloudcart', 'Flying'),
    (1002042, 'Cloudcruiser', 'Flying'),
    (1002043, 'Skystreaker', 'Flying'),
]
DLC_GROUPS = {"Aquatic", "Mechanical"}

_PLAIN = {"_characterKey", "_mercenaryNo", "_levelData", "_lastPaidTime", "_lastBreedingTime",
          "_spawnPosition", "_spawnYaw", "_spawnFieldInfoKey", "_isInitialize"}
_SENTINEL = b"\xff" * 8


class MountError(RuntimeError):
    pass


def _tree(raw: bytes):
    from save_parser import parse_schema, parse_toc, decode_object_blocks
    sch = parse_schema(raw)
    toc = parse_toc(raw, sch["schema_end"], [t.name for t in sch["types"]])
    return sch, decode_object_blocks(raw, toc["entries"], sch["types"])


def _merc_list(blocks):
    for b in blocks:
        if b.class_name == "MercenaryClanSaveData":
            for f in b.fields:
                if f.name == "_mercenaryDataList" and f.list_elements:
                    return b, f
    raise MountError("This save has no mercenary list yet (play until you own a mount or comrade).")


def _present(e) -> Dict[str, object]:
    return {cf.name: cf for cf in (e.child_fields or []) if cf.present}


def _u(raw: bytes, cf) -> int:
    n = cf.end_offset - cf.start_offset
    return struct.unpack_from({4: "<I", 8: "<Q"}[n], raw, cf.start_offset)[0]


def owned_keys(raw: bytes) -> set:
    """Character keys already in the save's mercenary list."""
    _, blocks = _tree(raw)
    _, lst = _merc_list(blocks)
    return {_u(raw, _present(e)["_characterKey"]) for e in lst.list_elements}


def _values(fields, out: list, pre: str = "") -> None:
    for f in fields or []:
        if not f.present:
            continue
        if f.child_fields:
            _values(f.child_fields, out, pre + f.name + ".")
        elif f.list_elements is not None:
            for k, e in enumerate(f.list_elements):
                _values(e.child_fields, out, f"{pre}{f.name}[{k}].")
        else:
            out.append((pre + f.name, f.value_repr))


def _stray_bytes(raw: bytes, out: bytes) -> int:
    """Bytes that differ between the two blobs in blocks of the same size,
    outside real payload pointers (8x FF + a u32 pointing right behind it)."""
    from parc_serializer import parse_parc_blob
    pa, pb = parse_parc_blob(raw), parse_parc_blob(out)
    stray = 0
    for ea, eb in zip(pa.toc_entries, pb.toc_entries):
        if ea.class_index != eb.class_index or ea.data_size != eb.data_size:
            continue
        a = raw[ea.data_offset:ea.data_offset + ea.data_size]
        b = out[eb.data_offset:eb.data_offset + eb.data_size]
        if a == b:
            continue
        ptr = set()
        i = a.find(_SENTINEL)
        while 0 <= i <= len(a) - 12:
            if struct.unpack_from("<I", a, i + 8)[0] == ea.data_offset + i + 12:
                ptr.update(range(i + 8, i + 12))
            i = a.find(_SENTINEL, i + 1)
        stray += sum(1 for k in range(len(a)) if a[k] != b[k] and k not in ptr)
    return stray


def add_mounts(raw: bytes, keys: Iterable[int]) -> Tuple[bytes, List[Tuple[int, int]]]:
    """Return (new blob, [(characterKey, mercenaryNo), ...]). Keys the save
    already has are skipped. Raises MountError if any check fails."""
    from parc_tree_serializer import serialize_object_block
    from parc_serializer import parse_parc_blob, replace_block_raw, serialize_parc

    raw = bytes(raw)
    sch, blocks = _tree(raw)
    schema_types = {t.index: t for t in sch["types"]}
    block, lst = _merc_list(blocks)
    old = list(lst.list_elements)
    have = {_u(raw, _present(e)["_characterKey"]) for e in old}
    max_no = max(_u(raw, _present(e)["_mercenaryNo"]) for e in old)

    plain = [e for e in old if set(_present(e)) == _PLAIN]
    if not plain:
        raise MountError("No plain mercenary entry in this save to copy from.")
    pattern = plain[0]
    pattern_fields = set(_present(pattern))

    added: List[Tuple[int, int]] = []
    for k in keys:
        k = int(k)
        if k in have or any(k == a for a, _ in added):
            continue
        max_no += 1
        # Deep copy WITH the pattern's offsets: the serializer re-emits it from
        # the pattern's bytes, with the changed fields and fresh pointers.
        new = copy.deepcopy(pattern)
        for cf in new.child_fields:
            if cf.present and cf.name in ("_characterKey", "_mercenaryNo"):
                if not cf.edit_format:
                    raise MountError(f"{cf.name} cannot be written in this save.")
                cf.value_repr = str(k if cf.name == "_characterKey" else max_no)
                cf.note = (cf.note or "") + " [modified]"
        # Before the last entry, which is written anew too: the serializer
        # copies everything behind the LAST element's end offset, and entries
        # copied unchanged keep their absolute payload pointer.
        lst.list_elements.insert(len(lst.list_elements) - 1, new)
        for cf in lst.list_elements[-1].child_fields:
            if cf.present and cf.name == "_characterKey":
                cf.note = (cf.note or "") + " [modified]"
        added.append((k, max_no))
    if not added:
        return raw, []
    for i, el in enumerate(lst.list_elements):
        el.field_index, el.name = i, f"[{i}]"
    lst.list_count = len(lst.list_elements)
    lst.note = (lst.note or "") + " [modified]"

    parc = parse_parc_blob(raw)
    replace_block_raw(parc, block.entry_index,
                      serialize_object_block(block, schema_types, raw, block.data_offset))
    out = serialize_parc(parc)

    # ── checks ──
    _, blocks2 = _tree(out)
    _, lst2 = _merc_list(blocks2)
    if len(lst2.list_elements) != len(old) + len(added):
        raise MountError("Check failed: mercenary count")
    by_no = {_u(out, _present(e)["_mercenaryNo"]): e for e in lst2.list_elements}
    for e in old:
        fa = _present(e)
        n = by_no.get(_u(raw, fa["_mercenaryNo"]))
        if n is None or set(_present(n)) != set(fa) \
                or _u(out, _present(n)["_characterKey"]) != _u(raw, fa["_characterKey"]) \
                or n.end_offset - n.start_offset != e.end_offset - e.start_offset:
            raise MountError("Check failed: an existing entry changed")
    for k, no in added:
        n = by_no.get(no)
        if n is None or set(_present(n)) != pattern_fields or _u(out, _present(n)["_characterKey"]) != k:
            raise MountError("Check failed: new entry")
    if len(blocks) != len(blocks2):
        raise MountError("Check failed: block count")
    for a, b in zip(blocks, blocks2):
        if a.class_name == "MercenaryClanSaveData":
            continue
        va, vb = [], []
        _values(a.fields, va)
        _values(b.fields, vb)
        if va != vb:
            raise MountError(f"Check failed: {a.class_name} reads differently")
    if _stray_bytes(raw, out):
        raise MountError("Check failed: data outside pointers changed")
    return out, added
