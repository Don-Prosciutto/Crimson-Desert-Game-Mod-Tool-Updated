# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""Shared helpers for the dmm-mod-* CLI tools (Phase T)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any, Iterator


# ── Findings ─────────────────────────────────────────────────────────────

class Finding:
    """Mirrors the {code, severity, message} shape used by the Rust
    validators (validate_dds, validate_audio) so that stdout / SWISS
    can render a unified result list."""

    __slots__ = ("code", "severity", "message", "context")

    def __init__(self, code: str, severity: str, message: str, context: str | None = None):
        if severity not in ("fatal", "error", "warning", "info"):
            raise ValueError(f"bad severity: {severity!r}")
        self.code = code
        self.severity = severity
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        d = {"code": self.code, "severity": self.severity, "message": self.message}
        if self.context:
            d["context"] = self.context
        return d

    def __str__(self) -> str:
        ctx = f" [{self.context}]" if self.context else ""
        return f"{self.severity.upper():7} {self.code}{ctx}: {self.message}"


# ── Field JSON I/O ───────────────────────────────────────────────────────

def load_field_json(path: str) -> dict[str, Any]:
    """Load a .field.json file. Raises ValueError with a clear message
    on JSON or schema problems."""
    if not os.path.isfile(path):
        raise ValueError(f"field json not found: {path}")
    with open(path, "rb") as f:
        raw = f.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be an object, got {type(data).__name__}")
    return data


def field_format_version(doc: dict[str, Any]) -> tuple[int, int]:
    """Return (major, minor) — defaults to (3, 0) if format_minor missing.
    Raises ValueError for unknown majors."""
    major = doc.get("format")
    if major not in (3,):
        raise ValueError(f"unsupported field format major: {major!r} (only 3 is supported)")
    minor = int(doc.get("format_minor", 0))
    return major, minor


# ── Hashing ──────────────────────────────────────────────────────────────

def sha256_file(path: str) -> str:
    """Return lowercase hex SHA-256 of a file. Streams in 1 MiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Targets / asset enumeration ──────────────────────────────────────────

def iter_targets(doc: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield each target dict from a field doc, regardless of 3.0 vs 3.1
    layout. v3.0 docs have a single inlined target; v3.1 wraps in
    `targets: [...]`."""
    if "targets" in doc and isinstance(doc["targets"], list):
        for t in doc["targets"]:
            if isinstance(t, dict):
                yield t
    else:
        yield doc


def target_kind(target: dict[str, Any]) -> str | None:
    """Return the canonical kind label for a target.

    v3.1 uses `target.kind` (e.g. "table", "asset"). v3.0 inferred kind
    from `target.table` (always table). Returns lowercase or None if
    we can't tell."""
    k = target.get("kind")
    if isinstance(k, str):
        return k.lower()
    if "table" in target:
        return "table"
    return None


# ── Output ───────────────────────────────────────────────────────────────

def emit_findings(findings: list[Finding], *, json_out: bool, stream=sys.stdout) -> int:
    """Write findings to stdout. Returns process exit code: 0 if no
    fatal/error findings, 1 otherwise."""
    fatal = sum(1 for f in findings if f.severity in ("fatal", "error"))
    if json_out:
        json.dump([f.to_dict() for f in findings], stream, indent=2)
        stream.write("\n")
    else:
        if not findings:
            stream.write("OK — no findings.\n")
        else:
            for f in findings:
                stream.write(str(f) + "\n")
            warnings = sum(1 for f in findings if f.severity == "warning")
            infos = sum(1 for f in findings if f.severity == "info")
            stream.write(
                f"\n{fatal} fatal/error, {warnings} warning, {infos} info"
                f"  ({len(findings)} total)\n"
            )
    return 0 if fatal == 0 else 1
