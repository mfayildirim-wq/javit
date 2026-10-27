"""macOS-Implementierung der Systemaktionen.

Delegiert an die unveränderten Mac-Werkzeuge in ``werkzeuge/mac.py`` (AppleScript, ``open``,
``pbcopy`` …), damit sich das Verhalten auf dem Mac durch die Plattform-Schicht nicht ändert.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import Systemaktionen


class MacAktionen(Systemaktionen):
    plattform = "mac"

    @staticmethod
    def _mac():
        from ..werkzeuge import mac

        return mac

    async def app_oeffnen(self, name: str) -> str:
        return await self._mac().app_oeffnen.ausfuehren(name=name)

    async def app_beenden(self, name: str) -> str:
        return await self._mac().app_beenden.ausfuehren(name=name)

    async def laufende_apps(self) -> str:
        return await self._mac().laufende_apps.ausfuehren()

    async def lautstaerke_setzen(self, prozent: int | None, aenderung: int | None, stumm: bool | None) -> str:
        return await self._mac().lautstaerke_setzen.ausfuehren(prozent=prozent, aenderung=aenderung, stumm=stumm)

    async def mitteilung_anzeigen(self, text: str, titel: str) -> str:
        return await self._mac().mitteilung_anzeigen.ausfuehren(text=text, titel=titel)

    async def musik_steuern(self, aktion: str, app: str, suchbegriff: str | None) -> str:
        return await self._mac().musik_steuern.ausfuehren(aktion=aktion, app=app, suchbegriff=suchbegriff)

    async def url_oeffnen(self, url: str) -> str:
        return await self._mac().url_oeffnen.ausfuehren(url=url)

    async def zwischenablage_lesen(self) -> str:
        return await self._mac().zwischenablage_lesen.ausfuehren()

    async def zwischenablage_schreiben(self, text: str) -> str:
        return await self._mac().zwischenablage_schreiben.ausfuehren(text=text)

    async def bildschirmfoto(self, pfad: str) -> str:
        return await self._mac().bildschirmfoto.ausfuehren(pfad=pfad)

    async def systeminfo(self) -> str:
        return await self._mac().systeminfo.ausfuehren()

    async def in_papierkorb(self, pfad: Path) -> str:
        mac = self._mac()
        await mac.osascript(f'tell application "Finder" to delete (POSIX file {mac.as_text(str(pfad))})')
        return f"{pfad} liegt jetzt im Papierkorb."

    async def dateien_suchen(self, anfrage: str, ordner: str, nur_namen: bool, max_treffer: int) -> list[str]:
        import shutil

        from ..werkzeuge import prozess

        if not shutil.which("mdfind"):
            return []
        befehl = ["mdfind", "-onlyin", ordner]
        befehl += ["-name", anfrage] if nur_namen else [anfrage]
        erg = await prozess.ausfuehren(*befehl, timeout=30)
        return [z for z in erg.ausgabe.splitlines() if z.strip()] if erg.ok else []

    def shell_befehl(self, befehl: str) -> list[str]:
        shell = "/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/sh"
        return [shell, "-c", befehl]
