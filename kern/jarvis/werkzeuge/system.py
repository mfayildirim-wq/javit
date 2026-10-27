"""System-Werkzeuge: Integrationen verwalten, Gedächtnis, Modellwechsel, Uhrzeit, Timer.

Diese Werkzeuge brauchen den Anwendungskontext (`Jarvis`-Objekt aus anwendung.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from . import FunktionsWerkzeug, Werkzeug, WerkzeugFehler, schema

if TYPE_CHECKING:  # pragma: no cover
    from ..anwendung import Jarvis

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
    "Oktober", "November", "Dezember",
]


def deutsches_datum(zeitpunkt: datetime | None = None, mit_uhrzeit: bool = True) -> str:
    z = zeitpunkt or datetime.now().astimezone()
    text = f"{WOCHENTAGE[z.weekday()]}, {z.day}. {MONATE[z.month - 1]} {z.year}"
    if mit_uhrzeit:
        text += f", {z:%H:%M} Uhr"
    return text


def _dauer_text(sekunden: float) -> str:
    sekunden = int(round(sekunden))
    h, rest = divmod(sekunden, 3600)
    m, s = divmod(rest, 60)
    teile = []
    if h:
        teile.append(f"{h} Stunde{'n' if h != 1 else ''}")
    if m:
        teile.append(f"{m} Minute{'n' if m != 1 else ''}")
    if s or not teile:
        teile.append(f"{s} Sekunde{'n' if s != 1 else ''}")
    return " und ".join(teile) if len(teile) <= 2 else ", ".join(teile[:-1]) + " und " + teile[-1]


def werkzeuge(app: Jarvis) -> list[Werkzeug]:
    # ---------------- Integrationen ----------------
    async def integration_hinzufuegen(
        quelle: str, name: str | None = None, werte: dict[str, Any] | None = None
    ) -> str:
        from ..integrationen.manager import FehlendeWerte, IntegrationsFehler

        anfrage: dict[str, Any] = {"quelle": quelle, "werte": werte or {}}
        if name:
            anfrage["name"] = name
        try:
            info = await app.manager.hinzufuegen(anfrage)
        except FehlendeWerte as e:
            details = "; ".join(
                f"{b.titel} ({b.name}{', geheim' if b.geheim else ''})" for b in e.fehlend
            )
            return (
                f"Es fehlen noch Angaben: {details}. {e.hinweis} "
                "Der Nutzer kann sie in der Oberfläche unter „Integration hinzufügen“ eintragen, "
                "per „jarvis add <id>“ im Terminal oder sie dir nennen (dann erneut mit werte aufrufen)."
            ).strip()
        except IntegrationsFehler as e:
            raise WerkzeugFehler(str(e)) from e
        if info["status"] == "verbunden":
            return f"Integration „{info['name']}“ ist verbunden ({info['werkzeuge']} Werkzeuge verfügbar)."
        return f"Integration „{info['name']}“ wurde gespeichert, Status: {info['status']}. {info.get('fehler', '')}".strip()

    async def integrationen_auflisten() -> str:
        liste = app.manager.liste()
        if not liste:
            return "Es sind keine Integrationen installiert."
        return "\n".join(
            f"{i['name']} ({i['id']}, {i['art']}): {i['status']}, {i['werkzeuge']} Werkzeuge"
            + (f" – Fehler: {i['fehler']}" if i.get("fehler") else "")
            for i in liste
        )

    def _einrichtung_text(eintrag: Any) -> str:
        from ..integrationen.einrichtung import einrichtung_stand

        schritte = einrichtung_stand(eintrag)
        if not schritte:
            return ""
        zeilen = []
        for n, s in enumerate(schritte, 1):
            stand = "✓ erledigt" if s["erfuellt"] else ("✗ offen" if s["erfuellt"] is False else "–")
            zeile = f"{n}. {s['titel']} [{stand}]"
            if s.get("text"):
                zeile += f": {s['text']}"
            if s.get("link"):
                zeile += f" Link: {s['link']}"
            if s.get("datei"):
                zeile += f" Datei-Ziel: {s['datei']} (Upload in der Oberfläche: Integrationen → Eintrag → Einrichtung)"
            if s.get("befehl"):
                zeile += f" Befehl: {s['befehl']} (ausführbar mit integration_schritt_ausfuehren, Schritt {n})"
            zeilen.append(zeile)
        return "Einrichtungsschritte:\n" + "\n".join(zeilen)

    async def integration_details(id: str) -> str:  # noqa: A002
        from ..integrationen.manager import IntegrationsFehler

        try:
            d = app.manager.details(id)
        except IntegrationsFehler as e:
            raise WerkzeugFehler(str(e)) from e
        teile = [f"{d['name']} ({d['id']}, {d['art']}): Status {d['status']}, {d['werkzeuge']} Werkzeuge"]
        if d.get("fehler"):
            teile.append(f"Fehler: {d['fehler']}")
        k = d["konfig"]
        if k.get("befehl"):
            teile.append("Befehl: " + " ".join(k["befehl"]))
        if k.get("url"):
            teile.append(f"URL: {k['url']}")
        if d.get("werte"):
            teile.append("Werte: " + ", ".join(f"{n}={w}" for n, w in d["werte"].items()))
        if k.get("umgebung") and not d.get("werte"):
            teile.append("Umgebung: " + ", ".join(f"{n}={w}" for n, w in k["umgebung"].items()))
        if k.get("kopfzeilen"):
            teile.append("Kopfzeilen: " + ", ".join(f"{n}={w}" for n, w in k["kopfzeilen"].items()))
        kat = d.get("katalog")
        if kat:
            if kat.get("hinweis"):
                teile.append(f"Hinweis: {kat['hinweis']}")
            eintrag = app.katalog.holen(kat["id"])
            if eintrag is not None:
                text = _einrichtung_text(eintrag)
                if text:
                    teile.append(text)
        if d.get("protokoll"):
            teile.append("Letzte Protokollzeilen:\n" + "\n".join(d["protokoll"][-8:]))
        return "\n".join(teile)

    async def integration_einrichtung(id: str) -> str:  # noqa: A002
        eintrag = app.katalog.holen(id)
        if eintrag is None and id in app.manager.konfigs and app.manager.konfigs[id].katalog:
            eintrag = app.katalog.holen(app.manager.konfigs[id].katalog or "")
        if eintrag is None:
            raise WerkzeugFehler(f"Kein Katalogeintrag zu „{id}“.")
        text = _einrichtung_text(eintrag)
        if not text:
            return f"{eintrag.name} braucht keine besonderen Einrichtungsschritte. {eintrag.hinweis}".strip()
        offen = [s for s in eintrag.einrichtung if s.datei and not __import__("os").path.isfile(__import__("os").path.expanduser(s.datei))]
        naechster = f"Nächster offener Schritt: {offen[0].titel}." if offen else "Alle prüfbaren Schritte sind erledigt."
        return f"{text}\n{naechster} Führe den Nutzer Schritt für Schritt; frage nach jedem Schritt, ob er erledigt ist."

    async def integration_konfigurieren(id: str, werte: dict[str, Any] | None = None, name: str | None = None) -> str:  # noqa: A002
        from ..integrationen.manager import FehlendeWerte, IntegrationsFehler

        anfrage: dict[str, Any] = {"werte": werte or {}}
        if name:
            anfrage["name"] = name
        try:
            d = await app.manager.aendern(id, anfrage)
        except FehlendeWerte as e:
            return "Es fehlen Angaben: " + "; ".join(f"{b.titel} ({b.name})" for b in e.fehlend)
        except IntegrationsFehler as e:
            raise WerkzeugFehler(str(e)) from e
        return f"{d['name']}: Status {d['status']}, {d['werkzeuge']} Werkzeuge." + (f" Fehler: {d['fehler']}" if d.get("fehler") else "")

    async def integration_schritt_ausfuehren(id: str, schritt: int) -> str:  # noqa: A002
        from ..integrationen.einrichtung import Ausfuehrer, EinrichtungsFehler

        eintrag = app.katalog.holen(id)
        if eintrag is None:
            raise WerkzeugFehler(f"Kein Katalogeintrag zu „{id}“.")
        ausfuehrer: Ausfuehrer = getattr(app, "einrichtung_ausfuehrer", None) or Ausfuehrer()
        app.einrichtung_ausfuehrer = ausfuehrer  # type: ignore[attr-defined]
        try:
            stand = await ausfuehrer.starten(eintrag, schritt - 1)
        except EinrichtungsFehler as e:
            raise WerkzeugFehler(str(e)) from e
        return (
            f"Schritt {schritt} („{eintrag.einrichtung[schritt - 1].titel}“) läuft im Hintergrund (Status {stand['status']}). "
            "Sage dem Nutzer, dass sich ggf. der Browser zur Anmeldung öffnet; den Stand zeigt die Oberfläche unter "
            "Integrationen → Eintrag → Einrichtung."
        )

    async def katalog_durchsuchen(suchbegriff: str | None = None) -> str:
        eintraege = app.katalog.suchen(suchbegriff)
        if not eintraege:
            return f"Kein Katalogeintrag zu „{suchbegriff}“."
        installiert = set(app.manager.konfigs)
        return "\n".join(
            f"{e.id}: {e.name} [{e.kategorie}] – {e.beschreibung}"
            + (" (installiert)" if e.id in installiert else "")
            + (f" | benötigt: {', '.join(b.name for b in e.benoetigt if not b.optional)}" if any(not b.optional for b in e.benoetigt) else "")
            for e in eintraege
        )

    async def verzeichnis_suchen(begriff: str, quelle: str | None = None) -> str:
        from ..integrationen.verzeichnisse import VerzeichnisFehler

        try:
            ergebnis = await app.verzeichnisse.suchen(begriff, quelle or None, limit=6)
        except VerzeichnisFehler as e:
            raise WerkzeugFehler(str(e)) from e
        zeilen = []
        for e in app.katalog.suchen(begriff)[:5]:
            zeilen.append(
                f"[Katalog] {e.id}: {e.name} – {e.beschreibung} ({'offiziell' if e.vertrauen == 'offiziell' else 'Community'}; "
                "installierbar mit integration_hinzufuegen)"
            )
        for t in ergebnis["treffer"]:
            art = {"fern": "Remote-Server", "npx": "lokal per npx", "uvx": "lokal per uvx"}.get(t["laufzeit"] or "", "nicht installierbar")
            merkmale = [t["herausgeber"], "verifiziert" if t["verifiziert"] else "nicht verifiziert", art]
            if t["nutzungen"]:
                merkmale.append(f"{t['nutzungen']} Nutzungen")
            if t["oauth"]:
                merkmale.append("Anmeldung im Browser")
            pflicht = [f["name"] for f in t["felder"] if not f["optional"]]
            zeile = f"[{t['quelle']}] {t['kennung']}: {t['name']} – {t['beschreibung'][:160]} ({'; '.join(merkmale)})"
            if pflicht:
                zeile += f" | benötigt: {', '.join(pflicht)}"
            if not t["installierbar"]:
                zeile += " | " + " ".join(t["warnungen"])
            zeilen.append(zeile)
        for quelle_id, text in ergebnis["fehler"].items():
            zeilen.append(f"Hinweis: Verzeichnis {quelle_id} nicht erreichbar ({text}).")
        if not zeilen:
            return f"Nichts zu „{begriff}“ gefunden – weder im Katalog noch in den Verzeichnissen."
        return (
            "\n".join(zeilen)
            + "\nNenne dem Nutzer Herausgeber und Verifizierung; installiere nur nach seiner Zustimmung "
            "(verzeichnis_installieren mit quelle und kennung; Felder vorher erfragen)."
        )

    async def verzeichnis_installieren(
        quelle: str, kennung: str, werte: dict[str, Any] | None = None, name: str | None = None
    ) -> str:
        from ..integrationen.manager import FehlendeWerte, IntegrationsFehler
        from ..integrationen.verzeichnisse import VerzeichnisFehler

        try:
            anfrage = await app.verzeichnisse.anfrage(quelle, kennung, werte or {}, name)
            info = await app.manager.hinzufuegen(anfrage)
        except FehlendeWerte as e:
            return "Es fehlen noch Angaben: " + "; ".join(
                f"{b.titel} ({b.name}{', geheim' if b.geheim else ''})" for b in e.fehlend
            ) + ". Frage den Nutzer danach und rufe das Werkzeug erneut mit werte auf."
        except (VerzeichnisFehler, IntegrationsFehler) as e:
            raise WerkzeugFehler(str(e)) from e
        if info["status"] == "verbunden":
            return f"Integration „{info['name']}“ ist verbunden ({info['werkzeuge']} Werkzeuge verfügbar)."
        return (
            f"Integration „{info['name']}“ wurde gespeichert, Status: {info['status']}. {info.get('fehler', '')} "
            "Bei OAuth öffnet sich die Anmeldung im Browser; danach neu verbinden."
        ).strip()

    # ---------------- Gedächtnis ----------------
    async def erinnern(text: str) -> str:
        await app.gedaechtnis.erinnern(text)
        return f"Gemerkt: {text}"

    async def erinnerung_suchen(anfrage: str) -> str:
        treffer = await app.gedaechtnis.suchen(anfrage, anzahl=8, mindestwert=0.2)
        if not treffer:
            return "Dazu habe ich nichts gespeichert."
        return "\n".join(f"- {t['text']} (gespeichert {t['zeit'][:10]})" for t in treffer)

    # ---------------- Modell, Zeit, Timer ----------------
    async def modell_wechseln(modell: str) -> str:
        app.konfig.aktualisieren({"modell": modell.strip()})
        return f"Modell gewechselt auf {modell}. Gilt ab der nächsten Anfrage."

    async def uhrzeit_datum() -> str:
        jetzt = datetime.now().astimezone()
        return f"{deutsches_datum(jetzt)} (Zeitzone {jetzt.tzname()}, Kalenderwoche {jetzt.isocalendar().week})"

    async def timer_stellen(sekunden: float | None = None, minuten: float | None = None, text: str | None = None) -> str:
        dauer = float(sekunden or 0) + float(minuten or 0) * 60
        if dauer <= 0:
            raise WerkzeugFehler("Bitte eine Dauer (sekunden oder minuten) angeben.")
        if dauer > 7 * 24 * 3600:
            raise WerkzeugFehler("Timer dürfen höchstens 7 Tage lang sein.")
        beschreibung = text or "Timer"
        await app.timer_stellen(dauer, beschreibung)
        return f"Timer „{beschreibung}“ für {_dauer_text(dauer)} gestellt."

    def wz(funktion: Any, name: str, beschreibung: str, json_schema: dict, risiko: str, **kw: Any) -> FunktionsWerkzeug:
        return FunktionsWerkzeug(funktion, name, beschreibung, json_schema, risiko, quelle="eingebaut", **kw)  # type: ignore[arg-type]

    return [
        wz(
            integration_hinzufuegen,
            "integration_hinzufuegen",
            "Fügt eine neue Integration hinzu (installiert ggf. Software): Katalog-ID (z. B. spotify, notion, "
            "github), MCP-Befehl („npx -y paket“), MCP-URL oder OpenAPI-URL. Vorher ggf. katalog_durchsuchen.",
            schema(
                {
                    "quelle": {"type": "string", "description": "Katalog-ID, MCP-Befehl oder URL"},
                    "name": {"type": "string"},
                    "werte": {"type": "object", "description": "Benötigte Werte, z. B. API-Schlüssel"},
                },
                ["quelle"],
            ),
            "kritisch",
            grund=lambda a: f"Integration hinzufügen (kann Software installieren/ausführen): {a.get('quelle')}",
        ),
        wz(integrationen_auflisten, "integrationen_auflisten", "Listet installierte Integrationen und ihren Status.", schema(), "lesen"),
        wz(
            integration_details,
            "integration_details",
            "Details einer installierten Integration: Status, Fehlergrund, Konfiguration (ohne Geheimnisse), "
            "Einrichtungsschritte mit Stand, letzte Protokollzeilen. Zuerst aufrufen, wenn eine Integration nicht geht.",
            schema({"id": {"type": "string", "description": "Kennung, z. B. gmail"}}, ["id"]),
            "lesen",
        ),
        wz(
            integration_einrichtung,
            "integration_einrichtung",
            "Einrichtungsschritte eines Katalogeintrags (z. B. gmail, google-kalender) mit Stand und nächstem Schritt – "
            "damit führst du den Nutzer Schritt für Schritt.",
            schema({"id": {"type": "string"}}, ["id"]),
            "lesen",
        ),
        wz(
            integration_konfigurieren,
            "integration_konfigurieren",
            "Ändert Werte einer installierten Katalog-Integration (z. B. VERZEICHNIS=~/Documents) und verbindet neu. "
            "Geheimnisse ohne neuen Wert bleiben erhalten.",
            schema(
                {"id": {"type": "string"}, "werte": {"type": "object", "description": "Feldname → neuer Wert"}, "name": {"type": "string"}},
                ["id", "werte"],
            ),
            "aendern",
        ),
        wz(
            integration_schritt_ausfuehren,
            "integration_schritt_ausfuehren",
            "Führt den Befehl eines Einrichtungsschritts aus dem Katalog aus (z. B. die einmalige Anmeldung bei Google). "
            "Schrittnummer wie in integration_einrichtung (ab 1).",
            schema({"id": {"type": "string"}, "schritt": {"type": "integer"}}, ["id", "schritt"]),
            "kritisch",
            grund=lambda a: f"Einrichtungsbefehl ausführen: {a.get('id')}, Schritt {a.get('schritt')}",
        ),
        wz(
            katalog_durchsuchen,
            "katalog_durchsuchen",
            "Durchsucht den Katalog verfügbarer Integrationen (Apps/Dienste).",
            schema({"suchbegriff": {"type": "string"}}),
            "lesen",
        ),
        wz(
            verzeichnis_suchen,
            "verzeichnis_suchen",
            "Sucht MCP-Server in seriösen Verzeichnissen (offizielles MCP-Registry, Smithery, eigene Registries) "
            "und im Katalog – für Dienste, die der Katalog nicht kennt. Liefert Herausgeber, Verifizierung, "
            "Art (Remote/lokal) und benötigte Felder.",
            schema({"begriff": {"type": "string"}, "quelle": {"type": "string", "description": "optional: mcp-registry, smithery oder Kennung eines eigenen Verzeichnisses"}}, ["begriff"]),
            "lesen",
        ),
        wz(
            verzeichnis_installieren,
            "verzeichnis_installieren",
            "Installiert einen Treffer aus verzeichnis_suchen als Integration (Remote-Server verbinden oder "
            "lokalen Server per npx/uvx ausführen). Nur nach Zustimmung des Nutzers.",
            schema(
                {
                    "quelle": {"type": "string", "description": "Verzeichnis-Kennung aus der Suche"},
                    "kennung": {"type": "string", "description": "Server-Kennung aus der Suche"},
                    "werte": {"type": "object", "description": "Benötigte Felder (Schlüssel, Pfade …)"},
                    "name": {"type": "string"},
                },
                ["quelle", "kennung"],
            ),
            "kritisch",
            grund=lambda a: f"Server aus Verzeichnis installieren (führt ggf. fremden Code aus): {a.get('quelle')}/{a.get('kennung')}",
        ),
        wz(
            erinnern,
            "erinnern",
            "Speichert eine dauerhafte Erinnerung über den Nutzer (Vorlieben, Fakten, Absprachen).",
            schema({"text": {"type": "string"}}, ["text"]),
            "aendern",
        ),
        wz(
            erinnerung_suchen,
            "erinnerung_suchen",
            "Durchsucht gespeicherte Erinnerungen.",
            schema({"anfrage": {"type": "string"}}, ["anfrage"]),
            "lesen",
        ),
        wz(
            modell_wechseln,
            "modell_wechseln",
            "Wechselt das Sprachmodell, z. B. ollama/qwen2.5:7b, anthropic/claude-sonnet-5-5, openai/gpt-6.1-sol, gemini/gemini-3.8-flash.",
            schema({"modell": {"type": "string"}}, ["modell"]),
            "aendern",
        ),
        wz(uhrzeit_datum, "uhrzeit_datum", "Aktuelles Datum, Uhrzeit, Wochentag und Kalenderwoche.", schema(), "lesen"),
        wz(
            timer_stellen,
            "timer_stellen",
            "Stellt einen Timer; nach Ablauf meldet sich der Assistent per Mitteilung und Sprache.",
            schema(
                {
                    "sekunden": {"type": "number"},
                    "minuten": {"type": "number"},
                    "text": {"type": "string", "description": "Wofür der Timer ist"},
                }
            ),
            "aendern",
        ),
    ]

