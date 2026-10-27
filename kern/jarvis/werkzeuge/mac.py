"""macOS-Werkzeuge über osascript (AppleScript), open, shortcuts, screencapture, pbcopy/pbpaste …

Auf anderen Systemen liefern die Werkzeuge eine freundliche Fehlermeldung.
Alle Programmaufrufe laufen über `prozess.ausfuehren` (in Tests gemockt).
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

from . import FunktionsWerkzeug, Werkzeug, WerkzeugFehler, schema, werkzeug
from . import prozess

NICHT_MAC = (
    "Dieses Werkzeug funktioniert nur auf macOS (aktuelles System: {system}). "
    "Bitte führen Sie den Assistenten auf Ihrem Mac aus."
)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def as_text(wert: object) -> str:
    """Python-Wert als AppleScript-Stringliteral (mit Escaping von \\ und Anführungszeichen)."""
    s = str(wert).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def as_datum(variable: str, zeitpunkt: datetime) -> str:
    """AppleScript-Zeilen, die `variable` locale-unabhängig auf `zeitpunkt` setzen."""
    sekunden = zeitpunkt.hour * 3600 + zeitpunkt.minute * 60 + zeitpunkt.second
    return "\n".join(
        [
            f"set {variable} to current date",
            f"set day of {variable} to 1",
            f"set year of {variable} to {zeitpunkt.year}",
            f"set month of {variable} to {zeitpunkt.month}",
            f"set day of {variable} to {zeitpunkt.day}",
            f"set time of {variable} to {sekunden}",
        ]
    )


def zeit_parsen(text: str) -> datetime:
    """ISO-8601 (lokale Zeit) parsen, z. B. 2025-03-01T14:30 oder 2025-03-01 14:30."""
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError as e:
        raise WerkzeugFehler(
            f"Ungültiges Datum „{text}“. Bitte ISO-Format verwenden, z. B. 2025-03-01T14:30."
        ) from e
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _mac_pruefen() -> None:
    if not prozess.ist_mac():
        raise WerkzeugFehler(NICHT_MAC.format(system=sys.platform))


async def osascript(skript: str, timeout: float = 30.0) -> str:
    _mac_pruefen()
    erg = await prozess.ausfuehren("osascript", "-e", skript, timeout=timeout)
    if not erg.ok:
        fehler = erg.fehler.strip() or erg.ausgabe.strip()
        if "-1743" in fehler or "Not authorized" in fehler:
            fehler += (
                " – Bitte in Systemeinstellungen › Datenschutz & Sicherheit › Automation "
                "dem Terminal bzw. Python die Steuerung erlauben."
            )
        raise WerkzeugFehler(f"AppleScript-Fehler: {fehler}")
    return erg.ausgabe.strip()


async def programm(*befehl: str, eingabe: str | None = None, timeout: float = 30.0) -> str:
    _mac_pruefen()
    erg = await prozess.ausfuehren(*befehl, eingabe=eingabe, timeout=timeout)
    if not erg.ok:
        raise WerkzeugFehler(f"{befehl[0]} fehlgeschlagen: {(erg.fehler or erg.ausgabe).strip()}")
    return erg.ausgabe.strip()


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------
@werkzeug(
    "app_oeffnen",
    "Öffnet bzw. aktiviert eine Mac-App (z. B. Safari, Mail, Spotify).",
    schema({"name": {"type": "string", "description": "Name der App"}}, ["name"]),
    risiko="aendern",
)
async def app_oeffnen(name: str) -> str:
    await programm("open", "-a", name)
    return f"{name} wurde geöffnet."


@werkzeug(
    "app_beenden",
    "Beendet eine laufende Mac-App.",
    schema({"name": {"type": "string"}}, ["name"]),
    risiko="aendern",
)
async def app_beenden(name: str) -> str:
    await osascript(f"tell application {as_text(name)} to quit")
    return f"{name} wurde beendet."


@werkzeug(
    "laufende_apps",
    "Listet die sichtbar laufenden Mac-Apps auf.",
    schema(),
    risiko="lesen",
)
async def laufende_apps() -> str:
    return await osascript(
        'tell application "System Events" to get name of every application process '
        "whose background only is false"
    )


# ---------------------------------------------------------------------------
# Ton, Mitteilungen, Musik
# ---------------------------------------------------------------------------
@werkzeug(
    "lautstaerke_setzen",
    "Setzt die Systemlautstärke (0–100), ändert sie relativ oder schaltet stumm.",
    schema(
        {
            "prozent": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Absolute Lautstärke"},
            "aenderung": {"type": "integer", "description": "Relative Änderung, z. B. +10 oder -20"},
            "stumm": {"type": "boolean", "description": "true = stumm, false = Ton an"},
        }
    ),
    risiko="aendern",
)
async def lautstaerke_setzen(
    prozent: int | None = None, aenderung: int | None = None, stumm: bool | None = None
) -> str:
    zeilen = []
    if stumm is not None:
        zeilen.append(f"set volume output muted {'true' if stumm else 'false'}")
    if prozent is not None:
        p = max(0, min(100, int(prozent)))
        zeilen.append(f"set volume output volume {p}")
    elif aenderung is not None:
        a = int(aenderung)
        zeilen.append(
            "set aktuell to output volume of (get volume settings)\n"
            f"set neu to aktuell + ({a})\n"
            "if neu > 100 then set neu to 100\n"
            "if neu < 0 then set neu to 0\n"
            "set volume output volume neu"
        )
    if not zeilen:
        raise WerkzeugFehler("Bitte prozent, aenderung oder stumm angeben.")
    zeilen.append("return output volume of (get volume settings)")
    stand = await osascript("\n".join(zeilen))
    return f"Lautstärke jetzt {stand} %." + (" (stumm)" if stumm else "")


@werkzeug(
    "mitteilung_anzeigen",
    "Zeigt eine macOS-Mitteilung (Notification) an.",
    schema(
        {"text": {"type": "string"}, "titel": {"type": "string", "description": "Titel (Standard: Name des Assistenten)"}},
        ["text"],
    ),
    risiko="lesen",
)
async def mitteilung_anzeigen(text: str, titel: str = "") -> str:
    if not titel:
        from ..konfig import aktueller_name

        titel = aktueller_name()
    await osascript(f"display notification {as_text(text)} with title {as_text(titel)}")
    return "Mitteilung angezeigt."


_MUSIK_BEFEHLE = {
    "play": "play",
    "pause": "pause",
    "playpause": "playpause",
    "weiter": "next track",
    "zurueck": "previous track",
}


async def _musik_app(app: str) -> str:
    if app == "spotify":
        return "Spotify"
    if app == "music":
        return "Music"
    laeuft = await osascript('return application "Spotify" is running')
    return "Spotify" if laeuft.strip() == "true" else "Music"


@werkzeug(
    "musik_steuern",
    "Steuert Musik in Apple Music oder der Spotify-App: play, pause, playpause, weiter, zurueck, "
    "aktuell (aktuellen Titel nennen) oder suchen (Titel/Künstler suchen und abspielen).",
    schema(
        {
            "aktion": {
                "type": "string",
                "enum": ["play", "pause", "playpause", "weiter", "zurueck", "aktuell", "suchen"],
            },
            "app": {"type": "string", "enum": ["auto", "music", "spotify"], "default": "auto"},
            "suchbegriff": {"type": "string", "description": "Nur für aktion=suchen"},
        },
        ["aktion"],
    ),
    risiko="aendern",
)
async def musik_steuern(aktion: str, app: str = "auto", suchbegriff: str | None = None) -> str:
    _mac_pruefen()
    name = await _musik_app(app)
    ziel = f"tell application {as_text(name)}"
    if aktion in _MUSIK_BEFEHLE:
        await osascript(f"{ziel} to {_MUSIK_BEFEHLE[aktion]}")
        return f"{name}: {aktion} ausgeführt."
    if aktion == "aktuell":
        return await osascript(
            f"{ziel}\n"
            '  if player state is stopped then return "Es läuft gerade nichts."\n'
            '  return (name of current track) & " – " & (artist of current track) & " (" & (player state as string) & ")"\n'
            "end tell"
        )
    if aktion == "suchen":
        if not suchbegriff:
            raise WerkzeugFehler("Für aktion=suchen wird ein suchbegriff benötigt.")
        if name == "Spotify":
            uri = "spotify:search:" + quote(suchbegriff)
            await programm("open", uri)
            try:
                await osascript(f"{ziel} to play track {as_text(uri)}")
            except WerkzeugFehler:
                pass
            return (
                f"Spotify-Suche nach „{suchbegriff}“ geöffnet. Für gezieltes Abspielen bestimmter "
                "Titel kann die Spotify-Integration aus dem Katalog hinzugefügt werden."
            )
        return await osascript(
            f"{ziel}\n"
            f"  set treffer to (search library playlist 1 for {as_text(suchbegriff)})\n"
            '  if treffer is {} then return "Nichts in der Mediathek gefunden."\n'
            "  play item 1 of treffer\n"
            '  return "Spiele " & (name of item 1 of treffer) & " – " & (artist of item 1 of treffer)\n'
            "end tell"
        )
    raise WerkzeugFehler(f"Unbekannte Aktion: {aktion}")


# ---------------------------------------------------------------------------
# URLs, Zwischenablage, Bildschirmfoto
# ---------------------------------------------------------------------------
_ERLAUBTE_SCHEMATA = {"http", "https", "mailto", "spotify", "music", "facetime", "tel", "maps", "x-apple.systempreferences"}


@werkzeug(
    "url_oeffnen",
    "Öffnet eine URL im Standardbrowser bzw. der zuständigen App (http, https, mailto, spotify …).",
    schema({"url": {"type": "string"}}, ["url"]),
    risiko="aendern",
)
async def url_oeffnen(url: str) -> str:
    schema_ = urlparse(url).scheme.lower()
    if not schema_:
        url = "https://" + url
        schema_ = "https"
    if schema_ not in _ERLAUBTE_SCHEMATA:
        raise WerkzeugFehler(f"URL-Schema „{schema_}“ ist nicht erlaubt.")
    await programm("open", url)
    return f"{url} geöffnet."


@werkzeug("zwischenablage_lesen", "Liest den Text in der Zwischenablage.", schema(), risiko="lesen")
async def zwischenablage_lesen() -> str:
    text = await programm("pbpaste")
    return text or "(Die Zwischenablage ist leer.)"


@werkzeug(
    "zwischenablage_schreiben",
    "Kopiert Text in die Zwischenablage.",
    schema({"text": {"type": "string"}}, ["text"]),
    risiko="aendern",
)
async def zwischenablage_schreiben(text: str) -> str:
    await programm("pbcopy", eingabe=text)
    return "Text in die Zwischenablage kopiert."


@werkzeug(
    "bildschirmfoto",
    "Erstellt ein Bildschirmfoto und speichert es als PNG (Standard: Schreibtisch).",
    schema({"pfad": {"type": "string", "description": "Optionaler Zielpfad (.png)"}}),
    risiko="aendern",
)
async def bildschirmfoto(pfad: str | None = None) -> str:
    if not pfad:
        stempel = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        pfad = str(Path("~/Desktop").expanduser() / f"Jarvis-Bildschirmfoto_{stempel}.png")
    pfad = os.path.expanduser(pfad)
    await programm("screencapture", "-x", pfad)
    return f"Bildschirmfoto gespeichert: {pfad}"


# ---------------------------------------------------------------------------
# Erinnerungen, Kalender, Notizen
# ---------------------------------------------------------------------------
@werkzeug(
    "erinnerung_anlegen",
    "Legt eine Erinnerung in der App Erinnerungen (Reminders) an, optional mit Fälligkeit.",
    schema(
        {
            "titel": {"type": "string"},
            "faellig": {"type": "string", "description": "ISO-Zeitpunkt (lokal), z. B. 2025-03-01T09:00"},
            "liste": {"type": "string", "description": "Name der Liste (sonst Standardliste)"},
            "notiz": {"type": "string"},
        },
        ["titel"],
    ),
    risiko="aendern",
)
async def erinnerung_anlegen(
    titel: str, faellig: str | None = None, liste: str | None = None, notiz: str | None = None
) -> str:
    eigenschaften = [f"name:{as_text(titel)}"]
    zeilen = []
    if faellig:
        zeilen.append(as_datum("faelligDatum", zeit_parsen(faellig)))
        eigenschaften.append("due date:faelligDatum")
    if notiz:
        eigenschaften.append(f"body:{as_text(notiz)}")
    ziel = f"list {as_text(liste)}" if liste else "default list"
    zeilen.append(
        'tell application "Reminders"\n'
        f"  tell {ziel}\n"
        f"    make new reminder with properties {{{', '.join(eigenschaften)}}}\n"
        "  end tell\n"
        "end tell"
    )
    await osascript("\n".join(zeilen))
    return f"Erinnerung „{titel}“ angelegt" + (f" (fällig {faellig})." if faellig else ".")


@werkzeug(
    "kalender_termine",
    "Liest Termine aus der Kalender-App für einen Zeitraum (Standard: heute).",
    schema(
        {
            "ab": {"type": "string", "description": "Startdatum ISO (Standard: heute 00:00)"},
            "tage": {"type": "integer", "default": 1, "minimum": 1, "maximum": 31},
        }
    ),
    risiko="lesen",
)
async def kalender_termine(ab: str | None = None, tage: int = 1) -> str:
    start = zeit_parsen(ab) if ab else datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    ende = start + timedelta(days=max(1, int(tage)))
    skript = "\n".join(
        [
            as_datum("startD", start),
            as_datum("endeD", ende),
            'set ausgabe to ""',
            'tell application "Calendar"',
            "  repeat with k in calendars",
            "    set termine to (every event of k whose start date ≥ startD and start date < endeD)",
            "    repeat with t in termine",
            '      set ausgabe to ausgabe & (summary of t) & " | " & ((start date of t) as string) & " | " & (name of k) & linefeed',
            "    end repeat",
            "  end repeat",
            "end tell",
            "return ausgabe",
        ]
    )
    ergebnis = await osascript(skript, timeout=60)
    return ergebnis or "Keine Termine im Zeitraum."


@werkzeug(
    "termin_anlegen",
    "Legt einen Termin in der Kalender-App an.",
    schema(
        {
            "titel": {"type": "string"},
            "start": {"type": "string", "description": "ISO-Zeitpunkt (lokal), z. B. 2025-03-01T14:00"},
            "ende": {"type": "string", "description": "ISO-Zeitpunkt; alternativ dauer_minuten"},
            "dauer_minuten": {"type": "integer", "default": 60},
            "kalender": {"type": "string", "description": "Kalendername (sonst erster beschreibbarer)"},
            "ort": {"type": "string"},
            "notiz": {"type": "string"},
        },
        ["titel", "start"],
    ),
    risiko="aendern",
)
async def termin_anlegen(
    titel: str,
    start: str,
    ende: str | None = None,
    dauer_minuten: int = 60,
    kalender: str | None = None,
    ort: str | None = None,
    notiz: str | None = None,
) -> str:
    beginn = zeit_parsen(start)
    schluss = zeit_parsen(ende) if ende else beginn + timedelta(minutes=int(dauer_minuten))
    eigenschaften = [f"summary:{as_text(titel)}", "start date:startD", "end date:endeD"]
    if ort:
        eigenschaften.append(f"location:{as_text(ort)}")
    if notiz:
        eigenschaften.append(f"description:{as_text(notiz)}")
    ziel = f"calendar {as_text(kalender)}" if kalender else "(first calendar whose writable is true)"
    skript = "\n".join(
        [
            as_datum("startD", beginn),
            as_datum("endeD", schluss),
            'tell application "Calendar"',
            f"  tell {ziel}",
            f"    make new event with properties {{{', '.join(eigenschaften)}}}",
            "  end tell",
            "end tell",
        ]
    )
    await osascript(skript)
    return f"Termin „{titel}“ am {beginn:%d.%m.%Y um %H:%M} angelegt."


def _html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    )


@werkzeug(
    "notiz_anlegen",
    "Legt eine Notiz in der Notizen-App (Notes) an.",
    schema(
        {"titel": {"type": "string"}, "text": {"type": "string"}, "ordner": {"type": "string"}},
        ["titel", "text"],
    ),
    risiko="aendern",
)
async def notiz_anlegen(titel: str, text: str, ordner: str | None = None) -> str:
    inhalt = f"<h1>{_html(titel)}</h1><div>{_html(text)}</div>"
    ort = f" at folder {as_text(ordner)}" if ordner else ""
    await osascript(
        'tell application "Notes"\n'
        f"  make new note{ort} with properties {{name:{as_text(titel)}, body:{as_text(inhalt)}}}\n"
        "end tell"
    )
    return f"Notiz „{titel}“ angelegt."


# ---------------------------------------------------------------------------
# Kurzbefehle (Shortcuts) – damit ist jede Apple-Kurzbefehl-Automation nutzbar
# ---------------------------------------------------------------------------
@werkzeug(
    "kurzbefehle_auflisten",
    "Listet alle Apple-Kurzbefehle (Shortcuts) des Nutzers auf.",
    schema(),
    risiko="lesen",
)
async def kurzbefehle_auflisten() -> str:
    return await programm("shortcuts", "list") or "Keine Kurzbefehle gefunden."


@werkzeug(
    "shortcuts_ausfuehren",
    "Führt einen Apple-Kurzbefehl (Shortcut) aus, optional mit Texteingabe. "
    "Namen vorher mit kurzbefehle_auflisten ermitteln.",
    schema(
        {"name": {"type": "string"}, "eingabe": {"type": "string", "description": "Optionale Texteingabe"}},
        ["name"],
    ),
    # Kurzbefehle können beliebige Aktionen enthalten (Shell, Nachrichten senden, Dateien löschen …)
    risiko="kritisch",
    grund=lambda a: f"Apple-Kurzbefehl „{a.get('name')}“ ausführen (kann beliebige Aktionen enthalten)",
)
async def shortcuts_ausfuehren(name: str, eingabe: str | None = None) -> str:
    _mac_pruefen()
    with tempfile.TemporaryDirectory(prefix="jarvis-shortcut-") as tmp:
        befehl = ["shortcuts", "run", name, "--output-path", os.path.join(tmp, "ausgabe")]
        if eingabe is not None:
            eingabe_pfad = os.path.join(tmp, "eingabe.txt")
            Path(eingabe_pfad).write_text(eingabe, encoding="utf-8")
            befehl += ["--input-path", eingabe_pfad]
        ausgabe = await programm(*befehl, timeout=120)
        datei = Path(tmp) / "ausgabe"
        if datei.exists():
            try:
                ausgabe = (ausgabe + "\n" + datei.read_text(encoding="utf-8", errors="replace")).strip()
            except OSError:
                pass
    return ausgabe or f"Kurzbefehl „{name}“ ausgeführt."


# ---------------------------------------------------------------------------
# Systeminfo
# ---------------------------------------------------------------------------
@werkzeug(
    "systeminfo",
    "Zeigt Systeminformationen: Akku, WLAN, Speicherplatz, Arbeitsspeicher, macOS-Version.",
    schema(),
    risiko="lesen",
)
async def systeminfo() -> str:
    _mac_pruefen()
    teile = []

    async def versuch(titel: str, *befehl: str) -> None:
        erg = await prozess.ausfuehren(*befehl, timeout=10)
        if erg.ok and erg.ausgabe.strip():
            teile.append(f"{titel}:\n{erg.ausgabe.strip()}")

    await versuch("macOS", "sw_vers")
    await versuch("Akku", "pmset", "-g", "batt")
    erg = await prozess.ausfuehren("ipconfig", "getsummary", "en0", timeout=10)
    ssid = [z.strip() for z in erg.ausgabe.splitlines() if z.strip().startswith("SSID")]
    if ssid:
        teile.append("WLAN: " + ssid[0])
    else:
        await versuch("WLAN", "networksetup", "-getairportnetwork", "en0")
    await versuch("Speicherplatz", "df", "-h", "/")
    erg = await prozess.ausfuehren("sysctl", "-n", "hw.memsize", timeout=10)
    if erg.ok and erg.ausgabe.strip().isdigit():
        teile.append(f"Arbeitsspeicher: {int(erg.ausgabe.strip()) / 1024**3:.0f} GB")
    await versuch("Laufzeit", "uptime")
    return "\n\n".join(teile) or "Keine Systeminformationen verfügbar."


def werkzeuge() -> list[Werkzeug]:
    return [w for w in globals().values() if isinstance(w, FunktionsWerkzeug)]

