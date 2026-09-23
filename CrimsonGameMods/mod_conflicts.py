"""Which active DMM mods change the same thing? Read-only.

DMM applies mods one after another. When two mods change the same field of
the same record, or replace the same file, only one of them can win - and
nothing says which. This check reads DMM's own config (active mods, load
order) and works out what each mod really changes:

  Field JSON (format 3) mods: every table target is applied IN MEMORY to the
      unmodded table from the game (group 0008) with the parser's
      apply_intents, and the result is compared with the unmodded table
      field by field. So a change counts only if it really happens - an
      outdated entry that no longer matches changes nothing and is not
      reported as a conflict.
      Rules the parser cannot evaluate here (e.g. "match" filters over many
      records) are listed per table and field as broad changes.
  Byte-patch JSON mods (older format): the changed byte ranges per file.
  Folder mods (loose files): every file the mod replaces.

Nothing is written - not to the game, not to DMM.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

TABLE_DIR = "gamedata/binary__/client/bin"
_SKIP_FILES = {"mod.json", "modinfo.json", "readme.txt", "readme.md", "manifest.json"}
_SKIP_EXT = {".txt", ".md", ".url", ".html"}
_PREVIEW_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass
class ModRef:
    name: str          # as DMM shows it (file name or folder)
    kind: str          # "json" or "folder"
    path: str          # absolute
    order: Optional[int] = None

    @property
    def label(self) -> str:
        base = self.name
        return f"{base} (#{self.order + 1})" if self.order is not None else base


@dataclass
class Finding:
    kind: str            # conflict | same | broad | file | bytes
    where: str           # what is changed
    mods: List[ModRef]
    table: str = ""
    record: str = ""     # "Name (key)" for field findings
    path: str = ""       # field path inside the record


@dataclass
class Report:
    mods: List[ModRef] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    not_checked: List[str] = field(default_factory=list)
    changes_per_mod: Dict[str, int] = field(default_factory=dict)

    def count(self, kind: str) -> int:
        return sum(1 for f in self.findings if f.kind == kind)

    def text(self) -> str:
        c, fl, b, by = (self._groups("conflict"), self.count("file"),
                        self._groups("broad"), self.count("bytes"))
        out = ["Conflict check of the active DMM mods",
               "Nothing was written - every mod was applied in memory only.", "",
               f"{len(self.mods)} active mods checked: {c} field conflict(s), {fl} file conflict(s), "
               f"{by} byte-patch overlap(s), {b} possible conflict(s).",
               "The #number is the mod's place in DMM's load order.", ""]
        if not (c or fl or b or by):
            out += ["No two active mods change the same thing differently. Load order does not "
                    "matter for these mods.", ""]

        def mods_line(ms):
            return "      " + "  vs  ".join(m.label for m in ms)

        def paths_text(paths):
            paths = sorted(paths)
            shown = ", ".join(paths[:3])
            return shown + (f" (+{len(paths) - 3} more)" if len(paths) > 3 else "")

        # field conflicts: one line per record and group of mods
        groups = self._grouped("conflict")
        if groups:
            out.append("FIELD CONFLICTS - the same field of the same record, set differently. "
                       "Only one mod can win:")
            for (table, record, _names), (ms, paths) in groups[:150]:
                n = len(paths)
                out.append(f"  {table} / {record}: {n} field{'s' if n != 1 else ''} - {paths_text(paths)}")
                out.append(mods_line(ms))
            if len(groups) > 150:
                out.append(f"  ... and {len(groups) - 150} more records")
            out.append("")
        for kind, head in (("file", "FILE CONFLICTS - the same game file, replaced or patched by "
                                    "more than one mod:"),
                           ("bytes", "BYTE-PATCH OVERLAPS - older-format mods that patch the same bytes:")):
            items = [f for f in self.findings if f.kind == kind]
            if items:
                out.append(head)
                for f in items[:150]:
                    out.append(f"  {f.where}")
                    out.append(mods_line(f.mods))
                out.append("")
        broad = self._grouped("broad", by_record=False)
        if broad:
            out.append("POSSIBLE CONFLICTS - a broad rule of one mod (over many records, not "
                       "evaluated here) touches a field another mod also changes:")
            for (table, _r, _names), (ms, paths) in broad:
                out.append(f"  {table}: {paths_text(paths)}")
                out.append(mods_line(ms))
            out.append("")
        same = self._grouped("same", by_record=False)
        if same:
            out.append("SAME CHANGE IN SEVERAL MODS - identical values, harmless:")
            for (table, _r, _names), (ms, paths) in same:
                out.append(f"  {table}: {len(paths)} identical change(s)")
                out.append(mods_line(ms))
            out.append("")
        if c or fl or by:
            out += ["Which mod wins depends on DMM's load order. If the result is not what you "
                    "want, change the order in DMM or deactivate one of the mods.", ""]
        if self.not_checked:
            out.append("NOT CHECKED:")
            out += [f"  {n}" for n in self.not_checked]
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    def _grouped(self, kind: str, by_record: bool = True):
        groups: Dict[tuple, Tuple[List[ModRef], List[str]]] = {}
        for f in self.findings:
            if f.kind != kind:
                continue
            key = (f.table, f.record if by_record else "", tuple(m.name for m in f.mods))
            ms, paths = groups.setdefault(key, (f.mods, []))
            paths.append(f.path if by_record else (f.path.split("[", 1)[0] if kind == "same" else f.path))
        if kind == "same":
            for k, (ms, paths) in groups.items():
                groups[k] = (ms, paths)
        return sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1]))

    def _groups(self, kind: str) -> int:
        return len(self._grouped(kind, by_record=(kind != "broad")))


# ── DMM setup ─────────────────────────────────────────────────────────────

def find_dmm_dir(candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "config.json")):
            try:
                with open(os.path.join(c, "config.json"), encoding="utf-8") as f:
                    doc = json.load(f)
                if "activeMods" in doc or "modsPath" in doc:
                    return c
            except Exception:  # noqa: BLE001
                continue
    return None


def read_setup(dmm_dir: str) -> Tuple[List[ModRef], List[str]]:
    with open(os.path.join(dmm_dir, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    mods_path = cfg.get("modsPath") or ""
    if not os.path.isdir(mods_path):          # DMM folder moved, or a path from another system
        mods_path = os.path.join(dmm_dir, "mods")
    order = cfg.get("definitiveLoadOrder") or []
    pos = {name: i for i, name in enumerate(order)}
    mods: List[ModRef] = []
    notes: List[str] = []
    for am in cfg.get("activeMods") or []:
        name = am.get("fileName") if isinstance(am, dict) else str(am)
        if not name:
            continue
        p = os.path.join(mods_path, name)
        o = pos.get(name)
        if o is None and "/" in name:
            o = pos.get("bundle:" + name.split("/", 1)[0])
        if not os.path.isfile(p):
            notes.append(f"{name}: file not found in the DMM mods folder")
            continue
        mods.append(ModRef(name, "json", p, o))
    for name in cfg.get("activeBrowserMods") or []:
        p = os.path.join(mods_path, name)
        o = pos.get("browser:" + name, pos.get("browser:" + name.split("/", 1)[0]))
        if not os.path.isdir(p):
            notes.append(f"{name}: folder not found in the DMM mods folder")
            continue
        mods.append(ModRef(name, "folder", p, o))
    for name in cfg.get("activeAsiMods") or []:
        notes.append(f"{name}: ASI mod (program code) - cannot be checked")
    return mods, notes


# ── what a mod changes ────────────────────────────────────────────────────

def _stem(name: str) -> str:
    base = os.path.basename(name or "").lower()
    for ext in (".pabgb", ".pabgh", ".staticinfobody", ".staticinfoheader"):
        if base.endswith(ext):
            return base[:-len(ext)]
    return base


def _leaf_diff(a, b, path: str, out: Dict[str, str]) -> None:
    if a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            _leaf_diff(a.get(k), b.get(k), f"{path}.{k}" if path else str(k), out)
        return
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            _leaf_diff(x, y, f"{path}[{i}]", out)
        return
    out[path] = json.dumps(b, sort_keys=True, default=repr)[:2000]


def _record_id(rec: dict, i: int):
    for k in ("key", "_key", "index"):
        if k in rec:
            return rec[k]
    return f"#{i}"


def _record_name(rec: dict) -> str:
    for k in ("string_key", "name", "entry"):
        v = rec.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _read_table(dmm, game_path: str, stem: str):
    body = bytes(dmm.extract_file(game_path, "0008", TABLE_DIR, stem + ".pabgb"))
    try:
        head = bytes(dmm.extract_file(game_path, "0008", TABLE_DIR, stem + ".pabgh"))
    except Exception:  # noqa: BLE001 - sequential tables have no index
        head = None
    return body, head


def _apply(dmm, stem: str, body: bytes, head, intents: list):
    """apply_intents, leaving out ops this parser build does not know
    (DMM itself may know them). Returns (output, intents left out)."""
    left_out: list = []
    todo = list(intents)
    for _ in range(6):
        try:
            return dmm.apply_intents(stem, body, None if stem == "iteminfo" else head, todo), left_out
        except ValueError as e:
            msg = str(e)
            if "unknown intent op" not in msg:
                raise
            op = msg.rsplit("'", 2)[-2] if msg.count("'") >= 2 else None
            if not op:
                raise
            left_out += [i for i in todo if isinstance(i, dict) and i.get("op") == op]
            todo = [i for i in todo if not (isinstance(i, dict) and i.get("op") == op)]
    raise ValueError("too many unknown intent ops")


def _table_changes(dmm, game_path: str, stem: str, jobs: List[Tuple[ModRef, list]],
                   specific: Dict[tuple, Dict[str, List[ModRef]]],
                   broad: Dict[tuple, List[ModRef]], notes: List[str],
                   counts: Dict[str, int]) -> None:
    """All mods that target one table, against one parse of the unmodded
    table - one table at a time keeps memory low (characterinfo alone parses
    into hundreds of MB)."""
    try:
        body, head = _read_table(dmm, game_path, stem)
        vanilla = {_record_id(r, i): r for i, r in enumerate(dmm.parse_table(stem, body, head))}
    except Exception as e:  # noqa: BLE001
        for mod, _ in jobs:
            notes.append(f"{mod.name} / {stem}: table not readable ({e})"[:300])
        return
    for mod, intents in jobs:
        try:
            out, left_out = _apply(dmm, stem, body, head, intents)
            new_head = out.get("pabgh")
            new = dmm.parse_table(stem, bytes(out["body"]), bytes(new_head) if new_head else head)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{mod.name} / {stem}: could not be applied here ({e})"[:300])
            continue
        n = 0
        for i, rec in enumerate(new):
            rid = _record_id(rec, i)
            old = vanilla.get(rid)
            if old is None:
                specific.setdefault((stem, rid, "<new record>", _record_name(rec)), {}) \
                    .setdefault(json.dumps(rec, sort_keys=True, default=repr)[:2000], []).append(mod)
                n += 1
                continue
            if rec == old:
                continue
            diff: Dict[str, str] = {}
            _leaf_diff(old, rec, "", diff)
            for path, val in diff.items():
                specific.setdefault((stem, rid, path, _record_name(rec)), {}) \
                    .setdefault(val, []).append(mod)
                n += 1
        del new
        counts[mod.name] = counts.get(mod.name, 0) + n
        applied = [i for i in intents if i not in left_out]
        for it, oc in zip(applied, out.get("outcomes") or []):
            if oc.get("status") != "applied" and isinstance(it, dict) and "match" in it and it.get("field"):
                broad.setdefault((stem, str(it["field"])), []).append(mod)
        for it in left_out:
            if it.get("field"):
                broad.setdefault((stem, str(it["field"])), []).append(mod)
        if left_out:
            ops = sorted({str(i.get("op")) for i in left_out})
            notes.append(f"{mod.name} / {stem}: {len(left_out)} change(s) with op "
                         f"{', '.join(ops)} counted as broad changes (not evaluated here)")


def analyze(dmm_dir: str, game_path: str,
            progress: Optional[Callable[[int, int, str], None]] = None, dmm=None) -> Report:
    if dmm is None:
        import dmm_parser as dmm  # noqa: PLC0415
    mods, notes = read_setup(dmm_dir)
    rep = Report(mods=mods, not_checked=notes)
    jobs: Dict[str, List[Tuple[ModRef, list]]] = defaultdict(list)
    specific: Dict[tuple, Dict[str, List[ModRef]]] = {}
    broad: Dict[tuple, List[ModRef]] = {}
    files: Dict[str, List[ModRef]] = defaultdict(list)
    byte_ranges: Dict[str, List[Tuple[int, int, ModRef]]] = defaultdict(list)

    for n, mod in enumerate(mods):
        if progress:
            progress(n, len(mods) + 1, mod.name)
        if mod.kind == "folder":
            for rel in _folder_files(mod.path):
                files[rel].append(mod)
            rep.changes_per_mod[mod.name] = -1
            continue
        try:
            with open(mod.path, encoding="utf-8-sig") as f:
                doc = json.load(f)
        except Exception as e:  # noqa: BLE001
            rep.not_checked.append(f"{mod.name}: not readable ({e})")
            continue
        if doc.get("format") == 3 or doc.get("targets"):
            rep.changes_per_mod.setdefault(mod.name, 0)
            for t in doc.get("targets") or []:
                fname = t.get("file") or t.get("table") or t.get("vpath") or ""
                kind, intents = t.get("kind"), t.get("intents")
                stem = _stem(fname)
                if (kind and kind != "table") or intents is None or "paloc" in stem:
                    files[fname.lower() or "?"].append(mod)
                    continue
                jobs[stem].append((mod, intents))
        elif doc.get("patches"):
            for p in doc["patches"]:
                gf = (p.get("game_file") or "").lower()
                for ch in p.get("changes") or []:
                    try:
                        off = int(ch.get("offset"))
                        ln = max(1, len(bytes.fromhex(ch.get("patched") or ch.get("original") or "00")))
                    except Exception:  # noqa: BLE001
                        continue
                    byte_ranges[gf].append((off, off + ln, mod))
            rep.changes_per_mod[mod.name] = sum(len(p.get("changes") or []) for p in doc["patches"])
        else:
            rep.not_checked.append(f"{mod.name}: format not recognised")
    steps = len(mods) + len(jobs)
    for k, (stem, table_jobs) in enumerate(sorted(jobs.items())):
        if progress:
            progress(len(mods) + k, steps, f"table {stem} ({len(table_jobs)} mod(s))")
        _table_changes(dmm, game_path, stem, table_jobs, specific, broad,
                       rep.not_checked, rep.changes_per_mod)
    if progress:
        progress(steps, steps, "")

    # field conflicts and identical changes
    touched_fields: Dict[tuple, Set[str]] = defaultdict(set)
    for (stem, rid, path, name), values in specific.items():
        head = f"{stem} / {name + ' ' if name else ''}({rid}) / {path}"
        root = path.split(".", 1)[0].split("[", 1)[0]
        for vs in values.values():
            for m in vs:
                touched_fields[(stem, root)].add(m.name)
        all_mods = _unique([m for vs in values.values() for m in vs])
        if len(all_mods) < 2:
            continue
        kind = "same" if len(values) == 1 else "conflict"
        rec_label = f"{name} ({rid})" if name else f"({rid})"
        rep.findings.append(Finding(kind, head, all_mods, stem, rec_label, path))

    for (stem, fld), bmods in broad.items():
        root = fld.split(".", 1)[0].split("[", 1)[0]
        others = [m for m in mods if m.name in touched_fields.get((stem, root), set())]
        involved = _unique(list(bmods) + others)
        if len(involved) >= 2:
            rep.findings.append(Finding("broad", f"{stem} / {fld} (rule over many records)", involved,
                                        stem, "", fld))

    # files: folder mods, asset targets and byte-patched files
    for gf, ranges in byte_ranges.items():
        files.setdefault(gf, [])
    for rel, fmods in sorted(files.items()):
        involved = _unique(fmods + [r[2] for r in byte_ranges.get(rel, [])])
        if len(involved) >= 2:
            rep.findings.append(Finding("file", rel, involved))
    for gf, ranges in byte_ranges.items():
        ranges.sort(key=lambda r: r[0])
        seen = set()
        for i, (a0, a1, am) in enumerate(ranges):
            for b0, b1, bm in ranges[i + 1:]:
                if b0 >= a1:
                    break
                if am is not bm and (am.name, bm.name) not in seen:
                    seen.add((am.name, bm.name))
                    rep.findings.append(Finding("bytes", f"{gf} at 0x{b0:X}", [am, bm]))

    order = {"conflict": 0, "file": 1, "bytes": 2, "broad": 3, "same": 4}
    rep.findings.sort(key=lambda f: (order[f.kind], f.where))
    return rep


def _unique(mods: List[ModRef]) -> List[ModRef]:
    seen, out = set(), []
    for m in mods:
        if m.name not in seen:
            seen.add(m.name)
            out.append(m)
    return sorted(out, key=lambda m: (m.order is None, m.order or 0))


def _folder_files(folder: str) -> List[str]:
    """Game paths a loose-file mod replaces (relative to the folder with mod.json)."""
    root = folder
    for dirpath, _dirs, names in os.walk(folder):
        if "mod.json" in {n.lower() for n in names}:
            root = dirpath
            break
    out = []
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            low = n.lower()
            rel = os.path.relpath(os.path.join(dirpath, n), root).replace("\\", "/").lower()
            ext = os.path.splitext(low)[1]
            if low in _SKIP_FILES or ext in _SKIP_EXT:
                continue
            if "/" not in rel and ext in _PREVIEW_EXT:
                continue      # preview picture next to mod.json
            out.append(rel)
    return out
