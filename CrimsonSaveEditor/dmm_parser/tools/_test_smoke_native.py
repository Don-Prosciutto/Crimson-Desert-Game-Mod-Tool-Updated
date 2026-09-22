# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""
Native-binding smoke tests for the dmm_parser PyO3 surface, focused
on the Tier 1 sequencer/schedule/attack-info functions added during
the dmm-parser Tier 1.5 → Tier 1 promotion loop (Sessions 1-29).

Skips gracefully when `dmm_parser` (the compiled native module) is
not importable — this lets the Python-only tools tests in
`_test_smoke.py` continue to pass on systems without maturin.

Run:
    python -m dmm_parser.tools._test_smoke_native

CI: this is the second smoke layer (after `_test_smoke.py`). Run
both to validate Python-side tools AND the native binding surface.
"""

from __future__ import annotations

import base64
import unittest

try:
    import dmm_parser as _dp  # type: ignore[import-not-found]
    HAS_NATIVE = True
except ImportError:
    HAS_NATIVE = False


def _make_pastage_bytes(name: str, prefab_path: str, body: bytes = b"\x00\x00\x00\x00") -> bytes:
    """Construct a minimal valid `.pastage` byte string for round-trip
    smoke tests. The body is opaque — it just needs to round-trip
    verbatim, the parser doesn't validate its internal structure."""
    name_bytes = name.encode("utf-8")
    prefab_bytes = prefab_path.encode("utf-8")
    out = bytearray()
    out += len(name_bytes).to_bytes(4, "little")
    out += name_bytes
    out += len(prefab_bytes).to_bytes(4, "little")
    out += prefab_bytes
    out += body
    return bytes(out)


@unittest.skipUnless(HAS_NATIVE, "dmm_parser native module not built (maturin develop required)")
class Tier1ParseSerialize(unittest.TestCase):
    """Round-trip smoke for every Tier 1 typed-format reader."""

    def test_pastage_round_trip(self):
        original = _make_pastage_bytes("WAIT", "quest/stagechart_common", b"\x01\x02\x03\x04")
        parsed = _dp.parse_pastage_bytes(original)
        self.assertEqual(parsed["name"], "WAIT")
        self.assertEqual(parsed["prefab_path"], "quest/stagechart_common")
        self.assertEqual(base64.b64decode(parsed["opaque_body_b64"]), b"\x01\x02\x03\x04")
        round_tripped = _dp.serialize_pastage(parsed)
        self.assertEqual(round_tripped, original)

    def test_pastage_field_edit(self):
        """Editing the name field must round-trip via serialize."""
        original = _make_pastage_bytes("OLD_NAME", "quest/stage", b"\x00")
        parsed = _dp.parse_pastage_bytes(original)
        parsed["name"] = "NEW_NAME"
        modified = _dp.serialize_pastage(parsed)
        re_parsed = _dp.parse_pastage_bytes(modified)
        self.assertEqual(re_parsed["name"], "NEW_NAME")
        self.assertEqual(re_parsed["prefab_path"], "quest/stage")

    def test_paatt_empty_round_trip(self):
        """A minimal valid .paatt: 0 infos + 7 empty string tables +
        empty frame_event_buffer."""
        out = bytearray()
        out += (0).to_bytes(4, "little")  # info_count = 0
        for _ in range(7):
            out += (0).to_bytes(2, "little")  # string_count = 0
        out += (0).to_bytes(4, "little")  # frame_event_buffer_size = 0
        original = bytes(out)
        parsed = _dp.parse_paatt_bytes(original)
        self.assertEqual(parsed["infos"], [])
        for table_key in (
            "string_table", "effect_name_table", "effect_info_key_table",
            "socket_name_table", "part_name_table", "sequencer_name_table",
            "prefab_name_table",
        ):
            self.assertEqual(parsed[table_key], [], f"{table_key} should be empty")
        self.assertEqual(base64.b64decode(parsed["frame_event_buffer_b64"]), b"")
        round_tripped = _dp.serialize_paatt(parsed)
        self.assertEqual(round_tripped, original)


@unittest.skipUnless(HAS_NATIVE, "dmm_parser native module not built")
class GenericPrimitives(unittest.TestCase):
    """walk_lp_strings + replace_cstring_at — the generic edit pair."""

    def test_walk_finds_lp_strings(self):
        # Construct: u32(5) + "HELLO" + u32(5) + "WORLD"
        data = (5).to_bytes(4, "little") + b"HELLO" + (5).to_bytes(4, "little") + b"WORLD"
        strings = _dp.walk_lp_strings(data)
        values = [s["value"] for s in strings]
        self.assertIn("HELLO", values)
        self.assertIn("WORLD", values)

    def test_replace_cstring_length_flexible(self):
        data = (5).to_bytes(4, "little") + b"HELLO" + b"\xff\xff"
        modified = _dp.replace_cstring_at(
            data, 0, "HELLO_WORLD", expected_value="HELLO",
        )
        # Length grew by 6 ("HELLO" → "HELLO_WORLD")
        self.assertEqual(len(modified), len(data) + 6)
        # u32 length prefix updated
        self.assertEqual(int.from_bytes(modified[:4], "little"), 11)
        # New string follows
        self.assertEqual(modified[4:15], b"HELLO_WORLD")
        # Tail bytes preserved
        self.assertEqual(modified[15:], b"\xff\xff")

    def test_replace_cstring_safety_check(self):
        data = (5).to_bytes(4, "little") + b"HELLO"
        with self.assertRaises(Exception):
            _dp.replace_cstring_at(
                data, 0, "REPLACEMENT", expected_value="WRONG_VALUE",
            )


if __name__ == "__main__":
    if not HAS_NATIVE:
        print("dmm_parser native module not built — all Tier 1 native smoke tests SKIPPED")
        print("Build with: maturin develop --release")
    unittest.main()
