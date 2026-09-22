"""Item-Datensaetze ueber das Schema des Spielstands lesen.

Der Baustein hat zwei Aufgaben.

**1. Fehltreffer der Bytemustersuche erkennen.**
`scan_items` findet Items ueber eine Bytemustersuche und akzeptiert dabei Stapel
bis 9*10^18 und beliebige Slotnummern. Dadurch meldet sie zufaellige Bytefolgen
als Items - in einem frisch begonnenen Spiel ohne Mods 126 Stueck, mit Stapeln
von 72 Billiarden auf Slot 256.

Eine einfache Plausibilitaetsgrenze genuegt dafuer nicht: der groesste ECHTE
Stapel in den Messdaten ist 88.888.888 (Stack-Mods), und 50 echte Items liegen
auf Slots ueber 255 (erweiterte Taschen). Ein Schwellwert allein wuerde echte
Items wegwerfen. Deshalb der Umweg ueber das Schema, das der Spielstand selbst
mitbringt: Was dort als Item-Datensatz steht, ist echt. Was nicht dort steht UND
unplausible Werte hat, ist ein Fehltreffer.

**2. Items nachbessern, die `enrich_items_with_parc` nicht erreicht.**
Der PARC-Weg des Autors liest nur Felder der Art `object_list`
(`_find_item_fields_in_parsed`: `if kind != "object_list": continue`). Items, die
hinter einem Zeiger haengen - so haengt Ausruestung an ihrem Slot -, erreicht er
nicht. In den Messdaten betrifft das slot104: 243 von 597 Items. Fuer die zeigte
das Tool als "Haltbarkeit" die gepackten Sockelzahlen an (5 statt 0, 773 statt 0),
und **aendern liess sich an ihnen gar nichts**, weil `_require_parc_field_offset`
ohne Feldposition zu Recht ablehnt.

Dieser Baustein geht denselben Datensaetzen ueber das Schema nach und liefert
Werte **samt Byte-Position**. Damit stimmen die Anzeigewerte, und der Schreibweg
trifft die richtige Stelle.

Belegt: An 5087 Feldern, die beide Wege erreichen, stimmen die Byte-Positionen
ueberein. Die einzigen 24 Abweichungen betrafen 8 Items, die zweimal im
Spielstand stehen - dort ordnete `enrich_items_with_parc` den falschen der beiden
Datensaetze zu, weil es nur nach `_itemNo` abgleicht. Das ist dort behoben.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, NamedTuple, Optional, Tuple

log = logging.getLogger(__name__)

# Blockklassen, die Items tragen koennen. Als Wortstaemme, nicht als exakte
# Namen: je nach Spielstand heisst der Inventarblock InventorySaveData oder
# InventoryItemContentsSaveData. Ein frisch begonnenes Spiel hat nur den
# zweiten — eine Liste exakter Namen uebersieht dort das halbe Inventar.
ITEMTRAGENDE_STAEMME = ("Inventory", "Equipment", "Store", "Mercenary")


def _traegt_items(klassenname: str) -> bool:
    return any(stamm in (klassenname or "") for stamm in ITEMTRAGENDE_STAEMME)

# 0xFFFF bedeutet in diesen Datensaetzen "nicht gesetzt", nicht 65535.
NICHT_GESETZT_U16 = 0xFFFF


class Feld(NamedTuple):
    """Ein Feldwert samt seiner Position im entpackten Spielstand."""
    wert: Optional[int]
    start: int
    ende: int
    sicher: bool = True

    @property
    def verwendbar(self) -> bool:
        """Darf diese Position benutzt werden, um zu lesen oder zu schreiben?

        Hinter den Listenfeldern laeuft dieser Index dem PARC-Weg um zwei
        Byte hinterher - nachgemessen an slot100: _transferredItemKey liegt
        laut PARC bei 34110 (Wert 1163042, plausibel), laut diesem Index bei
        34108 (Wert 3206676737, Unsinn). Offenbar belegt ein fehlendes
        Listenfeld trotzdem zwei Byte, die dieser Gang nicht mitzaehlt.

        Die Felder VOR den Listen sind davon nicht betroffen - dort stimmen
        beide Wege an 15.635 Stellen ueberein, und das sind genau die, die
        das Tool liest und schreibt. Damit niemand versehentlich auf die
        unsicheren baut, melden die sich hier von selbst ab.
        """
        return self.vorhanden and self.sicher

    @property
    def vorhanden(self) -> bool:
        """Steht dieses Feld ueberhaupt im Datensatz?

        Entschieden wird das an der Byte-Position, NICHT am Wert. Ein
        Listenfeld wie _socketSaveDataList hat keinen Zahlenwert, aber sehr
        wohl eine Position - frueher galt es hier deshalb faelschlich als
        nicht vorhanden, und der Index verschwieg genau das Feld, auf dem
        der Sockel-Reiter steht. Fehlende Felder haben start == ende == 0.
        """
        return self.ende > self.start

    @property
    def gesetzt(self) -> bool:
        """Vorhanden, mit Zahlenwert, und nicht der Sentinel fuer 'kein Wert'."""
        return (self.vorhanden and self.wert is not None
                and self.wert != NICHT_GESETZT_U16)


def _als_zahl(text: str) -> Optional[int]:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _sammle_items(feld, treffer: list) -> None:
    """Alle ItemSaveData-Knoten unterhalb eines Feldes einsammeln.

    Items stecken an zwei Stellen: als Listenelemente (Inventar) und hinter
    einem Zeiger (`object_locator`, so haengt Ausruestung an ihrem Slot).
    Beide Faelle muessen geprueft werden — nur auf Listenelemente zu achten
    uebersieht die komplette Ausruestung.
    """
    if getattr(feld, "child_type_name", "") == "ItemSaveData" and feld.child_fields:
        treffer.append(feld)
    for element in (getattr(feld, "list_elements", None) or []):
        typ = getattr(element, "child_type_name", "") or getattr(element, "type_name", "")
        if typ == "ItemSaveData" and element.child_fields:
            treffer.append(element)
        for kind in (element.child_fields or []):
            _sammle_items(kind, treffer)
    for kind in (getattr(feld, "child_fields", None) or []):
        _sammle_items(kind, treffer)


# Die Bytemustersuche meldet als `offset` die Stelle vier Byte vor `_itemNo`.
# Nachgemessen: bei allen eindeutigen Items stimmt dieser Wert exakt mit dem
# `offset` ueberein, den der PARC-Weg meldet. Dadurch laesst sich ein Item auch
# dann eindeutig einem Datensatz zuordnen, wenn dieselbe itemNo mehrfach im
# Spielstand steht.
# Die Bytemustersuche meldet als `offset` die Stelle vier Byte vor `_itemNo`.
# Nachgemessen an slot104: bei allen 340 eindeutigen Items stimmt dieser Wert
# exakt mit dem `offset` ueberein, den der PARC-Weg meldet. Dadurch laesst sich
# ein Item auch dann eindeutig einem Datensatz zuordnen, wenn dieselbe itemNo
# mehrfach im Spielstand steht.
ANKER_VERSATZ = 4


def _lies_datensaetze(blob) -> list:
    """Alle Item-Datensaetze als {Feldname: Feld} - einmal durch den Spielstand.

    Gibt bei jedem Fehler eine leere Liste zurueck. Der Aufrufer faellt dann auf
    die bisherigen Werte zurueck; ein Fehler hier darf das Laden eines
    Spielstands nicht verhindern.
    """
    try:
        import save_parser
    except ImportError:
        log.warning("save_parser unavailable - skipping the schema index")
        return []

    blob = bytes(blob)
    try:
        schema = save_parser.parse_schema(blob)
        typnamen = [t.name for t in schema["types"]]
        toc = save_parser.parse_toc(blob, schema["schema_end"], typnamen)
        eintraege = [e for e in toc["entries"] if _traegt_items(e.class_name)]
        if not eintraege:
            log.info("No item-bearing blocks found in this save")
            return []
        bloecke = save_parser.decode_object_blocks(blob, eintraege, schema["types"])
    except Exception as e:  # noqa: BLE001 - Diagnose darf nie das Laden kippen
        log.warning("Could not build the schema index: %s", e)
        return []

    knoten: list = []
    for block in bloecke:
        for feld in block.fields:
            _sammle_items(feld, knoten)

    datensaetze = []
    for knoten_ in knoten:
        felder: Dict[str, Feld] = {}
        # Ab dem ersten Listenfeld gelten die Positionen als unsicher, siehe
        # Feld.verwendbar. Die Liste selbst ist noch in Ordnung - nachgemessen
        # an 1.895 Items stimmt _socketSaveDataList mit dem PARC-Weg ueberein -,
        # erst was DAHINTER kommt, driftet.
        hinter_liste = False
        for cf in (knoten_.child_fields or []):
            felder[cf.name] = Feld(
                wert=_als_zahl(cf.value_repr) if cf.value_repr else None,
                start=cf.start_offset,
                ende=cf.end_offset,
                sicher=not hinter_liste,
            )
            if cf.name.endswith("List") or cf.name.endswith("Data"):
                hinter_liste = True
        if felder.get("_itemKey") and felder.get("_itemNo"):
            datensaetze.append(felder)

    log.info("Schema: %d item records from %d blocks",
             len(datensaetze), len(bloecke))
    return datensaetze


# Beim Laden eines Spielstands wird der Index zweimal gebraucht: einmal fuer die
# Phantomerkennung in scan_items, einmal fuer die Ergaenzung in
# enrich_items_with_parc. Der Durchgang kostet auf einem 6,7-MB-Spielstand rund
# eine Sekunde - also einmal rechnen, nicht zweimal. Gemerkt wird nur der
# zuletzt gelesene Spielstand; mehr wird nie gleichzeitig gebraucht.
_MERK_SCHLUESSEL = None
_MERK_ERGEBNIS = None


def _blob_schluessel(blob) -> str:
    import hashlib
    return f"{len(blob)}:{hashlib.md5(bytes(blob)).hexdigest()}"


def baue_indizes(blob) -> Tuple[Dict[Tuple[int, int], Dict[str, Feld]],
                                Dict[int, Dict[str, Feld]]]:
    """Beide Zuordnungen in einem Durchgang.

    - nach (itemKey, itemNo): fuer die Phantomerkennung. Dort genuegt die Frage
      "kommt dieser Schluessel ueberhaupt im Schema vor", Doppelungen schaden
      nicht.
    - nach Anker (Byte-Position): ordnet ein einzelnes Item eindeutig EINEM
      Datensatz zu, auch wenn dieselbe itemNo mehrfach vorkommt. Nur diese
      Zuordnung darf Grundlage fuer Schreibzugriffe sein.
    """
    global _MERK_SCHLUESSEL, _MERK_ERGEBNIS
    try:
        schluessel = _blob_schluessel(blob)
    except Exception:  # noqa: BLE001
        schluessel = None
    if schluessel is not None and schluessel == _MERK_SCHLUESSEL:
        return _MERK_ERGEBNIS

    nach_schluessel: Dict[Tuple[int, int], Dict[str, Feld]] = {}
    nach_anker: Dict[int, Dict[str, Feld]] = {}
    for felder in _lies_datensaetze(blob):
        # NICHT 'schluessel' nennen - so hiess oben der Schluessel des
        # Zwischenspeichers, und die Schleife hat ihn ueberschrieben. Gemerkt
        # wurde dann die itemNo des letzten Datensatzes statt der Pruefsumme
        # des Spielstands, und der Zwischenspeicher griff nie.
        itemschluessel = (felder["_itemKey"].wert, felder["_itemNo"].wert)
        if None not in itemschluessel:
            nach_schluessel[itemschluessel] = felder
        itemno = felder["_itemNo"]
        if itemno.vorhanden:
            nach_anker[itemno.start - ANKER_VERSATZ] = felder

    if schluessel is not None:
        _MERK_SCHLUESSEL, _MERK_ERGEBNIS = schluessel, (nach_schluessel, nach_anker)
    return nach_schluessel, nach_anker


def baue_index(blob: bytes | bytearray) -> Dict[Tuple[int, int], Dict[str, Feld]]:
    """Nur die Zuordnung nach (itemKey, itemNo) - fuer die Phantomerkennung."""
    return baue_indizes(blob)[0]



def feld_position(index, item_key: int, item_no: int, feldname: str) -> Optional[Tuple[int, int]]:
    """Byte-Position eines Feldes, oder None wenn es im Datensatz fehlt.

    Der Schreibweg fragt hier nach, bevor er etwas veraendert. Kommt None
    zurueck, existiert das Feld in diesem Datensatz nicht — dann darf nicht
    geschrieben werden, sonst landet der Wert in einem anderen Feld.
    """
    felder = index.get((item_key, item_no))
    if not felder:
        return None
    feld = felder.get(feldname)
    if feld is None or not feld.verwendbar:
        return None
    return (feld.start, feld.ende)


# -- Fehltreffer aussortieren ------------------------------------------------
#
# Die Bytemustersuche akzeptiert Stapel bis 9*10^18 und beliebige Slotnummern.
# Dadurch findet sie zufaellige Bytefolgen, die ihrem Muster entsprechen, und
# meldet sie als Items. Gemessen an sieben Spielstaenden:
#
#   nicht im Schema-Index: 114 / 115 / 126 / 2 Stueck
#   davon mit Stapel ueber 10 Mio: ALLE
#   im Schema-Index, Stapel ueber 10 Mio: KEINES
#   groesster echter Stapel: 8.951.308 (mit Stack-Mods)
#
# Die Trennung ist also vollstaendig. Trotzdem wird hier nur aussortiert, was
# BEIDES ist - nicht im Schema UND offensichtlich unplausibel. Ein echtes Item,
# das der Schema-Gang aus irgendeinem Grund nicht erreicht, bleibt dadurch
# sichtbar. Lieber ein Phantom zuviel als ein echtes Item zuwenig.

PLAUSIBLER_STAPEL = 9_999_999
PLAUSIBLE_SLOTNUMMER = 255


def ist_phantom(item, index) -> bool:
    """Fehltreffer der Bytemustersuche: nicht im Schema UND unplausible Werte."""
    if (item.item_key, item.item_no) in index:
        return False
    return (item.stack_count > PLAUSIBLER_STAPEL
            or item.slot_no > PLAUSIBLE_SLOTNUMMER)


def entferne_phantome(items, index) -> Tuple[list, list]:
    """Teilt die Itemliste in echte Items und Fehltreffer.

    Ohne Schema-Index wird nichts aussortiert - dann fehlt die Grundlage fuer
    die Entscheidung, und eine Vermutung ist kein Grund, etwas zu verstecken.
    """
    if not index:
        return list(items), []
    echt, phantome = [], []
    for it in items:
        (phantome if ist_phantom(it, index) else echt).append(it)
    if phantome:
        log.info("Dropped %d false hits of the byte-pattern scan (of %d)",
                 len(phantome), len(items))
    return echt, phantome


# ── Items nachbessern, die der PARC-Weg nicht erreicht ──────────────────────

# Felder, die der Schreibweg veraendern kann. Die Groesse steht dabei, weil
# `_require_parc_field_offset` sie prueft - ein Feld, dessen Schema-Eintrag eine
# andere Groesse hat, wird nicht uebernommen.
SCHREIBBARE_FELDER = {
    "_stackCount": 8,
    "_itemNo": 8,
    "_enchantLevel": 2,
    "_endurance": 2,
    "_sharpness": 2,
}


def _wert(felder, name: str) -> int:
    feld = felder.get(name)
    return feld.wert if (feld and feld.gesetzt) else 0


def ergaenze_ohne_parc(items, nach_anker) -> Dict[str, int]:
    """Items, die `enrich_items_with_parc` nicht erreicht hat, aus dem Schema fuellen.

    Betrifft Items hinter einem Zeiger - vor allem Ausruestung. Fuer die zeigte
    das Tool bisher die gepackten Sockelzahlen als "Haltbarkeit" an, und aendern
    liess sich an ihnen nichts.

    Angefasst wird nur, was der PARC-Weg NICHT erreicht hat. Was er geliefert
    hat, bleibt unveraendert - die beiden Wege stimmen dort nachweislich
    ueberein, und zwei Quellen fuer denselben Wert sind eine Fehlerquelle mehr.

    Die Zuordnung laeuft ueber die Byte-Position, nicht ueber die itemNo. Findet
    sich dort kein Datensatz, bleibt das Item wie es war: lieber ein Item ohne
    Schreibrecht als eine Aenderung an der falschen Stelle.
    """
    stat = {"ergaenzt": 0, "ohne_datensatz": 0, "werte_korrigiert": 0,
            "schreibbar_geworden": 0}
    if not nach_anker:
        return stat

    for it in items:
        if getattr(it, "parc_parsed", False) and it.field_offsets:
            continue
        felder = nach_anker.get(it.offset)
        if felder is None:
            stat["ohne_datensatz"] += 1
            continue
        stat["ergaenzt"] += 1

        neu_schaerfe = _wert(felder, "_sharpness")
        neu_haltbar = _wert(felder, "_endurance")
        if neu_schaerfe != it.sharpness or neu_haltbar != it.endurance:
            stat["werte_korrigiert"] += 1
        it.sharpness = neu_schaerfe
        it.endurance = neu_haltbar

        # Sockelzahlen getrennt mitgeben, statt sie wie die Bytemustersuche in
        # die Haltbarkeit zu packen.
        setattr(it, "max_socket_count", _wert(felder, "_maxSocketCount"))
        setattr(it, "valid_socket_count", _wert(felder, "_validSocketCount"))

        verzauberung = felder.get("_enchantLevel")
        if verzauberung and verzauberung.vorhanden:
            it.enchant_level = verzauberung.wert
            it.has_enchant = verzauberung.wert != NICHT_GESETZT_U16

        positionen = {}
        for name, groesse in SCHREIBBARE_FELDER.items():
            feld = felder.get(name)
            if feld and feld.verwendbar and feld.ende - feld.start == groesse:
                positionen[name] = feld.start
        if positionen:
            enden = [f.ende for f in felder.values() if f.verwendbar]
            positionen["_record_end"] = max(enden) if enden else 0
            it.field_offsets = positionen
            # Die Positionen stammen aus dem Schema des Spielstands - genau die
            # Bedingung, die `_require_parc_field_offset` sicherstellen soll.
            it.parc_parsed = True
            setattr(it, "positionsquelle", "schema_index")
            stat["schreibbar_geworden"] += 1

    if stat["ergaenzt"]:
        log.info("Filled in %d items from the schema (%d values corrected, "
                 "%d of them now editable), %d without a matching record",
                 stat["ergaenzt"], stat["werte_korrigiert"],
                 stat["schreibbar_geworden"], stat["ohne_datensatz"])
    return stat
