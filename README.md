# Crimson Desert — Game Mods & Save Editor (community update)

> **This is not an original work.** Everything here was created by
> **RicePaddySoftware / NattKh** and contributors. This repository only carries a
> maintenance update that makes the existing tool run on current game versions.
> All credit for the tool, the parser and the Field JSON format belongs to them.
>
> **Original project:** https://github.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS
> **Parser:** https://github.com/exodiaprivate-eng/dmm-parser
>
> Published with the author's permission (Discord, 2026-09-22). If you want to
> contribute, contribute upstream — that is where the work happens.

---

## Why this exists

The tool stopped working after game version 2.03. The author has said publicly that
he no longer has time to keep it updated and that anyone is welcome to carry it on.
This is that: the same tool, brought back to a running state. No new features, no
redesign, no rewrite.

**Bug reports about this build belong here, not with the original author.**
Maintainer of this update: Don_Prosciutto (Discord).

---

## What changed

Measured against the 134 static tables extracted from a live 2.03.01 install:

| | shipped release | this build |
|---|---|---|
| Tables parsing clean | 110 / 134 | **129 / 134** |
| Parse failures | 19 | 4 |
| Roundtrip mismatches | 4 | 1 |
| Write failures | 1 | 0 |

### 1. Parser updated

`dmm_parser.pyd` was the 1.18 build from 2026-08-15; it is now the 2.03.01 build.
`iteminfo` previously failed with `unknown SubItem type: 18` and now reads 6,816
items with a byte-identical roundtrip.

**Important if you built mods recently:** on the shipped 1.18 build, three tables
parse *without error* but serialize back wrong — `dropsetinfo` loses 502,250 bytes,
`spawningpoolautospawninfo` gains 35,583, `interactioninfo` diverges at offset 0x7D
with no size change. Mods authored against game 2.03 with the previous release may
have corrupted those tables silently. Worth re-checking.

### 2. Archive names (game 2.01+)

Since 2.01.00 the static tables are named `<table>.staticinfobody` /
`<table>.staticinfoheader` under `gamedata/binarystaticinfo__/bin`. `table_layout.py`
already handled this, but only two modules used it. The PAMT lookups in
`paz_patcher.py`, `store_editor.py` and `gui/utils.py` still searched the old
`.pabgb` names, found nothing, and fell through to hardcoded offsets — which
surfaced as `Short read: expected 761214771 bytes` and a misleading "your iteminfo
has been modified by another mod" warning. They now accept both spellings.

### 3. Field JSON 3.1 in the CLI

`cli.py apply-field-json-raw` read intents from `doc['intents']` only. Format 3.1
groups them under `targets[].intents`, so 3.1 mods produced `Applied: 0, Skipped: 0`
and an unchanged output file — a silent no-op. Both shapes are now accepted.

### 4. Item data is pulled from the game again

`item_db.sync_from_local_game` failed at four points and fell back to the bundled
`localizationstring_eng_items.tsv` every time, which is why the shipped item data was
five months old. Rewritten on top of `dmm_parser`, it now reads **6,816 items**
(previously 6,341) with **6,744 display names** resolved from the game's own
localization, and corrects 287 wrong names.

Existing item categories are preserved deliberately: re-deriving them from the
built-in name heuristic alone would drop `Equipment` from 2,284 entries to 18.

---

## Install

Download the release, put the `.exe` in a folder of its own, run it. Point the Game
Path bar at your Crimson Desert install if auto-detect does not find it.

## Build from source

Requires Python 3.12+ from python.org.

```bash
pip install PySide6 numpy lz4 cryptography Pillow pyinstaller
cd CrimsonGameMods
python -m PyInstaller CrimsonGameMods.spec --noconfirm
```

---

## License

Unchanged. The Python tool is **MPL-2.0**; `dmm-parser` is **CDMTL v1.0**. All
copyright notices, license texts and trademark notices are intact. Modified files
are published here in source form as both licenses require.

"CrimsonGameMods", "DMM", "Definitive Mod Manager", "SWISS" and "Field JSON v3.1"
are trademarks of RicePaddySoftware and are used here descriptively only.

## Credits

- **RicePaddySoftware / NattKh** — the tool, the Field JSON format, the releases
- **potter4208467** — the original `crimson-rs` parser toolkit
- **exodiaprivate-eng / AerowynX** — `dmm-parser`, ongoing game-version support
- **gek**, **LukeFZ**, **fire** — see `CrimsonGameMods/CREDITS.md`

Unofficial, non-commercial modding utilities for Crimson Desert (© Pearl Abyss).
No game assets or proprietary data are redistributed — extraction happens locally
from your own installed copy.
