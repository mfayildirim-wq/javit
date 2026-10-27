"""Einrichtungsschritte aus dem Katalog: prüfen (Datei vorhanden?), Dateien ablegen (Upload aus der
Oberfläche) und Befehle ausführen (z. B. die einmalige Anmeldung eines MCP-Servers).

Es werden nur Befehle und Dateiziele ausgeführt bzw. beschrieben, die im Katalog stehen – nie aus
einer Anfrage. Die Ausgabe eines Laufs landet in ``~/.jarvis/logs/einrichtung-<id>.log``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path
from typing import Any

from ..konfig import jarvis_home
from ..werkzeuge.prozess import befehl_zerlegen, erweiterter_path, programm_aufloesen
from .katalog import KatalogEintrag, Schritt

MAX_DATEI_BYTES = 1_000_000
ZEITLIMIT = 300.0
AUSGABE_ZEILEN = 40


class EinrichtungsFehler(ValueError):
    pass


def pfad_aufloesen(wert: str) -> Path:
    """``~`` auflösen; Platzhalter wie ``*``/``?`` sind keine Pfade."""
    wert = str(wert or "").strip()
    if not wert:
        raise EinrichtungsFehler("Leerer Pfad.")
    if any(z in wert for z in "*?"):
        raise EinrichtungsFehler(f"Platzhalter sind in Pfaden nicht erlaubt: {wert}")
    return Path(os.path.expanduser(wert))


def schritt_erfuellt(schritt: Schritt) -> bool | None:
    """True/False für prüfbare Schritte (Datei vorhanden), None wenn nichts prüfbar ist."""
    if schritt.datei:
        try:
            return pfad_aufloesen(schritt.datei).is_file()
        except EinrichtungsFehler:
            return False
    return None


def einrichtung_stand(eintrag: KatalogEintrag) -> list[dict[str, Any]]:
    return [{**s.als_info(), "erfuellt": schritt_erfuellt(s)} for s in eintrag.einrichtung]


def schritt_holen(eintrag: KatalogEintrag, nummer: int) -> Schritt:
    if nummer < 0 or nummer >= len(eintrag.einrichtung):
        raise EinrichtungsFehler(f"Schritt {nummer} gibt es bei „{eintrag.name}“ nicht.")
    return eintrag.einrichtung[nummer]


def datei_ablegen(eintrag: KatalogEintrag, nummer: int, inhalt_base64: str) -> Path:
    """Schreibt hochgeladenen Inhalt an das Datei-Ziel des Schritts (nur für Schritte mit ``datei``)."""
    schritt = schritt_holen(eintrag, nummer)
    if not schritt.datei:
        raise EinrichtungsFehler("Dieser Schritt erwartet keine Datei.")
    try:
        daten = base64.b64decode(str(inhalt_base64 or ""), validate=True)
    except (ValueError, TypeError) as e:
        raise EinrichtungsFehler("Dateiinhalt ist kein gültiges Base64.") from e
    if not daten:
        raise EinrichtungsFehler("Die Datei ist leer.")
    if len(daten) > MAX_DATEI_BYTES:
        raise EinrichtungsFehler(f"Die Datei ist zu groß (max. {MAX_DATEI_BYTES // 1000} kB).")
    ziel = pfad_aufloesen(schritt.datei)
    if ziel.suffix.lower() == ".json":
        try:
            json.loads(daten.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise EinrichtungsFehler("Erwartet wird eine JSON-Datei (z. B. die heruntergeladene OAuth-Client-Datei).") from e
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".tmp")
    tmp.write_bytes(daten)
    tmp.replace(ziel)
    try:
        os.chmod(ziel, 0o600)
    except OSError:
        pass
    return ziel


class SchrittLauf:
    def __init__(self, kennung: str, nummer: int, protokoll: Path):
        self.kennung = kennung
        self.nummer = nummer
        self.protokoll = protokoll
        self.status = "laeuft"
        self.rueckgabe: int | None = None
        self.start = time.monotonic()
        self.task: asyncio.Task[None] | None = None

    def ausgabe(self) -> list[str]:
        try:
            zeilen = self.protokoll.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return zeilen[-AUSGABE_ZEILEN:]

    def stand(self) -> dict[str, Any]:
        return {"status": self.status, "rueckgabe": self.rueckgabe, "ausgabe": self.ausgabe(), "sekunden": round(time.monotonic() - self.start)}


class Ausfuehrer:
    """Führt Einrichtungsbefehle im Hintergrund aus, höchstens einen je Katalogeintrag und Schritt."""

    def __init__(self) -> None:
        self.laeufe: dict[tuple[str, int], SchrittLauf] = {}

    def stand(self, kennung: str, nummer: int) -> dict[str, Any]:
        lauf = self.laeufe.get((kennung, nummer))
        return lauf.stand() if lauf else {"status": "nie", "rueckgabe": None, "ausgabe": [], "sekunden": 0}

    async def starten(self, eintrag: KatalogEintrag, nummer: int) -> dict[str, Any]:
        schritt = schritt_holen(eintrag, nummer)
        if not schritt.befehl:
            raise EinrichtungsFehler("Dieser Schritt hat keinen Befehl.")
        alt = self.laeufe.get((eintrag.id, nummer))
        if alt and alt.status == "laeuft":
            return alt.stand()
        ordner = jarvis_home() / "logs"
        ordner.mkdir(parents=True, exist_ok=True)
        protokoll = ordner / f"einrichtung-{eintrag.id}.log"
        protokoll.write_text(f"$ {schritt.befehl}\n", encoding="utf-8")
        lauf = SchrittLauf(eintrag.id, nummer, protokoll)
        self.laeufe[(eintrag.id, nummer)] = lauf
        lauf.task = asyncio.create_task(self._laufen(lauf, schritt.befehl), name=f"einrichtung-{eintrag.id}-{nummer}")
        return lauf.stand()

    async def _laufen(self, lauf: SchrittLauf, befehl: str) -> None:
        teile = befehl_zerlegen(befehl)
        pfad = erweiterter_path()
        programm = programm_aufloesen(teile[0], pfad) or teile[0]
        try:
            with lauf.protokoll.open("ab") as datei:
                prozess = await asyncio.create_subprocess_exec(
                    programm, *[os.path.expanduser(a) if a.startswith("~") else a for a in teile[1:]],
                    stdout=datei, stderr=datei, stdin=asyncio.subprocess.DEVNULL,
                    env={**os.environ, "PATH": pfad}, cwd=str(Path.home()),
                )
                try:
                    lauf.rueckgabe = await asyncio.wait_for(prozess.wait(), ZEITLIMIT)
                except asyncio.TimeoutError:
                    prozess.kill()
                    datei.write(f"\nZeitlimit von {ZEITLIMIT:.0f} s überschritten – abgebrochen.\n".encode())
                    lauf.status = "fehler"
                    return
            lauf.status = "fertig" if lauf.rueckgabe == 0 else "fehler"
        except (OSError, ValueError) as e:
            with lauf.protokoll.open("a", encoding="utf-8") as datei:
                datei.write(f"\nStart fehlgeschlagen: {e}\n")
            lauf.status = "fehler"
