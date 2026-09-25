"""Story chapters and quest groups.

The game sorts every quest into a quest group (questinfo `quest_group`,
table questgroupinfo). Groups 1000-1013 are the main story: 1000 is the
prologue, 1001-1012 are chapters 1-12 and 1013 is the epilogue. The other
groups are things like Exploration, Mastery, Combat, schedules and so on.

Where the data comes from:
  * quest_groups.json - made from the game's questgroupinfo by
    CrimsonGameMods/tools/build_quest_database.py. It has the real group
    names ("IV. The Price of Knowledge") and the quests of each group in
    the game's order.
  * quest_database.json - every quest with its group number and missions.
    Used alone when quest_groups.json is missing: then the chapters get
    plain names ("Chapter 4") and the order inside a group is by key.

Missions have no group of their own; they get the group of the quest that
lists them. Quest keys and mission keys are separate number ranges that
overlap (1000157 is a quest *and* a mission), so every lookup says which of
the two it means.

No Qt in here.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, Iterable, List, Optional, Tuple

PROLOGUE = 1000
EPILOGUE = 1013
MAIN_STORY = "Main Story"
_NOT_MAIN = 1_000_000          # sorts every non-story entry after the story
_LATE = 2 ** 62
# internal groups the game never shows (level-sequencer spawns, benchmark)
_HIDDEN_GROUPS = {9999, 41998}


def is_chapter_group(group) -> bool:
    return isinstance(group, int) and PROLOGUE <= group <= EPILOGUE


def chapter_label(group) -> str:
    """'Prologue', 'Chapter 1' ... 'Chapter 12', 'Epilogue' - or '' if not a chapter."""
    if not is_chapter_group(group):
        return ""
    if group == PROLOGUE:
        return "Prologue"
    if group == EPILOGUE:
        return "Epilogue"
    return f"Chapter {group - PROLOGUE}"


def all_chapter_labels() -> List[str]:
    return [chapter_label(g) for g in range(PROLOGUE, EPILOGUE + 1)]


def group_for_label(label: str) -> Optional[int]:
    for g in range(PROLOGUE, EPILOGUE + 1):
        if chapter_label(g) == label:
            return g
    return None


def _internal_name(name: str) -> bool:
    """System quests the game never shows (same rule as the C++ editor)."""
    return (not name or name.startswith("LevelSequencer") or name.startswith("Func_")
            or name.startswith("Spawn "))


class QuestGroup:
    __slots__ = ("key", "name", "display", "quests", "is_chapter", "synthetic")

    def __init__(self, key: int, name: str, display: str, quests: List[int],
                 synthetic: bool = False):
        self.key = key
        self.name = name
        self.display = display
        self.quests = quests
        self.is_chapter = is_chapter_group(key)
        self.synthetic = synthetic

    def __repr__(self) -> str:
        return f"QuestGroup({self.key}, {self.display!r}, {len(self.quests)} quests)"


class QuestChapters:
    """Quest data by group: chapter lookups, story order and the group list."""

    def __init__(self, entries: Iterable[dict] = (), groups: Optional[List[dict]] = None):
        self.quests: Dict[int, dict] = {}
        for e in entries or ():
            try:
                self.quests[int(e["key"])] = e
            except (KeyError, TypeError, ValueError):
                continue

        self.from_game = bool(groups)
        self.groups: List[QuestGroup] = []
        if groups:
            self._groups_from_game(groups)
        else:
            self._groups_from_database()
        self._add_ungrouped()

        # quest key -> (group, position); mission key -> (group, pos, mission pos)
        self._quest_pos: Dict[int, Tuple[int, int]] = {}
        self._mission_pos: Dict[int, Tuple[int, int, int]] = {}
        self._group_rank: Dict[int, int] = {}
        for rank, grp in enumerate(self.groups):
            self._group_rank.setdefault(grp.key, rank)
            for i, qk in enumerate(grp.quests):
                self._quest_pos.setdefault(qk, (grp.key, i))
        for qk, (gk, i) in self._quest_pos.items():
            for j, mk in enumerate((self.quests.get(qk) or {}).get("missions") or ()):
                try:
                    self._mission_pos.setdefault(int(mk), (gk, i, j))
                except (TypeError, ValueError):
                    pass

    # -- building the group list --------------------------------------
    def _groups_from_game(self, groups: List[dict]) -> None:
        for g in groups:
            try:
                key = int(g["key"])
            except (KeyError, TypeError, ValueError):
                continue
            if g.get("is_dev") or g.get("is_blocked"):
                continue
            if key in _HIDDEN_GROUPS:
                continue
            quests = [int(q) for q in g.get("quests") or () if int(q) in self.quests]
            display = g.get("display") or chapter_label(key) or g.get("name") or f"Group {key}"
            self.groups.append(QuestGroup(key, g.get("name", ""), display, quests))

    def _groups_from_database(self) -> None:
        by_group: Dict[int, List[int]] = {}
        for qk, e in self.quests.items():
            g = e.get("quest_group")
            if e.get("category_name") == MAIN_STORY and is_chapter_group(g):
                by_group.setdefault(g, []).append(qk)
        for g in sorted(by_group):
            self.groups.append(QuestGroup(g, "", chapter_label(g), sorted(by_group[g])))

    def _add_ungrouped(self) -> None:
        """Quests in no listed group, one extra group per category (like the C++ editor)."""
        grouped = {qk for grp in self.groups for qk in grp.quests}
        by_cat: Dict[str, List[int]] = {}
        for qk, e in self.quests.items():
            if (qk in grouped or e.get("quest_group") in _HIDDEN_GROUPS
                    or _internal_name(e.get("display") or "") or _internal_name(e.get("name") or "")):
                continue
            by_cat.setdefault(e.get("category_name") or "Side", []).append(qk)
        order = {"Side": 0, "Regional": 1}
        for i, cat in enumerate(sorted(by_cat, key=lambda c: (order.get(c, 9), c))):
            keys = sorted(by_cat[cat])
            self.groups.append(QuestGroup(90000 + i, f"Ungrouped_{cat}",
                                          f"{cat} Quests", keys, synthetic=True))

    # -- lookups ---------------------------------------------------------
    def __len__(self) -> int:
        return sum(1 for g in self.groups if g.is_chapter)

    def group_of(self, key, is_mission: bool = False) -> Optional[int]:
        """The chapter group of a quest or mission, None if it is not main story."""
        try:
            pos = (self._mission_pos if is_mission else self._quest_pos).get(int(key))
        except (TypeError, ValueError):
            return None
        if pos and is_chapter_group(pos[0]):
            return pos[0]
        return None

    def group_display(self, group) -> str:
        for grp in self.groups:
            if grp.key == group:
                return grp.display
        return chapter_label(group)

    def label_of(self, key, is_mission: bool = False) -> str:
        g = self.group_of(key, is_mission)
        return self.group_display(g) if g is not None else ""

    def missions_of(self, quest_key) -> List[int]:
        try:
            return [int(m) for m in (self.quests.get(int(quest_key)) or {}).get("missions") or ()]
        except (TypeError, ValueError):
            return []

    def sort_key(self, key, played_time: int = 0, is_mission: bool = False) -> Tuple[int, ...]:
        """Story order. With the game's group list: group, place in the group,
        place of the mission in its quest. Without it the game gives no order
        inside a chapter, so played quests come first in the order they were
        played (time from the save) and the rest by key."""
        try:
            k = int(key)
        except (TypeError, ValueError):
            k = 0
        g = self.group_of(k, is_mission)
        if g is None:
            return (_NOT_MAIN, _LATE, _LATE, k)
        rank = self._group_rank.get(g, g)
        if self.from_game:
            pos = self._mission_pos[k] if is_mission else self._quest_pos[k] + (-1,)
            return (rank, pos[1], pos[2], k)
        t = played_time if played_time and played_time > 0 else _LATE
        return (rank, t, 1 if is_mission else 0, k)


def _data_dirs() -> List[str]:
    dirs = [os.path.dirname(os.path.abspath(__file__))]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        dirs.append(meipass)
    return dirs


def _read_json(name: str, folder: Optional[str] = None):
    for d in ([folder] if folder else _data_dirs()):
        try:
            with open(os.path.join(d, name), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


_cached: Optional[QuestChapters] = None


def load(folder: Optional[str] = None) -> QuestChapters:
    """Read quest_database.json (+ quest_groups.json if there) once."""
    global _cached
    if folder is None and _cached is not None:
        return _cached
    db = _read_json("quest_database.json", folder)
    groups = _read_json("quest_groups.json", folder)
    result = QuestChapters(db if isinstance(db, list) else [],
                           groups if isinstance(groups, list) else None)
    if folder is None:
        _cached = result
    return result
