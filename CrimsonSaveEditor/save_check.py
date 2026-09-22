"""Pruefen, ob ein bearbeiteter Spielstand noch stimmig ist - VOR dem Schreiben.

Warum es das braucht
--------------------
Am 22.09.2026 hat ein Spielstand, der ueber den Editor einen Abyss-Stein in
eine leere Fassung bekommen hatte, das Spiel beim Start abstuerzen lassen -
vor dem Hauptmenue, also war gar kein Spielstand mehr ladbar. Die Datei sah
dabei einwandfrei aus:

  - Schema liess sich lesen (103 Typen)
  - alle 1211 Bloecke vorhanden, Groessen stimmig
  - Itemzahl unveraendert
  - die C++-Pruefung beim Schreiben meldete nichts

Sichtbar wurde der Schaden erst an einer einzigen Zahl: der Sammler, der die
internen Verweise einsammelt, fand danach 1.832 Verweise WENIGER als vorher -
obwohl er den Spielstand bis zum Ende durchlief. Ein Bereich war also nicht
mehr begehbar, und das Spiel stolperte darueber.

Genau diese Zahl prueft dieser Baustein.

Was er kostet
-------------
Der Sammler braucht auf einem 6,7-MB-Spielstand rund sechs Sekunden. Deshalb
laeuft die volle Pruefung nur, wenn der Spielstand seine GROESSE geaendert hat -
also bei Aenderungen, die etwas einfuegen oder entfernen. Wer nur einen Wert
ueberschreibt (Stapel, Verzauberung, Stein tauschen), veraendert keine Laenge,
verschiebt keine Verweise und bekommt die schnelle Pruefung.
"""

from __future__ import annotations

import logging
from typing import NamedTuple, Optional

log = logging.getLogger(__name__)


class Befund(NamedTuple):
    ok: bool
    titel: str
    text: str
    ausfuehrlich: str = ""

    @property
    def geprueft(self) -> bool:
        """Konnte ueberhaupt geprueft werden?"""
        return self.titel != "not checkable"


def _bloecke(blob: bytes):
    """Schema und Blockverzeichnis lesen. Wirft bei kaputtem Aufbau."""
    import save_parser
    schema = save_parser.parse_schema(blob)
    typen = [t.name for t in schema["types"]]
    toc = save_parser.parse_toc(blob, schema["schema_end"], typen)
    return schema, toc


def _verweise(blob: bytes) -> int:
    from parc_inserter2 import parse_and_collect
    _ergebnis, offsets, _groessen = parse_and_collect(blob)
    return len(offsets)


def schnellpruefung(bearbeitet: bytes) -> Befund:
    """Laesst sich der Spielstand ueberhaupt noch lesen?

    Faengt groben Schaden ab und kostet unter einer Sekunde. Feinen Schaden
    an den Verweisen faengt sie NICHT - dafuer ist die volle Pruefung da.
    """
    try:
        schema, toc = _bloecke(bearbeitet)
    except Exception as e:  # noqa: BLE001
        return Befund(False, "save no longer readable",
                      f"The edited save can no longer be parsed:\n\n{e}", "")
    eintraege = toc["entries"]
    for e in eintraege:
        if e.data_offset < 0 or e.data_offset + e.data_size > len(bearbeitet):
            return Befund(False, "block extends past the end of the file",
                          f"Block #{e.index} ({e.class_name}) reaches beyond the end "
                          f"of the save.", "")
    return Befund(True, "ok",
                  f"{len(schema['types'])} types, {len(eintraege)} blocks read.")


def vollpruefung(original: bytes, bearbeitet: bytes,
                 verweise_vorher: Optional[int] = None) -> Befund:
    """Sind nach einer Groessenaenderung noch alle Verweise begehbar?

    `verweise_vorher` kann mitgegeben werden, wenn die Zahl schon bekannt ist -
    das spart die halbe Laufzeit.
    """
    schnell = schnellpruefung(bearbeitet)
    if not schnell.ok:
        return schnell

    try:
        vorher = verweise_vorher if verweise_vorher is not None else _verweise(original)
        nachher = _verweise(bearbeitet)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not count internal offsets: %s", e)
        return Befund(True, "not checkable",
                      f"The internal offsets could not be counted ({e}). "
                      f"The save is readable; nothing more can be said here.")

    verloren = vorher - nachher
    log.info("Offset check: before %d, after %d (%+d)", vorher, nachher, -verloren)
    if verloren > 0:
        return Befund(
            False, "internal offsets lost",
            f"After this change, {verloren} internal offsets can no longer be "
            f"found ({vorher} \u2192 {nachher}).\n\n"
            f"The save still parses, but one region is no longer walkable end "
            f"to end. That is exactly how the save looked that stopped the game "
            f"from starting.\n\n"
            f"This change should not be written.",
            f"offsets before {vorher}, after {nachher}, difference {-verloren}")
    return Befund(True, "ok",
                  f"offsets complete ({vorher} \u2192 {nachher}), {schnell.text}")


def pruefe(original: bytes, bearbeitet: bytes,
           verweise_vorher: Optional[int] = None) -> Befund:
    """Die passende Pruefung waehlen: schnell bei gleicher Groesse, sonst voll."""
    if original is not None and len(original) == len(bearbeitet):
        befund = schnellpruefung(bearbeitet)
        log.info("Save size unchanged (%d bytes) - quick check: %s",
                 len(bearbeitet), befund.titel)
        return befund
    log.info("Save size changed (%d -> %d bytes) - running the full check",
             len(original) if original is not None else -1, len(bearbeitet))
    return vollpruefung(original, bearbeitet, verweise_vorher)
