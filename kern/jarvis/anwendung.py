"""Die Anwendung des Assistenten (Klasse ``Jarvis``, Name einstellbar): verdrahtet Konfiguration, Geheimnisse, LLM, Werkzeuge, Integrationen,
Gedächtnis, Agent und (optional) das Sprachmodul. Wird vom Server und von der CLI genutzt."""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from . import __version__
from .agent import Agent, freigabe_antwort_erkennen, fuer_sprache
from .gedaechtnis import Gedaechtnis
from .geheimnisse import Geheimnisspeicher
from .integrationen.katalog import Katalog
from .integrationen.manager import IntegrationsManager
from .konfig import Einstellungen, KonfigSpeicher, weckwort_engine
from .llm import LLMFassade
from .plattform import aktuelle_plattform
from .werkzeuge import WerkzeugRegister, dateien, desktop, mac, shell, system, web
from .werkzeuge import prozess

log = logging.getLogger("jarvis")

Hoerer = Callable[[dict[str, Any]], Awaitable[None]]


class Jarvis:
    def __init__(
        self,
        *,
        konfig: KonfigSpeicher | None = None,
        geheimnisse: Geheimnisspeicher | None = None,
        llm: LLMFassade | None = None,
        katalog: Katalog | None = None,
        http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
    ):
        self.konfig = konfig or KonfigSpeicher()
        self.geheimnisse = geheimnisse or Geheimnisspeicher()
        self._hoerer: list[Hoerer] = []
        self.llm = llm or LLMFassade(lambda: self.konfig.einstellungen)
        self.gedaechtnis = Gedaechtnis(einbetten=self.llm.einbetten)
        self.register = WerkzeugRegister()
        self.katalog = katalog or Katalog()
        self.manager = IntegrationsManager(
            self.register, self.geheimnisse, self.katalog, self.senden, http_client_fabrik=http_client_fabrik
        )
        self.agent = Agent(
            lambda: self.konfig.einstellungen,
            self.llm,
            self.register,
            self.gedaechtnis,
            self.senden,
            integrationen_info=self.manager.verbundene_beschreibungen,
            vorlesen=self.vorlesen,
            sprach_freigabe=self._sprach_freigabe,
        )
        self.stimme: Any = None
        self.stimme_fehler: str | None = None
        self._timer: set[asyncio.Task[None]] = set()
        self._start_task: asyncio.Task[None] | None = None
        self._stimm_task: asyncio.Task[Any] | None = None
        # Mac: alle Mac-Werkzeuge (inkl. Erinnerungen, Kalender, Notizen, Kurzbefehle);
        # Windows/Linux: die plattformneutralen Desktop-Werkzeuge mit gleichen Namen und Risikostufen
        self.plattform = aktuelle_plattform()
        self.register.alle_registrieren(desktop.plattform_werkzeuge(self.plattform))
        for modul in (dateien, shell, web):
            self.register.alle_registrieren(modul.werkzeuge())
        self.register.alle_registrieren(system.werkzeuge(self))

    @property
    def einstellungen(self) -> Einstellungen:
        return self.konfig.einstellungen

    @property
    def name(self) -> str:
        """Eingestellter Name des Assistenten (Standard „Javit“)."""
        return self.einstellungen.name

    # ---------- Ereignisse ----------
    def hoerer_hinzufuegen(self, hoerer: Hoerer) -> None:
        self._hoerer.append(hoerer)

    def hoerer_entfernen(self, hoerer: Hoerer) -> None:
        if hoerer in self._hoerer:
            self._hoerer.remove(hoerer)

    async def senden(self, ereignis: dict[str, Any]) -> None:
        for hoerer in list(self._hoerer):
            try:
                await hoerer(ereignis)
            except Exception:  # noqa: BLE001
                log.debug("Hörer-Fehler", exc_info=True)

    # ---------- Lebenszyklus ----------
    async def starten(self, integrationen: bool = True, stimme: bool = True) -> None:
        self.geheimnisse.in_umgebung_laden()
        if integrationen:
            self._start_task = asyncio.create_task(self.manager.alle_starten())
        if stimme and self.einstellungen.stimme.aktiv:
            await self.stimme_schalten(True, speichern=False)

    async def integrationen_abwarten(self) -> None:
        if self._start_task:
            await self._start_task

    async def stoppen(self) -> None:
        for t in list(self._timer):
            t.cancel()
        if self._stimm_task and not self._stimm_task.done():
            self._stimm_task.cancel()
        if self._start_task and not self._start_task.done():
            self._start_task.cancel()
        if self.stimme is not None:
            try:
                await self.stimme.stop()
            except Exception:  # noqa: BLE001
                log.warning("Sprachmodul konnte nicht gestoppt werden", exc_info=True)
        await self.manager.alle_stoppen()
        self.gedaechtnis.schliessen()

    # ---------- Anfragen ----------
    async def anfrage(self, text: str, sprechen: bool = False, quelle: str = "text") -> str:
        antwort = await self.agent.verarbeiten(text, sprechen=sprechen, quelle=quelle)
        if sprechen and quelle != "stimme" and antwort:
            await self.vorlesen(antwort)
        return antwort

    async def _stimm_anfrage(self, text: str) -> str:
        return await self.agent.verarbeiten(text, sprechen=True, quelle="stimme")

    async def vorlesen(self, text: str) -> None:
        text = fuer_sprache(text)
        if not text:
            return
        if self.stimme is not None and hasattr(self.stimme, "sprechen"):
            await self.stimme.sprechen(text)
            return
        if prozess.ist_mac() and shutil.which("say"):
            await self.senden({"typ": "zustand", "zustand": "spricht"})
            try:
                await prozess.ausfuehren("say", text, timeout=120)
            finally:
                await self.senden({"typ": "zustand", "zustand": self.agent.zustand})
        elif not prozess.ist_mac():
            await self._vorlesen_ohne_stimmdienst(text)

    async def _vorlesen_ohne_stimmdienst(self, text: str) -> None:
        """Windows/Linux ohne laufendes Sprachmodul (z. B. ``jarvis sag --sprechen``): einmalige
        Sprachausgabe mit der TTS-Einstellung (SAPI bzw. Piper/espeak-ng). Fehlt das Sprach-Extra,
        passiert nichts."""
        try:
            from .stimme.tts import einmal_vorlesen
        except ImportError:
            return
        await self.senden({"typ": "zustand", "zustand": "spricht"})
        try:
            await einmal_vorlesen(text, self.einstellungen)
        except Exception as e:  # noqa: BLE001
            log.info("Sprachausgabe nicht möglich: %s", e)
        finally:
            await self.senden({"typ": "zustand", "zustand": self.agent.zustand})

    def _stimmdienst(self) -> Any:
        """Erzeugt den StimmDienst bei Bedarf (ImportError, wenn das Modul fehlt)."""
        if self.stimme is None:
            from .stimme import StimmDienst  # optionales Modul

            self.stimme = StimmDienst(lambda: self.einstellungen, self.senden, self._stimm_anfrage)
        return self.stimme

    def _stimm_fehlertext(self, e: BaseException) -> str:
        if isinstance(e, ImportError):
            return "Sprachmodul nicht verfügbar – bitte installieren: pip install 'jarvis[stimme]'"
        return f"Sprachmodul-Fehler: {e}"

    def _im_hintergrund(self, koroutine: Any) -> asyncio.Task[Any]:
        """Startet Sprachaufgaben nicht blockierend (z. B. Laden des Weckwort-Modells) und meldet Fehler."""

        async def lauf() -> Any:
            try:
                return await koroutine
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.stimme_fehler = self._stimm_fehlertext(e)
                await self.senden({"typ": "fehler", "text": self.stimme_fehler})
                return None

        task = asyncio.create_task(lauf())
        self._stimm_task = task
        return task

    async def stimme_schalten(self, aktiv: bool, speichern: bool = True) -> bool:
        """Sprachmodul (Weckwort/Mikrofon) an- oder ausschalten. Start läuft im Hintergrund."""
        try:
            if aktiv:
                self._im_hintergrund(self._stimmdienst().start())
            elif self.stimme is not None:
                await self.stimme.stop()
            self.stimme_fehler = None
        except Exception as e:  # noqa: BLE001 - ImportError (Extra fehlt) oder Gerätefehler
            self.stimme_fehler = self._stimm_fehlertext(e)
            await self.senden({"typ": "fehler", "text": self.stimme_fehler})
            return False
        if speichern:
            self.konfig.aktualisieren({"stimme": {"aktiv": aktiv}})
        return True

    async def stimme_neu_starten(self) -> None:
        """Nach Änderung von Weckwort/Engine/Modell: laufendes Sprachmodul mit neuen Einstellungen starten."""
        if self.stimme is None or not self.einstellungen.stimme.aktiv:
            return
        try:
            await self.stimme.stop()
        except Exception:  # noqa: BLE001
            log.debug("Sprachmodul ließ sich nicht stoppen", exc_info=True)
        await self.stimme_schalten(True, speichern=False)

    async def zuhoeren(self) -> bool:
        """Push-to-talk: einmal zuhören ohne Weckwort (WebSocket-Typ „zuhoeren“)."""
        try:
            self._im_hintergrund(self._stimmdienst().einmal_zuhoeren())
        except Exception as e:  # noqa: BLE001
            self.stimme_fehler = self._stimm_fehlertext(e)
            await self.senden({"typ": "fehler", "text": self.stimme_fehler})
            return False
        return True

    async def _sprach_freigabe(self, frage: str) -> bool | None:
        """Freigabe per Sprache: fragt nach und hört auf „Ja“/„Nein“ (max. zwei Versuche)."""
        stimme = self.stimme
        if stimme is None or not hasattr(stimme, "antwort_abhoeren"):
            await self.vorlesen(frage)
            return None
        await stimme.sprechen(frage)
        for _ in range(2):
            text = await stimme.antwort_abhoeren(15)
            if not text:
                return None
            antwort = freigabe_antwort_erkennen(text)
            if antwort is not None:
                return antwort
            await stimme.sprechen("Bitte antworten Sie mit Ja oder Nein.")
        return None

    # ---------- Timer & proaktive Meldungen ----------
    async def timer_stellen(self, sekunden: float, text: str) -> None:
        async def ablauf() -> None:
            await asyncio.sleep(sekunden)
            await self.melden(f"Der Timer „{text}“ ist abgelaufen.")

        task = asyncio.create_task(ablauf())
        self._timer.add(task)
        task.add_done_callback(self._timer.discard)

    async def melden(self, text: str) -> None:
        """Proaktive Nachricht: Oberfläche, Desktop-Mitteilung (macOS/Windows/Linux) und Sprache."""
        e = self.einstellungen
        if e.anrede_verwenden and e.anrede:
            text = f"{e.anrede}, {text[0].lower()}{text[1:]}" if text else text
        antwort_id = f"meldung_{uuid.uuid4().hex[:12]}"
        await self.senden({"typ": "antwort_start", "id": antwort_id})
        await self.senden({"typ": "antwort_ende", "id": antwort_id, "text": text})
        self.gedaechtnis.verlauf_hinzufuegen("jarvis", text)
        if prozess.ist_mac():
            try:
                await mac.mitteilung_anzeigen.ausfuehren(text=text, titel=self.name)
            except Exception:  # noqa: BLE001
                pass
        else:
            await self._desktop_mitteilung(text)
        try:
            await self.vorlesen(text)
        except Exception:  # noqa: BLE001
            pass

    async def _desktop_mitteilung(self, text: str) -> None:
        """Windows/Linux: Desktop-Mitteilung (Toast bzw. notify-send); Fehler werden ignoriert."""
        try:
            await desktop.mitteilung_anzeigen.ausfuehren(text=text, titel=self.name)
        except Exception:  # noqa: BLE001
            log.debug("Mitteilung nicht möglich", exc_info=True)

    # ---------- Status ----------
    def status(self) -> dict[str, Any]:
        e = self.einstellungen
        return {
            "version": __version__,
            "name": e.name,
            "modell": e.modell,
            "stimme": {
                "aktiv": e.stimme.aktiv,
                "weckwort": e.stimme.weckwort,
                "hoert": bool(getattr(self.stimme, "hoert", False)),
                "engine": weckwort_engine(e.stimme),
            },
            "integrationen": len(self.manager.konfigs),
            "werkzeuge": len(self.register),
            "zustand": self.agent.zustand,
            "plattform": self.plattform,
        }
