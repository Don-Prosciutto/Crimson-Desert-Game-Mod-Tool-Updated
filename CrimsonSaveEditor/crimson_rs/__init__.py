"""Weiterleitung von crimson_rs auf dmm_parser.

Der Save Editor importiert an 23 Stellen `crimson_rs` — ein Paket, das in
seinem Ordner gar nicht liegt und dessen Nachfolger `dmm_parser` heisst.
Die benutzten Funktionen (extract_file, parse_iteminfo_from_bytes,
serialize_iteminfo, pack_mod) haben in beiden Paketen dieselbe Signatur,
deshalb genuegt diese Weiterleitung und keine der Aufrufstellen muss
geaendert werden.

Nebeneffekt, auf den es ankommt: dmm_parser bringt den Aufsatz aus
table_layout mit. Der setzt die Archivnamen von vor Spielversion 2.01
(gamedata/binary__/client/bin/<t>.pabgb) automatisch auf die aktuellen
um (gamedata/binarystaticinfo__/bin/<t>.staticinfobody). Die zehn fest
verdrahteten Verzeichnisangaben in gui.py funktionieren damit wieder,
ohne angefasst zu werden.
"""

from __future__ import annotations

import dmm_parser as _dmm

# Alles oeffentliche aus dmm_parser uebernehmen.
globals().update({k: v for k, v in vars(_dmm).items() if not k.startswith("_")})

from dmm_parser import Compression, Crypto, Language  # noqa: E402,F401

__all__ = [k for k in globals() if not k.startswith("_")]
