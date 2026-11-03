"""The mounts a player can actually ride (58, game 2.04.05 + DLC), as listed
on crimsondesert.gg/mounts, grouped the same way.

A name can stand for several character records (e.g. every wild "Brianto"
horse is its own record, and a tamed one keeps its record). The Mounts tab
changes all records of a name, with two rules:
  - if the name has records starting with "Riding_", only those are used
    (e.g. Wyvern -> Riding_Wyvern_1000, not the wild wyverns),
  - "Boss_" records are never touched (Blackstar's boss version).
No Qt in here.
"""

from __future__ import annotations

GROUPS = [
    ("Horses", ["Brianto", "Calphadean Scout's Horse", "Camora", "Elantrima",
                "Hernandian Soldier's Horse", "Herspia", "Numont", "Priden", "Race Horse",
                "Rokade", "Royler"]),
    ("Predators", ["Large White Wolf", "Large Wolf", "Silver Fang", "Swift Wolf",
                   "Circus Lion", "Lion", "Tiger"]),
    ("Bears", ["Bear", "Black Bear", "Captured Bear", "Clawed Bear", "Grizzly Bear",
               "White Bear"]),
    ("Camels", ["Sandwalk Camel"]),
    ("Boars", ["Rock Tusk Warthog"]),
    ("Deer", ["Rosehorn Deer", "Snowwhite Deer"]),
    ("Ibex", ["Ibex", "Icicle Edge Alpine Ibex"]),
    ("Birds", ["Leaping Kuku Bird", "Red-Feathered Raptor"]),
    ("Reptiles", ["Giant Green Iguana", "Giant Red Iguana"]),
    ("Mechanical", ["Ocean Drifter"]),
    ("Aquatic", ["Golden Shark", "Hammerhead Shark", "Shark", "Orca", "Sunfish",
                 "Spotted Seal", "Green Sea Turtle", "Hawksbill Sea Turtle",
                 "Hydrothermal Turtle", "Loggerhead Sea Turtle", "Olive Ridley Sea Turtle",
                 "Eagle Ray", "Electric Ray", "Giant Manta Ray", "Manta Ray",
                 "Pink Manta Ray", "Dolphin", "Pink Dolphin"]),
    ("Flying", ["Wyvern", "Blackstar", "Cloudcart", "Cloudcruiser", "Skystreaker"]),
]


# Mounts the game data does not mark with a mount type (vehicle_info 0, not
# callable), listed anyway: the Giant Manta Ray is ridden in the wild
# (crimsondesert.gg lists it with speed/accel/handling/jump).
EXTRA_RECORDS = {"Animal_Giant_MantaRay_Wild_1"}


def records_for(name: str, entries: list, name_of) -> list:
    """The mount entries that stand for `name` (rules above).
    `name_of(entry)` gives the in-game name of an entry."""
    hits = [e for e in entries if name_of(e) == name
            and not str(e.get('name', '')).startswith('Boss_')]
    riding = [e for e in hits if str(e.get('name', '')).startswith('Riding_')]
    return riding or hits
