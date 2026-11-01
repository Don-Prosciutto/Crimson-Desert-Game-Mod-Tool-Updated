from __future__ import annotations

import json
import os
import datetime
from typing import Dict, List, Optional

from models import ItemInfo

import sys as _sys
_exe_dir = os.path.dirname(os.path.abspath(_sys.executable)) if getattr(_sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
_bundle_dir = getattr(_sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

SEARCH_PATHS = [
    os.path.join(_exe_dir, "item_names.json"),
    os.path.join(_bundle_dir, "item_names.json"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "item_names.json"),
    r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert\bin64\CrimsonMods\item_names.json",
]


class ItemNameDB:

    def __init__(self) -> None:
        self.items: Dict[int, ItemInfo] = {}
        self.loaded_path: str = ""
        self.version: int = 0
        # The game version this database was built from. Empty for the data
        # that ships with the tool - it was generated at some point and nobody
        # knows when. That is exactly why it is written along from now on.
        self.game_version: str = ""
        self.load_auto()

    def load_auto(self) -> str:
        # A refreshed copy beside the EXE used to win over the bundled list
        # forever, so after an update the editor kept the old items (no DLC
        # items after v2.4.0). Built from an older game than the bundled list,
        # it is replaced by the bundled one; item keys only it has stay.
        local = SEARCH_PATHS[0]
        if os.path.isfile(local):
            for bundled in SEARCH_PATHS[1:]:
                if os.path.isfile(bundled) and os.path.normcase(os.path.abspath(bundled)) != \
                        os.path.normcase(os.path.abspath(local)):
                    if self._replace_outdated_local(local, bundled):
                        return local
                    break
        for path in SEARCH_PATHS:
            if os.path.isfile(path):
                self.load(path)
                if self.items:
                    return path

        return ""

    @staticmethod
    def _version_tuple(text: str) -> tuple:
        out = []
        for part in str(text or "").split("."):
            try:
                out.append(int(part))
            except ValueError:
                break
        return tuple(out)

    def _replace_outdated_local(self, local: str, bundled: str) -> bool:
        """Load the bundled list instead of an older local copy. True if done."""
        try:
            with open(local, "r", encoding="utf-8") as f:
                old = json.load(f)
            with open(bundled, "r", encoding="utf-8") as f:
                new = json.load(f)
        except (OSError, ValueError):
            return False
        old_ver = str(old.get("gameVersion", "") or "")
        new_ver = str(new.get("gameVersion", "") or "")
        if not new_ver or self._version_tuple(old_ver) >= self._version_tuple(new_ver):
            return False
        self.load(bundled)
        kept = 0
        for entry in old.get("items", []):
            key = entry.get("itemKey", 0)
            if key > 0 and key not in self.items:
                self.items[key] = ItemInfo(
                    item_key=key, name=entry.get("name", ""),
                    internal_name=entry.get("internalName", ""),
                    category=entry.get("category", "Misc"),
                    max_stack=entry.get("maxStack", 0))
                kept += 1
        try:
            backup = f"{local}.old-{old_ver or 'unversioned'}"
            if os.path.exists(backup):
                os.remove(backup)
            os.replace(local, backup)
        except OSError:
            pass
        self.loaded_path = local
        self.save()
        import logging
        logging.getLogger(__name__).info(
            "Item list beside the EXE was from game %s, replaced by the bundled one for %s "
            "(%d own item(s) kept)", old_ver or "unknown", new_ver, kept)
        return True

    def load(self, path: str) -> None:
        self.items.clear()
        self.loaded_path = path
        self.version = 0
        self.game_version = ""

        if not os.path.isfile(path):
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        self.version = data.get("version", 0)
        self.game_version = str(data.get("gameVersion", "") or "")
        for entry in data.get("items", []):
            key = entry.get("itemKey", 0)
            if key <= 0:
                continue
            self.items[key] = ItemInfo(
                item_key=key,
                name=entry.get("name", ""),
                internal_name=entry.get("internalName", ""),
                category=entry.get("category", "Misc"),
                max_stack=entry.get("maxStack", 0),
            )

    def apply_localization(self) -> int:
        try:
            from localization import get_language, _names_data
            if get_language() == 'en' or not _names_data:
                return 0
            items_map = _names_data.get('items', {})
            if not items_map:
                return 0
            count = 0
            for key, info in self.items.items():
                localized = items_map.get(str(key), '')
                if localized:
                    info.name = localized
                    count += 1
            return count
        except Exception:
            return 0

    def save(self, path: str | None = None) -> None:
        path = path or self.loaded_path
        if not path:
            return

        items_list = []
        for key in sorted(self.items.keys()):
            info = self.items[key]
            entry: dict = {"itemKey": key, "name": info.name}
            if info.internal_name:
                entry["internalName"] = info.internal_name
            entry["category"] = info.category
            if info.max_stack:
                entry["maxStack"] = info.max_stack
            items_list.append(entry)

        data = {"version": self.version, "items": items_list}
        if self.game_version:
            data["gameVersion"] = self.game_version
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_name(self, key: int) -> str:
        info = self.items.get(key)
        if info and info.name:
            return info.name
        return f"Unknown ({key})"

    def display_label(self, key: int, fallback: str = "") -> str:
        """Display name, plus the variant when several items share it.

        110 display names are shared by 326 pieces of equipment - there are
        two "Helms Leather Boots" (Desert_Harrier_Leather_Boots_I and _II),
        and a list that shows only the name gives no way to pick the right
        one. For those the differing part of the internal name is appended:
        "Helms Leather Boots (I)". Unique names are returned unchanged.
        """
        name = self.get_name(key)
        if name.startswith("Unknown") and fallback:
            name = fallback
        variant = self._variants().get(key)
        return f"{name} ({variant})" if variant else name

    def _variants(self) -> dict:
        sig = (len(self.items), self.version)
        cache = getattr(self, "_variant_cache", None)
        if cache is not None and cache[0] == sig:
            return cache[1]
        groups: dict = {}
        for k, info in self.items.items():
            if info.name and info.internal_name:
                groups.setdefault(info.name, []).append(info)
        out: dict = {}
        for members in groups.values():
            if len(members) < 2:
                continue
            toks = [m.internal_name.split("_") for m in members]
            i = 0
            while all(len(t) > i for t in toks) and len({t[i] for t in toks}) == 1:
                i += 1
            for m, t in zip(members, toks):
                v = "_".join(t[i:]) or m.internal_name
                # Keep the list readable; the end of the name is what differs.
                out[m.item_key] = v if len(v) <= 28 else "\u2026" + v[-27:]
        self._variant_cache = (sig, out)
        return out

    def get_category(self, key: int) -> str:
        info = self.items.get(key)
        return info.category if info else "Misc"

    def rename_item(self, key: int, new_name: str) -> None:
        self._variant_cache = None
        if key in self.items:
            self.items[key].name = new_name
        else:
            self.items[key] = ItemInfo(
                item_key=key,
                name=new_name,
                category="Misc",
            )

    def get_all_sorted(self) -> List[ItemInfo]:
        return [self.items[k] for k in sorted(self.items.keys())]

    def get_internal_name(self, key: int) -> str:
        info = self.items.get(key)
        return info.internal_name if info else ""

    def search(self, query: str) -> List[ItemInfo]:
        query_lower = query.lower().strip()
        if not query_lower:
            return self.get_all_sorted()

        results = []
        for info in self.items.values():
            if (query_lower in info.name.lower()
                    or query_lower in info.internal_name.lower()
                    or query_lower in str(info.item_key)):
                results.append(info)
        results.sort(key=lambda x: x.item_key)
        return results

    def sync_from_local_game(self, game_path: str) -> tuple[bool, str]:
        """Add/update item keys by reading the installed game's local archives."""
        try:
            import crimson_rs
            import struct
            header = crimson_rs.extract_file(
                game_path, "0008", "gamedata/binarystaticinfo__/bin",
                "iteminfo.staticinfoheader",
            )
            body = crimson_rs.extract_file(
                game_path, "0008", "gamedata/binarystaticinfo__/bin",
                "iteminfo.staticinfobody",
            )
        except Exception as exc:
            return False, f"Could not read local item data: {exc}"

        if len(header) < 2:
            return False, "Local item-data header is invalid."
        count = struct.unpack_from("<H", header, 0)[0]
        if len(header) < 2 + count * 8:
            return False, "Local item-data header is truncated."

        # Since game 2.04 a DLC ships its own item table under dlc/<name>/
        # ("Charting the Unknown": 1,552 records, 1,310 of them in no other
        # table). Reading only the main table left every DLC item out.
        tables = [("main", header, body)]
        dlc_base = os.path.join(game_path, "dlc")
        try:
            dlc_names = sorted(n for n in os.listdir(dlc_base)
                               if os.path.isdir(os.path.join(dlc_base, n, "meta")))
        except OSError:
            dlc_names = []
        for dlc in dlc_names:
            try:
                dh = crimson_rs.extract_file(
                    os.path.join(dlc_base, dlc), "0008", "gamedata/binarystaticinfo__/bin",
                    f"iteminfo.{dlc}.staticinfoheader")
                db_ = crimson_rs.extract_file(
                    os.path.join(dlc_base, dlc), "0008", "gamedata/binarystaticinfo__/bin",
                    f"iteminfo.{dlc}.staticinfobody")
            except Exception:  # noqa: BLE001 - a DLC without an item table
                continue
            if len(dh) >= 2 and len(dh) >= 2 + struct.unpack_from("<H", dh, 0)[0] * 8:
                tables.append((dlc, dh, db_))

        previous = dict(self.items)
        added = updated = parsed = 0
        extracted_keys: set[int] = set()
        per_table = []
        for table_name, header, body in tables:
            count = struct.unpack_from("<H", header, 0)[0]
            per_table.append(f"{table_name}: {count}")
            for index in range(count):
                key, offset = struct.unpack_from("<II", header, 2 + index * 8)
                end = (struct.unpack_from("<I", header, 2 + (index + 1) * 8 + 4)[0]
                       if index + 1 < count else len(body))
                try:
                    first = struct.unpack_from("<I", body, offset)[0]
                    if first == key:
                        # up to game 2.03: key, name length, name
                        record_key = first
                        name_length = struct.unpack_from("<I", body, offset + 4)[0]
                        name_start = offset + 8
                    else:
                        # since game 2.04: name length, name, key
                        name_length = first
                        name_start = offset + 4
                        if name_length > 512 or name_start + name_length + 4 > len(body):
                            continue
                        record_key = struct.unpack_from("<I", body, name_start + name_length)[0]
                        if record_key != key:
                            continue
                    if not record_key or name_length > 512 or name_start + name_length > len(body):
                        continue
                    if record_key in extracted_keys:
                        continue  # the main table comes first
                    internal = body[name_start:name_start + name_length].decode("ascii", "replace")
                    parsed += 1
                    extracted_keys.add(record_key)
                    existing = previous.get(record_key)
                    display = existing.name if existing and existing.name else internal.replace("_", " ")
                    self.items[record_key] = ItemInfo(
                        item_key=record_key,
                        name=display,
                        internal_name=internal,
                        # Items only a DLC has are filed as "DLC".
                        category=("DLC" if table_name != "main" else
                                  existing.category if existing else _guess_item_category(internal)),
                        max_stack=(existing.max_stack if existing else 0),
                    )
                    if existing:
                        updated += 1
                    else:
                        added += 1
                except (ValueError, struct.error):
                    continue

        # Names for items that only have their internal name: the game's own
        # English text (main table and DLC tables). Name text index of an
        # item = (item_key << 32) | 0x70.
        unnamed = [k for k in extracted_keys
                   if not (previous.get(k) and previous[k].name)]
        named = 0
        if unnamed:
            texts: dict[int, str] = {}
            sources = [(game_path, "item.paloc")] + [
                (os.path.join(dlc_base, n), f"item.{n}.paloc") for n, _h, _b in tables[1:]]
            for root, fname in sources:
                try:
                    raw = bytes(crimson_rs.extract_file(
                        root, "0020", "gamedata/stringtable/binary__/eng", fname))
                    if crimson_rs.paloc_is_container(raw):
                        raw = bytes(crimson_rs.unwrap_paloc_container(raw))
                    for entry in crimson_rs.parse_paloc_bytes(raw):
                        sk = str(entry.get("string_key") or "")
                        if sk.isdigit():
                            texts.setdefault(int(sk), str(entry.get("string_value") or ""))
                except Exception:  # noqa: BLE001 - names are a bonus
                    continue
            for k in unnamed:
                text = texts.get((k << 32) | 0x70, "").strip()
                if text and k in self.items:
                    self.items[k].name = text
                    named += 1

        if not self.items:
            return False, "No usable item records were found in the local game data."
        self.version += 1
        try:
            from game_version import read_game_version
            self.game_version = read_game_version(game_path) or ""
        except Exception:  # noqa: BLE001
            self.game_version = ""
        # A bundled one-file resource lives under PyInstaller's temporary
        # _MEIPASS directory.  Always persist refreshes beside the executable
        # so the current-client database survives the next launch.
        self.loaded_path = os.path.join(_exe_dir, "item_names.json")
        self.save()
        report = {
            "generatedUtc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source": "installed_client",
            "gamePath": os.path.abspath(game_path),
            "archive": "0008",
            "headerPath": "gamedata/binarystaticinfo__/bin/iteminfo.staticinfoheader",
            "bodyPath": "gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody",
            "tables": per_table,
            "declaredRecords": count,
            "parsedRecords": parsed,
            "uniqueClientItemKeys": len(extracted_keys),
            "gameVersion": self.game_version,
            "databaseItems": len(self.items),
            "added": added,
            "refreshed": updated,
            "preservedLocalOnlyKeys": len(set(previous) - extracted_keys),
        }
        report_path = os.path.join(os.path.dirname(self.loaded_path), "item_scan_report.json")
        try:
            with open(report_path, "w", encoding="utf-8") as report_file:
                json.dump(report, report_file, indent=2, ensure_ascii=False)
        except OSError:
            report_path = ""
        suffix = f" Report: {report_path}" if report_path else ""
        return True, (
            f"Local game scan complete: {len(extracted_keys)} current client items "
            f"({', '.join(per_table)}); {named} new names from the game; "
            f"{len(self.items)} total known ({added} added, {updated} refreshed)." + suffix
        )


def _guess_item_category(internal_name: str) -> str:
    name = internal_name.lower()
    if any(token in name for token in ("weapon", "armor", "shield", "helmet", "glove", "boot", "ring", "earring", "necklace")):
        return "Equipment"
    if any(token in name for token in ("potion", "food", "elixir", "meal", "drink")):
        return "Consumable"
    if any(token in name for token in ("ore", "ingot", "leather", "timber", "material")):
        return "Material"
    if "quest" in name:
        return "Quest"
    return "Misc"


def database_outdated(db, game_path: str):
    """Does the item database match the installed game version?

    Returns (outdated, game version, database version). `outdated` is None
    when the question cannot be answered - without a game path, for instance.

    Why this is needed: the database that ships with the tool is a snapshot
    from some point in time. Someone who does not know how many items the game
    has will never notice that some are missing - they simply do not find them
    and take that for normal. The count alone is not a good enough marker,
    because an update can also remove items; hence the game version.
    """
    if not game_path or not os.path.isdir(game_path):
        return None, "", getattr(db, "game_version", "")
    try:
        from game_version import read_game_version
        installed = read_game_version(game_path) or ""
    except Exception:  # noqa: BLE001
        return None, "", getattr(db, "game_version", "")
    if not installed:
        return None, "", getattr(db, "game_version", "")
    built_from = getattr(db, "game_version", "")
    # The bundled list may carry a data revision behind the game version
    # ("2.04.04.1" = second list for 2.04.04); only the game part counts.
    inst = ItemNameDB._version_tuple(installed)
    built = ItemNameDB._version_tuple(built_from)
    if inst and built[:len(inst)] == inst:
        return False, installed, built_from
    return (built_from != installed), installed, built_from
