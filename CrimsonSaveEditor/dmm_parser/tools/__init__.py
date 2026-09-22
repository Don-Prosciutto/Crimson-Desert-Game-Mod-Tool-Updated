# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/exodiaprivate-eng/dmm-parser
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""
Mod-author CLI toolkit (Phase T).

Each tool is a self-contained module with a `main(argv)` entry point so it
can be invoked as either:

    python -m dmm_parser.tools.validate   <args>
    python -m dmm_parser.tools.pack       <args>
    python -m dmm_parser.tools.inspect    <args>
    python -m dmm_parser.tools.diff       <args>

…or imported and called programmatically from SWISS:

    from dmm_parser.tools import validate
    rc = validate.main(["my_mod.field.json", "--assets", "assets/"])
"""

from . import validate, pack, inspect, diff  # noqa: F401
