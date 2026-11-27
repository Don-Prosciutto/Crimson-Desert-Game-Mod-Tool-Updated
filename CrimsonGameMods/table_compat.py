"""Game 2.06 tables for a parser that only knows the layout up to 2.05.

Since game 2.06 a table's records no longer start with their name: the name
sits in the index (.pabgh) and the record carries a row number right after
its key. The bundled dmm_parser (upstream 9d9747c, game 2.05.01) cannot read
that yet. Until upstream can, this layer sits between the tool and the
archives:

  reading  (dmm_parser.extract_file): a 2.06 table pair is handed out in the
           old layout - name back in front of each record, row number out,
           old index. Every reader in the tool then works as before.
  writing  (PackGroupBuilder): a table in the old layout is turned back into
           the 2.06 layout before it goes into the archive. Row numbers come
           from the original table (DLC tables number their rows their own
           way); records the original lacks get the next free number.

Only bytes are moved; decoding stays with dmm_parser. The conversion is
exact: game -> old -> game gives the original bytes for every 2.06.00 table
except characterappearanceindexinfo and the DLC's npcfriendlyinfo, which are
passed through untouched.

Since dmm-parser f6f1de3 (game 2.06.00) the parser itself works the same
way: its table readers keep the old layout, and named_to_legacy /
named_from_legacy move the bytes (with a "sidecar" for the row numbers, the
way DMM does it). When the bundled parser has those functions this layer
uses them; the own conversion below is only the fallback for 9d9747c.
Off with CGM_NO_TABLE_COMPAT=1. No Qt in here.
"""

from __future__ import annotations

import hashlib
import logging
import os
import struct
import sys
import threading

from table_index import read_index, TableIndex, IndexEntry, OLD, NEW

log = logging.getLogger(__name__)

_HEADER_EXTS = (".staticinfoheader", ".pabgh")
_BODY_EXTS = (".staticinfobody", ".pabgb")

# Tables that 9d9747c reads completely (no raw records) after the conversion
# and writes back byte-identical, checked on game 2.06.00
# (scripts/2.06.00/rundweg_test.py). Old record readers in the tool are only
# allowed on these; the other tables have new or changed fields.
VERIFIED_MAIN = frozenset({
    "actionrestrictionorderinfo", "aiactionattributeinfo", "aidialogstringinfo",
    "aidialogtypeinfo", "aieventtableinfo", "aimemoryinfo", "aimovespeedinfo",
    "autospawnfilterinfo", "bitmapposition", "breakableobjectinfo",
    "categorygroupinfo", "categoryinfo", "characterchange", "charactergroupinfo",
    "conditioninfo", "contentsphaseinfo", "crafttoolgroupinfo", "crafttoolinfo",
    "detectinfo", "detectreactioninfo", "dialogvoiceinfo", "effectinfo",
    "elementalmaterialinfo", "entitlementinfo", "equiptypeinfo", "factiongroup",
    "factionnodespawninfo", "factionoperationgroupinfo", "factionrelationgroup",
    "factionspawndatainfo", "factionwaypoint", "fieldlevelnametableinfo",
    "fieldreviveinfo", "gameadvicegroupinfo", "gameadviceinfo", "gameeventhandler",
    "gameglobaleffectinfo", "gameplaytrigger", "gameplayvariableinfo", "gamestartinfo",
    "gimmickeventtableinfo", "gimmickgateconnection", "gimmickgateinfo",
    "gimmickgroupinfo", "gimmickinfo", "globalgameevent", "globalgameeventgroup",
    "globalstagesequencerinfo", "houseinfo", "housingobjectgroupinfo", "inventory",
    "itemgroupinfo", "iteminfo", "itemuseinfo", "jobinfo", "keymap",
    "knowledgegroupinfo", "knowledgeinfo", "levelgimmicksceneobjectinfo",
    "localstringinfo", "materialblooddecalinfo", "materialmatchinfo",
    "materialrelationinfo", "mercenarygroupinfo", "mercenaryinfo",
    "npcactivitygroupinfo", "npcactivityinfo", "npcinfo", "partprefabdyeslotinfo",
    "partprefabdyetexturepalleteinfo", "patterndescriptioninfo", "personalityinfo",
    "platformachievementinfo", "questgaugeinfo", "questgroupinfo", "quickslotinfo",
    "quicktimeeventinfo", "regioninfo", "relationinfo", "reserveslot", "royalsupply",
    "sequencerspawninfo", "skillgroupinfo", "skilltreegroupinfo", "skilltreeinfo",
    "socketgroupinfo", "socketinfo", "specialmode", "stageinfo", "statchangeinfo",
    "statusgroupinfo", "stringinfo", "sublevelinfo", "terrainregionnaviinfo",
    "tribeinfo", "triggerregioninfo", "uifiltergroupinfo", "uisocialaction",
    "uitalktreeinfo", "validscheduleaction", "vehicleinfo", "vibratepatterninfo",
    "wantedinfo",
})
VERIFIED_DLC = frozenset({
    "aidialogstringinfo", "bitmapposition", "charactergroupinfo", "conditioninfo",
    "effectinfo", "entitlementinfo", "factiongroup", "factionmanagement",
    "factionnodespawninfo", "factionspawndatainfo", "factionwaypoint",
    "fieldreviveinfo", "gameadvicegroupinfo", "gameadviceinfo", "gameeventhandler",
    "gameplaytrigger", "gameplayvariableinfo", "gimmickgroupinfo", "gimmickinfo",
    "globalgameevent", "globalgameeventgroup", "globalstagesequencerinfo", "houseinfo",
    "housingobjectgroupinfo", "inventory", "itemgroupinfo", "iteminfo", "itemuseinfo",
    "knowledgegroupinfo", "knowledgeinfo", "localstringinfo", "managementbuffinfo",
    "managementneedssynergyinfo", "materialmatchinfo", "multichangeinfo",
    "npcactivitygroupinfo", "npcactivityinfo", "npcinfo", "npcnameinfo",
    "patterndescriptioninfo", "platformachievementinfo", "questgaugeinfo",
    "questgroupinfo", "regioninfo", "sequencerspawninfo", "skilltreeinfo",
    "specialmode", "stageinfo", "statusgroupinfo", "statusinfo", "stringinfo",
    "sublevelinfo", "uifiltergroupinfo", "vehicleinfo",
})

_lock = threading.Lock()
_pairs: dict = {}        # (game_dir, group, dir, stem) -> converted pair or None
_state: dict = {}        # (dir, stem) -> what to_new needs to restore the 2.06 layout
_orig_new: dict = {}     # (dir, stem) -> (index, body) as in the game
_converted: dict = {}    # sha1(old index) -> stem, for is_verified()
_active = None


def active() -> bool:
    global _active
    if _active is None:
        _active = not os.environ.get("CGM_NO_TABLE_COMPAT")
    return _active


def _parser():
    """The loaded dmm_parser if it has the official 2.06 conversion, else None."""
    m = sys.modules.get("dmm_parser")
    return m if m is not None and hasattr(m, "named_to_legacy") else None


def to_legacy(head: bytes, body: bytes):
    """(old index, old body, state) for a 2.06 table, or None if it is not one."""
    p = _parser()
    if p is not None:
        if not p.is_named_pair(head, body):
            return None
        h, b, sc = p.named_to_legacy(head, body)
        return bytes(h), bytes(b), ("dmm", bytes(sc))
    idx = read_index(head)
    if idx.layout != NEW or not idx.entries:
        return None
    oh, ob, rows = as_old(head, body)
    return oh, ob, ("own", rows, idx.count_size, idx.key_size)


def from_legacy(head: bytes, body: bytes, state):
    """(index, body) in the 2.06 layout from the old layout."""
    if state[0] == "dmm":
        p = _parser()
        h, b = p.named_from_legacy(bytes(head), bytes(body), state[1])
        return bytes(h), bytes(b)
    return to_new(head, body, state[1], state[2], state[3])


def _split(name: str):
    low = name.lower()
    for ext in _HEADER_EXTS:
        if low.endswith(ext):
            return name[: -len(ext)], "head", ext
    for ext in _BODY_EXTS:
        if low.endswith(ext):
            return name[: -len(ext)], "body", ext
    return None, None, None


def _sibling(stem: str, kind: str, ext: str) -> str:
    if ext.startswith(".static"):
        return stem + (".staticinfobody" if kind == "head" else ".staticinfoheader")
    return stem + (".pabgb" if kind == "head" else ".pabgh")


def as_old(head: bytes, body: bytes):
    """(index, body) of a 2.06 table in the old layout, plus key -> row."""
    idx = read_index(head)
    ks = idx.key_size
    out = TableIndex(OLD, idx.count_size, ks)
    new_body = bytearray()
    rows = {}
    for e, a, z in idx.spans(len(body)):
        rec = body[a:z]
        rows[e.key] = struct.unpack_from("<I", rec, ks)[0]
        out.entries.append(IndexEntry(e.key, len(new_body), None, None, e.raw_key))
        new_body += struct.pack("<I", len(e.name_raw)) + e.name_raw + rec[:ks] + rec[ks + 4:]
    return out.to_bytes(), bytes(new_body), rows


def to_new(head: bytes, body: bytes, rows: dict, count_size: int, key_size: int):
    """(index, body) in the 2.06 layout from a table in the old layout."""
    idx = read_index(head, OLD)
    nxt = max(rows.values(), default=-1) + 1
    out = TableIndex(NEW, count_size, key_size)
    new_body = bytearray()
    for e, a, z in idx.spans(len(body)):
        rec = body[a:z]
        ln = struct.unpack_from("<I", rec, 0)[0]
        name_raw = bytes(rec[4:4 + ln])
        rest = rec[4 + ln:]
        if rest[:key_size] != e.raw_key:
            raise ValueError(f"record {e.key}: key does not follow the name")
        r = rows.get(e.key)
        if r is None:
            r = nxt
            nxt += 1
        rec_new = rest[:key_size] + struct.pack("<I", r) + rest[key_size:]
        out.entries.append(IndexEntry(e.key, len(new_body), len(rec_new),
                                      name_raw.decode("utf-8", "replace"), e.raw_key, name_raw))
        new_body += rec_new
    return out.to_bytes(), bytes(new_body)


def _convert_pair(native, game_dir, group, dir_path, stem, ext):
    key = (str(game_dir), str(group), dir_path, stem)
    with _lock:
        if key in _pairs:
            return _pairs[key]
    hname = stem + (".staticinfoheader" if ext.startswith(".static") else ".pabgh")
    bname = stem + (".staticinfobody" if ext.startswith(".static") else ".pabgb")
    pair = None
    try:
        head = bytes(native(game_dir, group, dir_path, hname))
        body = bytes(native(game_dir, group, dir_path, bname))
        conv = to_legacy(head, body)
        if conv is not None:
            oh, ob, state = conv
            if from_legacy(oh, ob, state) == (head, body):
                pair = (oh, ob)
                with _lock:
                    _state.setdefault((dir_path, stem), state)
                    _orig_new.setdefault((dir_path, stem), (head, body))
                    _converted[hashlib.sha1(oh).hexdigest()] = stem
            else:
                log.warning("table %s: 2.06 layout does not convert exactly, left as is", stem)
    except Exception as e:  # noqa: BLE001 - a missing sibling etc.: hand out as stored
        log.debug("table %s: no conversion (%s)", stem, e)
    with _lock:
        _pairs[key] = pair
    return pair


def extract(native, game_dir, group, dir_path, file_name):
    """dmm_parser.extract_file with 2.06 tables handed out in the old layout."""
    if not active():
        return native(game_dir, group, dir_path, file_name)
    stem, kind, ext = _split(file_name)
    if stem is None:
        return native(game_dir, group, dir_path, file_name)
    pair = _convert_pair(native, game_dir, group, dir_path, stem, ext)
    if pair is None:
        return native(game_dir, group, dir_path, file_name)
    return pair[0] if kind == "head" else pair[1]


def is_verified(old_head: bytes) -> bool:
    """False for an index this layer converted from a 2.06 table whose record
    layout changed beyond the name move (old record readers must not use it)."""
    stem = _converted.get(hashlib.sha1(bytes(old_head)).hexdigest())
    if stem is None:
        return True
    base, _, tag = stem.partition(".")
    return base in (VERIFIED_DLC if tag else VERIFIED_MAIN)


class PackWriter:
    """Wraps PackGroupBuilder.add_file: table pairs in the old layout go into
    the archive in the 2.06 layout. Halves wait for each other; a half that
    comes alone is converted with the original other half."""

    def __init__(self, add):
        self._add = add
        self._wait = {}

    def add(self, dir_path, file_name, data):
        stem, kind, ext = _split(file_name)
        if not active() or stem is None or (dir_path, stem) not in _state:
            return self._add(dir_path, file_name, data)
        data = bytes(data)
        if kind == "head":
            try:
                if read_index(data, OLD) is None:
                    pass
            except ValueError:                              # not the old layout: already 2.06
                return self._add(dir_path, file_name, data)
        slot = self._wait.setdefault((dir_path, stem), {})
        slot[kind] = (file_name, data)
        if len(slot) == 2:
            self._flush(dir_path, stem)
        return None

    def _flush(self, dir_path, stem):
        slot = self._wait.pop((dir_path, stem))
        state = _state[(dir_path, stem)]
        orig_h, orig_b = _orig_new[(dir_path, stem)]
        head = slot.get("head")
        body = slot.get("body")
        try:
            if head is None:
                old_h = to_legacy(orig_h, orig_b)[0]
                nh, nb = from_legacy(old_h, body[1], state)
                if nh != orig_h:
                    raise ValueError("records changed size but no index was written")
                self._add(dir_path, body[0], nb)
                return
            if body is None:
                old_b = to_legacy(orig_h, orig_b)[1]
                nh, nb = from_legacy(head[1], old_b, state)
                self._add(dir_path, head[0], nh)
                return
            nh, nb = from_legacy(head[1], body[1], state)
        except Exception as e:
            raise RuntimeError(f"{stem}: could not write the table in the game 2.06 layout: {e}") from e
        self._add(dir_path, head[0], nh)
        self._add(dir_path, body[0], nb)

    def finish(self):
        for dir_path, stem in list(self._wait):
            self._flush(dir_path, stem)


def legacy_body_for(game_path: str, group: str, stem: str, body: bytes,
                    head: bytes = None) -> bytes:
    """`body` of table `stem`, read from the archives some other way (a raw
    PAZ read), in the old layout. `head` is its index if the caller has it;
    otherwise the game's own index is used. Unchanged when the table is not
    in the 2.06 layout or this layer is off."""
    if not active():
        return body
    try:
        if head is None:
            p = sys.modules.get("dmm_parser")
            if p is None:
                import dmm_parser as p  # noqa: PLC0415
            native = getattr(p, "_native_extract_file", None) or p.extract_file
            head = bytes(native(game_path, group, "gamedata/binarystaticinfo__/bin",
                                stem + ".staticinfoheader"))
        conv = to_legacy(bytes(head), bytes(body))
        if conv is not None:
            return conv[1]
    except Exception as e:  # noqa: BLE001
        log.warning("table %s: raw read not converted (%s)", stem, e)
    return body
