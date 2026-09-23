"""Copy the Save Editor into the Game Mod Tool as the package `save_editor`.

Why a generated copy: both tools grew out of one program and still share
22 module names (item_db, models, save_parser, ...) plus `gui` (a module in
the Save Editor, a package here). Imported side by side, whichever loads
first wins and the other tool silently gets the wrong module. The copy
rewrites the Save Editor's own imports to `save_editor.<name>`, so both
sets live next to each other without touching each other.

The Save Editor folder stays the one source of truth - it keeps working as
its own program. This script regenerates the copy; the PyInstaller spec runs
it before every build, and the Game Mod Tool runs it when started from
source and the copy is missing or older than the Save Editor.

Paths: the Save Editor finds its data through sys._MEIPASS / sys.executable
(frozen) or next to its own files. Its modules get a stand-in `sys`
(_sys_proxy) that answers those two with the Save Editor's own folders:
bundled data under save_editor/, user files (config, sets, refreshed item
database) in a folder "SaveEditorData" beside the EXE. Everything else is
the real sys. So its settings never mix with the Game Mod Tool's
editor_config.json, which has the same file name.
"""
from __future__ import annotations

import ast
import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GMT_DIR = os.path.dirname(HERE)                       # CrimsonGameMods/
REPO_DIR = os.path.dirname(GMT_DIR)
SRC_DIR = os.path.join(REPO_DIR, "CrimsonSaveEditor")
DST_DIR = os.path.join(GMT_DIR, "save_editor")
PKG = "save_editor"
STAMP = "_vendored_from.txt"

SKIP_DIRS = {"build", "dist", "pre-release", "__pycache__", "dmm_parser"}
SKIP_FILES = {"editor_config.json", "main.py"}
SKIP_EXT = {".exe", ".spec", ".pyc", ".log"}
# dmm_parser is byte-identical in both tools and stays the shared top-level
# package; everything else the Save Editor imports from its folder is local.
SHARED = {"dmm_parser"}


def _source_files():
    for root, dirs, files in os.walk(SRC_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f in SKIP_FILES or os.path.splitext(f)[1].lower() in SKIP_EXT:
                continue
            yield os.path.join(root, f)


def source_hash() -> str:
    h = hashlib.sha1()
    for p in sorted(_source_files()):
        rel = os.path.relpath(p, SRC_DIR).replace("\\", "/")
        h.update(rel.encode())
        with open(p, "rb") as f:
            h.update(f.read())
    root_packs = os.path.join(REPO_DIR, "knowledge_packs")
    if os.path.isdir(root_packs):
        for f in sorted(os.listdir(root_packs)):
            with open(os.path.join(root_packs, f), "rb") as fh:
                h.update(f.encode() + fh.read())
    return h.hexdigest()


def is_current() -> bool:
    stamp = os.path.join(DST_DIR, STAMP)
    if not os.path.isfile(stamp) or not os.path.isdir(SRC_DIR):
        return os.path.isfile(stamp)          # no source here (e.g. frozen): trust the copy
    with open(stamp, encoding="utf-8") as f:
        return f.read().strip() == source_hash()


def _local_names() -> set:
    names = set()
    for f in os.listdir(SRC_DIR):
        p = os.path.join(SRC_DIR, f)
        if f.endswith(".py") and f not in SKIP_FILES:
            names.add(f[:-3])
        elif os.path.isdir(p) and os.path.isfile(os.path.join(p, "__init__.py")) and f not in SKIP_DIRS:
            names.add(f)
    return names - SHARED


def _alias(a):
    return f" as {a.asname}" if a.asname else ""


def _rewrite_import(node, local):
    """Replacement source for one import statement, or None to keep it."""
    if isinstance(node, ast.ImportFrom):
        if node.level or not node.module:
            return None
        top = node.module.split(".")[0]
        if top not in local:
            return None
        names = ", ".join(a.name + _alias(a) for a in node.names)
        return f"from {PKG}.{node.module} import {names}"
    parts, changed = [], False
    for a in node.names:
        top = a.name.split(".")[0]
        if a.name == "sys":
            parts.append(f"from {PKG}._sys_proxy import sys{_alias(a)}")
            changed = True
        elif top in local and "." not in a.name:
            parts.append(f"from {PKG} import {a.name}{_alias(a)}")
            changed = True
        elif top in local:                      # import x.y  (binds x)
            if a.asname:
                parts.append(f"import {PKG}.{a.name} as {a.asname}")
            else:
                parts.append(f"from {PKG} import {top}; import {PKG}.{a.name}")
            changed = True
        else:
            parts.append(f"import {a.name}{_alias(a)}")
    return "; ".join(parts) if changed else None


def rewrite_source(src: str, local: set) -> str:
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln))

    def pos(lineno, col):
        # ast columns are UTF-8 byte offsets
        line = lines[lineno - 1]
        return offsets[lineno - 1] + len(line.encode("utf-8")[:col].decode("utf-8", "ignore"))

    edits = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            new = _rewrite_import(node, local)
            if new is not None:
                edits.append((pos(node.lineno, node.col_offset),
                              pos(node.end_lineno, node.end_col_offset), new))
    for start, end, new in sorted(edits, reverse=True):
        src = src[:start] + new + src[end:]
    # __import__('sys') hands out the real sys; give these the stand-in too.
    src = src.replace("__import__('sys')", f"__import__('{PKG}._sys_proxy', fromlist=['sys']).sys")
    src = src.replace('__import__("sys")', f"__import__('{PKG}._sys_proxy', fromlist=['sys']).sys")
    return src


SYS_PROXY = '''"""A stand-in for `sys` used by the vendored Save Editor (generated file).

Answers _MEIPASS and executable with the Save Editor's own folders when
frozen, so its data lookups and its settings stay separate from the Game Mod
Tool's. Everything else goes to the real sys.
"""
import os as _os
import sys as _real

_PKG_DIR = _os.path.dirname(_os.path.abspath(__file__))


def data_dir() -> str:
    """Folder for the Save Editor's own settings and files when frozen."""
    d = _os.path.join(_os.path.dirname(_os.path.abspath(_real.executable)), "SaveEditorData")
    try:
        _os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


class _SysProxy:
    def __getattr__(self, name):
        if getattr(_real, "frozen", False):
            if name == "_MEIPASS":
                return _PKG_DIR
            if name == "executable":
                return _os.path.join(data_dir(), "CrimsonSaveEditor.exe")
        return getattr(_real, name)

    def __setattr__(self, name, value):
        setattr(_real, name, value)

    def __dir__(self):
        return dir(_real)


sys = _SysProxy()
'''

INIT = '''"""The Save Editor, embedded in the Game Mod Tool (generated by
tools/vendor_save_editor.py - do not edit here; edit CrimsonSaveEditor/)."""
'''


def vendor(verbose: bool = True) -> str:
    if not os.path.isdir(SRC_DIR):
        raise SystemExit(f"Save Editor source not found: {SRC_DIR}")
    local = _local_names()
    tmp = DST_DIR + ".tmp"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    count_py = count_data = 0
    for p in _source_files():
        rel = os.path.relpath(p, SRC_DIR)
        out = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if p.endswith(".py"):
            with open(p, encoding="utf-8") as f:
                src = f.read()
            with open(out, "w", encoding="utf-8", newline="") as f:
                f.write(rewrite_source(src, local))
            count_py += 1
        else:
            shutil.copy2(p, out)
            count_data += 1
    # The Save Editor build also bundles the packs from the repository root.
    root_packs = os.path.join(REPO_DIR, "knowledge_packs")
    if os.path.isdir(root_packs):
        dst = os.path.join(tmp, "knowledge_packs")
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(root_packs):
            shutil.copy2(os.path.join(root_packs, f), os.path.join(dst, f))
    with open(os.path.join(tmp, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(INIT)
    with open(os.path.join(tmp, "_sys_proxy.py"), "w", encoding="utf-8") as f:
        f.write(SYS_PROXY)
    digest = source_hash()
    with open(os.path.join(tmp, STAMP), "w", encoding="utf-8") as f:
        f.write(digest)
    if os.path.isdir(DST_DIR):
        shutil.rmtree(DST_DIR)
    os.replace(tmp, DST_DIR)
    if verbose:
        print(f"save_editor: {count_py} modules rewritten, {count_data} data files copied "
              f"({len(local)} local module names)")
    return DST_DIR


def ensure_current() -> bool:
    """Regenerate the copy if the Save Editor source changed. True if usable."""
    try:
        if not is_current():
            vendor(verbose=False)
        return os.path.isfile(os.path.join(DST_DIR, "gui.py"))
    except Exception as e:  # noqa: BLE001
        print(f"save_editor vendoring failed: {e}", file=sys.stderr)
        return os.path.isfile(os.path.join(DST_DIR, "gui.py"))


if __name__ == "__main__":
    vendor()
