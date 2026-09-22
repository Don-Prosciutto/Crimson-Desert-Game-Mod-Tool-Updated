# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""
dmm-mod-diff — compare two v3 / v3.1 mods for compatibility. Flags any
target the two manifests both touch (same table+row, same vpath asset,
same paloc key) so SWISS Stacker can warn about conflicts before
merging load-order.

Usage:
    python -m dmm_parser.tools.diff <a.field.json> <b.field.json>
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from typing import Any

from ._common import iter_targets, load_field_json, target_kind


def _load(path: str) -> dict[str, Any]:
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(".field.json"):
                    return json.loads(z.read(name))
        raise ValueError(f"{path}: no *.field.json inside zip")
    return load_field_json(path)


def _table_keys(doc: dict[str, Any]) -> set[tuple[str, str]]:
    """Return {(table_name, row_key)} the doc writes to. Op shape is
    intentionally permissive: we look at common fields like `key`,
    `id`, `row`, `target_key`, plus an explicit `keys` list."""
    out: set[tuple[str, str]] = set()
    for t in iter_targets(doc):
        if target_kind(t) != "table":
            continue
        table = t.get("table") or "?"
        ops = t.get("ops") or t.get("changes") or []
        if not isinstance(ops, list):
            out.add((table, "<bulk>"))
            continue
        if not ops:
            out.add((table, "<bulk>"))
            continue
        for op in ops:
            if not isinstance(op, dict):
                out.add((table, "<unknown>"))
                continue
            key = (
                op.get("key")
                or op.get("id")
                or op.get("row")
                or op.get("target_key")
                or op.get("name")
            )
            if key is None and isinstance(op.get("keys"), list):
                for k in op["keys"]:
                    out.add((table, str(k)))
                continue
            out.add((table, str(key) if key is not None else "<unknown>"))
    return out


def _asset_vpaths(doc: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for t in iter_targets(doc):
        if target_kind(t) != "asset":
            continue
        v = t.get("vpath")
        if v:
            out.add(v.lower().lstrip("/"))
    return out


def _paloc_keys(doc: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for t in iter_targets(doc):
        if target_kind(t) != "paloc":
            continue
        entries = t.get("entries") or []
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict):
                    k = e.get("key") or e.get("string_key")
                    if k:
                        out.add(str(k))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dmm-mod-diff",
        description="Detect conflicts between two Field-JSON v3/v3.1 mods.",
    )
    parser.add_argument("a", help="First manifest (.field.json or .zip)")
    parser.add_argument("b", help="Second manifest (.field.json or .zip)")
    parser.add_argument(
        "--json", action="store_true",
        help="Emit conflict report as structured JSON",
    )
    args = parser.parse_args(argv)

    try:
        a = _load(args.a)
        b = _load(args.b)
    except (ValueError, FileNotFoundError) as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2

    table_conflicts = sorted(_table_keys(a) & _table_keys(b))
    asset_conflicts = sorted(_asset_vpaths(a) & _asset_vpaths(b))
    paloc_conflicts = sorted(_paloc_keys(a) & _paloc_keys(b))

    if args.json:
        json.dump({
            "a": args.a,
            "b": args.b,
            "table_conflicts": [{"table": t, "row": r} for t, r in table_conflicts],
            "asset_conflicts": asset_conflicts,
            "paloc_conflicts": paloc_conflicts,
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if not (table_conflicts or asset_conflicts or paloc_conflicts) else 1

    total = len(table_conflicts) + len(asset_conflicts) + len(paloc_conflicts)
    if total == 0:
        print("OK — no conflicts.")
        return 0

    print(f"{total} conflict{'s' if total != 1 else ''}:")
    if table_conflicts:
        print(f"  Table rows ({len(table_conflicts)}):")
        for table, row in table_conflicts:
            print(f"    {table}::{row}")
    if asset_conflicts:
        print(f"  Asset vpaths ({len(asset_conflicts)}):")
        for v in asset_conflicts:
            print(f"    {v}")
    if paloc_conflicts:
        print(f"  Paloc keys ({len(paloc_conflicts)}):")
        for k in paloc_conflicts:
            print(f"    {k}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
