"""Katalog der Bühne (``katalog.json``): Bausteine, Eigenschaften, Limits – laden, prüfen, säubern.

Komponenten bilden eine flache Liste (A2UI): jede hat ``id`` und ``component``; Verweise auf Kinder laufen über
IDs (``children`` als Liste oder als Template ``{"path", "componentId"}``, ``child`` als einzelne ID). Werte sind
Literale, Bindungen ``{"path": "…"}`` oder Funktionsaufrufe ``{"call": "…", "args": {…}}``.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

KATALOG_PFAD = Path(__file__).with_name("katalog.json")
_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_AKTIONSNAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FUNKTIONEN = ("formatString", "formatNumber", "formatCurrency", "formatDate", "pluralize")


@dataclass
class Katalog:
    id: str
    komponenten: dict[str, dict[str, Any]]
    limits: dict[str, int]
    funktionen: dict[str, str]
    beschreibung: str

    def beschreibung_fuer_prompt(self) -> str:
        """Kompakte Beschreibung aller Bausteine mit Eigenschaften und je einem Beispiel (für den Systemprompt)."""
        zeilen = [f"Katalog {self.id}. {self.beschreibung}", ""]
        for gruppe in ("layout", "anzeige", "aktion", "eingabe"):
            zeilen.append(f"## {gruppe}")
            for name, e in self.komponenten.items():
                if e.get("gruppe") != gruppe:
                    continue
                eigenschaften = ", ".join(f"{k}: {v}" for k, v in e.get("eigenschaften", {}).items())
                zeilen.append(f"- {name}: {e.get('beschreibung', '')} — Eigenschaften: {eigenschaften}")
                zeilen.append(f"  Beispiel: {json.dumps(e.get('beispiel', {}), ensure_ascii=False)}")
        zeilen.append("")
        zeilen.append("## Funktionen")
        for name, text in self.funktionen.items():
            zeilen.append(f"- {name}: {text}")
        zeilen.append("")
        zeilen.append(
            f"Limits: höchstens {self.limits.get('komponenten')} Komponenten, Tiefe {self.limits.get('tiefe')}, "
            f"Listen bis {self.limits.get('listenEintraege')} Einträge."
        )
        return "\n".join(zeilen)


@lru_cache(maxsize=4)
def katalog_laden(pfad: str | None = None) -> Katalog:
    daten = json.loads(Path(pfad or KATALOG_PFAD).read_text(encoding="utf-8"))
    return Katalog(
        id=str(daten.get("catalogId") or daten.get("$id") or "jarvis:buehne/1"),
        komponenten=dict(daten.get("komponenten") or {}),
        limits={k: int(v) for k, v in (daten.get("limits") or {}).items()},
        funktionen=dict(daten.get("funktionen") or {}),
        beschreibung=str(daten.get("beschreibung") or ""),
    )


# ---------------------------------------------------------------- Prüfung
def _typ(beschreibung: str) -> tuple[str, list[str]]:
    """Typkürzel aus der Eigenschaftsbeschreibung: „wert (Zahl)“ → ("wert", []), „a|b|c“ → ("enum", [a, b, c])."""
    kopf = beschreibung.split("(")[0].strip()
    if "|" in kopf:
        return "enum", [t.strip() for t in kopf.split("|")]
    return kopf, []


def _ist_wert(v: Any) -> str | None:
    """None = gültig, sonst Fehlertext."""
    if isinstance(v, (str, int, float, bool)):
        return None
    if isinstance(v, dict):
        if set(v) == {"path"} and isinstance(v["path"], str):
            return None
        if set(v) == {"call", "args"}:
            if v["call"] not in _FUNKTIONEN:
                return f"unbekannte Funktion „{v['call']}“"
            return None if isinstance(v["args"], dict) else "args muss ein Objekt sein"
        return "Bindung braucht genau {\"path\": …} oder {\"call\": …, \"args\": {…}}"
    return "Wert muss Literal, Bindung oder Funktionsaufruf sein"


def _ist_bindung(v: Any) -> str | None:
    if isinstance(v, dict) and set(v) == {"path"} and isinstance(v["path"], str):
        return None
    return "muss eine Bindung {\"path\": …} sein"


def _ist_aktion(v: Any) -> str | None:
    if not isinstance(v, dict) or len(v) != 1 or not (set(v) <= {"event", "functionCall"}):
        return "Aktion braucht genau event oder functionCall"
    if "event" in v:
        e = v["event"]
        if not isinstance(e, dict) or not isinstance(e.get("name"), str) or not _AKTIONSNAME.match(e["name"]):
            return "Aktionsname muss klein geschrieben sein (a–z, 0–9, _)"
        kontext = e.get("context", {})
        if not isinstance(kontext, dict):
            return "context muss ein Objekt sein"
        for k, w in kontext.items():
            f = _ist_wert(w)
            if f:
                return f"context.{k}: {f}"
        return None
    fc = v["functionCall"]
    if not isinstance(fc, dict) or fc.get("call") != "openUrl" or not isinstance(fc.get("args"), dict):
        return "functionCall erlaubt nur openUrl mit args"
    url = fc["args"].get("url")
    if isinstance(url, str) and not url.startswith("https://"):
        return "openUrl erlaubt nur https"
    return None


def _eigenschaft_pruefen(name: str, typ: str, optionen: list[str], v: Any) -> str | None:
    if typ == "wert":
        return _ist_wert(v)
    if typ == "bindung":
        return _ist_bindung(v)
    if typ == "aktion":
        return _ist_aktion(v)
    if typ == "kinder":
        if isinstance(v, list) and all(isinstance(k, str) for k in v):
            return None
        if isinstance(v, dict) and set(v) == {"path", "componentId"} and isinstance(v["path"], str) and isinstance(v["componentId"], str):
            return None
        return "children muss eine ID-Liste oder {\"path\", \"componentId\"} sein"
    if typ == "id":
        return None if isinstance(v, str) else "muss eine ID sein"
    if typ == "enum":
        if isinstance(v, bool):
            return f"{name} muss eins von {', '.join(optionen)} sein"
        return None if str(v) in optionen else f"{name} muss eins von {', '.join(optionen)} sein"
    if typ == "string":
        return None if isinstance(v, str) else "muss Text sein"
    if typ == "number":
        return None if isinstance(v, (int, float)) and not isinstance(v, bool) else "muss eine Zahl sein"
    if typ == "boolean":
        return None if isinstance(v, bool) else "muss true/false sein"
    if typ in ("string[]", "id[]"):
        return None if isinstance(v, list) and all(isinstance(k, str) for k in v) else "muss eine Textliste sein"
    if typ == "object[]":
        return None if isinstance(v, list) and all(isinstance(k, dict) for k in v) else "muss eine Objektliste sein"
    if typ == "object":
        return None if isinstance(v, dict) else "muss ein Objekt sein"
    return None


def komponenten_pruefen(komponenten: Any, katalog: Katalog | None = None) -> list[str]:
    """Prüft eine flache Komponentenliste; leere Liste = gültig, sonst verständliche Fehlertexte."""
    k = katalog or katalog_laden()
    fehler: list[str] = []
    if not isinstance(komponenten, list) or not komponenten:
        return ["Komponenten müssen eine nicht leere Liste sein"]
    if len(komponenten) > k.limits.get("komponenten", 300):
        fehler.append(f"zu viele Komponenten ({len(komponenten)} > {k.limits.get('komponenten', 300)})")
    nach_id: dict[str, dict[str, Any]] = {}
    for nr, komp in enumerate(komponenten):
        if not isinstance(komp, dict):
            fehler.append(f"Eintrag {nr} ist kein Objekt")
            continue
        kennung = komp.get("id")
        if not isinstance(kennung, str) or not _ID.match(kennung):
            fehler.append(f"Eintrag {nr}: ungültige oder fehlende id")
            continue
        if kennung in nach_id:
            fehler.append(f"id „{kennung}“ ist doppelt")
            continue
        nach_id[kennung] = komp
        art = komp.get("component")
        if art not in k.komponenten:
            fehler.append(f"„{kennung}“: unbekannte Komponente „{art}“")
            continue
        definition = k.komponenten[art].get("eigenschaften", {})
        for name, v in komp.items():
            if name in ("id", "component"):
                continue
            if name not in definition:
                fehler.append(f"„{kennung}“ ({art}): unbekannte Eigenschaft „{name}“")
                continue
            typ, optionen = _typ(str(definition[name]))
            f = _eigenschaft_pruefen(name, typ, optionen, v)
            if f:
                fehler.append(f"„{kennung}“ ({art}).{name}: {f}")
        if art == "Image" and isinstance(komp.get("url"), str) and not (
            komp["url"].startswith("https://") or komp["url"].startswith("data:image/")
        ):
            fehler.append(f"„{kennung}“ (Image): url erlaubt nur https oder data:image")
        if art == "Tabs":
            titel, kinder = komp.get("titles"), komp.get("children")
            if isinstance(titel, list) and isinstance(kinder, list) and len(titel) != len(kinder):
                fehler.append(f"„{kennung}“ (Tabs): titles und children müssen gleich lang sein")
    if "root" not in nach_id:
        fehler.append("es fehlt die Komponente mit id „root“")
        return fehler
    # Verweise und Zyklen/Tiefe
    for kennung, komp in nach_id.items():
        for kind in _kinder_ids(komp):
            if kind not in nach_id:
                fehler.append(f"„{kennung}“ verweist auf unbekannte Komponente „{kind}“")
    max_tiefe = k.limits.get("tiefe", 12)

    def ablaufen(kennung: str, pfad: tuple[str, ...]) -> None:
        if kennung in pfad:
            fehler.append(f"Zyklus über „{kennung}“")
            return
        if len(pfad) >= max_tiefe:
            fehler.append(f"Tiefe über {max_tiefe} bei „{kennung}“")
            return
        komp = nach_id.get(kennung)
        if komp is None:
            return
        for kind in _kinder_ids(komp):
            ablaufen(kind, (*pfad, kennung))

    ablaufen("root", ())
    # Fehler eindeutig halten (ein Zyklus wird sonst mehrfach gemeldet)
    eindeutig: list[str] = []
    for f in fehler:
        if f not in eindeutig:
            eindeutig.append(f)
    return eindeutig


def _kinder_ids(komp: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    kinder = komp.get("children")
    if isinstance(kinder, list):
        ids.extend(k for k in kinder if isinstance(k, str))
    elif isinstance(kinder, dict) and isinstance(kinder.get("componentId"), str):
        ids.append(kinder["componentId"])
    kind = komp.get("child")
    if isinstance(kind, str):
        ids.append(kind)
    return ids


def komponenten_saeubern(komponenten: list[dict[str, Any]], katalog: Katalog | None = None) -> list[dict[str, Any]]:
    """Kopie ohne unbekannte Eigenschaften (das Modell erfindet gern welche); Struktur bleibt."""
    k = katalog or katalog_laden()
    ergebnis: list[dict[str, Any]] = []
    for komp in komponenten:
        if not isinstance(komp, dict):
            continue
        art = komp.get("component")
        erlaubt = set(k.komponenten.get(art, {}).get("eigenschaften", {})) | {"id", "component"}
        ergebnis.append({name: copy.deepcopy(v) for name, v in komp.items() if name in erlaubt})
    return ergebnis
