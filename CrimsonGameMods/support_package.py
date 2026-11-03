"""Support package: one zip a user can send when something goes wrong.

Contents (the Windows user name is replaced by <user> everywhere):
    info.txt            tool / game / DLC / Windows versions, folders
    logs.txt            the end of the tool's log (logs.txt next to the exe)
    editor_config.json  the tool's settings (anything that looks like a
                        token, key or password is left out)
    dmm_mods.txt        names of the mods DMM has mounted (from the game's
                        bin64/dmm/manifest.tsv), not the files themselves
    dmm_activity.json   DMM's own log (logs/activity.json in the DMM folder:
                        mount errors, "N edit(s) skipped" ...), if the DMM
                        folder is known. Nothing else is read from that
                        folder (its login file stays untouched).
    mods/<name>         mod files the user chose to add (the one with the
                        problem), so the report shows exactly what is in it
No save files, no game files. No Qt in here.
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
import zipfile
from typing import List, Optional, Tuple

LOG_TAIL_BYTES = 2_000_000
MOD_FILE_MAX = 20_000_000        # per added mod file
_SECRET = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|auth|cookie|session)")


def _mask(text: str) -> str:
    try:
        from simple_report import _mask as mask
        return mask(text)
    except Exception:  # noqa: BLE001
        return re.sub(r"(?i)([\\/]Users[\\/])[^\\/\s\"']+", r"\1<user>", text)


def _app_dir() -> str:
    return os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))


def _tail(path: str, size: int) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            n = f.tell()
            f.seek(max(0, n - size))
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        if n > size:
            text = "... (older lines left out)\n" + text.split("\n", 1)[-1]
        return text
    except Exception as e:  # noqa: BLE001
        return f"(log not readable: {e})"


def _clean_config(obj):
    if isinstance(obj, dict):
        return {k: ("(left out)" if _SECRET.search(str(k)) else _clean_config(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_config(v) for v in obj]
    return obj


def _dmm_mods(game_path: str) -> str:
    man = os.path.join(game_path or "", "bin64", "dmm", "manifest.tsv")
    if not os.path.isfile(man):
        return "(no DMM mount list in the game folder - DMM has not mounted anything)"
    mods, n_files = {}, 0
    try:
        with open(man, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3 and parts[0] == "file":
                    n_files += 1
                    src = parts[2].replace("/", "\\")
                    m = re.search(r"(?i)\\mods\\([^\\]+)", src)
                    name = m.group(1) if m else "(files DMM made itself, e.g. merged tables)"
                    mods[name] = mods.get(name, 0) + 1
    except Exception as e:  # noqa: BLE001
        return f"(DMM mount list not readable: {e})"
    lines = [f"File mods mounted by DMM ({len(mods)} mods, {n_files} files):"]
    lines += [f"  {k}  ({v} files)" for k, v in sorted(mods.items(), key=lambda x: x[0].lower())]
    lines.append("")
    lines.append("Field JSON / byte-patch mods are built into the game tables by DMM and")
    lines.append("do not show up in this list.")
    return "\n".join(lines)


def guess_dmm_dir(game_path: str) -> str:
    """The DMM folder, read from DMM's mount list in the game folder: its
    lines name the mod files as <DMM folder>\\mods\\<mod>\\... . "" if unknown."""
    man = os.path.join(game_path or "", "bin64", "dmm", "manifest.tsv")
    try:
        with open(man, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3 and parts[0] == "file":
                    src = parts[2]
                    m = re.search(r"(?i)^(.*?)[\\/]mods[\\/]", src)
                    if m and os.path.isfile(os.path.join(m.group(1), "logs", "activity.json")):
                        return m.group(1)
    except Exception:  # noqa: BLE001
        pass
    return ""


def dmm_log_path(dmm_dir: str) -> str:
    p = os.path.join(dmm_dir or "", "logs", "activity.json")
    return p if dmm_dir and os.path.isfile(p) else ""


def build_support_zip(out_path: str, app_version: str, game_path: str,
                      config_path: Optional[str] = None,
                      log_path: Optional[str] = None,
                      extra: Optional[List[Tuple[str, str]]] = None,
                      dmm_dir: Optional[str] = None,
                      mod_files: Optional[List[str]] = None) -> List[str]:
    """Write the zip. Returns the names of the files in it."""
    game_path = game_path or ""
    log_path = log_path or os.path.join(_app_dir(), "logs.txt")
    names: List[str] = []

    info = [
        "CrimsonGameMods - support package",
        "=" * 50,
        f"Created:       {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Tool version:  {app_version}",
        f"Windows:       {platform.platform()}",
        f"Python:        {platform.python_version()}",
        f"Tool folder:   {_app_dir()}",
        f"Game folder:   {game_path or '(not set)'}",
    ]
    try:
        from game_version import read_game_version
        info.append(f"Game version:  {read_game_version(game_path) or '?'}")
    except Exception as e:  # noqa: BLE001
        info.append(f"Game version:  ? ({e})")
    dlc = os.path.join(game_path, "dlc")
    dlcs = sorted(d for d in os.listdir(dlc) if os.path.isdir(os.path.join(dlc, d))) \
        if os.path.isdir(dlc) else []
    info.append(f"DLC installed: {', '.join(dlcs) if dlcs else 'no'}")
    for label, text in extra or []:
        info.append(f"{label}: {text}")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("info.txt", _mask("\n".join(info) + "\n"))
        names.append("info.txt")
        z.writestr("logs.txt", _mask(_tail(log_path, LOG_TAIL_BYTES)))
        names.append("logs.txt")
        if config_path and os.path.isfile(config_path):
            try:
                with open(config_path, encoding="utf-8") as f:
                    cfg = _clean_config(json.load(f))
                z.writestr("editor_config.json",
                           _mask(json.dumps(cfg, indent=2, ensure_ascii=False)))
                names.append("editor_config.json")
            except Exception as e:  # noqa: BLE001
                z.writestr("editor_config.txt", f"(settings not readable: {e})")
                names.append("editor_config.txt")
        z.writestr("dmm_mods.txt", _mask(_dmm_mods(game_path)))
        names.append("dmm_mods.txt")
        dlog = dmm_log_path(dmm_dir or "")
        if dlog:
            z.writestr("dmm_activity.json", _mask(_tail(dlog, LOG_TAIL_BYTES)))
            names.append("dmm_activity.json")
        for i, mf in enumerate(mod_files or []):
            try:
                if os.path.getsize(mf) > MOD_FILE_MAX:
                    z.writestr(f"mods/{i}_TOO_BIG.txt", _mask(f"{mf}: larger than "
                                                           f"{MOD_FILE_MAX // 1_000_000} MB, left out"))
                    continue
                arc = f"mods/{os.path.basename(mf)}"
                with open(mf, "rb") as f:
                    data = f.read()
                if mf.lower().endswith((".json", ".txt", ".tsv", ".ini", ".xml")):
                    z.writestr(arc, _mask(data.decode("utf-8", errors="replace")))
                else:
                    z.writestr(arc, data)
                names.append(arc)
            except Exception as e:  # noqa: BLE001
                z.writestr(f"mods/{i}_NOT_READABLE.txt", _mask(f"{mf}: {e}"))
    return names
