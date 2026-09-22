# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""
Smoke tests for the dmm_parser.tools CLI suite. Designed to run without
maturin / compiled bindings — only `inspect` and `diff` are exercised
here; `validate` and `pack` are best tested in CI where the native
`dmm_parser` module is built. SWISS will exercise the validate/pack
flow during its own integration suite.

Run:
    python -m dmm_parser.tools._test_smoke
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest

# Make the parent dmm_parser tools importable when running this file
# directly without an installed package.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _PYTHON_ROOT not in sys.path:
    sys.path.insert(0, _PYTHON_ROOT)


from dmm_parser.tools import diff, inspect, _common  # noqa: E402


def _write_manifest(tmp: str, doc: dict) -> str:
    p = os.path.join(tmp, "mod.field.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    return p


class CommonHelpers(unittest.TestCase):
    def test_iter_targets_v3_0(self):
        # v3.0 inlines a single target at the top level
        doc = {"format": 3, "table": "ItemInfo", "ops": []}
        ts = list(_common.iter_targets(doc))
        self.assertEqual(len(ts), 1)
        self.assertEqual(_common.target_kind(ts[0]), "table")

    def test_iter_targets_v3_1(self):
        doc = {
            "format": 3, "format_minor": 1,
            "targets": [
                {"kind": "table", "table": "ItemInfo", "ops": []},
                {"kind": "asset", "asset_type": "dds", "file": "tex.dds"},
            ],
        }
        ts = list(_common.iter_targets(doc))
        self.assertEqual(len(ts), 2)
        self.assertEqual(_common.target_kind(ts[0]), "table")
        self.assertEqual(_common.target_kind(ts[1]), "asset")

    def test_format_version_default_minor(self):
        self.assertEqual(_common.field_format_version({"format": 3}), (3, 0))
        self.assertEqual(
            _common.field_format_version({"format": 3, "format_minor": 1}),
            (3, 1),
        )

    def test_format_version_rejects_unknown_major(self):
        with self.assertRaises(ValueError):
            _common.field_format_version({"format": 99})

    def test_emit_findings_returns_1_on_fatal(self):
        f = [_common.Finding("x", "fatal", "boom")]
        rc = _common.emit_findings(f, json_out=True, stream=io.StringIO())
        self.assertEqual(rc, 1)

    def test_emit_findings_returns_0_on_warnings_only(self):
        f = [_common.Finding("x", "warning", "easy")]
        rc = _common.emit_findings(f, json_out=True, stream=io.StringIO())
        self.assertEqual(rc, 0)


class InspectCli(unittest.TestCase):
    def test_inspect_text_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_manifest(tmp, {
                "format": 3, "format_minor": 1,
                "name": "Test Mod", "author": "potter",
                "targets": [
                    {"kind": "table", "table": "ItemInfo",
                     "ops": [{"key": "id_4242", "field": "name", "value": "Sword"}]},
                    {"kind": "asset", "asset_type": "dds",
                     "file": "icon.dds", "vpath": "ui/icon/sword.dds",
                     "size": 1024},
                ],
            })
            captured = io.StringIO()
            old = sys.stdout
            sys.stdout = captured
            try:
                rc = inspect.main([p])
            finally:
                sys.stdout = old
            self.assertEqual(rc, 0)
            text = captured.getvalue()
            self.assertIn("Test Mod", text)
            self.assertIn("v3.1", text)
            self.assertIn("ItemInfo", text)
            self.assertIn("ui/icon/sword.dds", text)

    def test_inspect_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_manifest(tmp, {
                "format": 3, "format_minor": 1,
                "name": "X", "targets": [{"kind": "paloc", "entries": []}]
            })
            captured = io.StringIO()
            old = sys.stdout
            sys.stdout = captured
            try:
                rc = inspect.main([p, "--json"])
            finally:
                sys.stdout = old
            self.assertEqual(rc, 0)
            obj = json.loads(captured.getvalue())
            self.assertEqual(obj["name"], "X")
            self.assertEqual(obj["format"], 3)
            self.assertEqual(obj["format_minor"], 1)
            self.assertEqual(obj["targets"][0]["kind"], "paloc")


class DiffCli(unittest.TestCase):
    def test_no_conflicts_when_disjoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.field.json")
            b = os.path.join(tmp, "b.field.json")
            with open(a, "w", encoding="utf-8") as f:
                json.dump({"format": 3, "format_minor": 1, "targets": [
                    {"kind": "table", "table": "ItemInfo",
                     "ops": [{"key": "id_1", "field": "x", "value": 1}]},
                ]}, f)
            with open(b, "w", encoding="utf-8") as f:
                json.dump({"format": 3, "format_minor": 1, "targets": [
                    {"kind": "table", "table": "SkillInfo",
                     "ops": [{"key": "id_99", "field": "y", "value": 2}]},
                ]}, f)

            captured = io.StringIO()
            old = sys.stdout
            sys.stdout = captured
            try:
                rc = diff.main([a, b])
            finally:
                sys.stdout = old
            self.assertEqual(rc, 0)
            self.assertIn("OK", captured.getvalue())

    def test_table_row_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.field.json")
            b = os.path.join(tmp, "b.field.json")
            shared = {"format": 3, "format_minor": 1, "targets": [
                {"kind": "table", "table": "ItemInfo",
                 "ops": [{"key": "id_42", "field": "name", "value": "x"}]},
            ]}
            with open(a, "w", encoding="utf-8") as f:
                json.dump(shared, f)
            with open(b, "w", encoding="utf-8") as f:
                json.dump(shared, f)

            captured = io.StringIO()
            old = sys.stdout
            sys.stdout = captured
            try:
                rc = diff.main([a, b])
            finally:
                sys.stdout = old
            self.assertEqual(rc, 1)
            self.assertIn("ItemInfo::id_42", captured.getvalue())

    def test_asset_vpath_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.field.json")
            b = os.path.join(tmp, "b.field.json")
            for path in (a, b):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"format": 3, "format_minor": 1, "targets": [
                        {"kind": "asset", "asset_type": "dds",
                         "file": "x.dds", "vpath": "/ui/icon/sword.dds"},
                    ]}, f)

            captured = io.StringIO()
            old = sys.stdout
            sys.stdout = captured
            try:
                rc = diff.main([a, b, "--json"])
            finally:
                sys.stdout = old
            self.assertEqual(rc, 1)
            obj = json.loads(captured.getvalue())
            self.assertEqual(obj["asset_conflicts"], ["ui/icon/sword.dds"])

    def test_paloc_key_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.field.json")
            b = os.path.join(tmp, "b.field.json")
            for path in (a, b):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"format": 3, "format_minor": 1, "targets": [
                        {"kind": "paloc",
                         "entries": [{"key": "STR_HELLO", "value": "hi"}]},
                    ]}, f)

            captured = io.StringIO()
            old = sys.stdout
            sys.stdout = captured
            try:
                rc = diff.main([a, b])
            finally:
                sys.stdout = old
            self.assertEqual(rc, 1)
            self.assertIn("STR_HELLO", captured.getvalue())


if __name__ == "__main__":
    unittest.main()
