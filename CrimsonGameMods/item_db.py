from __future__ import annotations

import json
import logging
import os
import struct
from typing import Dict, List
from urllib.request import urlopen, Request
from urllib.error import URLError

from data_db import get_connection, get_db_path, open_writable, reset_connection
from models import ItemInfo

log = logging.getLogger(__name__)

GITHUB_URL = (
    "https://raw.githubusercontent.com/"
    "NattKh/CrimsonDesertCommunityItemMapping/main/item_names.json"
)


class ItemNameDB:

    def __init__(self) -> None:
        self.items: Dict[int, ItemInfo] = {}
        self.loaded_path: str = ""
        self.version: int = 0
        self.load_auto()

    def load_auto(self) -> str:
        self.load()
        if self.items:
            return self.loaded_path

        try:
            ok, msg = self.sync_from_github()
            if ok and self.items:
                log.info("Bootstrap sync: %s", msg)
                return self.loaded_path
        except Exception as exc:
            log.warning("Bootstrap GitHub sync failed: %s", exc)
        return ""

    def load(self) -> None:
        self.items.clear()
        self.version = 0
        try:
            db = get_connection()
            rows = db.execute(
                "SELECT item_key, name, internal_name, category, max_stack FROM items"
            ).fetchall()
            for row in rows:
                key = row["item_key"]
                self.items[key] = ItemInfo(
                    item_key=key,
                    name=row["name"],
                    internal_name=row["internal_name"],
                    category=row["category"],
                    max_stack=row["max_stack"],
                )
            self.loaded_path = get_db_path()
            log.info("Loaded %d items from SQLite", len(self.items))
        except Exception as exc:
            log.warning("SQLite item load failed: %s", exc)

    def save(self) -> None:
        if not self.items:
            return
        rows = [
            (
                key,
                info.name,
                info.internal_name,
                info.category,
                info.max_stack,
            )
            for key, info in self.items.items()
        ]
        try:
            conn = open_writable()
            conn.executemany(
                "INSERT OR REPLACE INTO items VALUES (?,?,?,?,?)", rows
            )
            conn.commit()
            conn.close()
            reset_connection()
            log.info("Saved %d items to SQLite", len(rows))
        except Exception as exc:
            log.warning("SQLite item save failed: %s", exc)

    def apply_localization(self) -> int:
        try:
            from localization import get_language, _names_data
            if get_language() == "en" or not _names_data:
                return 0
            items_map = _names_data.get("items", {})
            if not items_map:
                return 0
            count = 0
            for key, info in self.items.items():
                localized = items_map.get(str(key), "")
                if localized:
                    info.name = localized
                    count += 1
            return count
        except Exception:
            return 0

    def get_name(self, key: int) -> str:
        info = self.items.get(key)
        if info and info.name:
            return info.name
        return f"Unknown ({key})"

    def get_category(self, key: int) -> str:
        info = self.items.get(key)
        return info.category if info else "Misc"

    def rename_item(self, key: int, new_name: str) -> None:
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
            if (
                query_lower in info.name.lower()
                or query_lower in info.internal_name.lower()
                or query_lower in str(info.item_key)
            ):
                results.append(info)
        results.sort(key=lambda x: x.item_key)
        return results

    def sync_from_github(self) -> tuple[bool, str]:
        try:
            req = Request(GITHUB_URL, headers={"User-Agent": "CrimsonSaveEditor/1.0"})
            with urlopen(req, timeout=10) as resp:
                raw = resp.read()
                data = json.loads(raw.decode("utf-8"))
        except (URLError, json.JSONDecodeError, OSError) as exc:
            return False, f"Download failed: {exc}"

        remote_version = data.get("version", 0)
        remote_items = data.get("items", [])

        if remote_version <= self.version and self.items:
            return True, f"Already up to date (v{self.version})."

        added = 0
        updated = 0
        for entry in remote_items:
            key = entry.get("itemKey", 0)
            if key <= 0:
                continue
            name = entry.get("name", "")
            category = entry.get("category", "Misc")
            internal = entry.get("internalName", "")
            max_stack = entry.get("maxStack", 0)

            if key not in self.items:
                self.items[key] = ItemInfo(
                    item_key=key,
                    name=name,
                    internal_name=internal,
                    category=category,
                    max_stack=max_stack,
                )
                added += 1
            else:
                existing = self.items[key]
                if name and (not existing.name or existing.name.startswith("Unknown")):
                    existing.name = name
                    updated += 1
                if internal and not existing.internal_name:
                    existing.internal_name = internal
                if category != "Misc" and existing.category == "Misc":
                    existing.category = category
                if max_stack and not existing.max_stack:
                    existing.max_stack = max_stack

        if remote_version > self.version:
            self.version = remote_version

        self.save()
        return True, f"Synced v{remote_version}: {added} new, {updated} updated."

    # Sprachpakete des Spiels: Gruppennummer je Sprachkuerzel. Wird nur als
    # Startpunkt benutzt; findet sich die Gruppe dort nicht, wird gesucht.
    _SPRACHGRUPPEN = {
        "kor": "0019", "eng": "0020", "jpn": "0021", "rus": "0022", "tur": "0023",
        "spa-es": "0024", "spa-mx": "0025", "fre": "0026", "ger": "0027",
        "ita": "0028", "pol": "0029", "por-br": "0030", "zho-tw": "0031",
        "zho-cn": "0032", "ara": "0033",
    }

    @staticmethod
    def _finde_sprachgruppe(dmm_parser, game_path: str, lang: str) -> str:
        """Gruppennummer des Sprachpakets, notfalls durch Suche im Spielordner."""
        kandidat = ItemNameDB._SPRACHGRUPPEN.get(lang)
        gesucht = f"gamedata/stringtable/binary__/{lang}"
        if kandidat:
            pfad = os.path.join(game_path, kandidat, "0.pamt")
            if os.path.isfile(pfad):
                try:
                    pamt = dmm_parser.parse_pamt_file(pfad)
                    for d in pamt.get("directories", []):
                        if d.get("path", "").replace("\\", "/").lower() == gesucht and d.get("files"):
                            return kandidat
                except Exception:
                    pass
        try:
            gruppen = sorted(n for n in os.listdir(game_path)
                             if n.isdigit() and len(n) == 4)
        except OSError:
            return ""
        for grp in gruppen:
            pfad = os.path.join(game_path, grp, "0.pamt")
            if not os.path.isfile(pfad):
                continue
            try:
                pamt = dmm_parser.parse_pamt_file(pfad)
            except Exception:
                continue
            for d in pamt.get("directories", []):
                if d.get("path", "").replace("\\", "/").lower() == gesucht and d.get("files"):
                    return grp
        return ""

    def sync_from_local_game(self, game_path: str, language: str = "eng") -> tuple[bool, str]:
        """Liest Items und Anzeigenamen direkt aus der installierten Spielversion.

        Frueher wurden die Datensaetze hier aus den Rohbytes gelesen — mit fest
        verdrahteten Feldoffsets und dem Archivverzeichnis von vor Spielversion
        2.01. Beides bricht bei jedem Update, weshalb die mitgelieferten Daten
        veraltet sind. Jetzt uebernimmt dmm_parser das Lesen, damit die Daten mit
        dem Spiel mitwachsen statt zu altern.
        """
        try:
            import dmm_parser
        except ImportError:
            return False, "dmm_parser-Modul nicht verfuegbar."

        try:
            from table_layout import INTERNAL_DIR
        except ImportError:
            INTERNAL_DIR = "gamedata/binarystaticinfo__/bin"

        try:
            pabgb_data = bytes(dmm_parser.extract_file(
                game_path, "0008", INTERNAL_DIR, "iteminfo.pabgb"))
        except Exception as e:
            return False, f"iteminfo konnte nicht entpackt werden: {e}"

        try:
            geparst = dmm_parser.parse_iteminfo_from_bytes(pabgb_data)
        except Exception as e:
            return False, f"iteminfo konnte nicht gelesen werden: {e}"

        items_raw = []
        for it in geparst:
            namensfeld = it.get("item_name") or {}
            items_raw.append((
                int(it.get("key") or 0),
                str(it.get("string_key") or ""),
                int(namensfeld.get("index") or 0),
                int(it.get("max_stack_count") or 0),
            ))

        if not items_raw:
            return False, "iteminfo enthielt keine Datensaetze."

        # ── Anzeigenamen aus der Lokalisierung des Spiels ──────────────────
        loc_map: Dict[int, str] = {}
        paloc_source = ""
        for lang in dict.fromkeys([language, "eng"]):
            grp = self._finde_sprachgruppe(dmm_parser, game_path, lang)
            if not grp:
                continue
            try:
                paloc = bytes(dmm_parser.extract_file(
                    game_path, grp,
                    f"gamedata/stringtable/binary__/{lang}", "item.paloc"))
                for eintrag in dmm_parser.parse_paloc_bytes(paloc):
                    schluessel = str(eintrag.get("string_key") or "")
                    if schluessel.isdigit():
                        loc_map[int(schluessel)] = str(eintrag.get("string_value") or "")
            except Exception:
                continue
            if loc_map:
                paloc_source = f"Spiel-Lokalisierung ({lang}, Gruppe {grp})"
                break

        if not loc_map:
            tsv_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "localizationstring_eng_items.tsv")
            if os.path.isfile(tsv_path):
                try:
                    with open(tsv_path, "r", encoding="utf-8") as f:
                        for line in f:
                            parts = line.strip().split(";", 1)
                            if len(parts) == 2 and parts[0].isdigit():
                                loc_map[int(parts[0])] = parts[1]
                    paloc_source = "mitgelieferte TSV (veraltet)"
                except Exception:
                    pass

        if not loc_map:
            paloc_source = "none (using internal names)"

        # Die vorhandenen Kategorien sind gepflegt und lassen sich aus den
        # Spieldaten nicht gleichwertig rekonstruieren: die Namens-Heuristik
        # allein wuerde 'Equipment' von 2.284 auf 18 Eintraege druecken.
        # Bestehende Zuordnungen bleiben deshalb stehen; nur wirklich neue
        # Items werden eingeordnet.
        alte_kategorien = {k: v.category for k, v in self.items.items() if v.category}
        old_keys = set(self.items.keys())
        self.items.clear()
        matched = 0
        for item_key, internal_name, loc_index, max_stack in items_raw:
            if item_key <= 0:
                continue
            display_name = loc_map.get(loc_index, '')
            if display_name:
                matched += 1
            else:
                display_name = internal_name.replace('_', ' ')
            kategorie = alte_kategorien.get(item_key) or _guess_item_category(internal_name)
            self.items[item_key] = ItemInfo(
                item_key=item_key,
                name=display_name,
                internal_name=internal_name,
                category=kategorie,
                max_stack=max_stack,
            )

        # Items, die das Spiel nicht mehr kennt, bleiben stehen: darunter
        # koennen selbst angelegte Eintraege sein. Sie werden nur gemeldet.
        verwaist = sorted(old_keys - set(self.items.keys()))

        self.version += 1
        self.save()

        new_keys = set(self.items.keys()) - old_keys
        neu_ohne_kategorie = sum(
            1 for k in new_keys if self.items[k].category == 'Misc')

        zeilen = [
            f"{len(self.items)} Items aus der Spielinstallation gelesen.",
            f"Neu hinzugekommen: {len(new_keys)}",
            f"Namen zugeordnet: {matched} (Quelle: {paloc_source})",
            f"Ohne Namen: {len(self.items) - matched}",
        ]
        if new_keys:
            zeilen.append(
                f"Davon ohne erkennbare Kategorie (als 'Misc' eingeordnet): "
                f"{neu_ohne_kategorie}")
        if verwaist:
            zeilen.append(
                f"{len(verwaist)} Eintraege kennt das Spiel nicht mehr — "
                f"sie bleiben erhalten, falls es eigene Items sind.")
        return True, "\n".join(zeilen)


def _guess_item_category(internal_name: str) -> str:
    n = internal_name.lower()
    if n.startswith('money') or n.startswith('currency'):
        return 'Currency'
    if any(n.startswith(p) for p in ['weapon_', 'onehand', 'twohand', 'bow_', 'crossbow']):
        return 'Equipment'
    if any(n.startswith(p) for p in ['armor_', 'helmet_', 'glove_', 'shoe_', 'shield_']):
        return 'Equipment'
    if any(n.startswith(p) for p in ['ring_', 'necklace_', 'earring_', 'belt_', 'accessory_']):
        return 'Equipment'
    if any(p in n for p in ['_ore', '_ingot', '_hide', '_leather', '_timber', '_plank',
                             '_herb', '_reagent', '_fabric', '_thread', '_stone', 'material']):
        return 'Material'
    if any(p in n for p in ['potion', 'food_', 'elixir', 'meal_', 'drink_', 'consumable']):
        return 'Consumable'
    if any(p in n for p in ['arrow', 'bolt_', 'ammo', 'quiver', 'pyeonjeon']):
        return 'Ammo'
    if any(p in n for p in ['quest_', 'quest']):
        return 'Quest'
    return 'Misc'
