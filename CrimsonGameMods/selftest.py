"""Game compatibility self-test: does the bundled parser still fit the game?

Why: after a game update the parser may read tables at the wrong positions.
Sometimes it fails loudly, sometimes it reads fine and writes the table back
damaged - and a mod built from that damages the game data without a word.
So this test does exactly what a mod would do, but only in memory: read every
table a page of the tool works with straight from the game (group 0008, the
unmodded data), write it back, and compare byte for byte. Nothing is saved.

A table that does not come back identical blocks the pages that edit it; all
other pages keep working. The result is remembered per game version and
parser build, so the test runs once after an update, not at every start.

No Qt in here - the window only calls run() in a background thread and shows
the result.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Callable, Dict, List, Optional

log = logging.getLogger(__name__)

TABLE_DIR = "gamedata/binary__/client/bin"
RESULT_FORMAT = 2
LEGACY_DROPSET = "dropsetinfo (DropSets page reader)"

# Pages that write game tables, and the tables each one edits.
# Key: class name of the page widget. Label: what the navigation shows.
PAGES: Dict[str, dict] = {
    "FieldEditTab": {"label": "FieldEdit", "tables": [
        "characterinfo", "regioninfo", "relationinfo", "wantedinfo", "allygroupinfo",
        "factionrelationgroup", "fieldinfo", "gameplaytrigger", "vehicleinfo"]},
    "ItemBuffsTab": {"label": "ItemBuffs", "tables": [
        "iteminfo", "buffinfo", "equipslotinfo", "equiptypeinfo", "gimmickinfo",
        "skill", "storeinfo", "dropsetinfo", "characterinfo"]},
    "StackerTab": {"label": "Stacker Tool", "tables": [
        "iteminfo", "buffinfo", "equipslotinfo", "equiptypeinfo", "skill",
        "characterinfo", "factionnode", "gameplaytrigger", "inventory"]},
    "StoreEditorTab": {"label": "Stores", "tables": ["storeinfo"]},
    "BagSpaceTab": {"label": "BagSpace", "tables": ["inventory"]},
    # The DropSets page still reads and writes with the old Python reader
    # (dropset_editor.py), so that reader is checked too.
    "DropsetTab": {"label": "DropSets", "tables": ["dropsetinfo", LEGACY_DROPSET]},
    "SpawnTab": {"label": "SpawnEdit", "tables": [
        "spawningpoolautospawninfo", "terrainregionautospawninfo", "factionnodespawninfo",
        "factionnode", "characterinfo"]},
    "SkillTreeTab": {"label": "SkillTree", "tables": [
        "skilltreeinfo", "skilltreegroupinfo", "skill"]},
    "MercPetsTab": {"label": "MercPets (game files)", "tables": ["mercenaryinfo"]},
}


def tables_needed() -> List[str]:
    seen: List[str] = []
    for page in PAGES.values():
        for t in page["tables"]:
            if t not in seen:
                seen.append(t)
    return seen


def parser_id() -> str:
    """Identifies the parser build: a new build means the test runs again."""
    try:
        import dmm_parser.dmm_parser as native  # noqa: PLC0415
        path = native.__file__
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()[:16]
    except Exception as e:  # noqa: BLE001
        log.info("Parser build not identifiable: %s", e)
        return "unknown"


def _check_table(dmm, game_path: str, name: str) -> dict:
    res = {"status": "OK", "detail": "", "records": None}
    try:
        raw = bytes(dmm.extract_file(game_path, "0008", TABLE_DIR, f"{name}.pabgb"))
    except Exception as e:  # noqa: BLE001
        return {"status": "MISSING", "detail": f"not found in the game: {e}", "records": None}
    try:
        head = bytes(dmm.extract_file(game_path, "0008", TABLE_DIR, f"{name}.pabgh"))
    except Exception:  # noqa: BLE001 - not every table has an index
        head = None

    if name == "iteminfo":
        # The tool reads and writes items through these two functions.
        try:
            items = dmm.parse_iteminfo_from_bytes(raw)
            res["records"] = len(items)
            back = bytes(dmm.serialize_iteminfo(items))
        except Exception as e:  # noqa: BLE001
            return {"status": "READ_FAIL", "detail": f"{type(e).__name__}: {e}"[:300], "records": None}
        if back != raw:
            return {"status": "WRITE_DIFF", "detail": _diff(raw, back), "records": res["records"]}

    try:
        items = dmm.parse_table(name, raw, head)
        res["records"] = len(items)
    except Exception as e:  # noqa: BLE001
        return {"status": "READ_FAIL", "detail": f"{type(e).__name__}: {e}"[:300], "records": None}
    try:
        try:
            back = dmm.serialize_table(name, items, None, head)
        except ValueError as e:
            if "not pabgh-bounded" not in str(e):
                raise
            back = dmm.serialize_table(name, items)
        written = bytes(back[0] if isinstance(back, tuple) else back)
    except Exception as e:  # noqa: BLE001
        return {"status": "WRITE_FAIL", "detail": f"{type(e).__name__}: {e}"[:300],
                "records": res["records"]}
    if written != raw:
        return {"status": "WRITE_DIFF", "detail": _diff(raw, written), "records": res["records"]}
    return res


def _check_legacy_dropset(dmm, game_path: str) -> dict:
    """Every drop set through dropset_editor.py and back, byte for byte."""
    import tempfile
    try:
        from dropset_editor import DropsetEditor
        body = bytes(dmm.extract_file(game_path, "0008", TABLE_DIR, "dropsetinfo.pabgb"))
        head = bytes(dmm.extract_file(game_path, "0008", TABLE_DIR, "dropsetinfo.pabgh"))
        with tempfile.TemporaryDirectory() as tmp:
            gh, gb = os.path.join(tmp, "d.pabgh"), os.path.join(tmp, "d.pabgb")
            with open(gh, "wb") as f:
                f.write(head)
            with open(gb, "wb") as f:
                f.write(body)
            ed = DropsetEditor()
            ed.load(gh, gb)
    except Exception as e:  # noqa: BLE001
        return {"status": "READ_FAIL", "detail": f"{type(e).__name__}: {e}"[:300], "records": None}
    bad = 0
    first = None
    for key, _off in ed.records:
        try:
            ds = ed.parse_dropset(key)
            ok = ds is not None and ed._serialize_dropset(ds) == body[ds.body_offset:ds.body_offset + ds.total_size]
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            bad += 1
            first = first or key
    if bad:
        return {"status": "WRITE_DIFF", "records": len(ed.records),
                "detail": f"{bad} of {len(ed.records)} drop sets are written back differently "
                          f"(first: key {first})"}
    return {"status": "OK", "detail": "", "records": len(ed.records)}


def _diff(original: bytes, written: bytes) -> str:
    size = (f"size {len(original)} -> {len(written)} ({len(written) - len(original):+d} bytes)"
            if len(original) != len(written) else f"same size ({len(original)} bytes)")
    for i in range(min(len(original), len(written))):
        if original[i] != written[i]:
            return f"written back differently: {size}, first difference at 0x{i:X}"
    return f"written back differently: {size}"


def run(game_path: str, progress: Optional[Callable[[int, int, str], None]] = None,
        dmm=None) -> dict:
    """Read and write back every table the pages use. Returns a result dict."""
    if dmm is None:
        import dmm_parser as dmm  # noqa: PLC0415
    from game_version import read_game_version  # noqa: PLC0415

    started = time.perf_counter()
    tables = tables_needed()
    results: Dict[str, dict] = {}
    for i, name in enumerate(tables):
        if progress:
            progress(i, len(tables), name)
        results[name] = (_check_legacy_dropset(dmm, game_path) if name == LEGACY_DROPSET
                         else _check_table(dmm, game_path, name))
        if results[name]["status"] != "OK":
            log.warning("Self-test: %s %s %s", name, results[name]["status"], results[name]["detail"])
    if progress:
        progress(len(tables), len(tables), "")
    return {
        "format": RESULT_FORMAT,
        "game_version": read_game_version(game_path) or "unknown",
        "parser": parser_id(),
        "game_path": os.path.normcase(os.path.abspath(game_path)),
        "when": time.strftime("%Y-%m-%d %H:%M"),
        "seconds": round(time.perf_counter() - started, 1),
        "results": results,
    }


def is_current(result: Optional[dict], game_path: str) -> bool:
    """True when a stored result still describes this game and this parser."""
    if not result or result.get("format") != RESULT_FORMAT:
        return False
    from game_version import read_game_version  # noqa: PLC0415
    return (result.get("game_version") == (read_game_version(game_path) or "unknown")
            and result.get("parser") == parser_id()
            and result.get("game_path") == os.path.normcase(os.path.abspath(game_path)))


def failed_tables(result: dict) -> Dict[str, dict]:
    return {t: r for t, r in (result or {}).get("results", {}).items() if r.get("status") != "OK"}


def blocked_pages(result: dict) -> Dict[str, List[str]]:
    """class name of a page -> the tables that block it."""
    bad = failed_tables(result)
    out: Dict[str, List[str]] = {}
    for cls, page in PAGES.items():
        hit = [t for t in page["tables"] if t in bad]
        if hit:
            out[cls] = hit
    return out


def summary(result: Optional[dict]) -> str:
    if not result:
        return "Game check: not run yet"
    bad = failed_tables(result)
    total = len(result.get("results", {}))
    ver = result.get("game_version", "?")
    if not bad:
        return f"Game {ver}: all {total} tables checked - OK"
    pages = blocked_pages(result)
    return (f"Game {ver}: {len(bad)} of {total} tables do not fit - "
            f"{len(pages)} page(s) blocked")


def report_text(result: Optional[dict]) -> str:
    """Plain text for the details dialog."""
    if not result:
        return "The game check has not run yet. It needs the game folder to be set."
    lines = [summary(result), "",
             f"Checked {result.get('when', '?')} in {result.get('seconds', '?')} s, "
             f"parser build {result.get('parser', '?')}.", ""]
    bad = failed_tables(result)
    if not bad:
        lines += ["Every table the tool edits was read from the game and written back "
                  "byte for byte identical. Building mods is safe with this game version."]
        return "\n".join(lines)
    lines += ["These tables are not read or written back correctly by the bundled parser. "
              "Mods built from them could damage the game data, so the pages that edit "
              "them are blocked until the parser is updated. Everything else works.", ""]
    for t, r in bad.items():
        lines.append(f"  {t}: {r['status']} - {r['detail']}")
    lines += ["", "Blocked pages:"]
    for cls, tabs in blocked_pages(result).items():
        lines.append(f"  {PAGES[cls]['label']}  (uses {', '.join(tabs)})")
    return "\n".join(lines)
