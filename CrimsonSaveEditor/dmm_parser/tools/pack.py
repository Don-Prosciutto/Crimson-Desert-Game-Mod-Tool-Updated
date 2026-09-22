# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""
dmm-mod-pack — produce a v3.1 mod package zip from a manifest + asset folder.

Computes SHA-256 for every asset target, optionally infers vpaths from
file paths (DDS / Wwise audio), and writes the resulting zip with the
.field.json at the root and assets/ underneath.

Usage:
    python -m dmm_parser.tools.pack <manifest.field.json> [--assets DIR] [--out OUT.zip]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from typing import Any

import dmm_parser

from ._common import (
    iter_targets,
    load_field_json,
    sha256_bytes,
    target_kind,
)


def _infer_vpath_for_asset(file_rel: str, asset_type: str | None) -> str | None:
    """Best-effort vpath inference based on asset type. The Rust
    `infer_*_vpath` helpers do the heavy lifting; we just dispatch."""
    asset_type = (asset_type or "").lower()
    if asset_type == "dds":
        try:
            return dmm_parser.infer_dds_vpath("", file_rel)
        except Exception:
            return None
    if asset_type in ("wem", "bnk", "audio"):
        # `infer_audio_vpath` is a class predicate, not a path mapper —
        # we can only confirm "this looks like an audio path", not
        # synthesize one. Pass through as-is.
        return None
    return None


def _fill_asset_target(target: dict[str, Any], assets_root: str) -> tuple[dict[str, Any], list[str]]:
    """Return (filled_target, errors). Mutates a copy of the target so
    the on-disk manifest stays untouched."""
    filled = dict(target)
    errors: list[str] = []

    file_rel = filled.get("file")
    if not file_rel:
        errors.append("asset target has no `file` field; cannot pack")
        return filled, errors

    full = os.path.join(assets_root, file_rel)
    if not os.path.isfile(full):
        errors.append(f"file not found on disk: {full}")
        return filled, errors

    with open(full, "rb") as f:
        data = f.read()

    actual_sha = sha256_bytes(data)
    if filled.get("sha256"):
        if filled["sha256"].lower() != actual_sha.lower():
            errors.append(
                f"sha256 mismatch for {file_rel}: "
                f"manifest={filled['sha256']} actual={actual_sha}"
            )
    else:
        filled["sha256"] = actual_sha

    if not filled.get("size"):
        filled["size"] = len(data)

    if not filled.get("vpath"):
        inferred = _infer_vpath_for_asset(file_rel, filled.get("asset_type"))
        if inferred:
            filled["vpath"] = inferred

    return filled, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dmm-mod-pack",
        description="Pack a v3.1 mod into a distributable zip.",
    )
    parser.add_argument("manifest", help="Path to the .field.json file")
    parser.add_argument(
        "--assets", default=None,
        help="Assets folder. Defaults to the manifest's parent directory.",
    )
    parser.add_argument(
        "--out", default=None,
        help="Output zip path. Defaults to <manifest_basename>.zip next to the manifest.",
    )
    parser.add_argument(
        "--no-fill", action="store_true",
        help="Don't mutate manifest fields (sha256/size/vpath) — pack as-is.",
    )
    args = parser.parse_args(argv)

    try:
        doc = load_field_json(args.manifest)
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2

    manifest_dir = os.path.dirname(os.path.abspath(args.manifest))
    assets_root = args.assets or manifest_dir
    out_zip = args.out or os.path.splitext(os.path.abspath(args.manifest))[0] + ".zip"

    errors: list[str] = []
    if not args.no_fill:
        # Walk targets and fill in sha256/size/vpath where missing.
        targets_list = doc.get("targets")
        if isinstance(targets_list, list):
            for i, t in enumerate(targets_list):
                if target_kind(t) == "asset":
                    filled, errs = _fill_asset_target(t, assets_root)
                    if errs:
                        for e in errs:
                            errors.append(f"target[{i}]: {e}")
                    targets_list[i] = filled
        elif target_kind(doc) == "asset":
            filled, errs = _fill_asset_target(doc, assets_root)
            if errs:
                errors.extend(errs)
            else:
                doc.update(filled)

    if errors:
        for e in errors:
            print(f"FATAL: {e}", file=sys.stderr)
        return 1

    # Collect every asset file we need to include.
    asset_files: list[tuple[str, str]] = []  # (arcname, on_disk)
    for t in iter_targets(doc):
        if target_kind(t) == "asset":
            file_rel = t.get("file")
            if file_rel:
                full = os.path.join(assets_root, file_rel)
                arc = os.path.join("assets", file_rel).replace("\\", "/")
                asset_files.append((arc, full))

    manifest_arc = os.path.basename(args.manifest)

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(manifest_arc, json.dumps(doc, indent=2, sort_keys=False))
        for arc, full in asset_files:
            z.write(full, arc)

    print(f"OK — packed {len(asset_files)} asset(s) + manifest → {out_zip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
