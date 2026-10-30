"""Datenmodell der Bühne: JSON-Pointer (RFC 6901), Abbildung Werkzeugergebnis → Datenmodell mit Formatierern,
Ergebnisse parsen, Signaturen (zum Wiedererkennen einer passenden Vorlage) und Standardvorlagen ohne Modell."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

_ZAUN = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_LISTEN_SCHLUESSEL = ("items", "eintraege", "entries", "results", "data", "daten", "list", "liste", "rows", "zeilen", "objekte", "entities")


# ---------------------------------------------------------------- JSON-Pointer
def _teile(pfad: str) -> list[str]:
    if pfad in ("", "/"):
        return []
    if not pfad.startswith("/"):
        pfad = "/" + pfad
    return [t.replace("~1", "/").replace("~0", "~") for t in pfad.split("/")[1:]]


def json_pointer_holen(obj: Any, pfad: str) -> Any:
    aktuell = obj
    for teil in _teile(pfad):
        if isinstance(aktuell, dict):
            if teil not in aktuell:
                return None
            aktuell = aktuell[teil]
        elif isinstance(aktuell, list):
            try:
                aktuell = aktuell[int(teil)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return aktuell


def json_pointer_setzen(obj: Any, pfad: str, wert: Any) -> Any:
    """Setzt ``wert`` unter ``pfad`` (legt Objekte an); ``/`` ersetzt das Ganze. Gibt das (neue) Objekt zurück."""
    teile = _teile(pfad)
    if not teile:
        return wert
    aktuell = obj
    for i, teil in enumerate(teile):
        letzter = i == len(teile) - 1
        if isinstance(aktuell, list):
            if teil == "-":
                if letzter:
                    aktuell.append(wert)
                    return obj
                neu: Any = {}
                aktuell.append(neu)
                aktuell = neu
                continue
            index = int(teil)
            while len(aktuell) <= index:
                aktuell.append(None)
            if letzter:
                aktuell[index] = wert
                return obj
            if not isinstance(aktuell[index], (dict, list)):
                aktuell[index] = {}
            aktuell = aktuell[index]
        else:
            if not isinstance(aktuell, dict):
                return obj
            if letzter:
                aktuell[teil] = wert
                return obj
            if not isinstance(aktuell.get(teil), (dict, list)):
                aktuell[teil] = {}
            aktuell = aktuell[teil]
    return obj


# ---------------------------------------------------------------- Formatierer
_DATUMSFORMATE = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f")


def _datum(wert: Any) -> Any:
    if not isinstance(wert, str):
        return wert
    text = wert.strip()
    for fmt in _DATUMSFORMATE:
        try:
            d = datetime.strptime(text.replace("Z", "+0000") if fmt.endswith("%z") else text, fmt)
            return d.replace(tzinfo=None).isoformat(timespec="seconds")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError:
        return wert


def _zahl_text(wert: float, nachkommastellen: int) -> str:
    text = f"{wert:,.{nachkommastellen}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _formatieren(wert: Any, formatierer: str) -> Any:
    name, _, arg = formatierer.partition(":")
    if name == "datum":
        return _datum(wert)
    if name == "waehrung":
        try:
            symbol = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}.get(arg.upper() or "EUR", arg.upper())
            return f"{_zahl_text(float(wert), 2)}\xa0{symbol}"
        except (TypeError, ValueError):
            return wert
    if name == "zahl":
        try:
            return _zahl_text(float(wert), int(arg or 0))
        except (TypeError, ValueError):
            return wert
    if name == "zeilen":
        return spalten_zu_zeilen(wert)
    return wert


def spalten_zu_zeilen(wert: Any) -> Any:
    """Spaltenweise Daten ``{"time": [...], "temp": [...]}`` → Liste von Einträgen ``[{"time": …, "temp": …}, …]``
    (Länge der längsten Liste; Skalare werden in jede Zeile übernommen). Listen bleiben, wie sie sind."""
    if not isinstance(wert, dict):
        return wert
    listen = {k: v for k, v in wert.items() if isinstance(v, list)}
    if not listen:
        return wert
    laenge = max(len(v) for v in listen.values())
    zeilen = []
    for i in range(laenge):
        zeile = {k: (v[i] if i < len(v) else None) for k, v in listen.items()}
        zeile.update({k: v for k, v in wert.items() if not isinstance(v, (list, dict))})
        zeilen.append(zeile)
    return zeilen


def abbildung_anwenden(abbildung: dict[str, str] | None, ergebnis: Any) -> Any:
    """Ziel-Pointer → Quell-Pointer (optional ``|formatierer[:arg]``). Ohne Abbildung wird das Ergebnis selbst zum
    Datenmodell; Listen landen unter ``/eintraege``, damit das Modell ein Objekt bleibt."""
    if not abbildung:
        return {"eintraege": ergebnis} if isinstance(ergebnis, list) else ergebnis
    modell: Any = {}
    for ziel, quelle in abbildung.items():
        quelle_pfad, _, formatierer = str(quelle).partition("|")
        wert = json_pointer_holen(ergebnis, quelle_pfad)
        if formatierer:
            wert = _formatieren(wert, formatierer)
        if ziel in ("", "/"):
            if isinstance(wert, dict):
                modell = {**wert, **modell} if isinstance(modell, dict) else wert
            elif isinstance(wert, list):
                modell = {"eintraege": wert}
            else:
                modell = {"wert": wert}
            continue
        modell = json_pointer_setzen(modell, ziel, wert)
    return modell


def _hat_werte(wert: Any) -> bool:
    if isinstance(wert, dict):
        return any(_hat_werte(v) for v in wert.values())
    if isinstance(wert, list):
        return any(_hat_werte(v) for v in wert)
    return wert is not None and wert != ""


def abbildung_greift(abbildung: dict[str, str] | None, ergebnis: Any) -> bool:
    """Passt die Abbildung zur Form des Ergebnisses? Ja, wenn mindestens ein Quellpfad im Ergebnis etwas findet – auch
    eine leere Liste (die Leere ist dann echt und darf angezeigt werden). Ohne Abbildung oder bei leerem Ergebnis ja.
    Nein heißt: anderes Format (z. B. Text statt JSON, andere Schlüssel)."""
    if not abbildung or not _hat_werte(ergebnis):
        return True
    for quelle in abbildung.values():
        pfad = str(quelle).partition("|")[0].strip()
        if pfad in ("", "/") or json_pointer_holen(ergebnis, pfad) is not None:
            return True
    return False


FEHLER_PRAEFIXE = ("fehler", "error", "nicht ausgeführt", "unbekanntes werkzeug", "http 4", "http 5", "timeout", "zeitüberschreitung", "mcp-fehler", "dienst nicht erreichbar", "service unavailable")


def ist_nur_text(daten: Any) -> bool:
    return isinstance(daten, dict) and set(daten) == {"text"}


def ist_fehlertext(daten: Any) -> bool:
    """Werkzeugergebnis, das nur eine Fehlermeldung ist (statt Daten) – darf nie zu einer Vorlage werden."""
    return ist_nur_text(daten) and str(daten["text"]).strip().lower().startswith(FEHLER_PRAEFIXE)


# ---------------------------------------------------------------- Ergebnisse
def _markdown_tabelle(text: str) -> list[dict[str, str]] | None:
    zeilen = [z.strip() for z in text.strip().splitlines() if z.strip().startswith("|")]
    if len(zeilen) < 3 or not re.match(r"^\|[\s:|-]+\|$", zeilen[1]):
        return None
    kopf = [z.strip() for z in zeilen[0].strip("|").split("|")]
    eintraege = []
    for zeile in zeilen[2:]:
        werte = [z.strip() for z in zeile.strip("|").split("|")]
        eintraege.append({k: (werte[i] if i < len(werte) else "") for i, k in enumerate(kopf)})
    return eintraege


_PUNKT = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.*)$")
_PAAR = re.compile(r"^\s*([A-Za-zÄÖÜäöüß][\w ÄÖÜäöüß/().-]{0,40}?)\s*:\s+(.+?)\s*$")


def _text_eintraege(text: str) -> list[dict[str, str]] | None:
    """Listenartiger Text → Einträge: Blöcke (Aufzählung/Nummerierung oder Leerzeilen) mit ``Schlüssel: Wert``-Zeilen
    (mehrere Paare je Zeile durch ``|`` getrennt; eine erste Zeile ohne Paar wird ``titel``). Erst ab zwei Einträgen
    mit mindestens zwei Feldern und gemeinsamen Schlüsseln; sonst bleibt es Text."""
    bloecke: list[list[str]] = []
    aktuell: list[str] = []
    for zeile in text.strip().splitlines():
        if not zeile.strip():
            if aktuell:
                bloecke.append(aktuell)
            aktuell = []
            continue
        punkt = _PUNKT.match(zeile)
        if punkt:
            if aktuell:
                bloecke.append(aktuell)
            aktuell = [punkt.group(1)]
        else:
            aktuell.append(zeile)
    if aktuell:
        bloecke.append(aktuell)
    eintraege: list[dict[str, str]] = []
    for block in bloecke:
        eintrag: dict[str, str] = {}
        for i, zeile in enumerate(block):
            teile = [t.replace("**", "").replace("__", "") for t in zeile.split(" | ")]
            paare = [m for m in (_PAAR.match(t) for t in teile) if m]
            for m in paare:
                eintrag.setdefault(m.group(1).strip(), m.group(2).strip())
            if not paare and i == 0 and zeile.strip():
                eintrag.setdefault("titel", zeile.strip().strip("*_"))
        if len(eintrag) >= 2:
            eintraege.append(eintrag)
    if len(eintraege) < 2:
        return None
    haeufigkeit: dict[str, int] = {}
    for e in eintraege:
        for k in e:
            haeufigkeit[k] = haeufigkeit.get(k, 0) + 1
    if not any(n >= max(2, len(eintraege) // 2) for n in haeufigkeit.values()):
        return None
    return eintraege


def ergebnis_parsen(ergebnis: Any) -> Any:
    """Werkzeugergebnis → JSON-Daten: JSON (auch in ```-Zäunen), Markdown-Tabelle oder listenartiger Text
    (Aufzählung mit ``Schlüssel: Wert``) → ``eintraege`` + ``text``, sonst ``text``."""
    if not isinstance(ergebnis, str):
        return ergebnis
    text = ergebnis.strip()
    kandidaten = [m.group(1) for m in _ZAUN.finditer(text)] + [text]
    # JSON hinter einem kurzen Präfix (z. B. „HTTP 200“ der REST-Werkzeuge oder „Ergebnis:“)
    start = min((i for i in (text.find("{"), text.find("[")) if 0 < i <= 160), default=-1)
    if start > 0:
        kandidaten.append(text[start:])
    for k in kandidaten:
        k = k.strip()
        if k[:1] in "{[":
            try:
                return json.loads(k)
            except ValueError:
                continue
    eintraege = _markdown_tabelle(text) or _text_eintraege(text)
    if eintraege is not None:
        return {"eintraege": eintraege, "text": ergebnis}
    return {"text": ergebnis}


def _groesste_liste(daten: Any) -> tuple[str, list[Any]] | None:
    """(Pfad, Liste) der größten Objektliste in einem Ergebnis (oberste Ebene oder bekannte Schlüssel)."""
    if isinstance(daten, list):
        return "/", daten
    if not isinstance(daten, dict):
        return None
    beste: tuple[str, list[Any]] | None = None
    for schluessel, wert in daten.items():
        if not (isinstance(wert, list) and wert and all(isinstance(e, dict) for e in wert)):
            continue
        if beste is None or len(wert) > len(beste[1]) or (schluessel in _LISTEN_SCHLUESSEL and len(wert) == len(beste[1])):
            beste = (f"/{schluessel}", wert)
    return beste


def signatur(werkzeug: str, ergebnis: Any) -> dict[str, Any]:
    """Wiedererkennung: Werkzeugname, Schlüssel der obersten Ebene, Schlüssel eines Listeneintrags."""
    daten = ergebnis_parsen(ergebnis)
    schluessel = sorted(daten.keys()) if isinstance(daten, dict) else []
    liste = _groesste_liste(daten)
    eintrag = sorted(liste[1][0].keys()) if liste and liste[1] and isinstance(liste[1][0], dict) else []
    return {"werkzeug": werkzeug, "schluessel": [str(s) for s in schluessel], "eintrag": [str(s) for s in eintrag]}


# ---------------------------------------------------------------- Standardvorlage (ohne Modell)
def _titel_aus(schluessel: str) -> str:
    return schluessel.replace("_", " ").strip().capitalize() or schluessel


def _spaltenformat(schluessel: str, wert: Any) -> str | None:
    name = schluessel.lower()
    if any(t in name for t in ("preis", "betrag", "kosten", "umsatz", "miete", "price", "amount")):
        return "waehrung"
    if any(t in name for t in ("datum", "zeit", "date", "time", "erstellt", "aktualisiert", "created", "updated")):
        return "datum"
    if any(t in name for t in ("status", "zustand", "state")):
        return "badge"
    if isinstance(wert, (int, float)) and not isinstance(wert, bool):
        return "zahl"
    return None


def standardvorlage(werkzeug: str, ergebnis: Any, titel: str) -> dict[str, Any]:
    """Deterministische Vorlage: Objektliste → Tabelle, flaches Objekt → Kennzahlen/Zeilen, Text → Markdown."""
    daten = ergebnis_parsen(ergebnis)
    kopf = {"id": "titel", "component": "Text", "text": titel, "variant": "h2"}
    liste = _groesste_liste(daten)
    if liste is not None and liste[1]:
        pfad, eintraege = liste
        erster = eintraege[0]
        spalten = []
        for schluessel, wert in list(erster.items())[:8]:
            if isinstance(wert, (dict, list)):
                continue
            spalte: dict[str, Any] = {"titel": _titel_aus(str(schluessel)), "path": str(schluessel)}
            fmt = _spaltenformat(str(schluessel), wert)
            if fmt:
                spalte["format"] = fmt
            spalten.append(spalte)
        komponenten = [
            {"id": "root", "component": "Column", "children": ["titel", "anzahl", "tabelle"], "gap": 12},
            kopf,
            {"id": "anzahl", "component": "Text", "text": {"call": "pluralize", "args": {"count": {"path": "/anzahl"}, "one": "Eintrag", "other": "Einträge"}}, "variant": "caption", "ton": "dezent"},
            {"id": "tabelle", "component": "Tabelle", "zeilen": {"path": "/eintraege"}, "spalten": spalten},
        ]
        abbildung = {"/eintraege": pfad}
        return {
            "name": titel,
            "zweck": f"Tabelle aus dem Ergebnis von {werkzeug} (Standardvorlage)",
            "komponenten": komponenten,
            "abbildung": abbildung,
            "datenschema": {"type": "object", "properties": {"eintraege": {"type": "array"}, "anzahl": {"type": "integer"}}},
            "anzahl_pfad": pfad,
        }
    if isinstance(daten, dict) and daten and set(daten) != {"text"}:
        kinder = ["titel"]
        komponenten: list[dict[str, Any]] = [kopf]
        for i, (schluessel, wert) in enumerate(list(daten.items())[:12]):
            if isinstance(wert, (dict, list)):
                continue
            kennung = f"f{i}"
            if isinstance(wert, (int, float)) and not isinstance(wert, bool):
                komponenten.append({"id": kennung, "component": "Kennzahl", "wert": {"path": f"/{schluessel}"}, "label": _titel_aus(str(schluessel))})
            else:
                komponenten.append({"id": kennung, "component": "Row", "children": [f"{kennung}l", f"{kennung}w"], "gap": 8})
                komponenten.append({"id": f"{kennung}l", "component": "Text", "text": _titel_aus(str(schluessel)), "ton": "dezent"})
                komponenten.append({"id": f"{kennung}w", "component": "Text", "text": {"path": f"/{schluessel}"}})
            kinder.append(kennung)
        komponenten.insert(0, {"id": "root", "component": "Column", "children": kinder, "gap": 8})
        return {"name": titel, "zweck": f"Werte aus dem Ergebnis von {werkzeug} (Standardvorlage)", "komponenten": komponenten, "abbildung": {"/": "/"}, "datenschema": {"type": "object"}}
    komponenten = [
        {"id": "root", "component": "Column", "children": ["titel", "text"], "gap": 8},
        kopf,
        {"id": "text", "component": "Text", "text": {"path": "/text"}, "variant": "body"},
    ]
    return {"name": titel, "zweck": f"Text aus {werkzeug} (Standardvorlage)", "komponenten": komponenten, "abbildung": {"/text": "/text"}, "datenschema": {"type": "object", "properties": {"text": {"type": "string"}}}}
