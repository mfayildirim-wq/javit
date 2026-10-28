"""Die Anwendung des Assistenten (Klasse ``Jarvis``, Name einstellbar): verdrahtet Konfiguration, Geheimnisse, LLM, Werkzeuge, Integrationen,
Gedächtnis, Agent und (optional) das Sprachmodul. Wird vom Server und von der CLI genutzt."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from . import __version__
from .agent import Agent, freigabe_antwort_erkennen, fuer_sprache
from .gedaechtnis import Gedaechtnis
from .gedaechtnis_pflege import BenannterEinbetter, EinbetterKette, LokaleEinbettung, Nachbereiter
from .geheimnisse import Geheimnisspeicher
from .integrationen.katalog import Katalog
from .integrationen.manager import IntegrationsManager
from .integrationen.verzeichnisse import Verzeichnisse
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
        self._http_client_fabrik = http_client_fabrik
        # Audio im Browser: genau eine Sitzung (Sender der WebSocket-Verbindung, Quelle, Ziel)
        self._browser_audio: dict[str, Any] | None = None
        self._hoerer: list[Hoerer] = []
        self.llm = llm or LLMFassade(lambda: self.konfig.einstellungen)
        # Einbettungen: eingestelltes Modell (Ollama/Cloud), sonst lokal über fastembed, sonst Volltext
        self.gedaechtnis = Gedaechtnis(
            einbetten=EinbetterKette(
                BenannterEinbetter(self.llm.einbetten, lambda: self.einstellungen.einbettungs_modell),
                LokaleEinbettung(),
            )
        )
        self.nachbereiter = Nachbereiter(self.llm, self.gedaechtnis, lambda: self.konfig.einstellungen)
        self._pflege: set[asyncio.Task[Any]] = set()
        self.register = WerkzeugRegister()
        self.katalog = katalog or Katalog()
        self.manager = IntegrationsManager(
            self.register, self.geheimnisse, self.katalog, self.senden, http_client_fabrik=http_client_fabrik
        )
        self.manager.rueckruf_url = lambda: f"http://127.0.0.1:{self.einstellungen.port}/oauth/rueckruf"
        self.verzeichnisse = Verzeichnisse(
            lambda: self.einstellungen.verzeichnisse_eigene, http_client_fabrik=http_client_fabrik
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
            nach_antwort=self._nach_antwort,
            sprecher=self._sprechsitzung,
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
        self._gedaechtnis_beim_start()
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
        for t in list(self._pflege):
            t.cancel()
        if self.stimme is not None:
            try:
                await self.stimme.stop()
            except Exception:  # noqa: BLE001
                log.warning("Sprachmodul konnte nicht gestoppt werden", exc_info=True)
        await self.manager.alle_stoppen()
        self.gedaechtnis.schliessen()

    # ---------- Unterhaltungen und Gedächtnis-Pflege ----------
    def _pflege_starten(self, aufgabe: Awaitable[Any]) -> None:
        """Hintergrundaufgabe (Titel, Nachbereitung, Nachbetten); Fehler landen nur im Protokoll."""
        async def laufen() -> None:
            try:
                await aufgabe
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.warning("Gedächtnis-Pflege fehlgeschlagen", exc_info=True)

        task = asyncio.create_task(laufen())
        self._pflege.add(task)
        task.add_done_callback(self._pflege.discard)

    async def pflege_abwarten(self) -> None:
        """Wartet auf laufende Pflegeaufgaben (Tests, geordnetes Beenden)."""
        # Nur offene Tasks abwarten: gather über fertige Tasks kehrt synchron zurück, der
        # Aufräum-Callback (discard) käme sonst nie an die Reihe
        while offen := [t for t in self._pflege if not t.done()]:
            await asyncio.gather(*offen, return_exceptions=True)

    def _gedaechtnis_beim_start(self) -> None:
        """Alte, nie nachbereitete aktuelle Unterhaltung (> 6 h) nachbereiten; fehlende Einbettungen nachholen."""
        try:
            u = self.gedaechtnis.aktuelle()
            aktualisiert = datetime.fromisoformat(u["aktualisiert"])
        except (ValueError, KeyError, TypeError):
            return
        if u["nachrichten"] >= 2 and not u["nachbereitet"] and datetime.now() - aktualisiert > timedelta(hours=6):
            self._pflege_starten(self.nachbereiter.nachbereiten(u["id"]))
        self._pflege_starten(self.gedaechtnis.nachbetten())

    async def _unterhaltung_melden(self, u: dict[str, Any], grund: str) -> None:
        await self.senden({"typ": "unterhaltung", "id": u["id"], "titel": u["titel"], "grund": grund})

    async def _nach_antwort(self) -> None:
        """Nach der ersten vollständigen Antwort einer Unterhaltung: Titel im Hintergrund erzeugen."""
        u = self.gedaechtnis.aktuelle()
        if u["titel_fest"] or u["nachrichten"] != 2:
            return
        self._pflege_starten(self._titel_erzeugen(u["id"]))

    async def _titel_erzeugen(self, kennung: int) -> None:
        titel = await self.nachbereiter.titel_erzeugen(kennung)
        u = self.gedaechtnis.unterhaltung(kennung)
        if titel and u:
            await self._unterhaltung_melden(u, "titel")

    async def unterhaltung_neu(self, titel: str | None = None) -> dict[str, Any]:
        """Neue Unterhaltung beginnen; die verlassene wird im Hintergrund nachbereitet."""
        alt = self.gedaechtnis.aktuelle()
        neu = self.gedaechtnis.unterhaltung_neu(titel)
        if titel:
            self.gedaechtnis.unterhaltung_umbenennen(neu["id"], titel)
            neu = self.gedaechtnis.unterhaltung(neu["id"]) or neu
        self._pflege_starten(self.nachbereiter.nachbereiten(alt["id"]))
        await self._unterhaltung_melden(neu, "neu")
        return neu

    async def unterhaltung_aktivieren(self, kennung: int) -> dict[str, Any]:
        alt = self.gedaechtnis.aktuelle()
        u = self.gedaechtnis.unterhaltung_aktivieren(kennung)
        if alt["id"] != u["id"]:
            self._pflege_starten(self.nachbereiter.nachbereiten(alt["id"]))
            await self._unterhaltung_melden(u, "gewechselt")
        return u

    async def unterhaltung_umbenennen(self, kennung: int, titel: str) -> dict[str, Any]:
        u = self.gedaechtnis.unterhaltung_umbenennen(kennung, titel)
        await self._unterhaltung_melden(u, "titel")
        return u

    async def unterhaltung_loeschen(self, kennung: int) -> dict[str, Any]:
        ergebnis = self.gedaechtnis.unterhaltung_loeschen(kennung)
        await self._unterhaltung_melden(ergebnis["aktuell"], "geloescht")
        return ergebnis

    # ---------- Anfragen ----------
    async def anfrage(self, text: str, sprechen: bool = False, quelle: str = "text") -> str:
        antwort = await self.agent.verarbeiten(text, sprechen=sprechen, quelle=quelle)
        if sprechen and quelle != "stimme" and antwort and not self.agent.antwort_gesprochen:
            await self.vorlesen(antwort)  # Fallback ohne Sprachmodul (z. B. „say“ am Mac, SAPI/Piper)
        return antwort

    async def _sprechsitzung(self) -> Any:
        """Streaming-Sprachausgabe für den Agenten: Sitzung des StimmDienstes oder None (kein Sprachmodul)."""
        try:
            stimme = self._stimmdienst()
        except ImportError:
            return None
        sprecher = await stimme.sprecher_beginnen(antwort=True)
        if sprecher is None:
            return None

        class Sitzung:
            gesprochen = False

            @staticmethod
            def einspeisen(delta: str) -> None:
                sprecher.einspeisen(delta)

            @staticmethod
            async def abschliessen() -> None:
                await stimme.sprecher_abschliessen(sprecher)
                Sitzung.gesprochen = sprecher.gesprochen

            @staticmethod
            def stoppen() -> None:
                sprecher.stoppen()
                self._im_hintergrund(stimme.sprecher_abschliessen(sprecher))

        return Sitzung()

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

    # ---------- Audio im Browser ----------
    async def browser_audio_start(self, sender: Callable[[Any], Awaitable[None]], rate: int = 48000) -> bool:
        """Browser-Mikrofon als Audioquelle und Browser als Ausgabeziel (ersetzt eine frühere Sitzung)."""
        from .stimme.sprecher import BrowserQuelle, BrowserZiel  # optionales Modul

        try:
            stimme = self._stimmdienst()
        except Exception as e:  # noqa: BLE001
            await self.senden({"typ": "fehler", "text": self._stimm_fehlertext(e)})
            return False
        alt = self._browser_audio
        if alt is not None and alt["sender"] is not sender:
            try:
                await alt["sender"]({"typ": "sprachausgabe", "zustand": "gestoppt", "grund": "ersetzt"})
            except Exception:  # noqa: BLE001
                pass

        async def pegel(wert: float) -> None:
            await self.senden({"typ": "pegel", "wert": wert})

        quelle = BrowserQuelle(rate=max(8000, min(int(rate or 48000), 192000)))
        ziel = BrowserZiel(sender, pegel=pegel)
        self._browser_audio = {"sender": sender, "quelle": quelle, "ziel": ziel}
        stimme.ausgabe_setzen(ziel)
        await stimme.quelle_setzen(quelle, starten=True)
        return True

    def browser_audio_daten(self, sender: Any, daten: bytes) -> None:
        sitzung = self._browser_audio
        if sitzung is not None and sitzung["sender"] is sender:
            sitzung["quelle"].einspeisen(daten)

    async def browser_audio_stop(self, sender: Any) -> None:
        sitzung = self._browser_audio
        if sitzung is None or sitzung["sender"] is not sender:
            return
        self._browser_audio = None
        stimme = self.stimme
        if stimme is None:
            return
        stimme.ausgabe_setzen(None)
        await stimme.quelle_setzen(None, starten=False)

    @property
    def browser_audio_aktiv(self) -> bool:
        return self._browser_audio is not None

    async def stimme_probe(self, text: str | None = None) -> dict[str, Any]:
        """Spricht einen Probesatz über den aktuellen Weg; wirft StimmFehler, wenn der Weg nicht geht."""
        from .stimme.einstellungen import StimmEinstellungen
        from .stimme.fehler import StimmFehler
        from .stimme.tts import erzeuge_tts, tts_art

        e = StimmEinstellungen.aus(self.einstellungen)
        art = tts_art(e)
        if art == "aus":
            raise StimmFehler("Sprachausgabe ist ausgeschaltet.")
        if art == "openrouter" and not self.geheimnisse.hat("OPENROUTER_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
            raise StimmFehler("OpenRouter-Schlüssel fehlt (OPENROUTER_API_KEY) – unter Einstellungen → Schlüssel hinterlegen.")
        tts = erzeuge_tts(e)
        stimme = self._stimmdienst()
        satz = (text or "").strip() or f"Hallo, hier ist {self.name}. So klinge ich mit dieser Stimme."
        await stimme.sprechen(satz)
        return {
            "ok": True,
            "art": art,
            "modell": getattr(tts, "modell", "") or "",
            "stimme": getattr(tts, "stimme", "") or "",
            "ziel": "browser" if self.browser_audio_aktiv else "lautsprecher",
        }

    async def stimme_modelle(self) -> dict[str, Any]:
        from .stimme.sprecher import openrouter_sprachmodelle

        return await openrouter_sprachmodelle(self._http_client_fabrik)

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
            "unterhaltung": self._unterhaltung_kurz(),
        }

    def _unterhaltung_kurz(self) -> dict[str, Any]:
        u = self.gedaechtnis.aktuelle()
        return {"id": u["id"], "titel": u["titel"]}
