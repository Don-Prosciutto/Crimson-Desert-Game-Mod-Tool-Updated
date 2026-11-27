"""Wyvern: fire breath, fireballs and a passenger seat - own build, CrimsonGameMods.

Everything here is built by our own code from the unmodded game files, without
an ASI, without speed changes and without whole tables:

  * m0004_ride_dragon_upper.paac (rider action chart shared by dragon, T-rex
    dragon and wyvern; read/written with paac_format):
      - fireballs: the wyvern variants of the fireball states shoot the
        projectile of their dragon base state (fireball instead of wind ball);
      - fire breath: wyvern variants (tag "wyvern") directly after the dragon's
        breath start / loop / end states, with the wyvern breath animations;
        entry "wyvern AND key" in the tested flight states; in the start state
        "wyvern AND key released" ends; the attack-input branch is taken out of
        the three breath states; the breath states get the flight movement mode
        (record +238, the dragon's are ground states - without this the breath
        only glows for a moment); hold = a new fire stream every 3.33 s (the
        dragon's rhythm, no stacking);
      - the projectile event of the wyvern gets its own spawn index (920, the
        wyvern's mouth in the game's runtime skeleton - measured in game; the .pab
        has only 327 bones so it cannot be derived here).
  * cd_m0004_00_wyvern.pab: second rider bone B_Rider_02 (0.40 m above the
    saddle point, so a passenger sits on the back and not in the body).
  * Field JSON (vehicleinfo, characterinfo, interactioninfo): second seat, carry
    dead/bound people, NPC on the back seat.

Game 2.05.00 and 2.06.00 (paac_format reads both layouts). No Qt in here.
"""

from __future__ import annotations

import io
import json
import struct
import zipfile
from typing import Callable, Dict, List, Optional

import paac_format
from paac_format import lookup3, parse, build

UPPER_GROUP = "0010"
UPPER_DIR = "actionchart/bin__/upperaction/2_mon"
UPPER_NAME = "m0004_ride_dragon_upper.paac"
PAB_GROUP = "0009"
PAB_DIR = "character/model/2_mon/cd_m0004_00_dragon/cd_m0004_00_wyvern"
PAB_NAME = "cd_m0004_00_wyvern.pab"

KEYS = {"rt": "key_hardattack", "lb": "key_guard"}   # RT = strong attack, LB = guard
DEFAULT_KEY = "rt"
SEAT_UP = 0.40


class WyvernError(Exception):
    pass


# ───────────────────────────────────────────────────────── skeleton (.pab)
_MAT = 64
_TRS = 40


def pab_parse(data: bytes) -> dict:
    """bones of a .pab: u16 count @20, records from 22 (hash, name, parent,
    4 x float[16] model/model-inverse/local/local-inverse, float[10] trs),
    then i32 parents[count], u8 flags[count], rest."""
    count = struct.unpack_from("<H", data, 20)[0]
    p = 22
    bones = []
    for _ in range(count):
        p += 4
        n = data[p]; p += 1
        name = data[p:p + n].decode("ascii"); p += n
        parent = struct.unpack_from("<i", data, p)[0]; p += 4
        mats = [list(struct.unpack_from("<16f", data, p + k * _MAT)) for k in range(4)]
        p += 4 * _MAT + _TRS
        bones.append({"name": name, "parent": parent, "model": mats[0]})
    parents = list(struct.unpack_from(f"<{count}i", data, p))
    flags_off = p + 4 * count
    return {"count": count, "bones": bones, "bones_end": p, "parents": parents,
            "flags": data[flags_off:flags_off + count], "rest_off": flags_off + count}


def _matmul(a: List[float], b: List[float]) -> List[float]:
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def _inverse(m: List[float]) -> List[float]:
    a = [list(m[r * 4:r * 4 + 4]) + [1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]
    for c in range(4):
        piv = max(range(c, 4), key=lambda r: abs(a[r][c]))
        a[c], a[piv] = a[piv], a[c]
        d = a[c][c]
        if abs(d) < 1e-12:
            raise WyvernError("bone matrix cannot be inverted")
        a[c] = [x / d for x in a[c]]
        for r in range(4):
            if r != c and a[r][c]:
                f = a[r][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c])]
    return [a[r][4 + c] for r in range(4) for c in range(4)]


def pab_add_bone(data: bytes, name: str, parent: int, translation) -> bytes:
    """`data` with one more bone (no rotation) at the end. Matrices are
    row-vector: model = local @ parentModel."""
    s = pab_parse(data)
    if any(b["name"] == name for b in s["bones"]):
        raise WyvernError(f"{name} is already in the skeleton")
    local = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0] + list(translation) + [1.0]
    model = _matmul(local, s["bones"][parent]["model"])
    mats = [model, _inverse(model), local, _inverse(local)]
    nb = name.encode("ascii")
    rec = (struct.pack("<IB", lookup3(nb), len(nb)) + nb + struct.pack("<i", parent)
           + b"".join(struct.pack("<16f", *m) for m in mats)
           + struct.pack("<10f", 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, *translation))
    out = bytearray(data[:s["bones_end"]]) + rec
    out += struct.pack(f"<{s['count'] + 1}i", *(s["parents"] + [parent]))
    out += bytes(s["flags"]) + b"\x00"
    out += data[s["rest_off"]:]
    struct.pack_into("<H", out, 20, s["count"] + 1)
    return bytes(out)


def build_pab(vanilla: bytes, seat_up: float = SEAT_UP) -> bytes:
    """Second rider bone behind the rider, on the saddle bone (index 29)."""
    s = pab_parse(vanilla)
    if s["count"] < 30 or "Rein" not in s["bones"][31]["name"]:
        raise WyvernError("unexpected wyvern skeleton (other game version?)")
    return pab_add_bone(vanilla, "B_Rider_02", 29, (-0.0, -0.1784 + seat_up, 0.7504))


# ─────────────────────────────────────────────────── action chart (.paac)
TAG_WYVERN = lookup3("wyvern")          # 0xa9b3d781
OP_KEY, OP_TAG = 234, 311     # AND/OR/NOT differ per game version: p.cond_ops
PROJ_SPAWN_OFS = {"2.06": 244, "2.05": 240}   # u16 spawn index in a projectile event
EV_PROJECTILE, EV_UPPER_ANIM, EV_DRAGON_VOICE = 0x07, 0x73, 0x4f

REC_BREATH_STT = 0xc6b2f626      # record name hashes (stable ids)
REC_BREATH_ING = 0x4d903ffd
REC_BREATH_END = 0x0eec44be
FLIGHT_RECORD = 0xb44ed8e4       # main flight state (node 0)
# states the breath can start from (tested; other records with the same
# animation run on another layer and cut the breath off)
BREATH_ENTRY_RECORDS = (0x0dcf66f2, 0x60ef55fd, 0x8767d78a, 0xabca7faf, 0xb44ed8e4,
                        0xb8a26cdd, 0xe066175d)
AIR_STATE_ANIMS = ("air_move_fly_walk_f_ing", "air_aim_std_idle")

WYV_DIR = "2_mon/cd_m0004_00_dragon/cd_m0004_00_wyvern/00_mon/"
WYV_BREATH = {"stt": WYV_DIR + "cd_rd_wyvern_basic_00_00_att_nor_std_breath_stt_00.paa",
              "ing": WYV_DIR + "cd_rd_wyvern_basic_00_00_att_nor_std_breath_ing_00.paa",
              "end": WYV_DIR + "cd_rd_wyvern_basic_00_00_att_nor_std_breath_end_00.paa"}
WYV_BREATH_LEN = 1.4666666984558105     # length of the three wyvern breath animations
WYV_PROJECTILE_TIME = 1.0333333015441895  # shot time in breath_stt (as the wyvern fireball)
WYV_MOUTH_SPAWN = 920                   # spawn index of the wyvern's mouth (see top)


def _u16(b, o): return struct.unpack_from("<H", b, o)[0]
def _u32(b, o): return struct.unpack_from("<I", b, o)[0]


def _set(b, fmt, o, v):
    b = bytearray(b); struct.pack_into(fmt, b, o, v); return bytes(b)


def node_tag(nd): return _u32(nd, 8)
def node_anim(nd): return _u16(nd, 4 + 152)


def node_events(nd):
    tab = struct.unpack_from("<20H", nd, 4 + 110)
    z = _u16(nd, 4 + 150)
    o = 4 + 164 + tab[19] + 16 * z
    return [list(struct.unpack_from("<ffIIHH", nd, o + 1 + 20 * i)) for i in range(nd[o])], o


def with_events(nd, events):
    _, o = node_events(nd)
    events = sorted(events, key=lambda t: t[0])
    out = bytearray(nd[:o]); out.append(len(events))
    for seq, t in enumerate(events):
        out += struct.pack("<ffIIHH", t[0], t[1], t[2], seq, t[4], t[5])
    return bytes(out)


def rec_hash(r): return _u32(r, 24)
def rec_node(r): return _u16(r, 84)
def rec_range(r): return _u16(r, 228), _u16(r, 232)
def event_type(p, word): return _u32(p.blob, 4 * word) & 0xffff


def anim_name(p, idx):
    lst = p.lists[1]
    return lst[idx].decode("latin1") if idx < len(lst) else ""


def _event_len(p, word):
    starts = sorted({t[2] for nd in p.nodes for t in node_events(nd)[0]} | {len(p.blob) // 4})
    return 4 * (min(s for s in starts if s > word) - word)


# conditions (prefix bytecode)
def KEY(p, name):
    pool = p.lists[0]
    b = name.encode()
    if b not in pool:
        pool.append(b)
    return ("KEY", pool.index(b), lookup3(name))
def TAG(h): return ("TAG", h)
def AND(a, b): return ("AND", a, b)
def OR(a, b): return ("OR", a, b)
def NOT(a): return ("NOT", a)


def emit(p, expr):
    """Append an expression to D1/D2, return (start, count) in D2."""
    start = len(p.D2); words = []
    OP_AND, OP_OR, OP_NOT = p.cond_ops
    def rec(e):
        k = e[0]
        if k in ("AND", "OR"):
            words.append([OP_AND if k == "AND" else OP_OR]); rec(e[1]); rec(e[2])
        elif k == "NOT":
            words.append([OP_NOT]); rec(e[1])
        elif k == "KEY":
            words.append([OP_KEY, e[1], e[2], 0, 0])
        else:
            words.append([OP_TAG, 0, e[1], 0, 0])
    rec(expr)
    d1 = bytearray(p.D1)
    for w in words:
        p.D2.append(len(d1) // 4)
        d1 += struct.pack("<%dI" % len(w), *w)
    p.D1 = bytes(d1)
    return start, len(words)


def decode(p, start, cnt):
    OP_AND, OP_OR, OP_NOT = p.cond_ops
    seq = []
    for i in range(start, start + cnt):
        w = p.D2[i]; op = _u32(p.D1, 4 * w)
        seq.append((op,) if op in (OP_AND, OP_OR, OP_NOT) else struct.unpack_from("<5I", p.D1, 4 * w))
    pos = [0]
    def rec():
        x = seq[pos[0]]; pos[0] += 1
        if x[0] in (OP_AND, OP_OR):
            return ("AND" if x[0] == OP_AND else "OR", rec(), rec())
        if x[0] == OP_NOT:
            return ("NOT", rec())
        if x[0] == OP_KEY:
            return ("KEY", x[1], x[2])
        if x[0] == OP_TAG:
            return ("TAG", x[2])
        return ("OP",) + tuple(x)
    out = rec()
    return out if pos[0] == len(seq) else None


def s5_cond(p, i, which):
    e = p.S5[i]
    start = _u16(e, 36 if which == "A" else 38)
    cnt = e[42] if which == "A" else e[43]
    return decode(p, start, cnt) if cnt else None


def s5_with(e, A=None, B=None):
    e = bytearray(e)
    if A is not None:
        struct.pack_into("<H", e, 36, A[0]); e[42] = A[1]
    if B is not None:
        struct.pack_into("<H", e, 38, B[0]); e[43] = B[1]
    return bytes(e)


def s6b_ref(template, s5_index):
    return template[:12] + struct.pack("<I", s5_index) + template[16:]


def patch_fireballs(p) -> int:
    """Wyvern variant shoots the projectile of its base state."""
    changed = 0
    users: Dict[int, set] = {}
    for i, nd in enumerate(p.nodes):
        for t in node_events(nd)[0]:
            users.setdefault(t[2], set()).add(i)
    for i in range(1, len(p.nodes)):
        nd = p.nodes[i]
        if node_tag(nd) != TAG_WYVERN:
            continue
        b = i - 1
        while b >= 0 and node_tag(p.nodes[b]) != 0:
            b -= 1
        if b < 0:
            continue
        base = [t[2] for t in node_events(p.nodes[b])[0] if event_type(p, t[2]) == EV_PROJECTILE]
        wyv = [t[2] for t in node_events(nd)[0] if event_type(p, t[2]) == EV_PROJECTILE]
        if len(base) != 1 or len(wyv) != 1:
            continue
        bh = p.blob[4 * base[0] + 12:4 * base[0] + 16]
        wo = 4 * wyv[0] + 12
        if p.blob[wo:wo + 4] == bh or any(node_tag(p.nodes[u]) != TAG_WYVERN for u in users[wyv[0]]):
            continue
        blob = bytearray(p.blob); blob[wo:wo + 4] = bh; p.blob = bytes(blob)
        changed += 1
    if changed:
        relabel_fireballs(p)
    return changed


def relabel_fireballs(p) -> int:
    """Key guide (S7, one entry per input id: u16 label = pool index, u16 key):
    "fire wind ball" -> "fire fireball" (label only, no logic)."""
    pool = p.lists[0]
    if b"keyguide_wyvern_windball" not in pool or b"keyguide_fireball" not in pool:
        return 0
    wind, fire = pool.index(b"keyguide_wyvern_windball"), pool.index(b"keyguide_fireball")
    n = 0
    for i, e in enumerate(p.S7):
        if _u16(e, 0) == wind:
            p.S7[i] = struct.pack("<H", fire) + e[2:]
            n += 1
    return n


def _insert_node(p, after, nd):
    pos = after + 1
    p.nodes.insert(pos, nd)
    p.records = [_set(r, "<H", 84, rec_node(r) + 1) if rec_node(r) >= pos else r for r in p.records]


def _wyvern_variant(p, base_nd, anim_idx, dur, proj_time, w_upper_event, mask_idx, proj_map):
    nd = bytearray(base_nd)
    struct.pack_into("<f", nd, 4, dur)
    struct.pack_into("<I", nd, 8, TAG_WYVERN)
    struct.pack_into("<I", nd, 12, 0x2000)              # flags of the wyvern variants
    struct.pack_into("<H", nd, 4 + 66, mask_idx)        # upper-body mask "WyvernHead"
    struct.pack_into("<HH", nd, 4 + 152, anim_idx, anim_idx)
    nd = bytes(nd)
    out = []
    for t in node_events(nd)[0]:
        ty = event_type(p, t[2])
        if ty == EV_DRAGON_VOICE:
            continue
        if ty == EV_UPPER_ANIM:
            t[2] = w_upper_event
        if ty == EV_PROJECTILE:
            if proj_time is not None:
                t[0] = proj_time
            t[2] = proj_map(t[2])
        out.append(t)
    return with_events(nd, out)


def patch_fire_breath(p, key: str = KEYS[DEFAULT_KEY], interval: Optional[float] = None,
                      keyguide: bool = True) -> dict:
    recidx = {rec_hash(r): i for i, r in enumerate(p.records)}
    try:
        r_stt, r_ing, r_end = (recidx[h] for h in (REC_BREATH_STT, REC_BREATH_ING, REC_BREATH_END))
    except KeyError:
        raise WyvernError("fire breath states not found (other game version?)")
    for r, part in ((r_stt, "firebreath_stt"), (r_ing, "firebreath_ing"), (r_end, "firebreath_end")):
        if part not in anim_name(p, node_anim(p.nodes[rec_node(p.records[r])])):
            raise WyvernError("unexpected animation in breath state %d" % r)
    if node_tag(p.nodes[rec_node(p.records[r_stt]) + 1]) == TAG_WYVERN:
        raise WyvernError("the wyvern fire breath is already in this file")
    pool = p.lists[0]
    if b"WyvernHead" not in pool:
        raise WyvernError("mask WyvernHead not found")
    mask_idx = pool.index(b"WyvernHead")
    hard = KEY(p, "key_hardattack"); wyv = TAG(TAG_WYVERN)
    same_key = key == "key_hardattack"
    bkey = hard if same_key else KEY(p, key)

    paa = p.lists[1]
    anim = {}
    for k, path in WYV_BREATH.items():
        b = path.encode()
        if b not in paa:
            paa.append(b)
        anim[k] = paa.index(b)
    w_upper = sorted({t[2] for nd in p.nodes if node_tag(nd) == TAG_WYVERN
                      for t in node_events(nd)[0] if event_type(p, t[2]) == EV_UPPER_ANIM})
    if len(w_upper) != 1:
        raise WyvernError("wyvern animation event not unique")
    w_upper = w_upper[0]

    # conditions
    ing_start, ing_cnt = rec_range(p.records[r_ing])
    ing_entries = list(p.S6b[ing_start:ing_start + ing_cnt])
    rel_i = held_i = None
    for j, e in enumerate(ing_entries):
        if _u32(e, 0):
            continue
        s = _u32(e, 12)
        if s5_cond(p, s, "B") == NOT(hard): rel_i = (j, s)
        if s5_cond(p, s, "B") == hard: held_i = (j, s)
    enter_src = None
    for s in range(len(p.S5)):
        if _u32(p.S5[s], 20) == REC_BREATH_STT and s5_cond(p, s, "B") == hard:
            enter_src = s
    if rel_i is None or held_i is None or enter_src is None:
        raise WyvernError("breath conditions not found")
    tmpl = p.S6b[ing_start + rel_i[0]]

    def new_range(r, entries):
        st = len(p.S6b); p.S6b += entries
        p.records[r] = _set(_set(p.records[r], "<H", 228, st), "<H", 232, len(entries))

    if not same_key:
        # hold / release in the loop: dragon = strong attack, wyvern = own key
        held = OR(AND(NOT(wyv), hard), AND(wyv, bkey))
        released = OR(AND(NOT(wyv), NOT(hard)), AND(wyv, NOT(bkey)))
        i_rel, i_held = len(p.S5), len(p.S5) + 1
        p.S5 += [s5_with(p.S5[rel_i[1]], B=emit(p, released)),
                 s5_with(p.S5[held_i[1]], B=emit(p, held))]
        ing_entries[rel_i[0]] = s6b_ref(tmpl, i_rel)
        ing_entries[held_i[0]] = s6b_ref(tmpl, i_held)
        new_range(r_ing, ing_entries)

    # breath states: no attack-input branch (it would cut the breath off)
    for r in (r_stt, r_ing, r_end):
        st, cnt = rec_range(p.records[r])
        ents = [e for e in p.S6b[st:st + cnt] if _u32(e, 0) == 0]
        if len(ents) != cnt:
            new_range(r, ents)

    # start state: wyvern releases the key -> end
    st, cnt = rec_range(p.records[r_stt])
    i_stop = len(p.S5)
    stop = bytearray(s5_with(p.S5[rel_i[1]], A=emit(p, AND(wyv, NOT(bkey))), B=(0, 0)))
    stop[29] = 0                                         # check condition A
    p.S5.append(bytes(stop))
    new_range(r_stt, [s6b_ref(tmpl, i_stop)] + list(p.S6b[st:st + cnt]))

    # breath states get the movement mode of the main flight state
    fly = [rec for rec in p.records if rec_hash(rec) == FLIGHT_RECORD]
    if len(fly) != 1:
        raise WyvernError("main flight state not found")
    for r in (r_stt, r_ing, r_end):
        rec = bytearray(p.records[r]); rec[238] = fly[0][238]; p.records[r] = bytes(rec)

    # entry: with keyguide the key is the input part B (the game then shows
    # "Fire Breath <key>" bottom right, like the dragon); else key in A, B empty
    # (the label always shows the dragon's breath key RT, so only for RT)
    i_enter = len(p.S5)
    if keyguide and same_key:
        p.S5.append(s5_with(p.S5[enter_src], A=emit(p, wyv), B=emit(p, bkey)))
    else:
        p.S5.append(s5_with(p.S5[enter_src], A=emit(p, AND(wyv, bkey)), B=(0, 0)))
    enter_ref = s6b_ref(tmpl, i_enter)
    entries = 0
    for r, rec in enumerate(p.records):
        if rec_hash(rec) not in BREATH_ENTRY_RECORDS:
            continue
        nm = anim_name(p, node_anim(p.nodes[rec_node(rec)]))
        if node_tag(p.nodes[rec_node(rec)]) != 0 or not any(a in nm for a in AIR_STATE_ANIMS):
            raise WyvernError("unexpected entry state")
        st, cnt = rec_range(rec)
        new_range(r, [enter_ref] + list(p.S6b[st:st + cnt]))
        entries += 1

    # wyvern variants of the three breath states (back to front)
    ing_base = rec_node(p.records[r_ing])
    if interval is None:
        interval = struct.unpack_from("<f", p.nodes[ing_base], 4)[0]
    interval = max(WYV_BREATH_LEN, float(interval))
    copies: Dict[int, int] = {}

    def proj_map(word):
        if word not in copies:
            ev = bytearray(p.blob[4 * word:4 * word + _event_len(p, word)])
            struct.pack_into("<H", ev, PROJ_SPAWN_OFS[p.layout], WYV_MOUTH_SPAWN)
            copies[word] = len(p.blob) // 4
            p.blob = p.blob + bytes(ev)
        return copies[word]

    plan = [(rec_node(p.records[r_stt]), anim["stt"], WYV_PROJECTILE_TIME, WYV_BREATH_LEN),
            (ing_base, anim["ing"], None, interval),
            (rec_node(p.records[r_end]), anim["end"], None, WYV_BREATH_LEN)]
    for base, a, pt, dur in sorted(plan, key=lambda x: -x[0]):
        _insert_node(p, base, _wyvern_variant(p, p.nodes[base], a, dur, pt, w_upper, mask_idx,
                                              proj_map))
    return {"entry_states": entries, "interval": round(interval, 3)}


def build_upper(vanilla: bytes, fire_breath: bool = True, fireballs: bool = True,
                key: str = KEYS[DEFAULT_KEY], interval: Optional[float] = None,
                keyguide: bool = True):
    p = parse(vanilla)
    if build(p) != vanilla:
        raise WyvernError("the action chart could not be read losslessly")
    info = {}
    if fireballs:
        info["fireballs"] = patch_fireballs(p)
    if fire_breath:
        info.update(patch_fire_breath(p, key, interval, keyguide))
    out = build(p)
    parse(out)
    return out, info


# ─────────────────────────────────────────────── passenger tables (Field JSON)
PASSENGER_TARGETS = [{'file': 'vehicleinfo.pabgb',
      'intents': [{'entry': 'Wyvern', 'key': 16975, 'field': 'max_vehicle_seat', 'op': 'set', 'new': 2},
                  {'entry': 'Wyvern',
                   'key': 16975,
                   'field': 'vehicle_seat_data_01',
                   'op': 'set',
                   'new': 14092401212423266675},
                  {'entry': 'Wyvern', 'key': 16975, 'field': 'cargo_seat_index_list', 'op': 'set', 'new': [1]}]},
     {'file': 'characterinfo.pabgb',
      'intents': [{'entry': 'Riding_Wyvern_1000',
                   'key': 1004233,
                   'field': 'interaction_info_list',
                   'op': 'set',
                   'new': [1000005, 1000264, 1900169, 303, 1000145, 1900170, 1900171]},
                  {'entry': 'Riding_Wyvern_1000',
                   'key': 1004233,
                   'field': 'interaction_info_list_with_recursive_child',
                   'op': 'set',
                   'new': [1000005, 1000264, 1900169, 303, 1000145, 1900170, 1900171]}]},
     {'file': 'interactioninfo.pabgb',
      'intents': [{'op': 'clone_record',
                   'source_key': 301,
                   'new_key': 1900169,
                   'patches': [{'path': 'interaction_pivot_list[0].pivot_key_name_116',
                                'new': 'TempPivotKey_Wyvrn_Carry_Dead_1'},
                               {'path': 'interaction_pivot_list[0].raw_a', 'new': 1077936128},
                               {'path': 'interaction_pivot_list[0].raw_b', 'new': 1082130432},
                               {'path': 'interaction_pivot_list[0].vec_c[0]', 'new': 1.649999976158142},
                               {'path': 'interaction_pivot_list[0].vec_c[2]', 'new': 0.30000001192092896},
                               {'path': 'interaction_pivot_list[0].vec_e[0]', 'new': -3.1415927410125732},
                               {'path': 'interaction_pivot_list[0].vec_e[1]', 'new': 3.1415927410125732},
                               {'path': 'interaction_pivot_list[1].pivot_key_name_116',
                                'new': 'TempPivotKey_Wyvrn_Carry_Dead_2'},
                               {'path': 'interaction_pivot_list[1].raw_a', 'new': 1077936128},
                               {'path': 'interaction_pivot_list[1].raw_b', 'new': 1082130432},
                               {'path': 'interaction_pivot_list[1].vec_c[0]', 'new': -1.649999976158142},
                               {'path': 'interaction_pivot_list[1].vec_c[2]', 'new': 0.30000001192092896},
                               {'path': 'interaction_pivot_list[1].vec_e[0]', 'new': -3.1415927410125732},
                               {'path': 'interaction_pivot_list[1].vec_e[1]', 'new': 3.1415927410125732},
                               {'path': 'string_key', 'new': 'Wyvrn_Carry_Dead'}]},
                  {'op': 'clone_record',
                   'source_key': 303,
                   'new_key': 1900170,
                   'patches': [{'path': 'interaction_pivot_list[0].pivot_key_name_116',
                                'new': 'TempPivotKey_Wyvrn_BackSeat_Ride_NPC_1'},
                               {'path': 'interaction_pivot_list[0].raw_a', 'new': 1094713344},
                               {'path': 'interaction_pivot_list[0].raw_b', 'new': 1084227584},
                               {'path': 'interaction_pivot_list[0].raw_c', 'new': 3231711232},
                               {'path': 'interaction_pivot_list[1].pivot_key_name_116',
                                'new': 'TempPivotKey_Wyvrn_BackSeat_Ride_NPC_2'},
                               {'path': 'interaction_pivot_list[1].raw_a', 'new': 1094713344},
                               {'path': 'interaction_pivot_list[1].raw_b', 'new': 1084227584},
                               {'path': 'interaction_pivot_list[1].raw_c', 'new': 3231711232},
                               {'path': 'string_key', 'new': 'Wyvrn_BackSeat_Ride_NPC'}]},
                  {'op': 'clone_record',
                   'source_key': 1000145,
                   'new_key': 1900171,
                   'patches': [{'path': 'interaction_pivot_list[0].pivot_key_name_116',
                                'new': 'TempPivotKey_Wyvrn_BackSeat_Ride_Teleport_NPC_1'},
                               {'path': 'interaction_pivot_list[0].raw_a', 'new': 1094713344},
                               {'path': 'interaction_pivot_list[0].raw_b', 'new': 1084227584},
                               {'path': 'interaction_pivot_list[0].raw_c', 'new': 3231711232},
                               {'path': 'string_key', 'new': 'Wyvrn_BackSeat_Ride_Teleport_NPC'}]},
                  {'entry': 'NpcBind_Release',
                   'key': 11026,
                   'field': 'cond_data_list[0].cond_b.tree.left.left.right.child',
                   'op': 'set',
                   'new': {'case': 'BinaryOpA',
                           'left': {'case': 'ConditionData',
                                    'data': {'base': {'tag': 265},
                                             'option_block': {'option_data': None, 'option_present': 0},
                                             'variant': {'body': {'field_at_24': 2769101393, 'field_at_28': 0},
                                                         'type': 'ConditionData_CheckRidingVehicleType'}}},
                           'right': {'case': 'ConditionData',
                                     'data': {'base': {'tag': 265},
                                              'option_block': {'option_data': None, 'option_present': 0},
                                              'variant': {'body': {'field_at_24': 2847135617, 'field_at_28': 0},
                                                          'type': 'ConditionData_CheckRidingVehicleType'}}}}},
                  {'entry': 'NpcBind_Down_Release',
                   'key': 1000222,
                   'field': 'cond_data_list[0].cond_b.tree.left.left.right.child',
                   'op': 'set',
                   'new': {'case': 'BinaryOpA',
                           'left': {'case': 'ConditionData',
                                    'data': {'base': {'tag': 265},
                                             'option_block': {'option_data': None, 'option_present': 0},
                                             'variant': {'body': {'field_at_24': 2769101393, 'field_at_28': 0},
                                                         'type': 'ConditionData_CheckRidingVehicleType'}}},
                           'right': {'case': 'ConditionData',
                                     'data': {'base': {'tag': 265},
                                              'option_block': {'option_data': None, 'option_present': 0},
                                              'variant': {'body': {'field_at_24': 2847135617, 'field_at_28': 0},
                                                          'type': 'ConditionData_CheckRidingVehicleType'}}}}},
                  {'entry': 'Horse_UnCarry_Dead',
                   'key': 302,
                   'field': 'cond_data_list[0].cond_b.tree.right',
                   'op': 'set',
                   'new': {'case': 'BinaryOpA',
                           'left': {'case': 'ConditionData',
                                    'data': {'base': {'tag': 265},
                                             'option_block': {'option_data': None, 'option_present': 0},
                                             'variant': {'body': {'field_at_24': 2769101393, 'field_at_28': 0},
                                                         'type': 'ConditionData_CheckRidingVehicleType'}}},
                           'right': {'case': 'ConditionData',
                                     'data': {'base': {'tag': 265},
                                              'option_block': {'option_data': None, 'option_present': 0},
                                              'variant': {'body': {'field_at_24': 2847135617, 'field_at_28': 0},
                                                          'type': 'ConditionData_CheckRidingVehicleType'}}}}}]}]


def passenger_field_json(title: str = "Wyvern: Passenger & Carry (tables)") -> dict:
    return {"modinfo": {"title": title, "version": "1.0", "author": "CrimsonGameMods",
                        "description": "Wyvern: second seat, carry dead/bound people, NPC on the "
                                       "back seat. Use together with the wyvern mod (.zip)."},
            "format": 3, "format_minor": 1, "targets": json.loads(json.dumps(PASSENGER_TARGETS))}


# ─────────────────────────────────────────────────────────────── whole mod
def read_game_files(game_path: str) -> Dict[str, bytes]:
    import dmm_parser
    return {"upper": bytes(dmm_parser.extract_file(game_path, UPPER_GROUP, UPPER_DIR, UPPER_NAME)),
            "pab": bytes(dmm_parser.extract_file(game_path, PAB_GROUP, PAB_DIR, PAB_NAME))}


def build_mod(files: Dict[str, bytes], fire_breath=True, fireballs=True, passenger=True,
              key: str = KEYS[DEFAULT_KEY], interval: Optional[float] = None,
              title: Optional[str] = None, keyguide: bool = True) -> dict:
    """{'zip': bytes or None, 'field_json': dict or None, 'info': dict}"""
    if not (fire_breath or fireballs or passenger):
        raise WyvernError("nothing selected")
    loose: Dict[str, bytes] = {}
    info: dict = {}
    if fire_breath or fireballs:
        up, info = build_upper(files["upper"], fire_breath, fireballs, key, interval, keyguide)
        loose[f"{UPPER_DIR}/{UPPER_NAME}"] = up
    if passenger:
        loose[f"{PAB_DIR}/{PAB_NAME}"] = build_pab(files["pab"])
    parts = []
    if fire_breath:
        parts.append("fire breath on " + ("RT" if key == "key_hardattack" else "LB")
                     + " (hold to keep breathing)")
    if fireballs:
        parts.append("fireballs instead of wind balls")
    if passenger:
        parts.append("passenger seat on the back (load the .field.json too)")
    if not title:
        names = (["Fire Breath"] if fire_breath else []) + (["Fireballs"] if fireballs else []) \
            + (["Second Seat"] if passenger else [])
        title = "Wyvern: " + " + ".join(names)
    modinfo = {"name": title, "title": title, "version": "1.0", "author": "CrimsonGameMods",
               "type": "mesh_loose_mod", "format": "v1", "game": "Crimson Desert",
               "files_dir": "files", "game_version": "2.05.00",
               "description": "Wyvern: " + ", ".join(parts) + ". No ASI, no speed change."}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("modinfo.json", json.dumps(modinfo, indent=2))
        for path, data in loose.items():
            z.writestr("files/" + path, data)
    return {"zip": buf.getvalue(), "field_json": passenger_field_json() if passenger else None,
            "info": info}
