"""Item icons: 256x256 webp pictures, one per item key.

Where they come from, in this order:
  1. the icon cache next to the program (icons_local/ beside the EXE, or
     beside this file when run from source) - downloads land here;
  2. icons_local/ folders that ship with the source (the Game Mod Tool folder,
     the repository root, a bundle);
  3. a download from the repository on GitHub, stored in (1) for next time.

Why this was rewritten: the Save Editor's copy only ever looked in (1) and
the Game Mod Tool's ItemBuffs list only asked for icons already on disk, so
in the EXEs (which have no icons_local/ beside them) "Show Icons" showed
nothing. The old downloader also built QPixmaps on worker threads, which Qt
does not allow. Now a small pool downloads bytes only; pictures are made on
the UI thread and callbacks run there.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional
from urllib.request import urlopen, Request

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

log = logging.getLogger(__name__)

ICON_SIZE = 32

# The fork carries the same icons_local/ as the original repository.
_GITHUB_ICON_BASE = ("https://raw.githubusercontent.com/"
                     "Don-Prosciutto/Crimson-Desert-Game-Mod-Tool-Updated/main/icons_local")
_GITHUB_ICON_FALLBACK = "https://raw.githubusercontent.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR/main/icons_local"

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


def _get_local_icons_dir() -> str:
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = _MODULE_DIR
    return os.path.join(base, "icons_local")


def _search_dirs(cache_dir: str) -> List[str]:
    dirs = [cache_dir,
            os.path.join(_MODULE_DIR, "icons_local"),
            os.path.join(os.path.dirname(_MODULE_DIR), "icons_local"),
            os.path.join(os.path.dirname(os.path.dirname(_MODULE_DIR)), "icons_local")]
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        dirs.append(os.path.join(meipass, "icons_local"))
    out, seen = [], set()
    for d in dirs:
        n = os.path.normcase(os.path.abspath(d))
        if n not in seen and os.path.isdir(d):
            seen.add(n)
            out.append(d)
    return out


class _Notifier(QObject):
    fetched = Signal(int, bool)


class IconCache:

    def __init__(self, icon_urls_path: Optional[str] = None):
        self._pixmaps: Dict[int, QPixmap] = {}
        self._pending: set = set()
        # Keys that could not be fetched this session; asked only once.
        self._missing: set = set()
        self._callbacks: Dict[int, List[Callable]] = {}
        self._lock = threading.Lock()
        self._local_dir = _get_local_icons_dir()
        try:
            os.makedirs(self._local_dir, exist_ok=True)
        except OSError:
            pass
        self._dirs = _search_dirs(self._local_dir) or [self._local_dir]
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="icons")
        self._notifier = _Notifier()
        self._notifier.fetched.connect(self._on_fetched)

    # ── lookup ──────────────────────────────────────────────────────────

    def icon_path(self, item_key: int) -> Optional[str]:
        """Path of the picture on disk, or None if it is not here yet."""
        name = f"{int(item_key)}.webp"
        for d in self._dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
        return None

    def has_icon(self, item_key: int) -> bool:
        return item_key not in self._missing

    def _load(self, item_key: int) -> Optional[QPixmap]:
        p = self.icon_path(item_key)
        if not p:
            return None
        px = QPixmap(p)
        if px.isNull():
            return None
        self._pixmaps[item_key] = px
        return px

    def get_pixmap(self, item_key: int) -> Optional[QPixmap]:
        """The picture if it is on disk; never downloads."""
        if item_key in self._pixmaps:
            return self._pixmaps[item_key]
        return self._load(item_key)

    # ── fetching ────────────────────────────────────────────────────────

    def request_icon(self, item_key: int, callback: Callable[[int, QPixmap], None]) -> None:
        """Call callback(key, pixmap) on the UI thread as soon as the picture
        is available - right away if it is on disk, else after a download."""
        px = self.get_pixmap(item_key)
        if px is not None:
            callback(item_key, px)
            return
        with self._lock:
            if item_key in self._missing:
                return
            self._callbacks.setdefault(item_key, []).append(callback)
            if item_key in self._pending:
                return
            self._pending.add(item_key)
        self._pool.submit(self._fetch, item_key)

    def preload_keys(self, keys: list, callback: Callable[[int, QPixmap], None]) -> None:
        for key in keys:
            if key not in self._pixmaps:
                self.request_icon(key, callback)

    def _download(self, item_key: int) -> bool:
        target = os.path.join(self._local_dir, f"{item_key}.webp")
        for base in (_GITHUB_ICON_BASE, _GITHUB_ICON_FALLBACK):
            try:
                req = Request(f"{base}/{item_key}.webp", headers={"User-Agent": "CrimsonGameMods"})
                with urlopen(req, timeout=15) as resp:
                    data = resp.read()
                if not data or len(data) < 100 or data[:4] != b"RIFF":
                    continue
                tmp = target + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, target)
                return True
            except Exception as e:  # noqa: BLE001 - offline, 404, ...
                log.debug("Icon %s from %s: %s", item_key, base, e)
        return False

    def _fetch(self, item_key: int) -> None:          # worker thread: bytes only
        ok = False
        try:
            ok = self._download(item_key)
        finally:
            self._notifier.fetched.emit(item_key, ok)

    def _on_fetched(self, item_key: int, ok: bool) -> None:   # UI thread
        with self._lock:
            self._pending.discard(item_key)
            callbacks = self._callbacks.pop(item_key, [])
        px = self._load(item_key) if ok else None
        if px is None:
            with self._lock:
                self._missing.add(item_key)
            return
        for cb in callbacks:
            try:
                cb(item_key, px)
            except Exception as e:  # noqa: BLE001
                log.debug("Icon callback for %s failed: %s", item_key, e)

    def download_icon_sync(self, item_key: int) -> Optional[QPixmap]:
        px = self.get_pixmap(item_key)
        if px is not None:
            return px
        if item_key in self._missing:
            return None
        if self._download(item_key):
            return self._load(item_key)
        self._missing.add(item_key)
        return None
