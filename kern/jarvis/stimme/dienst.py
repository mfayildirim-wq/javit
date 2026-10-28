"""StimmDienst – Weckwort → Aufnahme → Spracherkennung → Anfrage → Sprachausgabe.

Threads und asyncio:
* Das Mikrofon (sounddevice/PortAudio) liefert Rahmen in seinem eigenen Thread. Diese werden mit
  ``loop.call_soon_threadsafe`` in eine asyncio-Warteschlange gelegt (kein Blockieren des
  Audio-Threads, bei Überlauf werden die ältesten Rahmen verworfen).
* Ein Verarbeitungs-Task liest die Warteschlange. Die Weckwort-Erkennung (ONNX, CPU) läuft
  in einem eigenen Einzel-Thread-Executor, Spracherkennung per ``asyncio.to_thread``.
* Ereignisse an den Kern (``ereignis``) werden immer im Event-Loop gesendet.

Zustände (Modus): AUS → BEREIT (lauscht auf Weckwort) → AUFNAHME (hoert) → BESCHAEFTIGT
(denkt) → SPRICHT → (Folgefrage: AUFNAHME) → BEREIT.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Awaitable, Callable

import numpy as np

from .audio import AudioQuelle, MikrofonQuelle
from .einstellungen import StimmEinstellungen
from .fehler import StimmFehler, hinweis_mikrofon_rechte, kurz
from .stt import erzeuge_stt
from .sprecher import Ausgabeziel, LautsprecherZiel, Sprecher
from .text import fuer_sprache
from .tts import Abspieler, _plattform, erzeuge_tts, ton_datei
from .vad import ABTASTRATE, RAHMEN, Sprachpausenerkenner, erzeuge_vad, pegel_anzeige
from .weckwort import detektor_schluessel, erzeuge_detektor

log = logging.getLogger("jarvis.stimme")

Ereignis = Callable[[dict], Awaitable[None]]
Anfrage = Callable[[str], Awaitable[str]]

STILLE_FUER_RECHTEHINWEIS = int(3.0 * ABTASTRATE / RAHMEN)  # ~3 s nur digitale Nullen


class Modus(str, enum.Enum):
    AUS = "aus"
    BEREIT = "bereit"
    AUFNAHME = "aufnahme"
    BESCHAEFTIGT = "beschaeftigt"
    SPRICHT = "spricht"


class StimmDienst:
    """Sprachschnittstelle des Assistenten.

    ``StimmDienst(einstellungen, ereignis, anfrage)`` – ``einstellungen`` ist ein dict (ganz oder nur
    der Teil ``stimme``) oder ein Objekt mit Attribut ``stimme``. ``ereignis(dict)`` sendet
    WebSocket-Events (``zustand``, ``pegel``, ``transkript``, ``fehler``), ``anfrage(text)`` liefert
    die Antwort des Agenten, die der Dienst anschließend selbst vorliest.

    Die optionalen Schlüsselwort-Parameter dienen Tests und Sonderfällen (eigene Audioquelle usw.).
    """

    #: so lange nach der eigenen Ausgabe nichts auswerten (Nachhall, Selbsthören-Schutz)
    nachlauf_s: float = 0.35

    def __init__(
        self,
        einstellungen: Any,
        ereignis: Ereignis,
        anfrage: Anfrage,
        *,
        audioquelle: AudioQuelle | Callable[[StimmEinstellungen], AudioQuelle] | None = None,
        detektor=None,
        stt=None,
        tts=None,
        abspieler=None,
        ton: Callable[[], Any] | None = None,
        stopp_detektor=None,
        ausgabeziel: Ausgabeziel | Callable[[], Ausgabeziel] | None = None,
    ):
        self._einstellungs_quelle = einstellungen
        self._ereignis = ereignis
        self._anfrage = anfrage
        self._audioquelle_vorgabe = audioquelle
        self._detektor = detektor
        self._detektor_vorgegeben = detektor is not None
        self._stt_vorgabe, self._tts_vorgabe = stt, tts
        self._stt_cache: tuple[tuple, Any] | None = None
        self._tts_cache: tuple[tuple, Any] | None = None
        self._abspieler = abspieler or Abspieler()
        self._ton = ton
        # Streaming-Sprachausgabe (sprecher.py): laufende Sitzung, Ausgabeziel (Lautsprecher/Browser), Stoppwort
        self._sprecher: Sprecher | None = None
        self._ziel_vorgabe = ausgabeziel
        self._stopp_detektor = stopp_detektor
        self._stopp_detektor_vorgegeben = stopp_detektor is not None
        self._stopp_detektor_schluessel: tuple | None = None
        self._stoppwort_ausgeloest = False
        self._gesprochen_in_anfrage = False

        self._loop: asyncio.AbstractEventLoop | None = None
        self._quelle: AudioQuelle | None = None
        self._temporaer = False  # Mikrofon nur für einmal_zuhoeren() geöffnet
        self._weckwort_an = False
        self._rahmen: asyncio.Queue | None = None
        self._verarbeiter: asyncio.Task | None = None
        self._dialog_task: asyncio.Task | None = None
        self._hintergrund: set[asyncio.Task] = set()
        self._executor: ThreadPoolExecutor | None = None
        self._modus = Modus.AUS
        self._aufnahme: Sprachpausenerkenner | None = None
        self._aufnahme_ergebnis: asyncio.Future | None = None
        self._vad = None
        self._sprech_lock = asyncio.Lock()
        self._stopp = asyncio.Event()
        self._unterbrochen = False
        self._ignoriere_bis = 0.0
        self._null_rahmen = 0
        self._signal_gesehen = False
        self._rechte_gemeldet = False
        self._letzter_fehler: tuple[str, float] | None = None
        self._start_lock = asyncio.Lock()

    # ------------------------------------------------------------------------------------
    # Öffentliche Schnittstelle
    # ------------------------------------------------------------------------------------
    @property
    def einstellungen(self) -> StimmEinstellungen:
        quelle = self._einstellungs_quelle
        if callable(quelle) and not isinstance(quelle, dict) and not hasattr(quelle, "stimme"):
            quelle = quelle()  # Fabrik, z. B. lambda: konfig.einstellungen – immer aktuell
        return StimmEinstellungen.aus(quelle)

    @property
    def aktiv(self) -> bool:
        """Mikrofon offen und Weckwort-Erkennung an."""
        return self._quelle is not None and self._weckwort_an

    @property
    def hoert(self) -> bool:
        """Nimmt gerade eine Äußerung auf."""
        return self._modus is Modus.AUFNAHME

    @property
    def modus(self) -> str:
        return self._modus.value

    async def start(self) -> None:
        """Öffnet Mikrofon und Weckwort-Erkennung. Wirft nie – Probleme kommen als ``fehler``-Event."""
        async with self._start_lock:
            if self.aktiv:
                return
            e = self.einstellungen
            self._loop = asyncio.get_running_loop()
            try:
                await self._detektor_laden(e)
            except StimmFehler as f:
                await self._fehler(f.text)
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("Weckwort-Modell")
                await self._fehler(f"Weckwort-Erkennung konnte nicht gestartet werden ({kurz(exc)}).")
                return
            if self._quelle is not None and self._temporaer:
                self._temporaer = False  # laufendes einmal_zuhoeren() übernimmt das Mikrofon
            elif self._quelle is None:
                if not await self._quelle_oeffnen(e):
                    return
            self._weckwort_an = True
            if self._modus is Modus.AUS:
                self._modus = Modus.BEREIT
                await self._zustand("bereit")
            self._im_hintergrund(self._stt_vorbereiten())
            log.info("Sprachmodul aktiv – Weckwort „%s“ (%s)", e.weckwort, getattr(self._detektor, "engine", "eigener Detektor"))

    async def stop(self) -> None:
        """Schließt Mikrofon, bricht laufende Dialoge und Ausgaben ab."""
        async with self._start_lock:
            await self._stoppen_intern()

    async def sprechen(self, text: str) -> None:
        """Liest ``text`` vor (Markdown/Emojis werden entfernt). Ohne TTS (``tts=aus``) passiert nichts."""
        if not text or not fuer_sprache(text) or self._tts_holen() is None:
            return
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        laufend = self._sprecher
        if laufend is not None and not laufend.gestoppt:
            # Eine Sitzung spricht gerade (z. B. der Agent streamt): Text einreihen und warten, bis er gesprochen ist
            laufend.einspeisen(text + " ")
            await laufend.warten_bis_leer()
            return
        fremd = self._dialog_laeuft() and asyncio.current_task() is not self._dialog_task
        if fremd and self._modus is Modus.AUFNAHME:
            self._aufnahme_beenden(None)  # z. B. offenes Folgefrage-Fenster schließen
        self._unterbrochen = False
        await self._sprechen_intern(text)
        if self._dialog_laeuft():
            return  # der laufende Dialog setzt den Zustand selbst
        if self._unterbrochen and self.aktiv and self._modus is not Modus.AUFNAHME:
            # Barge-in per Weckwort während einer Ansage → direkt zuhören
            self._unterbrochen = False
            await self._weckwort_erkannt()
            return
        if self._modus is not Modus.AUFNAHME:
            self._modus = Modus.BEREIT if self._quelle is not None else Modus.AUS
            await self._zustand("bereit")

    async def einmal_zuhoeren(self, warten: bool = False) -> str | bool | None:
        """Push-to-talk: sofort eine Äußerung aufnehmen und beantworten (ohne Weckwort).

        Öffnet bei Bedarf das Mikrofon nur für diesen Dialog. Standardmäßig kehrt der Aufruf
        zurück, sobald die Aufnahme läuft (``True``/``False``); mit ``warten=True`` erst nach
        dem Dialog – Rückgabe ist dann der erkannte Text (oder ``None``).
        """
        self._loop = asyncio.get_running_loop()
        if self._modus is Modus.AUFNAHME:
            return (await self._dialog_abwarten()) if warten else True
        if self._modus is Modus.SPRICHT:
            self._ausgabe_stoppen()
            if self._dialog_laeuft():
                self._unterbrochen = True  # der Dialog nimmt direkt die nächste Frage auf
                return (await self._dialog_abwarten()) if warten else True
            async with self._sprech_lock:
                pass
            await asyncio.sleep(0)
            if self._dialog_laeuft():
                return (await self._dialog_abwarten()) if warten else True
        if self._modus is Modus.BESCHAEFTIGT and self._dialog_laeuft():
            return (await self._dialog_abwarten()) if warten else False
        if self._quelle is None:
            async with self._start_lock:
                if self._quelle is None:
                    if not await self._quelle_oeffnen(self.einstellungen):
                        return None if warten else False
                    self._temporaer = True
                    self._modus = Modus.BEREIT
        self._unterbrochen = False
        await self._weckwort_erkannt(push_to_talk=True)
        if warten:
            return await self._dialog_abwarten()
        return True

    async def antwort_abhoeren(self, warte_s: float | None = None) -> str | None:
        """Nimmt genau eine Äußerung auf und gibt den erkannten Text zurück – ohne ``anfrage()``.

        Gedacht für Rückfragen während einer laufenden Anfrage, z. B. Freigaben („Ja“/„Nein“).
        Sendet ``zustand=hoert``, Pegel und ``transkript``; danach wieder ``denkt`` (innerhalb
        eines Dialogs) bzw. ``bereit``. Rückgabe ``None``, wenn nichts gesagt wurde.
        """
        self._loop = asyncio.get_running_loop()
        if self._modus is Modus.AUFNAHME:
            return None
        laufend = self._sprecher
        if laufend is not None and not laufend.gestoppt:
            await laufend.warten_bis_leer()  # laufende Ausgabe erst zu Ende sprechen lassen
        else:
            async with self._sprech_lock:
                pass
        e = self.einstellungen
        warte_s = float(warte_s or e.warte_auf_sprache_s)
        temporaer = False
        if self._quelle is None:
            if not await self._quelle_oeffnen(e):
                return None
            temporaer = True
        vorher = self._modus
        im_dialog = self._dialog_laeuft()
        ergebnis = self._aufnahme_starten(e, warte_s)
        if e.bestaetigungston:
            self._ton_abspielen(e)
        await self._zustand("hoert")
        text = ""
        try:
            audio = await self._auf_aufnahme_warten(ergebnis, e, warte_s)
            if audio is not None and len(audio) >= ABTASTRATE // 5:
                text = await self._erkennen(audio)
            if text:
                await self._senden({"typ": "transkript", "text": text, "final": True})
        finally:
            if self._modus is Modus.AUFNAHME:
                self._aufnahme_beenden(None)
            if temporaer:
                await self._quelle_schliessen()
                self._modus = Modus.AUS
            else:
                self._modus = vorher if vorher is not Modus.AUFNAHME else Modus.BEREIT
                if self._modus is Modus.SPRICHT:
                    self._modus = Modus.BESCHAEFTIGT
            await self._zustand("denkt" if im_dialog else "bereit")
        return text or None

    # ------------------------------------------------------------------------------------
    # Laden / Öffnen / Schließen
    # ------------------------------------------------------------------------------------
    async def _detektor_laden(self, e: StimmEinstellungen) -> None:
        if self._detektor is None or (
            not self._detektor_vorgegeben and getattr(self._detektor, "schluessel", None) != detektor_schluessel(e)
        ):
            self._detektor = erzeuge_detektor(e)
        if not self._detektor_vorgegeben and hasattr(self._detektor, "schwelle"):
            self._detektor.schwelle = e.schwelle  # Vosk setzt sich nach einem Treffer selbst zurück
        laden = getattr(self._detektor, "laden", None)
        if callable(laden) and getattr(self._detektor, "_modell", True) is None:
            await asyncio.to_thread(laden)
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-weckwort")

    def _quelle_erzeugen(self, e: StimmEinstellungen) -> AudioQuelle:
        v = self._audioquelle_vorgabe
        if v is None:
            return MikrofonQuelle(e.geraet)
        if hasattr(v, "starten"):
            return v
        return v(e)

    async def _quelle_oeffnen(self, e: StimmEinstellungen) -> bool:
        self._loop = asyncio.get_running_loop()
        self._rahmen = asyncio.Queue(maxsize=250)
        self._vad = erzeuge_vad(e.vad)
        self._null_rahmen = 0
        self._signal_gesehen = False
        self._rechte_gemeldet = False
        try:
            quelle = self._quelle_erzeugen(e)
            await asyncio.to_thread(quelle.starten, self._rahmen_empfangen)
        except StimmFehler as f:
            await self._fehler(f.text)
            return False
        except Exception as exc:  # noqa: BLE001 – z. B. PortAudioError aus einer eigenen Quelle
            from .fehler import mikrofon_fehlertext

            await self._fehler(mikrofon_fehlertext(exc, e.geraet))
            return False
        self._quelle = quelle
        self._verarbeiter = asyncio.create_task(self._verarbeiten(), name="jarvis-stimme-verarbeitung")
        return True

    async def _quelle_schliessen(self) -> None:
        quelle, self._quelle = self._quelle, None
        self._weckwort_an = False
        self._temporaer = False
        if quelle is not None:
            try:
                await asyncio.to_thread(quelle.stoppen)
            except Exception:  # noqa: BLE001
                log.debug("Audioquelle ließ sich nicht sauber schließen", exc_info=True)
        task, self._verarbeiter = self._verarbeiter, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _stoppen_intern(self) -> None:
        self._ausgabe_stoppen()
        dialog, self._dialog_task = self._dialog_task, None
        if dialog is not None and not dialog.done() and dialog is not asyncio.current_task():
            dialog.cancel()
            await asyncio.gather(dialog, return_exceptions=True)
        self._aufnahme_beenden(None)
        await self._quelle_schliessen()
        for t in list(self._hintergrund):
            t.cancel()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        war_an = self._modus is not Modus.AUS
        self._modus = Modus.AUS
        if war_an:
            await self._zustand("bereit")

    # ------------------------------------------------------------------------------------
    # Audio-Thread → asyncio
    # ------------------------------------------------------------------------------------
    def _rahmen_empfangen(self, rahmen: np.ndarray) -> None:
        """Wird im Audio-Thread aufgerufen."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._einreihen, rahmen)
        except RuntimeError:  # Loop wird gerade beendet
            pass

    def _einreihen(self, rahmen: np.ndarray) -> None:
        q = self._rahmen
        if q is None:
            return
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(rahmen)

    def _rahmen_leeren(self) -> None:
        q = self._rahmen
        while q is not None and not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _verarbeiten(self) -> None:
        assert self._rahmen is not None
        while True:
            rahmen = await self._rahmen.get()
            try:
                await self._rahmen_verarbeiten(rahmen)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 – nie abstürzen
                log.exception("Fehler in der Audioverarbeitung")
                await self._fehler(f"Fehler in der Audioverarbeitung: {kurz(exc)}")

    async def _rahmen_verarbeiten(self, rahmen: np.ndarray) -> None:
        await self._rechte_pruefen(rahmen)
        loop = asyncio.get_running_loop()
        if loop.time() < self._ignoriere_bis:
            return  # Nachhall der eigenen Ausgabe
        modus = self._modus
        if modus is Modus.AUFNAHME and self._aufnahme is not None:
            self._aufnahme.zufuehren(rahmen)
            await self._senden({"typ": "pegel", "wert": pegel_anzeige(rahmen)})
            if self._aufnahme.fertig:
                self._aufnahme_beenden(self._aufnahme.audio())
            return
        if modus is Modus.BEREIT:
            if self._vad is not None:
                self._vad.ist_sprache(rahmen)  # Rauschpegel laufend nachführen
            if self._weckwort_an and self._dialog_task is None:
                e = self.einstellungen
                if await self._weckwort_score(rahmen) >= e.schwelle and self._modus is Modus.BEREIT:
                    await self._weckwort_erkannt()
        elif modus is Modus.SPRICHT:
            e = self.einstellungen
            if self._stopp_detektor is not None and await self._stoppwort_score(rahmen) >= min(e.schwelle + 0.2, 0.95):
                log.info("Stoppwort erkannt – Ausgabe wird abgebrochen")
                self._stoppwort_ausgeloest = True
                self._unterbrochen = False
                self._ausgabe_stoppen()
                await self._senden({"typ": "sprachausgabe", "zustand": "gestoppt", "grund": "stoppwort"})
                return
            if e.unterbrechen and self._weckwort_an:
                # Barge-in mit erhöhter Schwelle, damit die eigene Stimme nicht auslöst
                if await self._weckwort_score(rahmen) >= min(e.schwelle + 0.2, 0.95):
                    log.info("Weckwort während der Ausgabe – Ausgabe wird abgebrochen")
                    self._unterbrochen = True
                    self._ausgabe_stoppen()
        # BESCHAEFTIGT / SPRICHT ohne Barge-in: Rahmen verwerfen (Selbsthören-Schutz)

    async def _weckwort_score(self, rahmen: np.ndarray) -> float:
        if self._detektor is None:
            return 0.0
        try:
            loop = asyncio.get_running_loop()
            return float(await loop.run_in_executor(self._executor, self._detektor.pruefen, rahmen))
        except StimmFehler as f:
            self._weckwort_an = False
            await self._fehler(f.text)
        except Exception as exc:  # noqa: BLE001
            self._weckwort_an = False
            log.exception("Weckwort-Erkennung")
            await self._fehler(f"Weckwort-Erkennung ausgefallen ({kurz(exc)}). Bitte Sprache aus- und wieder einschalten.")
        return 0.0

    async def _stoppwort_score(self, rahmen: np.ndarray) -> float:
        detektor = self._stopp_detektor
        if detektor is None:
            return 0.0
        try:
            loop = asyncio.get_running_loop()
            return float(await loop.run_in_executor(self._executor, detektor.pruefen, rahmen))
        except Exception as exc:  # noqa: BLE001
            log.warning("Stoppwort-Erkennung ausgefallen: %s", kurz(exc))
            self._stopp_detektor = None
            return 0.0

    async def _stoppwort_laden(self, e: StimmEinstellungen) -> None:
        """Zweiter Vosk-Abgleich für das Stoppwort (lazy beim ersten Sprechen; leer = aus)."""
        if self._stopp_detektor_vorgegeben:
            return
        woerter = [w.strip() for w in (e.stoppwort or "").split(",") if w.strip()]
        schluessel = (tuple(woerter), e.vosk_modell, e.modell_verzeichnis)
        if not woerter:
            self._stopp_detektor = None
            self._stopp_detektor_schluessel = schluessel
            return
        if self._stopp_detektor is not None and self._stopp_detektor_schluessel == schluessel:
            return
        self._stopp_detektor_schluessel = schluessel
        try:
            from .weckwort_vosk import VoskWeckwortDetektor  # noqa: PLC0415

            detektor = VoskWeckwortDetektor(
                ", ".join(woerter),
                varianten=["stop", "stopp", "halt", "stopp jetzt", "sei still"],
                verzeichnis=Path(e.modell_verzeichnis) / "vosk",
                modell=e.vosk_modell,
                schwelle=e.schwelle,
                sha256=e.vosk_modell_sha256,
                nur_ganz=True,
            )
            await asyncio.to_thread(detektor.laden)
            self._stopp_detektor = detektor
        except StimmFehler as f:
            self._stopp_detektor = None
            await self._fehler(f"Stoppwort nicht verfügbar: {f.text}")
        except Exception as exc:  # noqa: BLE001
            self._stopp_detektor = None
            log.warning("Stoppwort-Detektor konnte nicht geladen werden: %s", kurz(exc))

    async def _detektor_zuruecksetzen(self) -> None:
        if self._detektor is None:
            return
        try:
            if self._executor is not None:
                await asyncio.get_running_loop().run_in_executor(self._executor, self._detektor.zuruecksetzen)
            else:
                self._detektor.zuruecksetzen()
        except Exception:  # noqa: BLE001
            log.debug("Weckwort-Detektor ließ sich nicht zurücksetzen", exc_info=True)

    async def _rechte_pruefen(self, rahmen: np.ndarray) -> None:
        """macOS liefert ohne Mikrofonberechtigung oft nur Nullen statt eines Fehlers."""
        if self._signal_gesehen or self._rechte_gemeldet:
            return
        if np.any(rahmen):
            self._signal_gesehen = True
            return
        self._null_rahmen += 1
        if self._null_rahmen >= STILLE_FUER_RECHTEHINWEIS:
            self._rechte_gemeldet = True
            await self._fehler(f"Das Mikrofon liefert nur Stille – vermutlich fehlt die Berechtigung. {hinweis_mikrofon_rechte()}")

    # ------------------------------------------------------------------------------------
    # Dialog
    # ------------------------------------------------------------------------------------
    def _dialog_laeuft(self) -> bool:
        return self._dialog_task is not None and not self._dialog_task.done()

    async def _dialog_abwarten(self):
        task = self._dialog_task
        if task is None:
            return None
        try:
            return await asyncio.shield(task)
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            return None

    async def _weckwort_erkannt(self, push_to_talk: bool = False) -> None:
        e = self.einstellungen
        ton = bool(e.bestaetigungston)
        ergebnis = self._aufnahme_starten(e, e.warte_auf_sprache_s, ignoriere_ms=150 if ton else 0)
        if ton:
            self._ton_abspielen(e)
        await self._zustand("hoert")
        self._dialog_task = asyncio.create_task(self._dialog(ergebnis), name="jarvis-stimme-dialog")

    def _aufnahme_starten(self, e: StimmEinstellungen, warte_s: float, ignoriere_ms: int = 0) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        self._aufnahme = Sprachpausenerkenner(
            vad=self._vad or erzeuge_vad(e.vad),
            stille_ms=e.stille_ms,
            max_aufnahme_s=e.max_aufnahme_s,
            warte_auf_sprache_s=warte_s,
            ignoriere_ms=ignoriere_ms,
        )
        self._aufnahme_ergebnis = loop.create_future()
        self._modus = Modus.AUFNAHME
        return self._aufnahme_ergebnis

    def _aufnahme_beenden(self, audio: np.ndarray | None) -> None:
        fut, self._aufnahme_ergebnis = self._aufnahme_ergebnis, None
        self._aufnahme = None
        if self._modus is Modus.AUFNAHME:
            self._modus = Modus.BESCHAEFTIGT
        if fut is not None and not fut.done():
            fut.set_result(audio)

    async def _auf_aufnahme_warten(self, fut: asyncio.Future, e: StimmEinstellungen, warte_s: float):
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=warte_s + e.max_aufnahme_s + 3.0)
        except asyncio.TimeoutError:  # keine Rahmen mehr (Mikrofon weg?)
            self._aufnahme_beenden(None)
            return None

    async def _dialog(self, ergebnis: asyncio.Future) -> str | None:
        erster_text: str | None = None
        e = self.einstellungen
        warte_s = e.warte_auf_sprache_s
        try:
            while True:
                audio = await self._auf_aufnahme_warten(ergebnis, e, warte_s)
                self._modus = Modus.BESCHAEFTIGT
                if audio is None or len(audio) < ABTASTRATE // 5:
                    break
                text = await self._erkennen(audio)
                if not text:
                    break
                erster_text = erster_text or text
                await self._senden({"typ": "transkript", "text": text, "final": True})
                await self._zustand("denkt")
                self._gesprochen_in_anfrage = False
                self._stoppwort_ausgeloest = False
                try:
                    antwort = await self._anfrage(text)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.exception("Anfrage fehlgeschlagen")
                    await self._fehler(f"Die Anfrage konnte nicht bearbeitet werden: {kurz(exc)}")
                    break
                if self._gesprochen_in_anfrage:
                    pass  # der Agent hat die Antwort bereits während der Anfrage gesprochen (Streaming)
                else:
                    self._unterbrochen = False
                    if antwort and str(antwort).strip():
                        await self._sprechen_intern(str(antwort))
                if self._quelle is None or self._stoppwort_ausgeloest:
                    break
                e = self.einstellungen
                if self._unterbrochen:  # Barge-in: sofort neue Frage aufnehmen
                    self._unterbrochen = False
                    warte_s = e.warte_auf_sprache_s
                    ergebnis = self._aufnahme_starten(e, warte_s)
                    if e.bestaetigungston:
                        self._ton_abspielen(e)
                    await self._zustand("hoert")
                    continue
                if e.folgemodus_s <= 0:
                    break
                # Folgefrage-Modus: ohne Weckwort weiter zuhören
                warte_s = e.folgemodus_s
                ergebnis = self._aufnahme_starten(e, warte_s)
                await self._zustand("hoert")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Fehler im Sprachdialog")
            await self._fehler(f"Fehler im Sprachdialog: {kurz(exc)}")
        finally:
            self._aufnahme_beenden(None)
            if self._dialog_task is asyncio.current_task():
                self._dialog_task = None
            await self._detektor_zuruecksetzen()
            self._rahmen_leeren()
            if self._quelle is not None and self._temporaer and not self._sprech_lock.locked():
                await self._quelle_schliessen()
                self._modus = Modus.AUS
                await self._zustand("bereit")
            elif not self._sprech_lock.locked():
                self._modus = Modus.BEREIT if self._quelle is not None else Modus.AUS
                await self._zustand("bereit")
            # sonst: eine fremde Ansage läuft gerade – sprechen() setzt den Zustand danach
        return erster_text

    async def _erkennen(self, audio: np.ndarray) -> str:
        try:
            stt = self._stt_holen()
            return (await stt.transkribieren(audio)).strip()
        except StimmFehler as f:
            await self._fehler(f.text)
        except Exception as exc:  # noqa: BLE001
            log.exception("Spracherkennung")
            await self._fehler(f"Spracherkennung fehlgeschlagen: {kurz(exc)}")
        return ""

    def _stt_holen(self):
        if self._stt_vorgabe is not None:
            return self._stt_vorgabe
        e = self.einstellungen
        schluessel = (e.stt, e.stt_modell, e.stt_cloud_modell, e.sprache)
        if self._stt_cache is None or self._stt_cache[0] != schluessel:
            self._stt_cache = (schluessel, erzeuge_stt(e))
        return self._stt_cache[1]

    def _tts_holen(self):
        if self._tts_vorgabe is not None:
            return self._tts_vorgabe
        e = self.einstellungen
        schluessel = (e.tts, e.tts_stimme, e.tts_cloud_modell, e.sprache, e.tts_tempo)
        if self._tts_cache is None or self._tts_cache[0] != schluessel:
            self._tts_cache = (schluessel, erzeuge_tts(e))
        return self._tts_cache[1]

    async def _stt_vorbereiten(self) -> None:
        try:
            stt = self._stt_holen()
            vorbereiten = getattr(stt, "vorbereiten", None)
            if vorbereiten is not None:
                await vorbereiten()
        except StimmFehler as f:
            await self._fehler(f.text)
        except Exception as exc:  # noqa: BLE001
            await self._fehler(f"Spracherkennung konnte nicht vorbereitet werden: {kurz(exc)}")

    # ------------------------------------------------------------------------------------
    # Sprachausgabe
    # ------------------------------------------------------------------------------------
    def _ziel_erzeugen(self) -> Ausgabeziel:
        v = self._ziel_vorgabe
        if v is None:
            return LautsprecherZiel(pegel=self._pegel)
        if callable(v) and not hasattr(v, "start"):
            return v()
        return v

    def ausgabe_setzen(self, ziel: Ausgabeziel | Callable[[], Ausgabeziel] | None) -> None:
        """Ausgabeziel wechseln: ``None`` = Lautsprecher, sonst z. B. ``BrowserZiel``."""
        self._ziel_vorgabe = ziel

    async def quelle_setzen(self, quelle: AudioQuelle | None, starten: bool | None = None) -> None:
        """Audioquelle wechseln (``None`` = Mikrofon). ``starten``: None = wie vorher, sonst an/aus."""
        async with self._start_lock:
            war_an = self.aktiv
            await self._stoppen_intern()
            self._audioquelle_vorgabe = quelle
        if starten if starten is not None else war_an:
            await self.start()

    async def sprecher_beginnen(self, antwort: bool = False) -> Sprecher | None:
        """Streaming-Sitzung: Text-Deltas mit ``einspeisen`` nachreichen, am Ende ``sprecher_abschliessen``.
        ``antwort=True`` = der Agent spricht die Antwort selbst (der Dialog liest sie dann nicht erneut vor).
        Ohne Sprachausgabe (``tts=aus``) ``None``."""
        tts = self._tts_holen()
        if tts is None:
            return None
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        laufend = self._sprecher
        if laufend is not None and not laufend.gestoppt:
            await laufend.warten_bis_leer()
        await self._sprech_lock.acquire()
        try:
            e = self.einstellungen
            self._stopp.clear()
            self._stoppwort_ausgeloest = False
            await self._stoppwort_laden(e)
            vorher = self._modus
            sprecher = Sprecher(
                tts,
                self._ziel_erzeugen(),
                abspieler=self._abspieler,
                pegel=self._pegel,
                stopp=self._stopp,
                fehler=lambda t: self._im_hintergrund(self._fehler(t)),
                bei_start=lambda: self._ausgabe_beginnt(vorher),
            )
            sprecher.modus_vorher = vorher  # type: ignore[attr-defined]
            sprecher.ist_antwort = antwort  # type: ignore[attr-defined]
            await sprecher.beginnen()
            self._sprecher = sprecher
            return sprecher
        except BaseException:
            self._sprech_lock.release()
            raise

    async def _ausgabe_beginnt(self, vorher: Modus) -> None:
        """Erster Ton: Zustand „spricht“ (Stoppwort/Barge-in werden ab jetzt geprüft)."""
        self._modus = Modus.SPRICHT
        await self._detektor_zuruecksetzen()
        await self._zustand("spricht")

    async def sprecher_abschliessen(self, sprecher: Sprecher) -> None:
        """Wartet, bis alles gesprochen ist, und räumt die Sitzung auf."""
        vorher = getattr(sprecher, "modus_vorher", self._modus)
        try:
            await sprecher.abschliessen()
        finally:
            if self._sprecher is sprecher:
                self._sprecher = None
            if sprecher.gesprochen and getattr(sprecher, "ist_antwort", False):
                self._gesprochen_in_anfrage = True
            # Selbsthören-Schutz: alles, was während der Ausgabe aufgenommen wurde, verwerfen
            self._rahmen_leeren()
            await self._detektor_zuruecksetzen()
            if self._loop is not None:
                self._ignoriere_bis = self._loop.time() + self.nachlauf_s
            if self._modus is Modus.SPRICHT:
                self._modus = Modus.BESCHAEFTIGT if vorher is not Modus.AUS else Modus.AUS
            self._sprech_lock.release()

    async def _sprechen_intern(self, text: str) -> None:
        sauber = fuer_sprache(text)
        if not sauber:
            return
        sprecher = await self.sprecher_beginnen()
        if sprecher is None:
            return
        sprecher.einspeisen(sauber)
        await self.sprecher_abschliessen(sprecher)

    def _ausgabe_stoppen(self) -> None:
        self._stopp.set()
        sprecher = self._sprecher
        if sprecher is not None:
            sprecher.stoppen()
        try:
            self._abspieler.abbrechen()
        except Exception:  # noqa: BLE001
            pass

    def _ton_abspielen(self, e: StimmEinstellungen) -> None:
        if self._ton is not None:
            try:
                ergebnis = self._ton()
                if asyncio.iscoroutine(ergebnis):
                    self._im_hintergrund(ergebnis)
            except Exception:  # noqa: BLE001
                log.debug("Bestätigungston fehlgeschlagen", exc_info=True)
            return
        if _plattform() != "mac":
            self._im_hintergrund(self._ton_ohne_mac(e))
            return
        datei = e.ton_datei
        if not datei or not Path(datei).exists() or not shutil.which("afplay"):
            return

        async def _abspielen():
            try:
                proc = await asyncio.create_subprocess_exec(
                    "afplay", datei, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
                await proc.wait()
            except Exception:  # noqa: BLE001
                log.debug("afplay fehlgeschlagen", exc_info=True)

        self._im_hintergrund(_abspielen())

    @staticmethod
    async def _ton_ohne_mac(e: StimmEinstellungen) -> None:
        """Windows/Linux: Ton-Datei aus den Einstellungen oder erzeugter „Pling“ über den Plattform-Abspieler."""
        try:
            await Abspieler().abspielen(ton_datei(e.ton_datei))
        except Exception:  # noqa: BLE001
            log.debug("Bestätigungston fehlgeschlagen", exc_info=True)

    # ------------------------------------------------------------------------------------
    # Ereignisse
    # ------------------------------------------------------------------------------------
    def _im_hintergrund(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._hintergrund.add(task)
        task.add_done_callback(self._hintergrund.discard)

    async def _senden(self, ereignis: dict) -> None:
        try:
            await self._ereignis(ereignis)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 – ein defekter Empfänger darf die Stimme nicht stoppen
            log.debug("Ereignis konnte nicht gesendet werden: %s", ereignis.get("typ"), exc_info=True)

    async def _zustand(self, zustand: str) -> None:
        await self._senden({"typ": "zustand", "zustand": zustand})

    async def _pegel(self, wert: float) -> None:
        await self._senden({"typ": "pegel", "wert": round(float(min(max(wert, 0.0), 1.0)), 3)})

    async def _fehler(self, text: str) -> None:
        log.warning("Stimme: %s", text)
        loop = asyncio.get_running_loop()
        jetzt = loop.time()
        if self._letzter_fehler and self._letzter_fehler[0] == text and jetzt - self._letzter_fehler[1] < 10:
            return  # gleiche Meldung nicht im Sekundentakt wiederholen
        self._letzter_fehler = (text, jetzt)
        await self._senden({"typ": "fehler", "text": text})
