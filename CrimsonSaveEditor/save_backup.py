"""Back up and restore ALL save games at once (no Qt in here).

Meant for "before I try a mod": one click zips the whole save folder of the
game - every account folder, every slot and the auto saves - into the tool's
backups/all_saves folder, with date and time in the name. A restore copies the
files of such a zip back over the save folder; before that it makes one more
zip of the current state ("before restore"), so a restore can be undone too.

Save folders (the same places the Save Browser looks in):
  %LOCALAPPDATA%\\Pearl Abyss\\CD\\save          (Steam)
  %LOCALAPPDATA%\\Pearl Abyss\\CD_Epic\\save     (Epic)
  %LOCALAPPDATA%\\Pearl Abyss\\CD_GamePass\\save
  a save folder set in the Save Browser settings (config "save_root")
  Linux/Proton: ...compatdata/3321460/.../Pearl Abyss/CD/save
Inside the zip each folder is stored under a short label (CD, CD_Epic, ...);
manifest.json maps the labels to the full paths they came from.

A restore only writes files that are in the zip. Files that are in the save
folder but not in the zip (e.g. a slot made later) stay as they are.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import zipfile
from typing import Dict, List, Optional

FOLDER = "all_saves"
KEEP = 20                       # newest zips kept; older ones are removed
MANIFEST = "manifest.json"
PREFIX = "CD_saves_"


def save_roots(config: Optional[dict] = None) -> Dict[str, str]:
    """{label: folder} of every save folder that exists."""
    config = config or {}
    found: Dict[str, str] = {}

    def add(label: str, path: str) -> None:
        if not path or not os.path.isdir(path):
            return
        norm = os.path.normcase(os.path.abspath(path))
        if any(os.path.normcase(os.path.abspath(p)) == norm for p in found.values()):
            return
        name, n = label, 2
        while name in found:
            name, n = f"{label}_{n}", n + 1
        found[name] = path

    custom = config.get("save_root", "")
    if custom:
        add("custom", custom)
    locals_ = [config.get("custom_localappdata", ""), os.environ.get("LOCALAPPDATA", "")]
    for local in locals_:
        if not local:
            continue
        for sub in ("CD", "CD_Epic", "CD_GamePass"):
            add(sub, os.path.join(local, "Pearl Abyss", sub, "save"))
    if sys.platform != "win32":
        user = os.getenv("USER", "")
        if user:
            add("CD", os.path.join(
                f"/home/{user}/.local/share/Steam/steamapps/compatdata",
                "3321460/pfx/drive_c/users/steamuser/AppData/Local", "Pearl Abyss/CD/save"))
    return found


def backup_folder(app_dir: str) -> str:
    return os.path.join(app_dir, "backups", FOLDER)


def game_running() -> bool:
    """True if CrimsonDesert.exe runs (Windows only; elsewhere False)."""
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CrimsonDesert.exe", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "crimsondesert.exe" in (out.stdout or "").lower()
    except Exception:  # noqa: BLE001
        return False


def _files(root: str):
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            full = os.path.join(dirpath, n)
            yield full, os.path.relpath(full, root)


def backup_all(app_dir: str, config: Optional[dict] = None, note: str = "",
               tool_version: str = "") -> dict:
    """Zip every save folder. Returns {"path", "files", "bytes", "roots"}.
    Raises FileNotFoundError when no save folder exists."""
    roots = save_roots(config)
    if not roots:
        raise FileNotFoundError("No save folder found.")
    dest = backup_folder(app_dir)
    os.makedirs(dest, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = "_before_restore" if note == "before restore" else ""
    path = os.path.join(dest, f"{PREFIX}{stamp}{tag}.zip")
    n = 2
    while os.path.exists(path):
        path = os.path.join(dest, f"{PREFIX}{stamp}{tag}_{n}.zip")
        n += 1
    tmp = path + ".part"
    count = total = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for label, root in roots.items():
            for full, rel in _files(root):
                z.write(full, f"{label}/{rel.replace(os.sep, '/')}")
                count += 1
                total += os.path.getsize(full)
        z.writestr(MANIFEST, json.dumps({
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "tool_version": tool_version, "note": note, "files": count, "bytes": total,
            "roots": roots}, indent=1))
    os.replace(tmp, path)
    _prune(dest)
    return {"path": path, "files": count, "bytes": total, "roots": roots}


def _prune(dest: str) -> None:
    zips = sorted((f for f in os.listdir(dest) if f.startswith(PREFIX) and f.endswith(".zip")),
                  key=lambda f: os.path.getmtime(os.path.join(dest, f)), reverse=True)
    for old in zips[KEEP:]:
        try:
            os.remove(os.path.join(dest, old))
        except OSError:
            pass


def read_manifest(path: str) -> dict:
    with zipfile.ZipFile(path) as z:
        try:
            return json.loads(z.read(MANIFEST).decode("utf-8"))
        except KeyError:
            return {}


def list_backups(app_dir: str) -> List[dict]:
    """Newest first: {"path", "name", "time", "size", "files", "note"}."""
    dest = backup_folder(app_dir)
    if not os.path.isdir(dest):
        return []
    out = []
    for f in os.listdir(dest):
        if not (f.startswith(PREFIX) and f.endswith(".zip")):
            continue
        p = os.path.join(dest, f)
        try:
            m = read_manifest(p)
        except (OSError, zipfile.BadZipFile, ValueError):
            m = {"note": "damaged"}
        out.append({"path": p, "name": f, "time": os.path.getmtime(p), "size": os.path.getsize(p),
                    "files": m.get("files"), "note": m.get("note", ""),
                    "created": m.get("created", "")})
    out.sort(key=lambda d: d["time"], reverse=True)
    return out


def restore(path: str, app_dir: str, config: Optional[dict] = None,
            tool_version: str = "") -> dict:
    """Copy the files of a backup zip back. First zips the current state.
    Returns {"files", "safety"} (safety = path of the "before restore" zip or "")."""
    m = read_manifest(path)
    roots: Dict[str, str] = dict(m.get("roots") or {})
    if not roots:
        raise ValueError("This zip is not a save backup made by the tool (no manifest).")
    safety = ""
    if save_roots(config):
        safety = backup_all(app_dir, config, note="before restore", tool_version=tool_version)["path"]
    written = 0
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir() or info.filename == MANIFEST:
                continue
            label, _, rel = info.filename.partition("/")
            root = roots.get(label)
            if not root or not rel:
                continue
            target = os.path.normpath(os.path.join(root, *rel.split("/")))
            if not os.path.normcase(target).startswith(os.path.normcase(os.path.normpath(root)) + os.sep):
                continue                                   # never outside the save folder
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tmp = target + ".restore_tmp"
            with z.open(info) as src, open(tmp, "wb") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
            os.replace(tmp, target)
            written += 1
    return {"files": written, "safety": safety}


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"
