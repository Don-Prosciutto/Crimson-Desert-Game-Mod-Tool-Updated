"""Forwarding shim from crimson_rs to dmm_parser.

The Save Editor imports `crimson_rs` in 23 places - a package that is not in
its folder at all, and whose successor is called `dmm_parser`. The functions
used (extract_file, parse_iteminfo_from_bytes, serialize_iteminfo, pack_mod)
have the same signature in both packages, so this forwarding is enough and no
call site has to be changed.

The side effect that matters: dmm_parser brings the table_layout layer with
it. That layer automatically rewrites the pre-2.01 archive names
(gamedata/binary__/client/bin/<t>.pabgb) to the current ones
(gamedata/binarystaticinfo__/bin/<t>.staticinfobody). The ten hard-wired
directory paths in gui.py therefore work again without being touched.
"""

from __future__ import annotations

import dmm_parser as _dmm

# Take everything public from dmm_parser.
globals().update({k: v for k, v in vars(_dmm).items() if not k.startswith("_")})

from dmm_parser import Compression, Crypto, Language  # noqa: E402,F401

__all__ = [k for k in globals() if not k.startswith("_")]
