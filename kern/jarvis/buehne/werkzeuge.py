"""Werkzeuge der Bühne für das Modell: zeigen, Vorlagen ändern/zurück, Daten, Rezepte, Stile, schließen.
Bereich technisch; Rezepte anlegen ist kritisch (dauerhafte Automatisierung mit Werkzeugaufrufen)."""

from __future__ import annotations

import json
from typing import Any

from ..werkzeuge import FunktionsWerkzeug, schema
from .manager import BuehnenFehler, BuehnenManager


def _text(daten: Any) -> str:
    return json.dumps(daten, ensure_ascii=False)


def werkzeuge(manager: BuehnenManager) -> list[FunktionsWerkzeug]:
    async def buehne_zeigen(
        werkzeug: str,
        argumente: dict[str, Any] | None = None,
        titel: str | None = None,
        wunsch: str = "",
        integration: str | None = None,
        vorlage: str | None = None,
    ) -> str:
        if str(werkzeug).startswith("buehne_"):
            raise BuehnenFehler("buehne_zeigen führt Datenwerkzeuge aus, keine Bühnen-Werkzeuge.")
        e = await manager.zeigen(str(werkzeug), argumente or {}, titel=titel, wunsch=wunsch or "", integration=integration, vorlage=vorlage or None)
        if e["neu"]:
            hinweis = "neue Vorlage gebaut" + (" nach deinem Wunsch" if wunsch else "")
        elif e.get("umgebaut"):
            hinweis = "vorhandene Vorlage nach deinem Wunsch umgebaut (neue Version)"
        else:
            hinweis = "vorhandene Vorlage mit den aktuellen Daten befüllt"
        anzahl = f", {e['anzahl']} Einträge" if e.get("anzahl") is not None else ""
        return f"Auf der Bühne gezeigt: „{e['titel']}“ (Fläche {e['surfaceId']}, Vorlage {e['vorlage']}, {hinweis}{anzahl}). Fasse das Ergebnis im Chat nur kurz zusammen."

    async def buehne_vorlage_aendern(vorlage: str, wunsch: str) -> str:
        e = await manager.aendern(vorlage, wunsch)
        return f"Vorlage {e['vorlage']} geändert (Version {e['version']}); die offene Fläche zeigt bereits die neue Darstellung mit den aktuellen Daten – kein Neuladen nötig. Rückgängig mit buehne_vorlage_zurueck."

    async def buehne_vorlage_zurueck(vorlage: str) -> str:
        e = await manager.zurueck(vorlage)
        return f"Vorlage {e['vorlage']} auf Version {e['version']} zurückgesetzt; die offene Fläche zeigt bereits wieder die alte Darstellung."

    async def buehne_daten(surfaceId: str, daten: dict[str, Any] | None = None, path: str = "/", value: Any = None) -> str:  # noqa: N803
        if daten is not None:
            await manager.daten_setzen(surfaceId, daten=daten)
        else:
            await manager.daten_setzen(surfaceId, path=path or "/", value=value)
        return f"Daten der Fläche {surfaceId} aktualisiert."

    async def buehne_neu_laden(surfaceId: str) -> str:  # noqa: N803
        f = await manager.neu_laden(surfaceId)
        daten = f.get("daten") or {}
        anzahl = daten.get("anzahl") if isinstance(daten, dict) else None
        return f"Fläche {surfaceId} neu geladen" + (f" ({anzahl} Einträge)." if anzahl is not None else ".")

    async def buehne_rezept_anlegen(
        vorlage: str,
        aktion: str,
        art: str,
        name: str | None = None,
        werkzeug: str | None = None,
        argument_abbildung: dict[str, Any] | None = None,
        auftrag: str | None = None,
        risiko: str = "aendern",
        bestaetigung: str | None = None,
    ) -> str:
        r = manager.rezept_anlegen(vorlage, aktion, art, name, werkzeug, argument_abbildung, auftrag, risiko, bestaetigung)
        return f"Rezept {r['id']} für Aktion „{aktion}“ der Vorlage {vorlage} angelegt."

    async def buehne_stil_ableiten(name: str, art: str, wert: str) -> str:
        if art not in ("url", "klassen", "datei"):
            raise BuehnenFehler("art muss url, klassen oder datei sein.")
        stil = await manager.stil_ableiten(name, {"art": art, "wert": wert})
        return f"Stil {stil['id']} („{stil['name']}“) angelegt: " + _text(stil["werte"])

    async def buehne_stil_aendern(
        stil: str,
        farben: dict[str, str] | None = None,
        schema_: str | None = None,
        rundung: int | None = None,
        abstand: int | None = None,
        dichte: str | None = None,
        schatten: str | None = None,
        schrift_familie: str | None = None,
        vorlieben: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> str:
        werte: dict[str, Any] = {}
        if farben:
            werte["farben"] = farben
        for feld, wert in (("schema", schema_), ("rundung", rundung), ("abstand", abstand), ("dichte", dichte), ("schatten", schatten)):
            if wert is not None:
                werte[feld] = wert
        if schrift_familie:
            werte["schrift"] = {"familie": schrift_familie}
        neu = manager.stil_aendern(stil, {"werte": werte, "vorlieben": vorlieben or {}}, name=name)
        return f"Stil {neu['id']} gespeichert: " + _text(neu["werte"]["farben"])

    async def buehne_stil_zuweisen(integration: str, stil: str | None = None) -> str:
        z = manager.stil_zuweisen(integration, stil)
        return "Zuordnung: " + _text(z)

    async def buehne_schliessen(surfaceId: str | None = None) -> str:  # noqa: N803
        g = await manager.schliessen(surfaceId)
        return f"Geschlossen: {', '.join(g) if g else 'nichts offen'}."

    def wz(fn: Any, name: str, beschreibung: str, json_schema: dict[str, Any], risiko: str, **kw: Any) -> FunktionsWerkzeug:
        return FunktionsWerkzeug(fn, name, beschreibung, json_schema, risiko, quelle="eingebaut", bereich="technisch", **kw)  # type: ignore[arg-type]

    async def stil_aendern_aufruf(**a: Any) -> str:  # „schema“ kollidiert mit dem Schema-Helfer
        if "schema" in a:
            a["schema_"] = a.pop("schema")
        return await buehne_stil_aendern(**a)

    return [
        wz(
            buehne_zeigen,
            "buehne_zeigen",
            "Führt ein Datenwerkzeug aus und zeigt das Ergebnis strukturiert auf der Bühne über dem Chat (Listen, "
            "Datensätze, Mails, Wetter, Vergleiche). Jede Sicht (z. B. Immobilien, Makler, Mails) hat ihre eigene Vorlage "
            "und Fläche: beim ersten Mal wird sie gebaut, danach nur mit Daten befüllt. Der Titel bestimmt die Sicht – "
            "gleicher Titel = gleiche Vorlage, anderer Titel = neue Vorlage. Statt des Werkzeugs selbst aufrufen, wenn der "
            "Nutzer eine Übersicht/Anzeige möchte. Filtern/Sortieren über die Argumente des Werkzeugs, nicht über den Wunsch.",
            schema(
                {
                    "werkzeug": {"type": "string", "description": "Name des Werkzeugs, das die Daten liefert"},
                    "argumente": {"type": "object", "description": "Argumente für dieses Werkzeug"},
                    "titel": {"type": "string", "description": "Titel der Sicht/Fläche, z. B. „Immobilien“ oder „Makler“ (bestimmt die Vorlage)"},
                    "wunsch": {"type": "string", "description": "Gestaltungswunsch (z. B. „als Kacheln mit Bild“); bei vorhandener Vorlage wird sie danach umgebaut"},
                    "integration": {"type": "string", "description": "Kennung der Integration (für den Stil)"},
                    "vorlage": {"type": "string", "description": "Kennung einer vorhandenen Vorlage, wenn genau diese Sicht gemeint ist (sonst entscheidet der Titel)"},
                },
                ["werkzeug"],
            ),
            "lesen",
        ),
        wz(
            buehne_vorlage_aendern,
            "buehne_vorlage_aendern",
            "Baut eine bestehende Bühnen-Vorlage nach Wunsch um (neue Version, alte bleibt für Rückgängig).",
            schema({"vorlage": {"type": "string"}, "wunsch": {"type": "string"}}, ["vorlage", "wunsch"]),
            "aendern",
        ),
        wz(
            buehne_vorlage_zurueck,
            "buehne_vorlage_zurueck",
            "Macht die letzte Änderung einer Bühnen-Vorlage rückgängig.",
            schema({"vorlage": {"type": "string"}}, ["vorlage"]),
            "aendern",
        ),
        wz(
            buehne_daten,
            "buehne_daten",
            "Setzt Daten einer offenen Fläche: ganzes Datenmodell (daten) oder einen Wert unter einem JSON-Pointer (path, value).",
            schema({"surfaceId": {"type": "string"}, "daten": {"type": "object"}, "path": {"type": "string"}, "value": {}}, ["surfaceId"]),
            "aendern",
        ),
        wz(
            buehne_neu_laden,
            "buehne_neu_laden",
            "Führt die Datenquelle einer offenen Fläche erneut aus und aktualisiert die Anzeige.",
            schema({"surfaceId": {"type": "string"}}, ["surfaceId"]),
            "lesen",
        ),
        wz(
            buehne_rezept_anlegen,
            "buehne_rezept_anlegen",
            "Hinterlegt dauerhaft, was ein Knopf (Aktion) einer Vorlage tut: art „werkzeug“ (Werkzeug + "
            "argument_abbildung {\"arg\": \"context.feld\"}) oder art „agent“ (Auftrag in Worten mit {feld}-Platzhaltern).",
            schema(
                {
                    "vorlage": {"type": "string"},
                    "aktion": {"type": "string", "description": "Name der Aktion aus der Vorlage"},
                    "art": {"type": "string", "enum": ["werkzeug", "agent"]},
                    "name": {"type": "string"},
                    "werkzeug": {"type": "string"},
                    "argument_abbildung": {"type": "object"},
                    "auftrag": {"type": "string"},
                    "risiko": {"type": "string", "enum": ["lesen", "aendern", "kritisch"]},
                    "bestaetigung": {"type": "string", "description": "Rückfrage vor Ausführung (optional)"},
                },
                ["vorlage", "aktion", "art"],
            ),
            "kritisch",
            grund=lambda a: f"Rezept „{a.get('aktion')}“ für Vorlage {a.get('vorlage')} dauerhaft anlegen ({a.get('art')}: {a.get('werkzeug') or a.get('auftrag')})",
        ),
        wz(
            buehne_stil_ableiten,
            "buehne_stil_ableiten",
            "Leitet einen Bühnen-Stil ab: aus einer App-/Webadresse (art url), aus CSS-Klassen (art klassen) oder "
            "Dateiinhalt (art datei). Der Stil kann danach Integrationen zugewiesen werden.",
            schema({"name": {"type": "string"}, "art": {"type": "string", "enum": ["url", "klassen", "datei"]}, "wert": {"type": "string"}}, ["name", "art", "wert"]),
            "aendern",
        ),
        wz(
            stil_aendern_aufruf,
            "buehne_stil_aendern",
            "Ändert Werte eines Bühnen-Stils (Farben als #rrggbb: primaer, akzent, hintergrund, flaeche, text, dezent, ok, "
            "warn, fehler; schema hell/dunkel; rundung; abstand; dichte; schatten; schrift_familie; vorlieben). "
            "Vordefinierte Stile werden als eigene Kopie gespeichert.",
            schema(
                {
                    "stil": {"type": "string"},
                    "farben": {"type": "object"},
                    "schema": {"type": "string", "enum": ["hell", "dunkel"]},
                    "rundung": {"type": "integer"},
                    "abstand": {"type": "integer"},
                    "dichte": {"type": "string", "enum": ["dicht", "normal", "luftig"]},
                    "schatten": {"type": "string", "enum": ["keiner", "weich", "stark"]},
                    "schrift_familie": {"type": "string"},
                    "vorlieben": {"type": "object"},
                    "name": {"type": "string"},
                },
                ["stil"],
            ),
            "aendern",
        ),
        wz(
            buehne_stil_zuweisen,
            "buehne_stil_zuweisen",
            "Weist einer Integration (Kennung) einen Bühnen-Stil zu; ohne stil wird die Zuordnung entfernt.",
            schema({"integration": {"type": "string"}, "stil": {"type": "string"}}, ["integration"]),
            "aendern",
        ),
        wz(
            buehne_schliessen,
            "buehne_schliessen",
            "Schließt eine Fläche der Bühne (surfaceId) oder alle.",
            schema({"surfaceId": {"type": "string"}}),
            "lesen",
        ),
    ]
