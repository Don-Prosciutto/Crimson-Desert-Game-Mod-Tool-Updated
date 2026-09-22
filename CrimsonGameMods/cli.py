#!/usr/bin/env python3
"""
CrimsonGameMods CLI — expose Stacker/ItemBuffs operations as commands.

Other tools (DMM, JMM, etc.) can call this instead of using the GUI.

Usage:
  python cli.py apply-field-json MOD.field.json --game "C:/path/to/game"
  python cli.py apply-field-json MOD.field.json --game "..." --overlay 0058
  python cli.py convert-legacy MOD.json --output MOD.field.json
  python cli.py preview MOD1.json MOD2.json --game "..."
  python cli.py export-field-json --game "..." --output merged.field.json MOD1.json MOD2.json
  python cli.py extract-vanilla --game "..." --output vanilla_iteminfo.pabgb
  python cli.py info MOD.json
  python cli.py roundtrip --game "..." (verify parse->serialize->compare)

Can also be called via the built exe:
  CrimsonGameMods.exe --cli apply-field-json MOD.field.json --game "..."
"""

import argparse
import copy
import json
import os
import shutil
import struct
import sys
import tempfile

def setup_path():
    """Ensure all modules are importable."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

setup_path()


def load_crimson_rs():
    import crimson_rs
    return crimson_rs


def extract_vanilla(game_dir):
    """Extract vanilla iteminfo from game."""
    cr = load_crimson_rs()
    INTERNAL = "gamedata/binary__/client/bin"
    pabgb = bytes(cr.extract_file(game_dir, "0008", INTERNAL, "iteminfo.pabgb"))
    pabgh = bytes(cr.extract_file(game_dir, "0008", INTERNAL, "iteminfo.pabgh"))
    return pabgb, pabgh


def parse_items(raw):
    cr = load_crimson_rs()
    return cr.parse_iteminfo_from_bytes(raw)


def serialize_items(items):
    cr = load_crimson_rs()
    return cr.serialize_iteminfo(items)


def apply_field_set(target, field_path, value):
    """Navigate dot/bracket path and set value on dict."""
    import re
    parts = re.split(r'\.(?![^\[]*\])', field_path)
    obj = target
    for part in parts[:-1]:
        m = re.match(r'^(.+?)\[(\d+)\]$', part)
        if m:
            key, idx = m.group(1), int(m.group(2))
            obj = obj[key][idx]
        else:
            obj = obj[part]
    last = parts[-1]
    m = re.match(r'^(.+?)\[(\d+)\]$', last)
    if m:
        key, idx = m.group(1), int(m.group(2))
        obj[key][idx] = value
    else:
        obj[last] = value


# ── Commands ─────────────────────────────────────────────────────────

def cmd_info(args):
    """Show info about a mod file."""
    for path in args.mods:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
        fmt = doc.get('format', '?')
        target = doc.get('target', 'iteminfo.pabgb')
        mi = doc.get('modinfo', {})
        title = mi.get('title', mi.get('name', os.path.basename(path)))

        if fmt == 3:
            intents = doc.get('intents', [])
            entries = set(i.get('entry', '') for i in intents)
            fields = set(i.get('field', '') for i in intents)
            print(f"{path}:")
            print(f"  Format: Field JSON v3")
            print(f"  Target: {target}")
            print(f"  Title: {title}")
            print(f"  Intents: {len(intents)}")
            print(f"  Unique entries: {len(entries)}")
            print(f"  Unique fields: {len(fields)}")
        else:
            patches = doc.get('patches', [])
            changes = sum(len(p.get('changes', [])) for p in patches)
            game_files = set(p.get('game_file', '') for p in patches)
            print(f"{path}:")
            print(f"  Format: Legacy v{fmt}")
            print(f"  Title: {title}")
            print(f"  Patches: {len(patches)}")
            print(f"  Changes: {changes}")
            print(f"  Game files: {', '.join(game_files)}")
        print()


def cmd_roundtrip(args):
    """Verify parse->serialize roundtrip on live game data."""
    pabgb, _ = extract_vanilla(args.game)
    print(f"Vanilla: {len(pabgb):,} bytes")
    items = parse_items(pabgb)
    print(f"Parsed: {len(items)} items")
    out = serialize_items(items)
    print(f"Serialized: {len(out):,} bytes")
    match = out == pabgb
    print(f"Roundtrip: {'PASS' if match else 'FAIL'}")
    if not match:
        for i in range(min(len(out), len(pabgb))):
            if out[i] != pabgb[i]:
                print(f"  First diff at byte {i} (0x{i:X})")
                break
    return 0 if match else 1


def cmd_extract_vanilla(args):
    """Extract vanilla iteminfo.pabgb from game."""
    pabgb, pabgh = extract_vanilla(args.game)
    out = args.output or "vanilla_iteminfo.pabgb"
    with open(out, 'wb') as f:
        f.write(pabgb)
    print(f"Extracted: {len(pabgb):,} bytes -> {out}")
    if args.pabgh:
        with open(args.pabgh, 'wb') as f:
            f.write(pabgh)
        print(f"Header: {len(pabgh):,} bytes -> {args.pabgh}")


def cmd_apply_field_json(args):
    """Apply Field JSON v3 mod(s) to game via overlay."""
    pabgb, pabgh = extract_vanilla(args.game)
    items = parse_items(pabgb)
    by_name = {it['string_key']: it for it in items}
    by_key = {it['key']: it for it in items}

    total_applied = 0
    total_skipped = 0

    for mod_path in args.mods:
        with open(mod_path, encoding='utf-8') as f:
            doc = json.load(f)

        if doc.get('format') != 3:
            print(f"SKIP: {mod_path} is not Format 3")
            continue

        intents = doc.get('intents', [])
        applied = 0
        skipped = 0

        for intent in intents:
            entry = intent.get('entry', '')
            target = by_name.get(entry) or by_key.get(intent.get('key'))
            if not target:
                skipped += 1
                continue
            op = intent.get('op', 'set')
            field = intent.get('field', '')
            if op == 'set' and field:
                try:
                    apply_field_set(target, field, intent.get('new'))
                    applied += 1
                except Exception as e:
                    skipped += 1
                    if args.verbose:
                        print(f"  SKIP {entry}.{field}: {e}")
            else:
                skipped += 1

        title = (doc.get('modinfo') or {}).get('title', os.path.basename(mod_path))
        print(f"{title}: {applied} applied, {skipped} skipped")
        total_applied += applied
        total_skipped += skipped

    if total_applied == 0:
        print("No changes to apply.")
        return 1

    # Serialize
    final = serialize_items(items)
    print(f"Serialized: {len(final):,} bytes ({len(items)} items)")

    if args.output:
        # Write raw pabgb
        with open(args.output, 'wb') as f:
            f.write(final)
        print(f"Written to: {args.output}")
    else:
        # Pack into overlay
        cr = load_crimson_rs()
        overlay = args.overlay or "0058"
        INTERNAL = "gamedata/binary__/client/bin"

        with tempfile.TemporaryDirectory() as tmp:
            group_dir = os.path.join(tmp, overlay)
            builder = cr.PackGroupBuilder(
                group_dir, cr.Compression.NONE, cr.Crypto.NONE)
            builder.add_file(INTERNAL, "iteminfo.pabgb", final)
            builder.add_file(INTERNAL, "iteminfo.pabgh", pabgh)
            pamt_bytes = bytes(builder.finish())
            checksum = cr.parse_pamt_bytes(pamt_bytes)["checksum"]

            game_overlay = os.path.join(args.game, overlay)
            if os.path.isdir(game_overlay):
                shutil.rmtree(game_overlay)
            os.makedirs(game_overlay, exist_ok=True)
            shutil.copy2(os.path.join(group_dir, "0.paz"),
                         os.path.join(game_overlay, "0.paz"))
            shutil.copy2(os.path.join(group_dir, "0.pamt"),
                         os.path.join(game_overlay, "0.pamt"))

            papgt_path = os.path.join(args.game, "meta", "0.papgt")
            papgt = cr.parse_papgt_file(papgt_path)
            papgt['entries'] = [
                e for e in papgt['entries'] if e.get('group_name') != overlay]
            papgt = cr.add_papgt_entry(papgt, overlay, checksum, 0, 16383)
            cr.write_papgt_file(papgt, papgt_path)

        print(f"Applied to game: {overlay}/ overlay")
        print(f"Total: {total_applied} intents applied")


def cmd_convert_legacy(args):
    """Convert legacy byte-offset JSON to Field JSON v3."""
    with open(args.mod, encoding='utf-8') as f:
        doc = json.load(f)

    if doc.get('format') == 3:
        print("Already Format 3, nothing to convert.")
        return

    # Find matching baseline
    baselines_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'game_baselines')
    best_data = None
    best_ver = None
    best_score = -1

    patches = doc.get('patches', [])
    changes = []
    for p in patches:
        changes.extend(p.get('changes', []))

    for ver in sorted(os.listdir(baselines_dir)) if os.path.isdir(baselines_dir) else []:
        path = os.path.join(baselines_dir, ver, 'iteminfo.pabgb')
        if not os.path.isfile(path):
            continue
        data = open(path, 'rb').read()
        score = 0
        for c in changes:
            off_raw = c.get('offset')
            orig_hex = c.get('original', '')
            if off_raw is None or not orig_hex:
                continue
            try:
                off = int(str(off_raw).strip(), 16) if isinstance(off_raw, str) else int(off_raw)
            except:
                continue
            orig = bytes.fromhex(orig_hex)
            if off + len(orig) <= len(data) and data[off:off+len(orig)] == orig:
                score += 1
        if score > best_score:
            best_score = score
            best_ver = ver
            best_data = data

    if not best_data:
        print("ERROR: No matching baseline found in game_baselines/")
        return 1

    print(f"Matched baseline: {best_ver} ({best_score}/{len(changes)} bytes match)")

    # Apply patches to baseline
    from cli_core import apply_one_legacy_patch as _apply_one_legacy_patch
    sorted_changes = sorted(changes,
        key=lambda c: int(str(c.get('offset', 0)).strip(), 16) if isinstance(c.get('offset'), str) else int(c.get('offset', 0)),
        reverse=True)
    patched = bytearray(best_data)
    applied = 0
    for c in sorted_changes:
        try:
            applied += _apply_one_legacy_patch(patched, best_data, c)
        except:
            pass

    print(f"Applied {applied}/{len(changes)} patches to baseline")

    # Parse both — try current parser, fall back to legacy
    try:
        vanilla_items = parse_items(best_data)
        parser_name = "current"
    except Exception:
        from cli_core import load_legacy_parser
        legacy_rs = load_legacy_parser()
        if not legacy_rs:
            print("ERROR: Current parser failed and no legacy parser available.")
            return 1
        vanilla_items = legacy_rs.parse_iteminfo_from_bytes(best_data)
        parser_name = "legacy"
    print(f"Parsed baseline with {parser_name} parser: {len(vanilla_items)} items")

    try:
        patched_items = parse_items(bytes(patched))
    except Exception:
        if parser_name == "legacy":
            patched_items = legacy_rs.parse_iteminfo_from_bytes(bytes(patched))
        else:
            print("ERROR: Failed to parse patched data.")
            return 1
    van_lookup = {it['string_key']: it for it in vanilla_items}

    from cli_core import deep_diff_to_intents as _deep_diff_to_intents
    intents = []
    for pit in patched_items:
        skey = pit.get('string_key', '')
        van = van_lookup.get(skey)
        if not van:
            continue
        diffs = _deep_diff_to_intents(skey, van.get('key', 0), van, pit)
        intents.extend(diffs)

    print(f"Generated {len(intents)} field-level intents")

    mi = doc.get('modinfo', doc)
    title = mi.get('title', mi.get('name', os.path.basename(args.mod)))

    output = {
        'modinfo': {
            'title': title,
            'version': mi.get('version', '1.0'),
            'author': mi.get('author', 'CrimsonGameMods CLI'),
            'description': f'{len(intents)} field-level intent(s)',
            'note': 'Format 3 — converted from legacy byte-offset JSON',
        },
        'format': 3,
        'target': 'iteminfo.pabgb',
        'intents': intents,
    }

    out_path = args.output or args.mod.replace('.json', '.field.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"Saved: {out_path}")


def cmd_export_field_json(args):
    """Load mods, merge, export as Field JSON v3."""
    pabgb, _ = extract_vanilla(args.game)
    vanilla_items = parse_items(pabgb)
    van_lookup = {it['string_key']: it for it in vanilla_items}
    merged = copy.deepcopy(vanilla_items)
    merged_lookup = {it['string_key']: it for it in merged}

    for mod_path in args.mods:
        with open(mod_path, encoding='utf-8') as f:
            doc = json.load(f)

        if doc.get('format') == 3:
            intents = doc.get('intents', [])
            applied = 0
            for intent in intents:
                target = merged_lookup.get(intent.get('entry'))
                if not target:
                    continue
                field = intent.get('field', '')
                if intent.get('op') == 'set' and field:
                    try:
                        apply_field_set(target, field, intent.get('new'))
                        applied += 1
                    except:
                        pass
            print(f"{os.path.basename(mod_path)}: {applied} intents applied")
        else:
            print(f"SKIP: {mod_path} (not Format 3, use convert-legacy first)")

    # Diff merged vs vanilla
    from cli_core import deep_diff_to_intents as _deep_diff_to_intents
    intents = []
    for mit in merged:
        skey = mit.get('string_key', '')
        van = van_lookup.get(skey)
        if not van:
            continue
        diffs = _deep_diff_to_intents(skey, van.get('key', 0), van, mit)
        intents.extend(diffs)

    output = {
        'modinfo': {
            'title': 'Merged Stack',
            'version': '1.0',
            'author': 'CrimsonGameMods CLI',
            'description': f'{len(intents)} field-level intent(s)',
        },
        'format': 3,
        'target': 'iteminfo.pabgb',
        'intents': intents,
    }

    out_path = args.output or 'merged.field.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"Exported {len(intents)} intents -> {out_path}")


def cmd_apply_field_json_raw(args):
    """Apply Field JSON v3 to a raw pabgb file — no game extraction needed."""
    raw = open(args.input, 'rb').read()
    print(f"Input: {len(raw):,} bytes")

    items = parse_items(raw)
    by_name = {it['string_key']: it for it in items}
    by_key = {it['key']: it for it in items}

    with open(args.mod_file, encoding='utf-8') as f:
        doc = json.load(f)

    if doc.get('format') != 3:
        print("ERROR: not a Format 3 Field JSON file")
        return 1

    # Format 3.0 legt die Intents flach ab, Format 3.1 gruppiert sie unter
    # "targets": [{"file": ..., "intents": [...]}, ...]. Ohne diesen Zweig
    # fand der Befehl bei 3.1-Mods nichts und schrieb die Datei unveraendert
    # zurueck — mit der Meldung "Applied: 0, Skipped: 0".
    intents = list(doc.get('intents') or [])
    for target_block in (doc.get('targets') or []):
        ziel_datei = (target_block.get('file') or '').lower()
        if ziel_datei and 'iteminfo' not in ziel_datei:
            print(f"WARNUNG: uebersprungen — dieser Befehl bearbeitet nur iteminfo, "
                  f"der Mod zielt auch auf {target_block.get('file')}")
            continue
        intents.extend(target_block.get('intents') or [])

    if not intents:
        print("ERROR: keine Intents in der Mod-Datei gefunden")
        return 1

    applied = 0
    skipped = 0

    for intent in intents:
        entry = intent.get('entry', '')
        target = by_name.get(entry) or by_key.get(intent.get('key'))
        if not target:
            skipped += 1
            continue
        op = intent.get('op', 'set')
        field = intent.get('field', '')
        if op == 'set' and field:
            try:
                apply_field_set(target, field, intent.get('new'))
                applied += 1
            except:
                skipped += 1
        else:
            skipped += 1

    final = serialize_items(items)
    with open(args.output, 'wb') as f:
        f.write(final)
    print(f"Applied: {applied}, Skipped: {skipped}")
    print(f"Output: {len(final):,} bytes -> {args.output}")


def cmd_remove_overlay(args):
    """Remove an overlay and update PAPGT."""
    cr = load_crimson_rs()
    overlay = args.overlay
    game_mod = os.path.join(args.game, overlay)
    if not os.path.isdir(game_mod):
        print(f"No {overlay}/ overlay found.")
        return

    shutil.rmtree(game_mod)
    papgt_path = os.path.join(args.game, "meta", "0.papgt")
    if os.path.isfile(papgt_path):
        papgt = cr.parse_papgt_file(papgt_path)
        papgt['entries'] = [
            e for e in papgt['entries'] if e.get('group_name') != overlay]
        cr.write_papgt_file(papgt, papgt_path)
    print(f"Removed {overlay}/ overlay and updated PAPGT.")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        prog='crimson-cli',
        description='CrimsonGameMods CLI — Stacker operations without the GUI')

    sub = ap.add_subparsers(dest='command')

    # info
    p = sub.add_parser('info', help='Show info about mod file(s)')
    p.add_argument('mods', nargs='+')

    # roundtrip
    p = sub.add_parser('roundtrip', help='Verify parse->serialize roundtrip')
    p.add_argument('--game', required=True)

    # extract-vanilla
    p = sub.add_parser('extract-vanilla', help='Extract vanilla iteminfo')
    p.add_argument('--game', required=True)
    p.add_argument('--output', '-o')
    p.add_argument('--pabgh')

    # apply-field-json
    p = sub.add_parser('apply-field-json', help='Apply Field JSON v3 mod(s) to game')
    p.add_argument('mods', nargs='+')
    p.add_argument('--game', required=True)
    p.add_argument('--overlay', default='0058')
    p.add_argument('--output', '-o', help='Write raw pabgb instead of overlay')
    p.add_argument('--verbose', '-v', action='store_true')

    # convert-legacy
    p = sub.add_parser('convert-legacy', help='Convert legacy JSON to Field JSON v3')
    p.add_argument('mod')
    p.add_argument('--output', '-o')

    # export-field-json
    p = sub.add_parser('export-field-json', help='Merge mods and export as Field JSON v3')
    p.add_argument('mods', nargs='+')
    p.add_argument('--game', required=True)
    p.add_argument('--output', '-o')

    # apply-field-json-raw (for mod manager integration — takes raw pabgb input)
    p = sub.add_parser('apply-field-json-raw',
        help='Apply Field JSON v3 to a raw pabgb file (no game extraction)')
    p.add_argument('--input', required=True, help='Input pabgb file')
    p.add_argument('--mod', required=True, dest='mod_file', help='Field JSON v3 mod file')
    p.add_argument('--output', '-o', required=True, help='Output pabgb file')

    # remove-overlay
    p = sub.add_parser('remove-overlay', help='Remove an overlay from game')
    p.add_argument('--game', required=True)
    p.add_argument('--overlay', required=True)

    args = ap.parse_args()

    if not args.command:
        ap.print_help()
        return

    commands = {
        'info': cmd_info,
        'roundtrip': cmd_roundtrip,
        'extract-vanilla': cmd_extract_vanilla,
        'apply-field-json': cmd_apply_field_json,
        'convert-legacy': cmd_convert_legacy,
        'export-field-json': cmd_export_field_json,
        'apply-field-json-raw': cmd_apply_field_json_raw,
        'remove-overlay': cmd_remove_overlay,
    }

    result = commands[args.command](args)
    sys.exit(result or 0)


if __name__ == '__main__':
    main()
