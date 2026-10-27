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
            katalog_durchsuchen,
            "katalog_durchsuchen",
            "Durchsucht den Katalog verfügbarer Integrationen (Apps/Dienste).",
            schema({"suchbegriff": {"type": "string"}}),
            "lesen",
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

