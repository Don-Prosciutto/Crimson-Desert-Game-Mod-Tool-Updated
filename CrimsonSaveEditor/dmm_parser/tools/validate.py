# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""
dmm-mod-validate — validate a v3 / v3.1 .field.json mod against an assets
folder. Reports findings using the same {code, severity, message} shape
that the Rust DDS/audio validators return so SWISS can render results
uniformly.

Usage:
    python -m dmm_parser.tools.validate <field.json> [--assets DIR] [--json]
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import dmm_parser

from ._common import (
    Finding,
    emit_findings,
    field_format_version,
    iter_targets,
    load_field_json,
    sha256_file,
    target_kind,
)


def _validate_doc(doc: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    try:
        major, minor = field_format_version(doc)
        findings.append(Finding(
            "field_version", "info",
            f"field json version {major}.{minor}",
        ))
    except ValueError as e:
        findings.append(Finding("field_version", "fatal", str(e)))
        return findings

    if not doc.get("name"):
        findings.append(Finding("missing_name", "warning", "no `name` field set"))
    if not doc.get("author"):
        findings.append(Finding("missing_author", "warning", "no `author` field set"))

    targets = list(iter_targets(doc))
    if not targets:
        findings.append(Finding("no_targets", "fatal", "no targets present"))

    return findings


def _validate_target(
    target: dict[str, Any],
    assets_root: str | None,
    *,
    index: int,
) -> list[Finding]:
    findings: list[Finding] = []
    ctx = f"target[{index}]"
    kind = target_kind(target)

    if kind is None:
        findings.append(Finding(
            "unknown_kind", "warning",
            "target has no `kind` and no `table` field — cannot validate",
            context=ctx,
        ))
        return findings

    if kind == "asset":
        findings.extend(_validate_asset_target(target, assets_root, ctx=ctx))
    elif kind == "table":
        findings.extend(_validate_table_target(target, ctx=ctx))
    elif kind == "paloc":
        findings.extend(_validate_paloc_target(target, assets_root, ctx=ctx))
    else:
        findings.append(Finding(
            "unknown_kind", "warning",
            f"unrecognized kind: {kind!r}",
            context=ctx,
        ))

    return findings


def _validate_asset_target(
    target: dict[str, Any], assets_root: str | None, *, ctx: str,
) -> list[Finding]:
    findings: list[Finding] = []
    asset_type = (target.get("asset_type") or "").lower()
    file_rel = target.get("file")
    expected_sha = target.get("sha256")
    vpath = target.get("vpath")

    if not file_rel:
        findings.append(Finding(
            "asset_missing_file", "fatal",
            "asset target has no `file` field",
            context=ctx,
        ))
        return findings
    if not vpath:
        findings.append(Finding(
            "asset_missing_vpath", "warning",
            f"asset target has no `vpath` for {file_rel}",
            context=ctx,
        ))
    if assets_root is None:
        findings.append(Finding(
            "asset_no_root", "info",
            f"--assets not provided; skipped on-disk check for {file_rel}",
            context=ctx,
        ))
        return findings

    full = os.path.join(assets_root, file_rel)
    if not os.path.isfile(full):
        findings.append(Finding(
            "asset_missing_file", "fatal",
            f"file not found on disk: {full}",
            context=ctx,
        ))
        return findings

    actual_sha = sha256_file(full)
    if expected_sha and actual_sha.lower() != expected_sha.lower():
        findings.append(Finding(
            "asset_sha_mismatch", "fatal",
            f"sha256 mismatch for {file_rel}: manifest={expected_sha} actual={actual_sha}",
            context=ctx,
        ))
    elif not expected_sha:
        findings.append(Finding(
            "asset_no_sha", "warning",
            f"no `sha256` in manifest for {file_rel}; would compute {actual_sha}",
            context=ctx,
        ))

    with open(full, "rb") as f:
        data = f.read()

    if asset_type == "dds":
        for f_ in dmm_parser.validate_dds(data):
            findings.append(Finding(
                f_["code"], _severity_to_kind(f_["severity"]), f_["message"],
                context=f"{ctx}/{file_rel}",
            ))
    elif asset_type in ("wem", "bnk", "audio"):
        for f_ in dmm_parser.validate_audio(data):
            findings.append(Finding(
                f_["code"], _severity_to_kind(f_["severity"]), f_["message"],
                context=f"{ctx}/{file_rel}",
            ))
    else:
        findings.append(Finding(
            "asset_type_unknown", "warning",
            f"asset_type={asset_type!r} not recognized; skipped format validation",
            context=ctx,
        ))

    return findings


def _severity_to_kind(s: str) -> str:
    """Normalize Rust severity strings → Finding severities."""
    s = s.lower()
    if s in ("fatal", "error", "warning", "info"):
        return s
    return "warning"


def _validate_table_target(target: dict[str, Any], *, ctx: str) -> list[Finding]:
    findings: list[Finding] = []
    table = target.get("table")
    if not table:
        findings.append(Finding(
            "table_missing", "fatal",
            "table target has no `table` field",
            context=ctx,
        ))
        return findings
    try:
        if not dmm_parser.is_supported_table(table):
            findings.append(Finding(
                "table_unsupported", "warning",
                f"table {table!r} is not in dmm_parser's supported list — caller must validate manually",
                context=ctx,
            ))
    except AttributeError:
        # is_supported_table not yet bound to Python; soft-skip
        pass

    ops = target.get("ops") or target.get("changes")
    if not ops:
        findings.append(Finding(
            "table_no_ops", "warning",
            f"table target {table!r} has no `ops` / `changes`",
            context=ctx,
        ))
    return findings


def _validate_paloc_target(
    target: dict[str, Any], assets_root: str | None, *, ctx: str,
) -> list[Finding]:
    findings: list[Finding] = []
    if "entries" not in target and not target.get("file"):
        findings.append(Finding(
            "paloc_empty", "warning",
            "paloc target has neither inline `entries` nor a `file` reference",
            context=ctx,
        ))
        return findings
    if "file" in target and assets_root:
        full = os.path.join(assets_root, target["file"])
        if not os.path.isfile(full):
            findings.append(Finding(
                "paloc_missing_file", "fatal",
                f"paloc file not found: {full}",
                context=ctx,
            ))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dmm-mod-validate",
        description="Validate a Field-JSON v3/v3.1 mod manifest + assets.",
    )
    parser.add_argument("manifest", help="Path to the .field.json file")
    parser.add_argument(
        "--assets", default=None,
        help="Path to the assets folder (relative paths in manifest resolve here). "
             "Defaults to the manifest's parent directory.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit findings as a JSON array instead of human text",
    )
    args = parser.parse_args(argv)

    try:
        doc = load_field_json(args.manifest)
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2

    assets_root = args.assets or os.path.dirname(os.path.abspath(args.manifest))

    findings = _validate_doc(doc)
    for i, t in enumerate(iter_targets(doc)):
        findings.extend(_validate_target(t, assets_root, index=i))

    return emit_findings(findings, json_out=args.json)


if __name__ == "__main__":
    sys.exit(main())
