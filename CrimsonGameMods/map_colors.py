"""Map colours: recolour the world map (ui/worldmapview.css) as a DMM byte-patch mod.

The world map's colours are "@material-param preset-worldmap... { _xxxColor:
color, #rrggbbaa; }" entries in ui/xml/gamemain/play/worldmapview.css (group
0012). A colour is always written as the same number of hex digits, so a
recolour is a same-length byte patch - DMM's "patches" format. The offsets are
found in the installed game's own file at export time, so a game update that
moves the file around does not break a mod made after it.

Only the 6 RGB digits are replaced; the alpha digits stay. No Qt in here.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

GAME_FILE = "ui/worldmapview.css"            # DMM resolves it by name
GROUP = "0012"
DIR = "ui/xml/gamemain/play"
NAME = "worldmapview.css"

# role -> (label, [(preset, property), ...])
ROLES: List[Tuple[str, str, List[Tuple[str, str]]]] = [
    ("sea", "Sea / map base", [
        ("preset-worldmap", "_originalColorTint"),
        ("preset-worldmap-overfog", "_originalColorTint")]),
    ("paper", "Map paper (zoomed out)", [
        ("preset-worldmap-2", "_originalColorTint"),
        ("preset-worldmap-sea", "_originalColorTint")]),
    ("land_line", "Coastline (land side)", [
        ("preset-worldmap", "_mapLandOutlineColor"),
        ("preset-worldmap-overfog", "_mapLandOutlineColor"),
        ("preset-worldmap-2", "_mapLandOutlineColor")]),
    ("sea_line", "Coastline (sea side)", [
        ("preset-worldmap", "_mapSeaOutlineColor"),
        ("preset-worldmap-overfog", "_mapSeaOutlineColor")]),
    ("fog", "Fog / unexplored", [
        ("preset-worldmap-fog", "_originalColorTint"),
        ("preset-worldmap-none-play-region", "_originalColorTint")]),
    ("mountain", "Mountains", [
        ("preset-worldmap-mountain", "_originalColorTint")]),
    ("mountain_line", "Mountain outline", [
        ("preset-worldmap-mountain", "_mapLandOutlineColor")]),
    ("height", "Height lines", [
        ("preset-worldmap-height-line", "_originalColorTint")]),
    ("road", "Roads", [
        ("preset-worldmap-road", "_originalColorTint")]),
    ("road_line", "Road edge", [
        ("preset-worldmap-road", "_mapLandOutlineColor")]),
    ("wagon", "Wagon roads", [
        ("preset-worldmap-road-wagon", "_originalColorTint"),
        ("preset-worldmap-road-wagon", "_mapLandOutlineColor")]),
    ("abyss", "Abyss background", [
        ("preset-worldmap-abyss-background-hex", "_originalColorTint")]),
    ("abyss_fog", "Abyss fog", [
        ("preset-worldmap-abyss-fog", "_originalColorTint"),
        ("preset-worldmap-abyss-border-fog", "_originalColorTint")]),
    ("loading", "Loading screen", [
        ("preset-worldmap-loading", "_originalColorTint"),
        ("preset-worldmap-loading-2", "_originalColorTint"),
        ("preset-worldmap-abyss-loading", "_originalColorTint")]),
    ("wanted", "Wanted region", [
        ("preset-worldmap-wanted-region", "_originalColorTint")]),
    ("restricted", "Restricted area", [
        ("preset-worldmap-restricted-area-town", "_originalColorTint"),
        ("preset-worldmap-restricted-area-gameplay-trigger", "_originalColorTint")]),
    ("religion", "Religion area", [
        ("preset-worldmap-region-religion-area", "_originalColorTint")]),
]

# Presets: role -> #rrggbb. Roles left out keep the game's colour.
PRESETS: Dict[str, Dict[str, str]] = {
    "Original": {},
    "Night": {"sea": "#021424", "paper": "#030405", "land_line": "#55513c", "sea_line": "#5a6d80",
              "fog": "#010102", "mountain": "#131c13", "mountain_line": "#394534", "road": "#766d56",
              "road_line": "#685f4b", "abyss": "#030405", "abyss_fog": "#010102", "loading": "#030405"},
    "Midnight Blue": {"sea": "#0a1a3a", "paper": "#0d1530", "land_line": "#8aa4d6", "sea_line": "#3b5c9a",
                      "fog": "#060b18", "mountain": "#1c2a4a", "mountain_line": "#4a6aa0", "height": "#2a3a5c",
                      "road": "#c8d4f0", "road_line": "#6f86b8", "wagon": "#a0b4e0", "loading": "#0a1228"},
    "Parchment": {"sea": "#6f8a94", "paper": "#e8d9b5", "land_line": "#6b4f2a", "sea_line": "#8a7a5a",
                  "fog": "#c9b48a", "mountain": "#a08a60", "mountain_line": "#6b5638", "height": "#7a6a4a",
                  "road": "#8a5a2a", "road_line": "#5a3a1a", "wagon": "#7a4a20", "loading": "#d8c8a0"},
    "Emerald": {"sea": "#0b3a32", "paper": "#0e2a22", "land_line": "#7fd1a0", "sea_line": "#2f8a6a",
                "fog": "#06140f", "mountain": "#1f4a2e", "mountain_line": "#5fa070", "height": "#2a5a3a",
                "road": "#d8f0c0", "road_line": "#80b080", "wagon": "#b0d890", "loading": "#081c16"},
    "Crimson": {"sea": "#2a0608", "paper": "#1a0405", "land_line": "#e0a070", "sea_line": "#8a2a2a",
                "fog": "#0e0203", "mountain": "#4a1a14", "mountain_line": "#a0503a", "height": "#5a2a20",
                "road": "#f0d0a0", "road_line": "#b07050", "wagon": "#e0b080", "loading": "#1a0405"},
    "Arctic": {"sea": "#9fc4d8", "paper": "#e6f0f5", "land_line": "#4a6a80", "sea_line": "#6a90a8",
               "fog": "#c8d8e0", "mountain": "#b8ccd8", "mountain_line": "#5a7a90", "height": "#8aa4b8",
               "road": "#3a5068", "road_line": "#24384a", "wagon": "#4a6078", "loading": "#dce8ee"},
    "Royal Purple": {"sea": "#1e0f3a", "paper": "#160a2a", "land_line": "#d4b0ff", "sea_line": "#6a4aa0",
                     "fog": "#0b0518", "mountain": "#3a2060", "mountain_line": "#8a60c0", "height": "#4a2a70",
                     "road": "#f0d890", "road_line": "#a08040", "wagon": "#e0c070", "loading": "#120826"},
    "Gold": {"sea": "#1a1408", "paper": "#2a2210", "land_line": "#f0c050", "sea_line": "#a07a20",
             "fog": "#0e0b04", "mountain": "#4a3a14", "mountain_line": "#c09030", "height": "#5a4818",
             "road": "#fff0b0", "road_line": "#c0a050", "wagon": "#f0d070", "loading": "#1a1408"},
    "Grayscale": {"sea": "#2a2a2a", "paper": "#3a3a3a", "land_line": "#d0d0d0", "sea_line": "#808080",
                  "fog": "#151515", "mountain": "#505050", "mountain_line": "#a0a0a0", "height": "#606060",
                  "road": "#f0f0f0", "road_line": "#909090", "wagon": "#c0c0c0", "loading": "#202020"},
    "Ocean Teal": {"sea": "#04363f", "paper": "#06262c", "land_line": "#f0e0b0", "sea_line": "#2aa0a8",
                   "fog": "#021418", "mountain": "#2a4a3a", "mountain_line": "#70a088", "height": "#30584a",
                   "road": "#f8e8c0", "road_line": "#b0a070", "wagon": "#e8d090", "loading": "#04262c"},
    "Desert Sand": {"sea": "#3a6a7a", "paper": "#d8b878", "land_line": "#7a4a1a", "sea_line": "#5a8a8a",
                    "fog": "#b89860", "mountain": "#a87838", "mountain_line": "#6a4018", "height": "#8a6030",
                    "road": "#5a3010", "road_line": "#3a2008", "wagon": "#6a3a14", "loading": "#c8a868"},
}

_PARAM = re.compile(rb"@material-param\s+([\w-]+)\s*\{([^}]*)\}")
_COLOR = re.compile(rb"(_\w+)\s*:\s*color\s*,\s*#([0-9a-fA-F]{6,8})")


def read_css(game_path: str) -> bytes:
    import dmm_parser
    return bytes(dmm_parser.extract_file(game_path, GROUP, DIR, NAME))


def find_colors(css: bytes) -> Dict[Tuple[str, str], Tuple[int, str]]:
    """(preset, property) -> (byte offset of the 6 RGB digits, current rrggbb)."""
    out: Dict[Tuple[str, str], Tuple[int, str]] = {}
    for m in _PARAM.finditer(css):
        preset = m.group(1).decode("ascii", "replace")
        for p in _COLOR.finditer(m.group(2)):
            off = m.start(2) + p.start(2)
            out[(preset, p.group(1).decode("ascii", "replace"))] = (off, p.group(2)[:6].decode().lower())
    return out


def current_roles(css: bytes) -> Dict[str, str]:
    """role -> the game's current colour (#rrggbb) of its first entry."""
    found = find_colors(css)
    res = {}
    for role, _label, targets in ROLES:
        for t in targets:
            if t in found:
                res[role] = "#" + found[t][1]
                break
    return res


def _norm(c: str) -> Optional[str]:
    c = (c or "").strip().lstrip("#").lower()
    return c if re.fullmatch(r"[0-9a-f]{6}", c) else None


def build_mod(css: bytes, colors: Dict[str, str], title: str = "Map Colors",
              author: str = "CrimsonGameMods Map Colors") -> dict:
    """DMM byte-patch mod for `colors` (role -> #rrggbb). Unchanged entries
    are left out. Raises ValueError if nothing changes."""
    found = find_colors(css)
    changes = []
    for role, label, targets in ROLES:
        new = _norm(colors.get(role, ""))
        if not new:
            continue
        for preset, prop in targets:
            if (preset, prop) not in found:
                continue
            off, old = found[(preset, prop)]
            if old == new:
                continue
            changes.append({
                "offset": off,
                "label": f"{label}: {prop} #{old} -> #{new} [{preset}]",
                "original": css[off:off + 6].hex(),
                "patched": new.encode("ascii").hex(),
            })
    if not changes:
        raise ValueError("No colour differs from the game's - nothing to write.")
    changes.sort(key=lambda c: c["offset"])
    return {
        "modinfo": {"title": title, "version": "1.0", "author": author,
                    "description": f"World map colours ({len(changes)} values)."},
        "patches": [{"game_file": GAME_FILE, "source_group": GROUP, "changes": changes}],
    }


def write_mod(path: str, mod: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mod, f, indent=2, ensure_ascii=False)
