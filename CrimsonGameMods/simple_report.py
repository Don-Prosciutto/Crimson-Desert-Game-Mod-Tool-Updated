"""Log file and feedback report for CrimsonGameMods Simple.

Everything Simple does is written to a log file. "Create Report" puts the
useful parts into one text file on the desktop that a tester can send:
versions, the pack list of the game, what Simple installed, a check whether
each installed mod really is in the game files, and the end of the log.

The Windows user name is replaced by <user> everywhere in the report.
No Qt in here.
"""

from __future__ import annotations

import getpass
import logging
import logging.handlers
import os
import platform
import re
import sys
import time
import traceback
from typing import Callable, List, Optional

LOG_NAME = "CrimsonGameModsSimple.log"
_log_path: Optional[str] = None


def _app_dir() -> str:
    return os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))


def _writable(folder: str) -> bool:
    try:
        os.makedirs(folder, exist_ok=True)
        t = os.path.join(folder, ".cgms_write_test")
        with open(t, "w") as f:
            f.write("t")
        os.remove(t)
        return True
    except Exception:  # noqa: BLE001
        return False


def log_path() -> str:
    return _log_path or os.path.join(_app_dir(), LOG_NAME)


def setup_logging(app_version: str) -> str:
    """Log to a file next to the exe (or %LOCALAPPDATA% if that folder is
    read-only) and to the console. Also logs crashes. Returns the log path."""
    global _log_path
    folder = _app_dir()
    if not _writable(folder):
        folder = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                              "CrimsonGameModsSimple")
        os.makedirs(folder, exist_ok=True)
    _log_path = os.path.join(folder, LOG_NAME)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        fh = logging.handlers.RotatingFileHandler(_log_path, maxBytes=1_000_000, backupCount=1,
                                                  encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:  # noqa: BLE001 - logging must never stop the program
        pass
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)

    def hook(kind, value, tb):
        logging.getLogger("crash").error("Unhandled error:\n%s",
                                         "".join(traceback.format_exception(kind, value, tb)))
        sys.__excepthook__(kind, value, tb)
    sys.excepthook = hook
    logging.getLogger("simple").info("=== Simple %s started (%s, Python %s) ===",
                                     app_version, platform.platform(), platform.python_version())
    return _log_path


def _mask(text: str) -> str:
    """Hide the Windows user name (paths like C:\\Users\\name\\...)."""
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = ""
    text = re.sub(r"(?i)([\\/]Users[\\/])[^\\/\s\"']+", r"\1<user>", text)
    if user and len(user) > 2:
        text = re.sub(re.escape(user), "<user>", text, flags=re.I)
    return text


def _tail(path: str, lines: int) -> List[str]:
    out: List[str] = []
    for p in (path + ".1", path):          # older rotated file first
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                out += f.read().splitlines()
        except Exception:  # noqa: BLE001
            pass
    return out[-lines:]


def desktop_dir() -> str:
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    for d in (os.path.join(os.environ.get("OneDrive", ""), "Desktop") if os.environ.get("OneDrive") else "",
              os.path.join(home, "Desktop"), os.path.join(home, "Schreibtisch")):
        if d and os.path.isdir(d):
            return d
    return _app_dir()


def build_report(app_version: str, game_build: str, game_path: str, selected: List[str],
                 progress: Callable[[str], None] = lambda m: None) -> str:
    import simple_engine as engine  # noqa: PLC0415
    L: List[str] = []
    add = L.append
    add("CrimsonGameMods Simple - feedback report")
    add("=" * 60)
    add(f"Created:        {time.strftime('%Y-%m-%d %H:%M:%S')}")
    add(f"Simple:         {app_version} (built for game {game_build})")
    add(f"Windows:        {platform.platform()}")
    add(f"Game folder:    {game_path or '(not set)'}")
    try:
        from game_version import read_game_version  # noqa: PLC0415
        add(f"Game version:   {read_game_version(game_path) or '?'}")
    except Exception as e:  # noqa: BLE001
        add(f"Game version:   ? ({e})")
    add(f"Selected mods:  {', '.join(sorted(selected)) or '(none)'}")
    add("")

    try:
        import dmm_parser as dmm  # noqa: PLC0415
        progress("Reading the pack list...")
        state, text = engine.health(game_path, dmm)
        add(f"Simple state:   {state} - {text}")
        mark = engine.installed(game_path)
        if mark:
            add(f"Installed:      {mark.get('when')} for game {mark.get('game_version')}")
            add(f"Installed mods: {', '.join(mark.get('mods', []))}")
            add("Values changed per mod when applied:")
            for m, n in sorted((mark.get("changes") or {}).items()):
                add(f"    {m:18} {n}")
            add("Tables taken from:")
            for t, g in sorted((mark.get("sources") or {}).items()):
                add(f"    {t:18} {g}")
        add("")
        entries = dmm.parse_papgt_file(os.path.join(game_path, "meta", "0.papgt"))["entries"]
        add(f"Pack list (meta/0.papgt), {len(entries)} entries, in load order:")
        others = [e["group_name"] for e in entries
                  if not (e["group_name"].isdigit() and int(e["group_name"]) <= 40)]
        add("    mods / overlays: " + (", ".join(others) or "(none)"))
        missing = [e["group_name"] for e in entries
                   if not os.path.isfile(os.path.join(game_path, e["group_name"], "0.pamt"))]
        add("    listed but folder missing: " + (", ".join(missing) or "(none)"))
        add("")
        if mark:
            add("Check - is each installed mod really in the game files?")
            for m, res in sorted(engine.verify(game_path, progress, dmm).items()):
                add(f"    {m:18} {res}")
            add("")
    except Exception as e:  # noqa: BLE001
        add(f"Could not read the game state: {type(e).__name__}: {e}")
        add("")

    add(f"Last lines of the log ({log_path()}):")
    add("-" * 60)
    L += _tail(log_path(), 400)
    return _mask("\n".join(L)) + "\n"


def write_report(text: str) -> str:
    name = f"CrimsonGameModsSimple_report_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    for folder in (desktop_dir(), _app_dir(), os.path.dirname(log_path())):
        try:
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return path
        except Exception:  # noqa: BLE001
            continue
    raise OSError("Could not save the report anywhere.")
