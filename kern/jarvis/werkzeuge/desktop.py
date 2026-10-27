"""Plattformneutrale Desktop-Werkzeuge für Windows und Linux.

Gleiche Namen und Risikostufen wie die Mac-Werkzeuge in ``mac.py``; die Arbeit erledigt die
Plattform-Schicht (``jarvis.plattform.systemaktionen()``). Auf dem Mac werden weiterhin die
unveränderten Werkzeuge aus ``mac.py`` registriert – inklusive der Mac-exklusiven (Erinnerungen,
Kalender, Notizen, Kurzbefehle), siehe ``plattform_werkzeuge()``.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from ..plattform import Plattform, aktuelle_plattform, systemaktionen
from . import FunktionsWerkzeug, Werkzeug, WerkzeugFehler, schema, werkzeug

# Nur auf dem Mac verfügbare Werkzeuge (Apple-Apps bzw. Apple-Kurzbefehle)
NUR_MAC = ("erinnerung_anlegen", "kalender_termine", "termin_anlegen", "notiz_anlegen",
           "kurzbefehle_auflisten", "shortcuts_ausfuehren")

_ERLAUBTE_SCHEMATA = {"http", "https", "mailto", "spotify", "tel"}


def _aktionen():
    return systemaktionen()


@werkzeug(
    "app_oeffnen",
    "Öffnet bzw. startet eine App (z. B. Firefox, Spotify, Rechner) – nur den Namen angeben.",
    schema({"name": {"type": "string", "description": "Name der App"}}, ["name"]),
    risiko="aendern",
)
async def app_oeffnen(name: str) -> str:
    return await _aktionen().app_oeffnen(name)


@werkzeug(
    "app_beenden",
    "Beendet eine laufende App.",
    schema({"name": {"type": "string"}}, ["name"]),
    risiko="aendern",
)
async def app_beenden(name: str) -> str:
    return await _aktionen().app_beenden(name)


@werkzeug("laufende_apps", "Listet die sichtbar laufenden Apps bzw. offenen Fenster auf.", schema(), risiko="lesen")
async def laufende_apps() -> str:
    return await _aktionen().laufende_apps()


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
async def lautstaerke_setzen(prozent: int | None = None, aenderung: int | None = None, stumm: bool | None = None) -> str:
    if prozent is None and aenderung is None and stumm is None:
        raise WerkzeugFehler("Bitte prozent, aenderung oder stumm angeben.")
    return await _aktionen().lautstaerke_setzen(
        None if prozent is None else int(prozent), None if aenderung is None else int(aenderung), stumm
    )


@werkzeug(
    "mitteilung_anzeigen",
    "Zeigt eine Desktop-Mitteilung (Notification) an.",
    schema(
        {"text": {"type": "string"}, "titel": {"type": "string", "description": "Titel (Standard: Name des Assistenten)"}},
        ["text"],
    ),
    risiko="lesen",
)
async def mitteilung_anzeigen(text: str, titel: str = "") -> str:
    from ..konfig import aktueller_name

    return await _aktionen().mitteilung_anzeigen(text, titel or aktueller_name())


@werkzeug(
    "musik_steuern",
    "Steuert die Musikwiedergabe (Spotify oder den aktiven Player): play, pause, playpause, weiter, "
    "zurueck, aktuell (aktuellen Titel nennen) oder suchen (Spotify-Suche öffnen).",
    schema(
        {
            "aktion": {"type": "string", "enum": ["play", "pause", "playpause", "weiter", "zurueck", "aktuell", "suchen"]},
            "app": {"type": "string", "enum": ["auto", "spotify"], "default": "auto"},
            "suchbegriff": {"type": "string", "description": "Nur für aktion=suchen"},
        },
        ["aktion"],
    ),
    risiko="aendern",
)
async def musik_steuern(aktion: str, app: str = "auto", suchbegriff: str | None = None) -> str:
    if app not in ("auto", "spotify"):
        app = "auto"  # „music“ (Apple Music) gibt es nur auf dem Mac
    return await _aktionen().musik_steuern(aktion, app, suchbegriff)


def url_pruefen(url: str) -> str:
    url = (url or "").strip()
    schema_ = urlparse(url).scheme.lower()
    if not schema_:
        url = "https://" + url
        schema_ = "https"
    if schema_ not in _ERLAUBTE_SCHEMATA:
        raise WerkzeugFehler(f"URL-Schema „{schema_}“ ist nicht erlaubt.")
    return url


@werkzeug(
    "url_oeffnen",
    "Öffnet eine URL im Standardbrowser bzw. der zuständigen App (http, https, mailto, spotify …).",
    schema({"url": {"type": "string"}}, ["url"]),
    risiko="aendern",
)
async def url_oeffnen(url: str) -> str:
    return await _aktionen().url_oeffnen(url_pruefen(url))


@werkzeug("zwischenablage_lesen", "Liest den Text in der Zwischenablage.", schema(), risiko="lesen")
async def zwischenablage_lesen() -> str:
    text = await _aktionen().zwischenablage_lesen()
    return text or "(Die Zwischenablage ist leer.)"


@werkzeug(
    "zwischenablage_schreiben",
    "Kopiert Text in die Zwischenablage.",
    schema({"text": {"type": "string"}}, ["text"]),
    risiko="aendern",
)
async def zwischenablage_schreiben(text: str) -> str:
    return await _aktionen().zwischenablage_schreiben(text)


def _foto_pfad(pfad: str | None) -> str:
    if pfad:
        return os.path.abspath(os.path.expanduser(pfad))
    from ..plattform.gemeinsam import bilder_ordner

    stempel = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return str(bilder_ordner() / f"Jarvis-Bildschirmfoto_{stempel}.png")


def _foto_risiko(argumente: dict[str, Any]):
    from .dateien import _pfad, schreib_grund

    pfad = argumente.get("pfad")
    return "kritisch" if pfad and schreib_grund(_pfad(str(pfad))) else "aendern"


@werkzeug(
    "bildschirmfoto",
    "Erstellt ein Bildschirmfoto und speichert es als PNG (Standard: Schreibtisch bzw. Bilder-Ordner).",
    schema({"pfad": {"type": "string", "description": "Optionaler Zielpfad (.png)"}}),
    risiko="aendern",
    risiko_fuer=_foto_risiko,
    grund=lambda a: f"Bildschirmfoto speichern nach {a.get('pfad')} (geschützter Ort)",
)
async def bildschirmfoto(pfad: str | None = None) -> str:
    return await _aktionen().bildschirmfoto(_foto_pfad(pfad))


@werkzeug(
    "systeminfo",
    "Zeigt Systeminformationen: Betriebssystem, Akku, WLAN, Speicherplatz, Arbeitsspeicher, Laufzeit.",
    schema(),
    risiko="lesen",
)
async def systeminfo() -> str:
    return await _aktionen().systeminfo()


def werkzeuge() -> list[Werkzeug]:
    return [w for w in globals().values() if isinstance(w, FunktionsWerkzeug)]


def plattform_werkzeuge(plattform: Plattform | None = None) -> list[Werkzeug]:
    """System-Werkzeuge der Plattform: Mac → ``mac.py`` (alle, unverändert), sonst die neutralen."""
    if (plattform or aktuelle_plattform()) == "mac":
        from . import mac

        return mac.werkzeuge()
    return werkzeuge()
