# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""
dmm-parser-rename-string — surgical string rename for `.pastage`,
`.paseq`, `.paseqc`, or any other format that stores values as
`u32 length + bytes` CStrings.

Usage:
    python -m dmm_parser.tools.rename_string FILE OLD_VALUE NEW_VALUE [--out PATH]
    python -m dmm_parser.tools.rename_string FILE --list

The `--list` form prints every length-prefixed string in the file
with its byte offset. Useful for finding what's editable.

The rename form replaces the FIRST occurrence of OLD_VALUE with
NEW_VALUE. Length-flexible — the file size adjusts. Fails (without
modifying the file) if OLD_VALUE is not present.

For STRUCTURED-HEADER formats (`.paschedule`, `.paatt`), use the
JSON-path workflow instead via `parse_<format>_from_file` /
`write_<format>_to_file` — see docs/MOD_AUTHOR_GUIDE.md §12.
"""

from __future__ import annotations

import argparse
import sys
from typing import List


def _list_strings(path: str) -> int:
    try:
        import dmm_parser as _dp  # type: ignore[import-not-found]
    except ImportError:
        print(
            "error: dmm_parser native module not built. Run "
            "`maturin develop --release` from the repo root.",
            file=sys.stderr,
        )
        return 2

    with open(path, "rb") as f:
        data = f.read()

    strings = _dp.walk_lp_strings(data)
    if not strings:
        print(f"{path}: no length-prefixed strings found.")
        print(
            "Note: u8-length-prefixed string tables (.paatt) need "
            "format-specific accessors, not the generic walker."
        )
        return 0
    print(f"{path}: {len(strings)} length-prefixed strings\n")
    for s in strings:
        display = s["value"]
        if len(display) > 80:
            display = display[:77] + "..."
        print(f"  0x{s['file_offset']:08x}  {display!r}")
    return 0


def _rename(path: str, old: str, new: str, out: str | None) -> int:
    try:
        import dmm_parser as _dp  # type: ignore[import-not-found]
    except ImportError:
        print(
            "error: dmm_parser native module not built. Run "
            "`maturin develop --release` from the repo root.",
            file=sys.stderr,
        )
        return 2

    with open(path, "rb") as f:
        data = f.read()

    strings = _dp.walk_lp_strings(data)
    matches: List[dict] = [s for s in strings if s["value"] == old]
    if not matches:
        print(
            f"error: {old!r} not found in {path}.",
            file=sys.stderr,
        )
        print(
            "Use --list to see what strings are present, or check "
            "for u8-length-prefix string tables in `.paatt` (use the "
            "JSON path for those).",
            file=sys.stderr,
        )
        return 1
    if len(matches) > 1:
        print(
            f"warning: {len(matches)} occurrences of {old!r} found at "
            f"offsets {[hex(m['file_offset']) for m in matches]}; "
            "replacing the FIRST one.",
            file=sys.stderr,
        )

    target = matches[0]
    modified = _dp.replace_cstring_at(
        data, target["file_offset"], new, expected_value=old,
    )

    out_path = out or path
    with open(out_path, "wb") as f:
        f.write(modified)
    delta = len(modified) - len(data)
    sign = "+" if delta >= 0 else ""
    print(
        f"renamed {old!r} → {new!r} at offset "
        f"0x{target['file_offset']:08x} ({sign}{delta} bytes); "
        f"wrote {out_path}"
    )
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dmm_parser.tools.rename_string",
        description=(
            "Surgical string rename for u32-length-prefixed file formats "
            "(.pastage, .paseq, .paseqc)."
        ),
    )
    parser.add_argument("file", help="path to the binary file to edit")
    parser.add_argument(
        "old_value",
        nargs="?",
        help="the existing string value to replace",
    )
    parser.add_argument(
        "new_value",
        nargs="?",
        help="the replacement string value",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="output path (default: overwrite input)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list every length-prefixed string with its byte offset and exit",
    )
    args = parser.parse_args(argv)

    if args.list:
        return _list_strings(args.file)
    if args.old_value is None or args.new_value is None:
        parser.error("OLD_VALUE and NEW_VALUE required (or use --list)")
    return _rename(args.file, args.old_value, args.new_value, args.out)


if __name__ == "__main__":
    sys.exit(main())
