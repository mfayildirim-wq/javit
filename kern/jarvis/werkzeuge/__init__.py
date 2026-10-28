"""Werkzeug-Register: Basisklasse, Risikostufen, Heuristik."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any, Literal

Risiko = Literal["lesen", "aendern", "kritisch"]
RISIKEN: tuple[Risiko, ...] = ("lesen", "aendern", "kritisch")
#: Bereich eines Werkzeugs: „technisch“ (Dateien, Shell, Apps, Umgebung – läuft ohne Rückfrage mit den
#: Rechten des Systembenutzers) oder „fachlich“ (Nachrichten, Termine, Einträge in Diensten, Geld –
#: Nutzer bestätigt alles, was nicht nur liest).
Bereich = Literal["technisch", "fachlich"]
BEREICHE: tuple[Bereich, ...] = ("technisch", "fachlich")
#: Eingebaute Werkzeuge, die fachliche Daten anlegen (Kalender, Erinnerungen, Notizen)
FACHLICH_EINGEBAUT = frozenset({"termin_anlegen", "erinnerung_anlegen", "notiz_anlegen"})
FreigabeFachlich = Literal["aendern", "kritisch", "nie"]

MAX_ERGEBNIS_ZEICHEN = 12000

_KRITISCH_WOERTER = {
    "delete", "remove", "send", "pay", "purchase", "transfer", "buy", "destroy", "drop",
    "erase", "wipe", "kill", "terminate", "publish", "post", "checkout", "refund",
    "charge", "withdraw", "execute", "exec", "run", "install", "uninstall",
    "loeschen", "löschen", "entfernen", "senden", "bezahlen", "kaufen", "ueberweisen",
    "überweisen", "bestellen", "installieren", "ausfuehren", "ausführen",
}
_LESEN_WOERTER = {
    "get", "list", "search", "read", "fetch", "find", "query", "show", "describe", "view",
    "lookup", "retrieve", "count", "status", "info", "check", "browse", "download", "export",
    "lesen", "suchen", "auflisten", "anzeigen", "abrufen", "holen", "finden",
}


def _woerter(name: str) -> list[str]:
    # camelCase und Trennzeichen aufteilen
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return [w for w in re.split(r"[^A-Za-zÄÖÜäöüß0-9]+", name.lower()) if w]


def risiko_schaetzen(name: str, standard: Risiko = "aendern") -> Risiko:
    """Heuristik anhand des Werkzeugnamens.

    Namen mit delete/remove/send/pay/purchase/transfer … → kritisch,
    get/list/search/read … → lesen, sonst `standard` (Standard: aendern).
    Kritische Wörter haben Vorrang.
    """
    woerter = _woerter(name)
    if any(w in _KRITISCH_WOERTER for w in woerter):
        return "kritisch"
    if woerter and woerter[0] in _LESEN_WOERTER:
        return "lesen"
    if any(w in _LESEN_WOERTER for w in woerter) and standard != "kritisch":
        return "lesen"
    return standard


def name_bereinigen(name: str, max_laenge: int = 64) -> str:
    """Werkzeugnamen auf das von allen Anbietern akzeptierte Muster ^[a-zA-Z0-9_-]{1,64}$ bringen."""
    ersetzt = (
        name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
    )
    sauber = re.sub(r"[^a-zA-Z0-9_-]+", "_", ersetzt).strip("_") or "werkzeug"
    return sauber[:max_laenge]


def ergebnis_als_text(ergebnis: Any, max_zeichen: int = MAX_ERGEBNIS_ZEICHEN) -> str:
    if ergebnis is None:
        text = "OK"
    elif isinstance(ergebnis, str):
        text = ergebnis
    else:
        try:
            text = json.dumps(ergebnis, ensure_ascii=False, indent=1, default=str)
        except (TypeError, ValueError):
            text = str(ergebnis)
    if len(text) > max_zeichen:
        text = text[:max_zeichen] + f"\n… (gekürzt, {len(text) - max_zeichen} Zeichen ausgelassen)"
    return text


class WerkzeugFehler(Exception):
    """Fehler, dessen Text dem Modell (und dem Nutzer) gezeigt werden kann."""


class Werkzeug:
    """Basisklasse aller Werkzeuge."""

    def __init__(
        self,
        name: str,
        beschreibung: str,
        json_schema: dict[str, Any] | None = None,
        risiko: Risiko = "aendern",
        quelle: str = "eingebaut",
        integration: str | None = None,
        bereich: Bereich | None = None,
        schutz: bool = False,
    ):
        if risiko not in RISIKEN:
            raise ValueError(f"Ungültige Risikostufe: {risiko}")
        if bereich is not None and bereich not in BEREICHE:
            raise ValueError(f"Ungültiger Bereich: {bereich}")
        self.name = name
        self.bereich: Bereich = bereich or ("fachlich" if name in FACHLICH_EINGEBAUT else "technisch")
        #: Schutz: auch ohne technische Freigaben bestätigen lassen (Dateien löschen, Zugangsdaten lesen)
        self.schutz = schutz
        self.beschreibung = beschreibung
        self.json_schema = json_schema or {"type": "object", "properties": {}}
        self.json_schema.setdefault("type", "object")
        self.json_schema.setdefault("properties", {})
        self.risiko: Risiko = risiko
        self.quelle = quelle
        self.integration = integration

    async def ausfuehren(self, **argumente: Any) -> Any:  # pragma: no cover - abstrakt
        raise NotImplementedError

    def risiko_fuer(self, argumente: dict[str, Any]) -> Risiko:
        """Risiko für einen konkreten Aufruf (kann von Unterklassen verschärft werden)."""
        return self.risiko

    def freigabe_grund(self, argumente: dict[str, Any]) -> str:
        if self.risiko_fuer(argumente) == "kritisch":
            return f"„{self.name}“ ist als kritisch eingestuft: {self.beschreibung}"
        return f"„{self.name}“ ändert Daten (fachliche Aktion): {self.beschreibung}"

    def als_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.beschreibung[:1024],
                "parameters": self.json_schema,
            },
        }

    def als_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "name": self.name,
            "beschreibung": self.beschreibung,
            "quelle": self.quelle,
            "risiko": self.risiko,
            "bereich": self.bereich,
        }
        if self.integration:
            info["integration"] = self.integration
        return info


class FunktionsWerkzeug(Werkzeug):
    """Werkzeug, das eine async-Funktion kapselt."""

    def __init__(
        self,
        funktion: Callable[..., Awaitable[Any]],
        name: str,
        beschreibung: str,
        json_schema: dict[str, Any] | None = None,
        risiko: Risiko = "aendern",
        quelle: str = "eingebaut",
        integration: str | None = None,
        risiko_fuer: Callable[[dict[str, Any]], Risiko] | None = None,
        grund: Callable[[dict[str, Any]], str] | None = None,
        bereich: Bereich | None = None,
        schutz: bool = False,
    ):
        super().__init__(name, beschreibung, json_schema, risiko, quelle, integration, bereich, schutz)
        self._funktion = funktion
        self._risiko_fuer = risiko_fuer
        self._grund = grund

    async def ausfuehren(self, **argumente: Any) -> Any:
        return await self._funktion(**argumente)

    def risiko_fuer(self, argumente: dict[str, Any]) -> Risiko:
        if self._risiko_fuer:
            return self._risiko_fuer(argumente)
        return self.risiko

    def freigabe_grund(self, argumente: dict[str, Any]) -> str:
        if self._grund:
            return self._grund(argumente)
        return super().freigabe_grund(argumente)


def freigabe_noetig(
    w: Werkzeug, argumente: dict[str, Any], freigabe_technisch: bool = False, freigabe_fachlich: str = "aendern"
) -> Risiko | None:
    """Entscheidet, ob ein Aufruf dem Nutzer vorgelegt wird; liefert die Risikostufe oder None.

    * fachlich: alles außer Lesen (Stufe ``freigabe_fachlich``: „aendern“ = ab Ändern, „kritisch“ = nur
      Kritisches, „nie“ = gar nicht).
    * technisch: nur bei ``freigabe_technisch`` kritische Aufrufe – Ausnahme ``schutz`` (Dateien löschen,
      Zugangsdaten lesen), das bleibt immer bestätigungspflichtig.
    """
    risiko = w.risiko_fuer(argumente)
    if risiko == "lesen":
        return None
    if w.bereich == "fachlich":
        if freigabe_fachlich == "nie":
            return None
        if freigabe_fachlich == "kritisch" and risiko != "kritisch":
            return None
        return risiko
    if risiko == "kritisch" and (freigabe_technisch or w.schutz):
        return risiko
    return None


def schema(eigenschaften: dict[str, Any] | None = None, pflicht: list[str] | None = None) -> dict:
    """Kurzform für JSON-Schemas: schema({"text": {"type": "string"}}, ["text"])."""
    s: dict[str, Any] = {"type": "object", "properties": eigenschaften or {}}
    if pflicht:
        s["required"] = pflicht
    return s


def werkzeug(
    name: str,
    beschreibung: str,
    json_schema: dict[str, Any] | None = None,
    risiko: Risiko = "aendern",
    **kwargs: Any,
) -> Callable[[Callable[..., Awaitable[Any]]], FunktionsWerkzeug]:
    """Dekorator: macht aus einer async-Funktion ein Werkzeug."""

    def dekorator(funktion: Callable[..., Awaitable[Any]]) -> FunktionsWerkzeug:
        return FunktionsWerkzeug(funktion, name, beschreibung, json_schema, risiko, **kwargs)

    return dekorator


class WerkzeugRegister:
    def __init__(self) -> None:
        self._werkzeuge: dict[str, Werkzeug] = {}
        self._beobachter: list[Callable[[], None]] = []

    def registrieren(self, w: Werkzeug, ersetzen: bool = True) -> None:
        if w.name in self._werkzeuge and not ersetzen:
            raise ValueError(f"Werkzeug {w.name} existiert bereits")
        self._werkzeuge[w.name] = w

    def alle_registrieren(self, werkzeuge: list[Werkzeug]) -> None:
        for w in werkzeuge:
            self.registrieren(w)

    def entfernen(self, name: str) -> bool:
        return self._werkzeuge.pop(name, None) is not None

    def entfernen_integration(self, integration: str) -> int:
        namen = [n for n, w in self._werkzeuge.items() if w.integration == integration]
        for n in namen:
            del self._werkzeuge[n]
        return len(namen)

    def holen(self, name: str) -> Werkzeug | None:
        return self._werkzeuge.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._werkzeuge

    def __len__(self) -> int:
        return len(self._werkzeuge)

    def alle(self) -> list[Werkzeug]:
        return list(self._werkzeuge.values())

    def von_integration(self, integration: str) -> list[Werkzeug]:
        return [w for w in self._werkzeuge.values() if w.integration == integration]

    def als_openai(self) -> list[dict[str, Any]]:
        return [w.als_openai() for w in self._werkzeuge.values()]

    def infos(self) -> list[dict[str, Any]]:
        return [w.als_info() for w in self._werkzeuge.values()]

    async def ausfuehren(
        self, name: str, argumente: dict[str, Any], timeout: float | None = None, max_zeichen: int = MAX_ERGEBNIS_ZEICHEN
    ) -> tuple[bool, str]:
        """Führt ein Werkzeug aus; gibt (ok, Ergebnistext) zurück, wirft nie (außer bei Abbruch).

        `timeout` (Sekunden) ist eine Obergrenze für hängende Werkzeuge; `max_zeichen` kürzt den Ergebnistext
        (Standard für das Modell; die Bühne braucht das vollständige Ergebnis).
        """
        w = self.holen(name)
        if w is None:
            return False, f"Unbekanntes Werkzeug: {name}"
        try:
            if timeout and timeout > 0:
                ergebnis = await asyncio.wait_for(w.ausfuehren(**(argumente or {})), timeout)
            else:
                ergebnis = await w.ausfuehren(**(argumente or {}))
            return True, ergebnis_als_text(ergebnis, max_zeichen)
        except asyncio.TimeoutError:
            return False, f"Zeitüberschreitung: {name} hat nicht innerhalb von {timeout:.0f} s geantwortet."
        except WerkzeugFehler as e:
            return False, str(e)
        except TypeError as e:
            return False, f"Ungültige Argumente für {name}: {e}"
        except Exception as e:  # noqa: BLE001 - Fehler gehen als Text ans Modell
            return False, f"Fehler in {name}: {type(e).__name__}: {e}"
