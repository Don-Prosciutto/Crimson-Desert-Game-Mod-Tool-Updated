from __future__ import annotations

import gzip
import os
import sqlite3
import sys

DB_FILENAME  = "crimson_data.db"
DBZ_FILENAME = "crimson_data.db.gz"

_connection: sqlite3.Connection | None = None


def _exe_dir() -> str:
    return (
        os.path.dirname(os.path.abspath(sys.executable))
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )


# A writable copy of the database lives beside the EXE once anything was saved
# to it (a renamed item, a sync). It used to win over the database inside the
# EXE forever - so after an update the tool kept showing the old item list
# (no DLC items after v2.4.0). The database now carries a data_version in a
# meta table; a copy older than the bundled one is rebuilt from the bundled
# one, keeping item keys only the copy knows (items the user added).
_META_TABLE = "meta"
_VERSION_KEY = "data_version"
_refresh_checked = False      # the check runs once per start, not per lookup


def _version_tuple(text: str) -> tuple:
    out = []
    for part in str(text or "").replace("-", ".").split("."):
        try:
            out.append(int(part))
        except ValueError:
            break
    return tuple(out)


def _data_version_of(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute(
            f"SELECT value FROM {_META_TABLE} WHERE key = ?", (_VERSION_KEY,)).fetchone()
        return str(row[0]) if row else ""
    except sqlite3.Error:
        return ""


def _bundled_bytes(path: str, compressed: bool) -> bytes:
    if compressed:
        with gzip.open(path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()


def _refresh_local_copy(local: str, bundled: str, compressed: bool) -> None:
    """Replace an outdated beside-the-EXE copy with the bundled database."""
    import logging
    log = logging.getLogger(__name__)
    try:
        src = sqlite3.connect(":memory:")
        src.deserialize(_bundled_bytes(bundled, compressed))
        new_ver = _data_version_of(src)
        old = sqlite3.connect(f"file:{local}?mode=ro", uri=True)
        old_ver = _data_version_of(old)
        if new_ver and _version_tuple(old_ver) >= _version_tuple(new_ver):
            old.close()
            src.close()
            return
        tmp = local + ".new"
        if os.path.exists(tmp):
            os.remove(tmp)
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        src.close()
        # Items only the old copy has (added by the user) stay.
        kept = 0
        try:
            have = {r[0] for r in dst.execute("SELECT item_key FROM items")}
            cols = [r[1] for r in old.execute("PRAGMA table_info(items)")]
            rows = [r for r in old.execute(f"SELECT {', '.join(cols)} FROM items")
                    if r[0] not in have]
            if rows:
                dst.executemany(
                    f"INSERT OR IGNORE INTO items ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' * len(cols))})", rows)
                kept = len(rows)
            dst.commit()
        except sqlite3.Error as e:
            log.warning("Item database refresh: own items not carried over: %s", e)
        dst.close()
        old.close()
        backup = f"{local}.old-{old_ver or 'unversioned'}"
        if os.path.exists(backup):
            os.remove(backup)
        os.replace(local, backup)
        os.replace(tmp, local)
        log.info("Item database beside the EXE was %s, refreshed to %s (%d own item(s) kept, "
                 "old copy: %s)", old_ver or "unversioned", new_ver, kept, backup)
    except Exception as e:  # noqa: BLE001 - never block start-up
        log.warning("Item database beside the EXE could not be refreshed: %s", e)


def _resolve() -> tuple[str, bool]:
    exe    = _exe_dir()
    meipass = getattr(sys, "_MEIPASS", exe)
    dev    = os.path.dirname(os.path.abspath(__file__))

    local = os.path.join(exe, DB_FILENAME)
    bundled = [
        (os.path.join(meipass, DBZ_FILENAME), True),
        (os.path.join(meipass, DB_FILENAME),  False),
        (os.path.join(dev,     DB_FILENAME),  False),
    ]
    global _refresh_checked
    if not _refresh_checked and os.path.isfile(local):
        _refresh_checked = True
        for path, compressed in bundled:
            if os.path.isfile(path) and os.path.normcase(os.path.abspath(path)) != \
                    os.path.normcase(os.path.abspath(local)):
                _refresh_local_copy(local, path, compressed)
                break
    candidates = [(local, False)] + bundled
    for path, compressed in candidates:
        if os.path.isfile(path):
            return path, compressed
    return candidates[-1][0], False


def get_db_path() -> str:
    path, _ = _resolve()
    return path


def _open_compressed(path: str) -> sqlite3.Connection:
    with gzip.open(path, "rb") as f:
        data = f.read()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.deserialize(data)
    conn.row_factory = sqlite3.Row
    return conn


def get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        path, compressed = _resolve()
        if not os.path.isfile(path):
            _connection = sqlite3.connect(":memory:", check_same_thread=False)
            _connection.row_factory = sqlite3.Row
        elif compressed:
            _connection = _open_compressed(path)
        else:
            _connection = sqlite3.connect(
                f"file:{path}?mode=ro", uri=True, check_same_thread=False
            )
            _connection.row_factory = sqlite3.Row
    return _connection


def open_writable() -> sqlite3.Connection:
    import shutil

    target = os.path.join(_exe_dir(), DB_FILENAME)
    if not os.path.isfile(target):
        path, compressed = _resolve()
        if os.path.isfile(path) and path != target:
            if compressed:
                with gzip.open(path, "rb") as f:
                    data = f.read()
                with open(target, "wb") as out:
                    out.write(data)
            else:
                shutil.copy2(path, target)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


_TABLE_TO_JSON: dict[str, str] = {
    "characters":           "character_catalog.json",
    "equipment_slots":      "equip_type_hash_map.json",
    "item_icons":           "icon_urls.json",
    "world_locations":      "all_world_locations.json",
    "faction_nodes":        "faction_node_locations.json",
    "quest_chains":         "quest_chains.json",
    "quest_chain_members":  "quest_chains.json",
    "dye_slots":            "dye_slot_db.json",
}

USER_EDITABLE_NEVER_DB = frozenset({
    "knowledge_packs", "equipment_sets", "editor_config",
    "localization", "localization_eng", "locale",
})

import logging
_log = logging.getLogger(__name__)
_FALLBACK_WARNED: set[str] = set()


def _data_dir_candidates() -> list[str]:
    exe = _exe_dir()
    meipass = getattr(sys, "_MEIPASS", "") or ""
    here = os.path.dirname(os.path.abspath(__file__))
    out: list[str] = []
    for base in (exe, meipass, here):
        if base:
            out.append(os.path.join(base, "data"))
            out.append(base)
    return out


def _load_json_fallback(filename: str):
    import json
    for cand in _data_dir_candidates():
        p = os.path.join(cand, filename)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                _log.warning("data_db: JSON fallback %s failed: %s", filename, e)
    return None


def query_with_fallback(sql: str, params: tuple = (),
                        table: str | None = None,
                        json_to_rows=None) -> list:
    conn = get_connection()
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
    except sqlite3.Error as e:
        rows = []
        _log.warning("data_db: SQL error on %s — %s", table, e)

    if rows:
        return rows

    if not table or table not in _TABLE_TO_JSON:
        return rows
    if table in USER_EDITABLE_NEVER_DB:
        return rows

    fname = _TABLE_TO_JSON[table]
    data = _load_json_fallback(fname)
    if data is None:
        return rows

    if table not in _FALLBACK_WARNED:
        _log.warning(
            "data_db: table %r empty in SQLite — falling back to %s",
            table, fname,
        )
        _FALLBACK_WARNED.add(table)

    if json_to_rows is not None:
        try:
            return json_to_rows(data)
        except Exception as e:
            _log.warning("data_db: json_to_rows for %s failed: %s", table, e)
            return []
    return [data]


def reset_connection() -> None:
    global _connection
    if _connection is not None:
        try:
            _connection.close()
        except Exception:
            pass
        _connection = None
