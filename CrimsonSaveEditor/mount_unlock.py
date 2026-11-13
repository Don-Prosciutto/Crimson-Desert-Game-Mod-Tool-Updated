"""Add mounts and pets to a save - by copying an entry of the same save, no foreign templates.

Why this way: the old "Unlock Mounts" inserted hex blocks taken from someone
else's save of an older game version and guessed internal numbers. This copies
the plainest entry of the player's own mercenary list (the layout this game
version writes), changes only which character it is and gives it a new number.
The game fills in the rest itself on the next save (owner, HP, position).

Tested in game 2.05.00 (13.11.2026): first White Bear, Silver Fang, Snowwhite
Deer and Rock Tusk (call, ride, attack, save, restart, load, play on, load
again), then all 57 mounts below in one save, then all 84 pets in one save,
then the 101 pet variants next to them.
Mounts and pets live in the same list, so add_mounts() adds either.

Every result is checked before it is returned: list count, the new entries,
the old entries, every other block decoded identically and not a single byte
changed outside real payload pointers. Anything else raises and nothing is
changed. No Qt in here.
"""

from __future__ import annotations

import copy
import os
import struct
import sys
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
# Filter buttons on the page: group -> area
AREA = {"Horses": "Land", "Predators": "Land", "Bears": "Land", "Camels": "Land",
        "Boars": "Land", "Deer": "Land", "Ibex": "Land", "Birds": "Land",
        "Reptiles": "Land", "Mechanical": "Sea", "Aquatic": "Sea", "Flying": "Air"}


# (characterKey, name, group) - the pets as listed on crimsondesert.gg/pets,
# the tameable ("Domestic") record where there is one. Abyss Heuklang is left
# out: it comes with its quest. Tested in game 2.05.00, 13.11.2026: all 84 in
# one save - call, follow, pick up; they come with full trust.
PETS: List[Tuple[int, str, str]] = [
    # Birds
    (1004087, 'Kuku Bird Chick', 'Birds'),
    (1000306, 'Crow', 'Birds'),
    (1000302, 'Eagle', 'Birds'),
    (31423, 'Goose', 'Birds'),
    (30071, 'Sparrow', 'Birds'),
    (32352, 'Kentish Plover', 'Birds'),
    (32367, 'Meadow Bunting', 'Birds'),
    (1003779, 'Long-Tailed Tit', 'Birds'),
    (1003916, 'Hyacinth Macaw', 'Birds'),
    (1000798, 'Iron Eagle', 'Birds'),
    (32288, 'Common Tern', 'Birds'),
    (32285, 'Smew', 'Birds'),
    (1003814, 'Condor', 'Birds'),
    (30079, 'Blue Jay', 'Birds'),
    (32381, 'Sand Grouse', 'Birds'),
    (30084, 'Seagull', 'Birds'),
    (1003813, 'Citron-Crested Cockatoo', 'Birds'),
    (1003812, 'Ringneck Parrot', 'Birds'),
    (1003811, 'Little Blue Macaw', 'Birds'),
    (32883, 'Grey Parrot', 'Birds'),
    (1003810, 'Sun Conure', 'Birds'),
    (1003809, 'Eclectus Parrot', 'Birds'),
    (1003808, 'Parrot', 'Birds'),
    (32395, 'Eastern Sparrowhawk', 'Birds'),
    (32380, 'Red-Footed Falcon', 'Birds'),
    (31420, 'Steppe Eagle', 'Birds'),
    (31416, 'Gyrfalcon', 'Birds'),
    (30059, 'Hawk', 'Birds'),
    (1001889, 'Desert Goose', 'Birds'),
    (1000780, 'Partridge', 'Birds'),
    (32411, 'Collared Dove', 'Birds'),
    (30081, 'Pigeon', 'Birds'),
    (30020, 'Wild Duck', 'Birds'),
    (32266, 'Yellow-Billed Loon', 'Birds'),
    (32038, 'Cuckoo', 'Birds'),
    (30009, 'White-Winged Redstart', 'Birds'),
    (30060, 'Owl', 'Birds'),
    (1001618, 'Phoenix', 'Birds'),
    # Cats
    (31467, 'Short-Haired Cat', 'Cats'),
    (30024, 'Cat', 'Cats'),
    (1000317, 'Loafy Cat', 'Cats'),
    (1000323, 'Slim Cat', 'Cats'),
    (31468, 'Short-Haired Kitten', 'Cats'),
    (31511, 'Kitten', 'Cats'),
    (32033, 'Desert Cat', 'Cats'),
    (30007, 'Long-Haired Cat', 'Cats'),
    # Dogs
    (30046, 'Fox', 'Dogs'),
    (30186, 'Pointy-Eared Bulldog', 'Dogs'),
    (30038, 'Snowfield Fox', 'Dogs'),
    (30070, 'Husky', 'Dogs'),
    (1002047, 'Shepherd', 'Dogs'),
    (30022, 'Boarhound', 'Dogs'),
    (32181, 'Greyhound', 'Dogs'),
    (31400, 'Saluki', 'Dogs'),
    (1002258, 'Jindo', 'Dogs'),
    (1001396, 'Floppy-Eared Bulldog', 'Dogs'),
    (31410, 'Desert Fox', 'Dogs'),
    (31336, 'Boarhound Puppy', 'Dogs'),
    (1004307, 'Dalmatian', 'Dogs'),
    (32189, 'Beagle', 'Dogs'),
    # Other
    (30045, 'Hedgehog', 'Other'),
    (30039, 'Weasel', 'Other'),
    (30065, 'Chipmunk', 'Other'),
    (32035, 'Snowfield Chipmunk', 'Other'),
    (32370, 'Red Squirrel', 'Other'),
    (32357, 'Choppy', 'Other'),
    (1000804, 'Flying Squirrel', 'Other'),
    (1004045, 'Baby Wyvern', 'Other'),
    (1000979, 'Meerkat', 'Other'),
    (1004022, 'Red Panda', 'Other'),
    (32359, 'Feathered Weasel', 'Other'),
    (32355, 'Skunky', 'Other'),
    (1000991, 'Desert Porcupine', 'Other'),
    (32261, 'Porcupine', 'Other'),
    (30142, 'Badger', 'Other'),
    (30141, 'Skunk', 'Other'),
    (1000841, 'Wombat', 'Other'),
    (30139, 'Beaver', 'Other'),
    (1000923, 'Platypus', 'Other'),
    (1003796, 'Raccoon', 'Other'),
    (32034, 'Snowfield Weasel', 'Other'),
    (30078, 'Armadillo', 'Other'),
    (31409, 'Desert Rabbit', 'Other'),
    (30189, 'Forest Rabbit', 'Other'),
]
PET_GROUPS = ("Birds", "Cats", "Dogs", "Other")

# (characterKey, name, group, base pet key or 0) - further looks of the pets
# above: cat colours, dog coats and the named town cats and dogs. Each is its
# own game record with its own pet portrait. Tested in game 2.05.00,
# 14.11.2026: all in one save next to the 84 pets - they look right and
# behave like normal pets.
PET_VARIANTS: List[Tuple[int, str, str, int]] = [
    # Cats
    (1000296, 'Long-Haired Cat (White)', 'Cats', 30007),
    (1003952, 'Ragdoll Cat', 'Cats', 30007),
    (1000314, 'Cat (Black)', 'Cats', 30024),
    (1000316, 'Cat (Calico)', 'Cats', 30024),
    (1000312, 'Cat (Ginger)', 'Cats', 30024),
    (1003951, 'Cat (Russian Blue)', 'Cats', 30024),
    (1000315, 'Cat (Two-Tone)', 'Cats', 30024),
    (1000313, 'Cat (White)', 'Cats', 30024),
    (1000356, 'Short-Haired Cat (Brown)', 'Cats', 31467),
    (1000359, 'Short-Haired Cat (Tabby)', 'Cats', 31467),
    (1000358, 'Short-Haired Cat (Two-Tone)', 'Cats', 31467),
    (1000357, 'Short-Haired Cat (White)', 'Cats', 31467),
    (1000364, 'Short-Haired Kitten (Brown)', 'Cats', 31468),
    (1000367, 'Short-Haired Kitten (Tabby)', 'Cats', 31468),
    (1000366, 'Short-Haired Kitten (Two-Tone)', 'Cats', 31468),
    (1000365, 'Short-Haired Kitten (White)', 'Cats', 31468),
    (1000348, 'Kitten (Black)', 'Cats', 31511),
    (1000350, 'Kitten (Calico)', 'Cats', 31511),
    (1000346, 'Kitten (Ginger)', 'Cats', 31511),
    (1003961, 'Kitten (Russian Blue)', 'Cats', 31511),
    (1000349, 'Kitten (Two-Tone)', 'Cats', 31511),
    (1000347, 'Kitten (White)', 'Cats', 31511),
    (1000320, 'Loafy Cat (Black)', 'Cats', 1000317),
    (1000322, 'Loafy Cat (Calico)', 'Cats', 1000317),
    (1000318, 'Loafy Cat (Ginger)', 'Cats', 1000317),
    (1003959, 'Loafy Cat (Russian Blue)', 'Cats', 1000317),
    (1000321, 'Loafy Cat (Two-Tone)', 'Cats', 1000317),
    (1000319, 'Loafy Cat (White)', 'Cats', 1000317),
    (1000326, 'Slim Cat (Black)', 'Cats', 1000323),
    (1000328, 'Slim Cat (Calico)', 'Cats', 1000323),
    (1000324, 'Slim Cat (Ginger)', 'Cats', 1000323),
    (1003960, 'Slim Cat (Russian Blue)', 'Cats', 1000323),
    (1000327, 'Slim Cat (Two-Tone)', 'Cats', 1000323),
    (1000325, 'Slim Cat (White)', 'Cats', 1000323),
    (1000337, 'Delesyia Cat', 'Cats', 0),
    (1000336, 'Demeniss Cat', 'Cats', 0),
    (1000335, 'Hernand Cat', 'Cats', 0),
    (1000338, 'Pailune Cat', 'Cats', 0),
    (1001853, 'Pororin Cat', 'Cats', 0),
    (1001854, 'Red Orc Cat', 'Cats', 0),
    (1002899, 'Tashkalp Cat', 'Cats', 0),
    # Dogs
    (1003681, 'Boarhound #1', 'Dogs', 30022),
    (1003682, 'Boarhound #2', 'Dogs', 30022),
    (1003683, 'Boarhound #3', 'Dogs', 30022),
    (1003684, 'Boarhound #4', 'Dogs', 30022),
    (1003685, 'Boarhound #8', 'Dogs', 30022),
    (1003686, 'Boarhound #9', 'Dogs', 30022),
    (1003687, 'Boarhound #10', 'Dogs', 30022),
    (32427, 'Boarhound with Pack', 'Dogs', 30022),
    (1003667, 'Pointy-Eared Bulldog #2', 'Dogs', 30186),
    (1003668, 'Pointy-Eared Bulldog #3', 'Dogs', 30186),
    (1003669, 'Pointy-Eared Bulldog #4', 'Dogs', 30186),
    (1003670, 'Pointy-Eared Bulldog #5', 'Dogs', 30186),
    (1003671, 'Pointy-Eared Bulldog #6', 'Dogs', 30186),
    (1003672, 'Pointy-Eared Bulldog #7', 'Dogs', 30186),
    (1003673, 'Pointy-Eared Bulldog #8', 'Dogs', 30186),
    (1003688, 'Boarhound Puppy #1', 'Dogs', 31336),
    (1003689, 'Boarhound Puppy #2', 'Dogs', 31336),
    (1003690, 'Boarhound Puppy #3', 'Dogs', 31336),
    (1003691, 'Boarhound Puppy #4', 'Dogs', 31336),
    (1003692, 'Boarhound Puppy #8', 'Dogs', 31336),
    (1003693, 'Boarhound Puppy #9', 'Dogs', 31336),
    (1003694, 'Boarhound Puppy #10', 'Dogs', 31336),
    (1003695, 'Saluki #1', 'Dogs', 31400),
    (1003696, 'Saluki #2', 'Dogs', 31400),
    (1003697, 'Saluki #3', 'Dogs', 31400),
    (1003698, 'Saluki #4', 'Dogs', 31400),
    (1003699, 'Saluki #5', 'Dogs', 31400),
    (1003700, 'Greyhound #1', 'Dogs', 32181),
    (1003701, 'Greyhound #2', 'Dogs', 32181),
    (1003702, 'Greyhound #3', 'Dogs', 32181),
    (1003703, 'Greyhound #4', 'Dogs', 32181),
    (1003704, 'Greyhound #5', 'Dogs', 32181),
    (1003705, 'Greyhound #6', 'Dogs', 32181),
    (1003706, 'Greyhound #7', 'Dogs', 32181),
    (1003707, 'Greyhound #8', 'Dogs', 32181),
    (1003708, 'Greyhound #9', 'Dogs', 32181),
    (1003709, 'Greyhound #10', 'Dogs', 32181),
    (1003710, 'Beagle #1', 'Dogs', 32189),
    (1003711, 'Beagle #2', 'Dogs', 32189),
    (1003712, 'Beagle #3', 'Dogs', 32189),
    (1003713, 'Beagle #4', 'Dogs', 32189),
    (1003674, 'Floppy-Eared Bulldog #1', 'Dogs', 1001396),
    (1003675, 'Floppy-Eared Bulldog #2', 'Dogs', 1001396),
    (1003676, 'Floppy-Eared Bulldog #3', 'Dogs', 1001396),
    (1003677, 'Floppy-Eared Bulldog #4', 'Dogs', 1001396),
    (1003678, 'Floppy-Eared Bulldog #5', 'Dogs', 1001396),
    (1003679, 'Floppy-Eared Bulldog #6', 'Dogs', 1001396),
    (1003680, 'Floppy-Eared Bulldog #7', 'Dogs', 1001396),
    (1003665, 'Jindo #2', 'Dogs', 1002258),
    (1003666, 'Jindo #3', 'Dogs', 1002258),
    (1000370, 'Delesyia Dog', 'Dogs', 0),
    (1000369, 'Demeniss Dog', 'Dogs', 0),
    (1000368, 'Hernand Dog', 'Dogs', 0),
    (1002271, 'Hernand Dog 2', 'Dogs', 0),
    (1001855, 'Jijeong Temple Dog', 'Dogs', 0),
    (1001856, 'Longleaf Dog', 'Dogs', 0),
    (1000371, 'Pailune Dog', 'Dogs', 0),
    (31195, 'Righteous Arrows Dog', 'Dogs', 0),
    (1002900, 'Tashkalp Dog', 'Dogs', 0),
    (59002, 'Trained Dog', 'Dogs', 0),
]


def pet_entries() -> List[Tuple[int, str, str, bool]]:
    """(key, name, group, is_variant) in display order: each pet followed by
    its variants, the town pets at the end of their group."""
    by_base: Dict[int, list] = {}
    for k, n, g, b in PET_VARIANTS:
        by_base.setdefault(b, []).append((k, n, g, True))
    out: List[Tuple[int, str, str, bool]] = []
    groups = [g for g in PET_GROUPS]
    for g in groups:
        for k, n, pg in PETS:
            if pg != g:
                continue
            out.append((k, n, pg, False))
            out.extend(by_base.get(k, []))
        out.extend(e for e in by_base.get(0, []) if e[2] == g)
    return out


def portrait_path(key: int):
    """Path of the mount's or pet's picture (mount_portraits/ or
    pet_portraits/<key>.webp, 128 px, made from the game's own portrait
    textures), or None."""
    name = f"{int(key)}.webp"
    for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))):
        if base:
            for folder in ("mount_portraits", "pet_portraits"):
                p = os.path.join(base, folder, name)
                if os.path.isfile(p):
                    return p
    return None

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
