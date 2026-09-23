"""Check Field JSON mods against the installed game - without writing anything.

Why this exists: a mod that was built for an older game version does not
announce that it no longer fits. Items it targets may have been removed or
renumbered, and the mod manager applies what it can and skips the rest
quietly. You notice in game, if at all.

How it checks: every intent is applied IN MEMORY to a fresh copy of the
table read from the game (group 0008, the unmodded data), with the same
dmm_parser.apply_intents the tools use to write. Nothing is saved; the
result is only the parser's own verdict per intent - applied or skipped,
and why. So "applied" here means exactly what it means when the mod is
installed for real.

Not covered: asset targets (textures, audio), localization, and manifests
in other shapes than the Field JSON 3.0 / 3.1 intent lists the tools write.
Those are reported as "not checked", never as "fine".
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from typing import Dict, List, NamedTuple, Optional

log = logging.getLogger(__name__)

TABLE_DIR = "gamedata/binary__/client/bin"


class TargetResult(NamedTuple):
    table: str
    total: int
    applied: int
    skipped: int
    reasons: List[str]      # most common skip reasons, "count x reason"
    error: str = ""         # set when the whole target could not be checked
    not_checked: str = ""   # set for targets this check does not cover


class ModResult(NamedTuple):
    path: str
    title: str
    targets: List[TargetResult]
    error: str = ""

    @property
    def total(self) -> int:
        return sum(t.total for t in self.targets)

    @property
    def applied(self) -> int:
        return sum(t.applied for t in self.targets)

    @property
    def skipped(self) -> int:
        return sum(t.skipped for t in self.targets)

    @property
    def verdict(self) -> str:
        if self.error:
            return "could not be read"
        if any(t.error for t in self.targets):
            return "could not be checked"
        if self.targets and all(t.not_checked for t in self.targets):
            return "not checked"
        if self.total == 0:
            return "nothing to check"
        if self.skipped == 0:
            return "works"
        if self.applied == 0:
            return "does not work"
        return "partly works"


def _targets(doc: dict):
    """(table file, intents, unsupported reason) for each target in the mod."""
    if doc.get("targets"):
        for t in doc["targets"]:
            kind = t.get("kind")
            if kind and kind != "table":
                yield (t.get("file") or t.get("vpath") or kind), [], f"{kind} target"
                continue
            if "intents" not in t:
                yield (t.get("file") or t.get("table") or "?"), [], "format not supported"
                continue
            yield (t.get("file") or t.get("table") or ""), t.get("intents") or [], ""
    elif doc.get("intents") is not None:
        yield doc.get("target", ""), doc.get("intents") or [], ""


def _table_stem(name: str) -> str:
    base = os.path.basename(name or "").lower()
    for ext in (".pabgb", ".pabgh", ".staticinfobody", ".staticinfoheader"):
        if base.endswith(ext):
            return base[: -len(ext)]
    return base


def check_mod(path: str, game_path: str, _cache: Optional[Dict] = None) -> ModResult:
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:  # noqa: BLE001
        return ModResult(path, os.path.basename(path), [], f"not a readable JSON file: {e}")
    title = ((doc.get("modinfo") or {}).get("title") or doc.get("name")
             or os.path.basename(path))
    if doc.get("format") != 3:
        return ModResult(path, title, [], "not a Field JSON (format 3) mod")

    import dmm_parser
    cache = _cache if _cache is not None else {}
    results: List[TargetResult] = []
    for fname, intents, unsupported in _targets(doc):
        stem = _table_stem(fname)
        if unsupported:
            results.append(TargetResult(fname, 0, 0, 0, [], not_checked=unsupported))
            continue
        if stem.endswith(".paloc") or "paloc" in stem:
            results.append(TargetResult(fname, len(intents), 0, 0, [],
                                        not_checked="localization"))
            continue
        try:
            if stem not in cache:
                body = bytes(dmm_parser.extract_file(game_path, "0008", TABLE_DIR, stem + ".pabgb"))
                try:
                    head = bytes(dmm_parser.extract_file(game_path, "0008", TABLE_DIR, stem + ".pabgh"))
                except Exception:  # noqa: BLE001 - sequential tables have none
                    head = None
                cache[stem] = (body, head)
            body, head = cache[stem]
            out = dmm_parser.apply_intents(stem, body, None if stem == "iteminfo" else head,
                                           intents)
            outcomes = out.get("outcomes") or []
        except Exception as e:  # noqa: BLE001
            log.warning("Mod check: %s / %s failed: %s", path, stem, e)
            results.append(TargetResult(fname, len(intents), 0, 0, [], error=str(e)))
            continue
        applied = sum(1 for o in outcomes if o.get("status") == "applied")
        skipped = len(outcomes) - applied
        reasons = Counter((o.get("reason") or "no reason given")
                          for o in outcomes if o.get("status") != "applied")
        results.append(TargetResult(
            fname, len(outcomes), applied, skipped,
            [f"{n} x {r}" for r, n in reasons.most_common(5)]))
    return ModResult(path, title, results)


def check_mods(paths: List[str], game_path: str) -> List[ModResult]:
    cache: Dict = {}
    return [check_mod(p, game_path, cache) for p in paths]


def format_report(results: List[ModResult], game_version: str = "") -> str:
    lines = []
    head = "Mod check against the installed game"
    if game_version:
        head += f" ({game_version})"
    lines += [head, "Nothing was written - every change was tried in memory only.", ""]
    for r in results:
        lines.append(f"{r.title}  -  {r.verdict.upper()}")
        lines.append(f"   {os.path.basename(r.path)}")
        if r.error:
            lines.append(f"   {r.error}")
        for t in r.targets:
            if t.not_checked:
                lines.append(f"   {t.table}: not checked ({t.not_checked})")
            elif t.error:
                lines.append(f"   {t.table}: could not be checked - {t.error}")
            else:
                lines.append(f"   {t.table}: {t.applied} of {t.total} changes apply"
                             + (f", {t.skipped} skipped" if t.skipped else ""))
                for reason in t.reasons:
                    lines.append(f"      {reason}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
