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
        return self.titel != "nicht pruefbar"


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
        return Befund(False, "Spielstand nicht mehr lesbar",
                      f"Der bearbeitete Spielstand laesst sich nicht mehr auslesen:\n\n{e}",
                      "")
    eintraege = toc["entries"]
    for e in eintraege:
        if e.data_offset < 0 or e.data_offset + e.data_size > len(bearbeitet):
            return Befund(False, "Blockgrenze ausserhalb der Datei",
                          f"Block #{e.index} ({e.class_name}) reicht ueber das Ende "
                          f"des Spielstands hinaus.", "")
    return Befund(True, "in Ordnung",
                  f"{len(schema['types'])} Typen, {len(eintraege)} Bloecke gelesen.")


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
        log.warning("Verweispruefung nicht moeglich: %s", e)
        return Befund(True, "nicht pruefbar",
                      f"Die Verweise konnten nicht gezaehlt werden ({e}). "
                      f"Der Spielstand ist lesbar, mehr laesst sich hier nicht sagen.")

    verloren = vorher - nachher
    log.info("Verweispruefung: vorher %d, nachher %d (%+d)", vorher, nachher, -verloren)
    if verloren > 0:
        return Befund(
            False, "Verweise verloren",
            f"Nach der Aenderung sind {verloren} interne Verweise nicht mehr "
            f"auffindbar ({vorher} → {nachher}).\n\n"
            f"Der Spielstand laesst sich zwar lesen, aber ein Bereich ist nicht "
            f"mehr durchgaengig begehbar. Genau so sah der Spielstand aus, der "
            f"das Spiel beim Start abstuerzen liess.\n\n"
            f"Diese Aenderung sollte nicht gespeichert werden.",
            f"Verweise vorher {vorher}, nachher {nachher}, Differenz {-verloren}")
    return Befund(True, "in Ordnung",
                  f"Verweise vollstaendig ({vorher} → {nachher}), "
                  f"{schnell.text}")


def pruefe(original: bytes, bearbeitet: bytes,
           verweise_vorher: Optional[int] = None) -> Befund:
    """Die passende Pruefung waehlen: schnell bei gleicher Groesse, sonst voll."""
    if original is not None and len(original) == len(bearbeitet):
        befund = schnellpruefung(bearbeitet)
        log.info("Spielstand unveraendert gross (%d Byte) - Schnellpruefung: %s",
                 len(bearbeitet), befund.titel)
        return befund
    log.info("Spielstand hat die Groesse geaendert (%d → %d Byte) - volle Pruefung",
             len(original) if original is not None else -1, len(bearbeitet))
    return vollpruefung(original, bearbeitet, verweise_vorher)
