"""Weapon effect colours: recolour a weapon's glow as a DMM byte-patch mod.

WEAPONS lists the weapons this works for (tested ones first). The first is
the Lumen Sword; more follow (lightning spear etc.).

The Lumen Sword / Lumen Longsword (DLC, Beam_OneHandSword / Beam_TwoHandSword)
draws its blade with four effect files in group 0007:
effect/binary__/releasebin/fx_lightning_swordlong_a__beam1/2/_off1/_off2.pae.
Their textures are grey masks; the pink comes from float colours in the
emitters (EmitterRenderData._emissiveColor / _color and a few light colours),
e.g. (0.4287, 0.0203, 0.1946). Found 16.11.2026 (game 2.05.00): 13 different
pink values, 39 places in the four files.

A recolour keeps each value's brightness (HSV value, may be > 1 = HDR glow)
and its relative saturation and puts the chosen hue on it - so the glow
stays as bright as the game's. Every value is 12 bytes (3 floats) at the same
place, so the mod is a same-length byte patch (DMM's "patches" format, like
Map Colors). The places are searched in the installed game's files at export
time. No Qt in here.
"""

from __future__ import annotations

import colorsys
import json
import re
import struct
from typing import Dict, List, Tuple

GROUP = "0007"
DIR = "effect/binary__/releasebin"
FILES = ["fx_lightning_swordlong_a__beam1.pae", "fx_lightning_swordlong_a__beam2.pae",
         "fx_lightning_swordlong_a__beam_off1.pae", "fx_lightning_swordlong_a__beam_off2.pae"]

# The game's pink colours (r, g, b as stored) - 12 bytes each.
PINKS = [
    "547ddb3e3334a63ce449473e",   # (0.4287, 0.0203, 0.1946) main emissive
    "f95f053f69a5023d9018783e",   # (0.5210, 0.0319, 0.2423)
    "4b930a3ff9d9883d8596553e",   # (0.5413, 0.0668, 0.2086)
    "425a533ef71c1a3bc0854b3d",   # (0.2064, 0.0024, 0.0497)
    "85284f3ef71c1a3bc0854b3d",   # (0.2023, 0.0024, 0.0497)
    "1b4ab93f50538b3d7d3c283f",   # (1.4476, 0.0680, 0.6572)
    "cbda363e786d003c209a293e",   # (0.1786, 0.0078, 0.1656)
    "601d373e786d003c209a293e",   # (0.1788, 0.0078, 0.1656)
    "e8f6fa3ee277b33d289b723e",   # (0.4902, 0.0876, 0.2369)
    "28630c3efab48a3d5f61013e",   # (0.1371, 0.0677, 0.1263)
    "fd65db3f6666263ffd65db3f",   # (1.7140, 0.6500, 1.7140) pink-white
    "7446ec3f3333333f7446ec3f",   # (1.8459, 0.7000, 1.8459) pink-white
    "b003873fcdcccc3eb003873f",   # (1.0548, 0.4000, 1.0548) pink-white
]
GAME_PINK_SAT = 0.95              # saturation of the main pink

# id -> what to recolour. "values": the game's colours (12 bytes each),
# "ref_sat": saturation of the main colour (keeps whitish parts whitish).
WEAPONS = {
    "lumen": {"name": "Lumen Sword / Lumen Longsword", "files": FILES, "values": PINKS,
              "ref_sat": GAME_PINK_SAT, "dlc": True, "tested": True},
}

# Fully saturated colours: the beam's bright core blooms towards white in the
# game (since 2.05.01/2.06), so paler presets came out almost white.
PRESETS: List[Tuple[str, str]] = [
    ("Blue", "#0018ff"), ("Ice Blue", "#00a8ff"), ("Cyan", "#00e0ff"), ("Teal", "#00c896"),
    ("Green", "#00ff28"), ("Toxic Green", "#8cff00"), ("Yellow", "#ffe800"), ("Gold", "#ffb000"),
    ("Orange", "#ff6000"), ("Red", "#ff0000"), ("Crimson Red", "#c80018"), ("Magenta", "#ff00c8"),
    ("Purple", "#6a00ff"), ("Violet", "#9a30ff"), ("Silver", "#c9d3e6"), ("White", "#ffffff"),
]


def read_files(game_path: str, weapon: str = "lumen") -> Dict[str, bytes]:
    import dmm_parser
    return {n: bytes(dmm_parser.extract_file(game_path, GROUP, DIR, n))
            for n in WEAPONS[weapon]["files"]}


def find_spots(data: bytes, weapon: str = "lumen") -> List[Tuple[int, bytes]]:
    """(offset, 12 bytes) of every game colour of `weapon` in one file."""
    spots = []
    for h in WEAPONS[weapon]["values"]:
        s = bytes.fromhex(h)
        p = data.find(s)
        while p != -1:
            spots.append((p, s))
            p = data.find(s, p + 1)
    spots.sort()
    return spots


def _parse_hex(color: str) -> Tuple[float, float, float]:
    c = (color or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        raise ValueError(f"Not a colour: {color!r} (use #rrggbb)")
    return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def recolor(old: Tuple[float, float, float], color: str,
            ref_sat: float = GAME_PINK_SAT) -> Tuple[float, float, float]:
    """The old value in the new colour: same brightness, hue of `color`,
    saturation scaled like the game's (pink-white stays whitish)."""
    r, g, b = old
    v = max(r, g, b)
    if v <= 0:
        return old
    _h, s_old, _v = colorsys.rgb_to_hsv(r / v, g / v, b / v)
    th, ts, tv = colorsys.rgb_to_hsv(*_parse_hex(color))
    s_new = min(1.0, ts * s_old / ref_sat)
    nr, ng, nb = colorsys.hsv_to_rgb(th, s_new, 1.0)
    k = v * max(tv, 0.05)
    return (nr * k, ng * k, nb * k)


def build_mod(files: Dict[str, bytes], color: str, title: str = "",
              weapon: str = "lumen") -> dict:
    """DMM byte-patch mod that recolours `weapon`'s effect to `color`."""
    w = WEAPONS[weapon]
    name = title or f"{w['name']} {color.upper()}"
    patches = []
    total = 0
    for fname in w["files"]:
        data = files.get(fname)
        if not data:
            continue
        changes = []
        for off, raw in find_spots(data, weapon):
            old = struct.unpack("<3f", raw)
            new = struct.pack("<3f", *recolor(old, color, w.get("ref_sat", GAME_PINK_SAT)))
            if new == raw:
                continue
            changes.append({"offset": off,
                            "label": "beam colour (%.3f, %.3f, %.3f) -> %s" % (old + (color,)),
                            "original": raw.hex(), "patched": new.hex()})
        if changes:
            total += len(changes)
            patches.append({"game_file": f"effect/{fname}", "source_group": GROUP,
                            "changes": changes})
    if not total:
        raise ValueError(f"The colours of {w['name']} were not found in the game files.")
    info = {"title": name, "version": "1.0", "author": "CrimsonGameMods",
            "description": f"{w['name']}: effect colour {color} ({total} colour values)."
                           + (" Needs the DLC." if w.get("dlc") else "")}
    if w.get("dlc"):
        info["requires_dlc"] = True
    return {"modinfo": info, "patches": patches}


def write_mod(path: str, mod: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mod, f, indent=2, ensure_ascii=False)
