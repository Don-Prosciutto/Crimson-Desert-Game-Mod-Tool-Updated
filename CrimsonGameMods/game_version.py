"""Installierte Spielversion lesen und gegen den Stand des Parsers halten.

Warum das noetig ist: Der Parser kennt genau ein Feld-Layout. Fuegt ein
Spielupdate irgendwo ein Feld ein, verschiebt sich alles dahinter, und der
Parser liest ab dieser Stelle an falschen Positionen. Manchmal bricht er ab —
dann sieht man es. Manchmal laeuft er durch und liefert Unsinn, oder schreibt
Tabellen verkuerzt zurueck, ohne zu warnen. Genau das ist im Sommer 2026
monatelang unbemerkt geblieben.

Diese Pruefung macht den Fall beim Setzen des Spielpfads sichtbar, statt ihn
erst beim dritten beschaedigten Mod auffallen zu lassen.

Erfahrungswert aus dem Update 2.03.00 -> 2.03.01: Ein Hotfix, der nur die
dritte Zahl bewegt, brachte Inhaltszuwaechse in fuenf Tabellen, aber keine
Layout-Aenderung. Deshalb warnt diese Pruefung nur bei abweichender
Haupt- oder Nebenversion und erwaehnt einen abweichenden Hotfix bloss.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

# Spielversion, fuer die der mitgelieferte Parser gebaut wurde.
# Beim Parser-Update mit hochsetzen.
PARSER_TARGET = "2.03.01"


def read_game_version(game_path: str) -> str | None:
    """Liest meta/0.paver. Drei u16 little-endian ergeben major.minor.patch."""
    pfad = os.path.join(game_path or "", "meta", "0.paver")
    try:
        with open(pfad, "rb") as f:
            roh = f.read(6)
    except OSError as e:
        log.info("Spielversion nicht lesbar (%s): %s", pfad, e)
        return None
    if len(roh) < 6:
        return None
    teile = [int.from_bytes(roh[i:i + 2], "little") for i in (0, 2, 4)]
    return f"{teile[0]}.{teile[1]:02d}.{teile[2]:02d}"


def _dreiteilig(version: str) -> tuple[int, int, int]:
    try:
        teile = [int(t) for t in version.split(".")]
    except (ValueError, AttributeError):
        return (0, 0, 0)
    teile += [0, 0, 0]
    return tuple(teile[:3])  # type: ignore[return-value]


def check(game_path: str) -> tuple[str, str] | None:
    """Gibt (Titel, Meldung) zurueck, wenn etwas zu melden ist, sonst None."""
    installiert = read_game_version(game_path)
    if not installiert:
        return None

    spiel = _dreiteilig(installiert)
    parser = _dreiteilig(PARSER_TARGET)

    if spiel[:2] != parser[:2]:
        richtung = "neuer" if spiel[:2] > parser[:2] else "aelter"
        return (
            "Spielversion passt nicht zum Parser",
            f"Installierte Spielversion: {installiert}\n"
            f"Der mitgelieferte Parser zielt auf: {PARSER_TARGET}\n\n"
            f"Das Spiel ist {richtung}. Damit koennen Tabellen falsch gelesen "
            f"werden — und schlimmer, beim Zurueckschreiben stillschweigend "
            f"beschaedigt werden.\n\n"
            f"Bis ein passender Parser vorliegt: keine Mods bauen, die auf "
            f"Spieltabellen schreiben."
        )

    if spiel[2] != parser[2]:
        return (
            "Abweichender Hotfix",
            f"Installierte Spielversion: {installiert}\n"
            f"Der Parser zielt auf: {PARSER_TARGET}\n\n"
            f"Nur die letzte Zahl weicht ab. Erfahrungsgemaess aendern "
            f"Hotfixes das Datenlayout nicht, das Tool sollte also normal "
            f"arbeiten.\n\n"
            f"Falls doch Tabellen nicht mehr gelesen werden, ist das der "
            f"erste Ort zum Nachsehen."
        )

    return None
