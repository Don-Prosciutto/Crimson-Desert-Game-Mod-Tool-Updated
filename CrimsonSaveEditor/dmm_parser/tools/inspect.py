# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""
dmm-mod-inspect — print a human-readable summary of what a v3 / v3.1
mod manifest does. For users vetting third-party mods before applying.

Usage:
    python -m dmm_parser.tools.inspect <field.json>            # read raw manifest
    python -m dmm_parser.tools.inspect <bundle.zip>            # peek at the .field.json inside a packed mod
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from typing import Any

from ._common import (
    field_format_version,
    iter_targets,
    load_field_json,
    target_kind,
)


def _read_manifest_from_zip(zpath: str) -> dict[str, Any]:
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if name.lower().endswith(".field.json"):
                return json.loads(z.read(name))
    raise ValueError(f"{zpath}: no *.field.json at the top level of the zip")


def _summarize(doc: dict[str, Any]) -> str:
    out = io.StringIO()

    name = doc.get("name") or "(unnamed)"
    author = doc.get("author") or "(unknown author)"
    version = doc.get("version") or "(no version)"
    desc = doc.get("description") or ""

    try:
        fmajor, fminor = field_format_version(doc)
        fmt_label = f"v{fmajor}.{fminor}"
    except ValueError:
        fmt_label = "unknown"

    out.write(f"Mod: {name}\n")
    out.write(f"  Author : {author}\n")
    out.write(f"  Version: {version}\n")
    out.write(f"  Format : {fmt_label}\n")
    if desc:
        out.write(f"  Notes  : {desc}\n")
    out.write("\n")

    targets = list(iter_targets(doc))
    out.write(f"Targets: {len(targets)}\n")
    if not targets:
        out.write("  (no targets)\n")
        return out.getvalue()

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for t in targets:
        k = target_kind(t) or "unknown"
        by_kind.setdefault(k, []).append(t)

    for k in sorted(by_kind):
        ts = by_kind[k]
        out.write(f"  {k} ({len(ts)}):\n")
        for t in ts:
            out.write("    - " + _short_target(t, k) + "\n")

    return out.getvalue()


def _short_target(t: dict[str, Any], kind: str) -> str:
    if kind == "table":
        table = t.get("table") or "?"
        ops = t.get("ops") or t.get("changes") or []
        if isinstance(ops, list):
            return f"{table:30} ({len(ops)} op{'s' if len(ops) != 1 else ''})"
        return f"{table:30} ({type(ops).__name__})"
    if kind == "asset":
        atype = t.get("asset_type") or "?"
        file_rel = t.get("file") or "?"
        vpath = t.get("vpath") or "(no vpath)"
        size = t.get("size")
        size_str = f" {size} bytes" if size else ""
        return f"[{atype}] {file_rel} -> {vpath}{size_str}"
    if kind == "paloc":
        n = len(t.get("entries") or [])
        if n:
            return f"paloc inline ({n} string{'s' if n != 1 else ''})"
        if t.get("file"):
            return f"paloc file ref -> {t['file']}"
        return "paloc (empty)"
    return repr(t)[:80]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dmm-mod-inspect",
        description="Print what a Field-JSON v3/v3.1 mod will do.",
    )
    parser.add_argument(
        "path",
        help="Path to the .field.json file or a packed .zip mod bundle",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit a structured JSON summary instead of the text format",
    )
    args = parser.parse_args(argv)

    p = args.path
    try:
        if p.lower().endswith(".zip"):
            doc = _read_manifest_from_zip(p)
        else:
            doc = load_field_json(p)
    except (ValueError, FileNotFoundError) as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2

    if args.json:
        try:
            fmajor, fminor = field_format_version(doc)
        except ValueError:
            fmajor, fminor = (None, None)
        out = {
            "name": doc.get("name"),
            "author": doc.get("author"),
            "version": doc.get("version"),
            "format": fmajor,
            "format_minor": fminor,
            "targets": [
                {"kind": target_kind(t), **{k: v for k, v in t.items() if k != "kind"}}
                for t in iter_targets(doc)
            ],
        }
        json.dump(out, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    sys.stdout.write(_summarize(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
