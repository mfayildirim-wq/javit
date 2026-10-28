"""Sprachausgabe: macOS ``say``, Windows SAPI (System.Speech über PowerShell), Linux Piper
(Fallback espeak-ng) oder Cloud-TTS über LiteLLM. Wiedergabe: macOS ``afplay``, Linux
``pw-play``/``paplay``/``aplay``, Windows ``winsound``.

Einstellung ``tts``: ``auto`` (Standard; Mac → say, Windows → sapi, Linux → piper mit Fallback
espeak-ng), ``say``, ``sapi``, ``piper``, ``espeak``, ``cloud`` oder ``aus``. ``say`` außerhalb des
Macs wird wie ``auto`` behandelt.

Beide Varianten erzeugen zuerst eine WAV-Datei und spielen sie dann ab. So kann während der
Wiedergabe ein synchroner Pegel (Orb-Animation) gesendet und die Ausgabe jederzeit
abgebrochen werden (Barge-in, ``stop()``).

Der Text wird nie als Kommandozeilenargument übergeben, sondern über stdin (``say -f -``,
``espeak-ng --stdin``, Piper) bzw. Base64-kodiert über stdin an PowerShell (SAPI) – dadurch ist
kein Escaping nötig und Texte, die mit „-“ beginnen, werden nicht als Option gelesen.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Protocol

import numpy as np

from .audio import wav_bytes, wav_lesen
from .fehler import StimmFehler, kurz

log = logging.getLogger("jarvis.stimme.tts")

PEGEL_RATE = 15  # Pegel-Events pro Sekunde

BEVORZUGTE_STIMMEN = ("Anna", "Petra", "Helena", "Markus", "Yannick", "Viktor", "Martin")
SPASS_STIMMEN = {"eddy", "flo", "grandma", "grandpa", "reed", "rocko", "sandy", "shelley", "bad news", "bahh",
                 "bells", "boing", "bubbles", "cellos", "good news", "jester", "organ", "superstar", "trinoids",
                 "whisper", "wobble", "zarvox", "albert", "fred", "junior", "kathy", "ralph"}

_SAY_ZEILE = re.compile(r"^(?P<name>.+?)\s+(?P<sprache>[a-z]{2,3}[_-][A-Za-z0-9]{2,4})\s+#")


@dataclass
class SayStimme:
    name: str
    sprache: str

    @property
    def qualitaet(self) -> int:
        n = self.name.lower()
        if "premium" in n:
            return 3
        if "enhanced" in n or "erweitert" in n:
            return 2
        return 1

    @property
    def basisname(self) -> str:
        return self.name.split("(")[0].strip()


def say_stimmen_parsen(ausgabe: str) -> list[SayStimme]:
    stimmen = []
    for zeile in ausgabe.splitlines():
        m = _SAY_ZEILE.match(zeile.strip())
        if m:
            stimmen.append(SayStimme(m.group("name").strip(), m.group("sprache").replace("-", "_")))
    return stimmen


def beste_say_stimme(stimmen: list[SayStimme], sprache: str = "de", wunsch: str = "") -> str | None:
    """Gewünschte Stimme, sonst beste deutsche: Premium > Enhanced > normal, dann Anna > Petra > …"""
    if wunsch:
        for s in stimmen:
            if s.name.lower() == wunsch.lower():
                return s.name
        for s in stimmen:
            if s.basisname.lower() == wunsch.lower():
                return s.name
    passend = [s for s in stimmen if s.sprache.lower().startswith(sprache.lower() + "_")]
    passend = [s for s in passend if s.basisname.lower() not in SPASS_STIMMEN] or passend
    if not passend:
        return wunsch or None

    def rang(s: SayStimme):
        try:
            vorliebe = BEVORZUGTE_STIMMEN.index(s.basisname)
        except ValueError:
            vorliebe = len(BEVORZUGTE_STIMMEN)
        land = 0 if s.sprache.upper().endswith("_" + sprache.upper()) else 1  # de_DE vor de_AT/de_CH
        return (-s.qualitaet, land, vorliebe, s.name)

    return sorted(passend, key=rang)[0].name


# --------------------------------------------------------------------------------------------
# Prozesse (für Tests austauschbar)
# --------------------------------------------------------------------------------------------
async def prozess_ausfuehren(befehl: list[str], eingabe: bytes | None = None, timeout: float = 60) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *befehl,
        stdin=asyncio.subprocess.PIPE if eingabe is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        aus, err = await asyncio.wait_for(proc.communicate(eingabe), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        _beenden(proc)
        raise
    return proc.returncode, aus, err


def _beenden(proc) -> None:
    try:
        if proc.returncode is None:
            proc.terminate()
    except ProcessLookupError:
        pass


def _plattform() -> str:
    from ..plattform import aktuelle_plattform

    return aktuelle_plattform()


# Linux-Abspielprogramme: WAV bevorzugt über PipeWire/PulseAudio/ALSA, andere Formate über mpv/ffplay
LINUX_ABSPIELER_WAV = (("pw-play",), ("paplay",), ("aplay", "-q"))
LINUX_ABSPIELER_ANDERE = (("mpv", "--no-video", "--really-quiet"), ("ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"),
                          ("pw-play",), ("paplay",))


class Abspieler:
    """Spielt Audiodateien ab und meldet dabei den Pegel (15/s).

    ``programm`` erzwingt ein Abspielprogramm; ohne Angabe: macOS ``afplay``, Linux ``pw-play``/
    ``paplay``/``aplay`` (bzw. ``mpv``/``ffplay`` für MP3), Windows ``winsound`` (nur WAV).
    """

    def __init__(self, programm: str | None = None):
        self.programm = programm
        self._proc = None
        self._beenden_fn: Callable[[], None] | None = None

    def befehl(self, pfad: str) -> list[str] | None:
        """Abspielbefehl für ``pfad``; ``None`` = Windows-``winsound``."""
        programm = self.programm or ("afplay" if _plattform() == "mac" else None)
        if programm:
            if not shutil.which(programm):
                zusatz = " (nur unter macOS verfügbar)" if programm == "afplay" else ""
                raise StimmFehler(f"Wiedergabeprogramm „{programm}“ nicht gefunden{zusatz}.")
            return [programm, pfad]
        if _plattform() == "windows":
            return None
        kandidaten = LINUX_ABSPIELER_WAV if pfad.lower().endswith(".wav") else LINUX_ABSPIELER_ANDERE
        for kandidat in kandidaten:
            if shutil.which(kandidat[0]):
                return [*kandidat, pfad]
        from ..plattform.gemeinsam import installationsbefehl

        raise StimmFehler(
            "Kein Wiedergabeprogramm gefunden (pw-play, paplay oder aplay"
            + ("" if pfad.lower().endswith(".wav") else ", für MP3 mpv oder ffplay")
            + f"). Installieren mit: {installationsbefehl('paplay')}"
        )

    @staticmethod
    def _winsound_starten(pfad: str, huellkurve):
        """Windows: asynchrone Wiedergabe mit ``winsound``; Dauer aus der WAV-Hüllkurve."""
        if huellkurve is None:
            raise StimmFehler(
                "Unter Windows lassen sich nur WAV-Dateien abspielen – für Cloud-Stimmen ein Modell mit WAV-Ausgabe "
                "wählen oder in den Einstellungen „Automatisch“ (Windows-Sprachausgabe) nutzen."
            )
        import winsound  # noqa: PLC0415 - nur unter Windows vorhanden

        ende = asyncio.Event()
        winsound.PlaySound(pfad, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

        async def warten() -> None:
            try:
                await asyncio.wait_for(ende.wait(), len(huellkurve) / PEGEL_RATE + 0.15)
            except asyncio.TimeoutError:
                pass

        def beenden() -> None:
            winsound.PlaySound(None, winsound.SND_PURGE)
            ende.set()

        return asyncio.ensure_future(warten()), beenden

    async def abspielen(self, pfad: str, pegel: Callable[[float], Awaitable[None]] | None = None,
                        stopp: asyncio.Event | None = None) -> None:
        befehl = self.befehl(pfad)
        huellkurve = _huellkurve(pfad)
        if befehl is None:
            warten, beenden = self._winsound_starten(pfad, huellkurve)
        else:
            self._proc = proc = await asyncio.create_subprocess_exec(
                *befehl, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            warten = asyncio.ensure_future(proc.wait())

            def beenden() -> None:
                _beenden(proc)

        self._beenden_fn = beenden
        loop = asyncio.get_running_loop()
        start = loop.time()
        try:
            while not warten.done():
                if stopp is not None and stopp.is_set():
                    beenden()
                    break
                if pegel is not None:
                    t = loop.time() - start
                    if huellkurve is not None:
                        i = int(t * PEGEL_RATE)
                        await pegel(float(huellkurve[i]) if i < len(huellkurve) else 0.0)
                    else:  # unbekanntes Format (z. B. mp3): gleichmäßige Animation
                        await pegel(0.45 + 0.25 * math.sin(t * 9.0))
                await asyncio.wait({warten}, timeout=1 / PEGEL_RATE)
            await warten
        except asyncio.CancelledError:
            beenden()
            raise
        finally:
            self._proc = None
            self._beenden_fn = None
            if pegel is not None:
                await pegel(0.0)

    def abbrechen(self) -> None:
        if self._beenden_fn is not None:
            self._beenden_fn()


def _huellkurve(pfad: str) -> np.ndarray | None:
    """Pegel 0..1 je 1/15 s aus einer WAV-Datei (andere Formate: None)."""
    try:
        daten, rate = wav_lesen(pfad)
    except Exception:  # noqa: BLE001
        return None
    fenster = max(int(rate / PEGEL_RATE), 1)
    n = len(daten) // fenster
    if n == 0:
        return np.zeros(1)
    x = daten[: n * fenster].astype(np.float32).reshape(n, fenster) / 32768.0
    rms = np.sqrt(np.mean(x * x, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    return np.clip((db + 50) / 40, 0.0, 1.0)


# --------------------------------------------------------------------------------------------
# Synthese
# --------------------------------------------------------------------------------------------
class Sprachsynthese(Protocol):
    async def synthetisieren(self, text: str, ziel: str) -> str:
        """Erzeugt eine Audiodatei für ``text`` (Pfad-Vorschlag ``ziel``) und gibt ihren Pfad zurück."""


class SayTTS:
    """macOS ``say``. Stimme: Einstellung ``tts_stimme`` oder automatisch die beste deutsche."""

    def __init__(self, stimme: str = "", sprache: str = "de", tempo: int = 0, ausfuehren=prozess_ausfuehren):
        self.wunsch = stimme or ""
        self.sprache = sprache or "de"
        self.tempo = int(tempo or 0)
        self._ausfuehren = ausfuehren
        self._stimme: str | None = None
        self._ermittelt = False

    async def stimme(self) -> str | None:
        if not self._ermittelt:
            try:
                code, aus, _ = await self._ausfuehren(["say", "-v", "?"], None, 15)
                stimmen = say_stimmen_parsen(aus.decode("utf-8", "replace")) if code == 0 else []
            except (FileNotFoundError, OSError):
                stimmen = []
            self._stimme = beste_say_stimme(stimmen, self.sprache, self.wunsch) if stimmen else (self.wunsch or None)
            self._ermittelt = True
            log.info("say-Stimme: %s", self._stimme or "Systemstandard")
        return self._stimme

    async def befehl(self, ziel: str) -> list[str]:
        befehl = ["say"]
        stimme = await self.stimme()
        if stimme:
            befehl += ["-v", stimme]
        if self.tempo > 0:
            befehl += ["-r", str(self.tempo)]
        befehl += ["-o", ziel, "--file-format=WAVE", "--data-format=LEI16@22050", "-f", "-"]
        return befehl

    async def synthetisieren(self, text: str, ziel: str) -> str:
        if sys.platform != "darwin" and not shutil.which("say"):
            raise StimmFehler("Sprachausgabe mit „say“ gibt es nur unter macOS – in den Einstellungen tts=cloud wählen.")
        ziel = str(Path(ziel).with_suffix(".wav"))
        try:
            code, _, err = await self._ausfuehren(await self.befehl(ziel), text.encode("utf-8"), 120)
        except FileNotFoundError as exc:
            raise StimmFehler("Programm „say“ nicht gefunden (nur unter macOS verfügbar).") from exc
        if code != 0:
            raise StimmFehler(f"say ist fehlgeschlagen: {kurz(err.decode('utf-8', 'replace') or code)}")
        return ziel


class CloudTTS:
    """Sprachausgabe über ``litellm.aspeech`` (z. B. ``openai/tts-1``)."""

    def __init__(self, modell: str = "openai/tts-1", stimme: str = "", **parameter):
        self.modell = modell or "openai/tts-1"
        self.stimme = stimme or "onyx"
        self.parameter = parameter

    async def synthetisieren(self, text: str, ziel: str) -> str:
        try:
            import litellm  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"LiteLLM ist nicht installiert ({kurz(exc)}).") from exc
        try:
            antwort = await litellm.aspeech(
                model=self.modell, input=text, voice=self.stimme, response_format="wav", **self.parameter
            )
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"Cloud-Sprachausgabe ({self.modell}) fehlgeschlagen: {kurz(exc)}. API-Schlüssel hinterlegt?") from exc
        daten = getattr(antwort, "content", None)
        if daten is None and hasattr(antwort, "read"):
            daten = antwort.read()
        if isinstance(daten, str):
            daten = daten.encode("latin-1")
        if not daten:
            raise StimmFehler("Cloud-Sprachausgabe lieferte keine Audiodaten.")
        endung = ".wav" if bytes(daten[:4]) == b"RIFF" else ".mp3"
        ziel = str(Path(ziel).with_suffix(endung))
        Path(ziel).write_bytes(bytes(daten))
        return ziel


# Windows: SAPI (System.Speech) über PowerShell. Alle Daten (Text, Ziel, Stimme) kommen als
# Base64-kodiertes JSON über stdin – nie über die Kommandozeile.
SKRIPT_SAPI = r"""
$daten = (Jarvis-Eingabe) | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$sprecher = New-Object System.Speech.Synthesis.SpeechSynthesizer
$stimmen = @($sprecher.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo })
$wahl = $null
if ($daten.stimme) {
  $wahl = $stimmen | Where-Object { $_.Name.IndexOf([string]$daten.stimme, [StringComparison]::OrdinalIgnoreCase) -ge 0 } | Select-Object -First 1
}
if (-not $wahl) {
  $wahl = $stimmen | Where-Object { $_.Culture.Name.StartsWith([string]$daten.sprache, [StringComparison]::OrdinalIgnoreCase) } | Select-Object -First 1
}
if ($wahl) { $sprecher.SelectVoice($wahl.Name) }
if ($null -ne $daten.rate) { $sprecher.Rate = [int]$daten.rate }
$sprecher.SetOutputToWaveFile([string]$daten.ziel)
$sprecher.Speak([string]$daten.text)
$sprecher.Dispose()
if ($wahl) { Jarvis-Ausgabe $wahl.Name } else { Jarvis-Ausgabe '' }
"""


def sapi_rate(tempo: int) -> int | None:
    """Wörter/Minute (wie bei say) → SAPI-Rate −10…10 (0 = Standard ≈ 180 Wörter/Minute)."""
    if not tempo or tempo <= 0:
        return None
    return max(-10, min(10, round((int(tempo) - 180) / 20)))


class SapiTTS:
    """Windows-Sprachausgabe (SAPI, ``System.Speech``) mit deutscher Stimme (z. B. „Microsoft Hedda“)."""

    def __init__(self, stimme: str = "", sprache: str = "de", tempo: int = 0, ausfuehren=prozess_ausfuehren):
        self.stimme = stimme or ""
        self.sprache = sprache or "de"
        self.tempo = int(tempo or 0)
        self._ausfuehren = ausfuehren
        self.gewaehlte_stimme: str | None = None

    def befehl(self) -> list[str]:
        from ..plattform.windows import powershell_befehl

        return powershell_befehl(SKRIPT_SAPI)

    def eingabe(self, text: str, ziel: str) -> bytes:
        daten = {"text": text, "ziel": ziel, "stimme": self.stimme, "sprache": self.sprache,
                 "rate": sapi_rate(self.tempo)}
        return base64.b64encode(json.dumps(daten, ensure_ascii=False).encode("utf-8"))

    async def synthetisieren(self, text: str, ziel: str) -> str:
        ziel = str(Path(ziel).with_suffix(".wav"))
        try:
            code, aus, err = await self._ausfuehren(self.befehl(), self.eingabe(text, ziel), 120)
        except FileNotFoundError as exc:
            raise StimmFehler("PowerShell nicht gefunden – die Windows-Sprachausgabe ist nicht verfügbar.") from exc
        if code != 0:
            raise StimmFehler(f"Windows-Sprachausgabe fehlgeschlagen: {kurz(err.decode('utf-8', 'replace') or code)}")
        if self.gewaehlte_stimme is None:
            try:
                self.gewaehlte_stimme = base64.b64decode(aus.strip() or b"").decode("utf-8", "replace")
            except ValueError:
                self.gewaehlte_stimme = ""
            if not self.gewaehlte_stimme:
                log.warning("Keine deutsche SAPI-Stimme gefunden – Windows nutzt die Standardstimme. "
                            "Deutsch nachinstallieren: Einstellungen → Zeit und Sprache → Sprache → Deutsch → Sprachausgabe.")
        return ziel


PIPER_STANDARD = "de_DE-thorsten-medium"
PIPER_BASIS_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
_PIPER_NAME = re.compile(r"^(?P<sprache>[a-z]{2,3})_(?P<land>[A-Z]{2})-(?P<sprecher>[A-Za-z0-9_]+)-(?P<qualitaet>x_low|low|medium|high)$")


def piper_urls(name: str) -> tuple[str, str]:
    """Download-Adressen (Modell, Konfiguration) einer Piper-Stimme, z. B. de_DE-thorsten-medium."""
    m = _PIPER_NAME.match(name)
    if not m:
        raise StimmFehler(f"Unbekannter Piper-Stimmenname „{name}“ (Format z. B. de_DE-thorsten-medium).")
    basis = f"{PIPER_BASIS_URL}/{m['sprache']}/{m['sprache']}_{m['land']}/{m['sprecher']}/{m['qualitaet']}/{name}"
    return f"{basis}.onnx?download=true", f"{basis}.onnx.json?download=true"


async def _herunterladen(url: str, ziel: Path) -> None:
    import httpx  # noqa: PLC0415

    teil = ziel.with_name(ziel.name + ".teil")
    async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as client:
        async with client.stream("GET", url) as antwort:
            antwort.raise_for_status()
            with open(teil, "wb") as f:
                async for block in antwort.aiter_bytes(1 << 16):
                    f.write(block)
    teil.replace(ziel)


def piper_verfuegbar() -> bool:
    return importlib.util.find_spec("piper") is not None


class PiperTTS:
    """Linux: Piper (``pip install piper-tts``) mit deutschem Modell, Standard ``de_DE-thorsten-medium``.

    Das Modell (~60 MB) wird beim ersten Gebrauch nach ``<modell_verzeichnis>/piper`` geladen
    (abschaltbar mit ``JARVIS_KEIN_DOWNLOAD=1``). ``stimme`` kann ein anderer Piper-Stimmenname
    oder der Pfad zu einer ``.onnx``-Datei sein.
    """

    def __init__(self, stimme: str = "", modell_verzeichnis: str | None = None, tempo: int = 0,
                 ausfuehren=prozess_ausfuehren, laden=_herunterladen):
        self.stimme = stimme or PIPER_STANDARD
        from .einstellungen import STANDARD_MODELL_VERZEICHNIS

        self.verzeichnis = Path(modell_verzeichnis or STANDARD_MODELL_VERZEICHNIS).expanduser() / "piper"
        self.tempo = int(tempo or 0)
        self._ausfuehren = ausfuehren
        self._laden = laden
        self._sperre = asyncio.Lock()

    async def modell(self) -> Path:
        if self.stimme.endswith(".onnx"):
            pfad = Path(self.stimme).expanduser()
            if not pfad.exists():
                raise StimmFehler(f"Piper-Modell nicht gefunden: {pfad}")
            return pfad
        pfad = self.verzeichnis / f"{self.stimme}.onnx"
        konfig = self.verzeichnis / f"{self.stimme}.onnx.json"
        async with self._sperre:
            if pfad.exists() and konfig.exists():
                return pfad
            if os.environ.get("JARVIS_KEIN_DOWNLOAD"):
                raise StimmFehler(f"Piper-Stimme „{self.stimme}“ fehlt und Downloads sind abgeschaltet (JARVIS_KEIN_DOWNLOAD).")
            modell_url, konfig_url = piper_urls(self.stimme)
            self.verzeichnis.mkdir(parents=True, exist_ok=True)
            log.info("Lade Piper-Stimme %s nach %s …", self.stimme, self.verzeichnis)
            try:
                await self._laden(konfig_url, konfig)
                await self._laden(modell_url, pfad)
            except StimmFehler:
                raise
            except Exception as exc:  # noqa: BLE001
                raise StimmFehler(f"Piper-Stimme „{self.stimme}“ konnte nicht geladen werden: {kurz(exc)}") from exc
        return pfad

    async def befehl(self, ziel: str) -> list[str]:
        befehl = [sys.executable, "-m", "piper", "-m", str(await self.modell()), "-f", ziel]
        if self.tempo > 0:  # Wörter/Minute → Phonemlänge (größer = langsamer)
            befehl += ["--length-scale", f"{max(0.5, min(2.0, 180 / self.tempo)):.2f}"]
        return befehl

    async def synthetisieren(self, text: str, ziel: str) -> str:
        if not piper_verfuegbar():
            raise StimmFehler("Piper ist nicht installiert: pip install piper-tts (in der venv unter ~/.jarvis/venv).")
        ziel = str(Path(ziel).with_suffix(".wav"))
        code, _, err = await self._ausfuehren(await self.befehl(ziel), text.encode("utf-8"), 120)
        if code != 0:
            raise StimmFehler(f"Piper ist fehlgeschlagen: {kurz(err.decode('utf-8', 'replace') or code)}")
        return ziel


class EspeakTTS:
    """Linux-Fallback: ``espeak-ng`` (bzw. ``espeak``), Text über stdin, Ausgabe als WAV."""

    def __init__(self, stimme: str = "", sprache: str = "de", tempo: int = 0, ausfuehren=prozess_ausfuehren):
        self.stimme = stimme or sprache or "de"
        self.tempo = int(tempo or 0)
        self._ausfuehren = ausfuehren

    def programm(self) -> str:
        for name in ("espeak-ng", "espeak"):
            if shutil.which(name):
                return name
        from ..plattform.gemeinsam import installationsbefehl

        raise StimmFehler(f"espeak-ng ist nicht installiert. Installieren mit: {installationsbefehl('espeak-ng')}")

    def befehl(self, ziel: str) -> list[str]:
        befehl = [self.programm(), "-v", self.stimme, "-b", "1", "-w", ziel]
        if self.tempo > 0:
            befehl += ["-s", str(self.tempo)]
        return befehl + ["--stdin"]

    async def synthetisieren(self, text: str, ziel: str) -> str:
        ziel = str(Path(ziel).with_suffix(".wav"))
        code, _, err = await self._ausfuehren(self.befehl(ziel), text.encode("utf-8"), 120)
        if code != 0:
            raise StimmFehler(f"espeak-ng ist fehlgeschlagen: {kurz(err.decode('utf-8', 'replace') or code)}")
        return ziel


class KetteTTS:
    """Probiert mehrere Sprachausgaben der Reihe nach (z. B. Piper → espeak-ng)."""

    def __init__(self, glieder: list):
        self.glieder = list(glieder)

    async def synthetisieren(self, text: str, ziel: str) -> str:
        fehler: list[str] = []
        for glied in list(self.glieder):
            try:
                return await glied.synthetisieren(text, ziel)
            except StimmFehler as exc:
                fehler.append(exc.text)
                if len(self.glieder) > 1:  # dauerhaft fehlende Varianten nicht jedes Mal erneut probieren
                    log.info("Sprachausgabe %s nicht nutzbar: %s", type(glied).__name__, exc.text)
                    self.glieder.remove(glied)
        raise StimmFehler(" / ".join(fehler) or "Keine Sprachausgabe verfügbar.")


def openrouter_schluessel_vorhanden() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


#: Standardstimme je OpenRouter-Modell (Präfix → Stimme); Deutsch, wo das Modell es anbietet
OPENROUTER_STANDARD_STIMMEN = (
    ("elevenlabs/", "daniel"),
    ("microsoft/mai-voice-2.1-flash", "de-DE-Klaus:MAI-Voice-2.1-Flash"),
    ("microsoft/mai-voice-2.1", "de-DE-Klaus:MAI-Voice-2.1"),
    ("microsoft/mai-voice-2-flash", "de-DE-Klaus:MAI-Voice-2"),
    ("microsoft/mai-voice-2", "de-DE-Klaus:MAI-Voice-2"),
    ("google/", "Kore"),
    ("mistralai/", "en_paul_neutral"),
)


def openrouter_standard_stimme(modell: str) -> str:
    for praefix, stimme in OPENROUTER_STANDARD_STIMMEN:
        if modell.startswith(praefix):
            return stimme
    return ""


def tts_art(e) -> str:
    """Wirksame TTS-Art: ``auto``/``say`` werden je Plattform (und OpenRouter-Schlüssel) aufgelöst."""
    art = (e.tts or "auto").lower()
    plattform = _plattform()
    if art == "say" and plattform != "mac":
        art = "auto"
    if art in ("windows", "sapi5"):
        art = "sapi"
    if art == "espeak-ng":
        art = "espeak"
    if art not in ("aus", "cloud", "openrouter", "say", "sapi", "piper", "espeak"):
        art = "auto"
    if art == "auto":
        if openrouter_schluessel_vorhanden():
            art = "openrouter"
        else:
            art = {"mac": "say", "windows": "sapi"}.get(plattform, "piper")
    return art


def erzeuge_tts(e) -> Sprachsynthese | None:
    art = tts_art(e)
    if art == "aus":
        return None
    if art == "cloud":
        return CloudTTS(modell=e.tts_cloud_modell, stimme=e.tts_stimme)
    if art == "openrouter":
        from .sprecher import OpenRouterTTS  # noqa: PLC0415 – sprecher importiert dieses Modul

        modell = getattr(e, "tts_openrouter_modell", "") or "elevenlabs/eleven-flash-v2.5"
        return OpenRouterTTS(modell, e.tts_stimme or openrouter_standard_stimme(modell))
    if art == "sapi":
        return SapiTTS(stimme=e.tts_stimme, sprache=e.sprache, tempo=e.tts_tempo)
    if art == "piper":
        return KetteTTS([
            PiperTTS(stimme=e.tts_stimme, modell_verzeichnis=e.modell_verzeichnis, tempo=e.tts_tempo),
            EspeakTTS(sprache=e.sprache, tempo=e.tts_tempo),
        ])
    if art == "espeak":
        return EspeakTTS(stimme=e.tts_stimme, sprache=e.sprache, tempo=e.tts_tempo)
    return SayTTS(stimme=e.tts_stimme, sprache=e.sprache, tempo=e.tts_tempo)


async def einmal_vorlesen(text: str, einstellungen, abspieler: Abspieler | None = None) -> None:
    """Liest ``text`` einmalig vor (ohne laufenden StimmDienst, z. B. ``jarvis sag --sprechen``)."""
    from .einstellungen import StimmEinstellungen

    e = StimmEinstellungen.aus(einstellungen)
    tts = erzeuge_tts(e)
    if tts is None or not text.strip():
        return
    verzeichnis = temp_verzeichnis()
    try:
        pfad = await tts.synthetisieren(text, str(Path(verzeichnis) / "teil0"))
        await (abspieler or Abspieler()).abspielen(pfad)
    finally:
        aufraeumen(verzeichnis)


def ton_datei(gewuenscht: str | None = None) -> str:
    """Bestätigungston: gewünschte Datei, falls vorhanden – sonst ein erzeugter kurzer „Pling“ (WAV)."""
    if gewuenscht and Path(gewuenscht).exists():
        return gewuenscht
    pfad = Path(tempfile.gettempdir()) / "jarvis-bestaetigungston.wav"
    if not pfad.exists():
        rate = 22050
        t = np.arange(int(rate * 0.12)) / rate
        huelle = np.minimum(1.0, t / 0.005) * np.exp(-t * 28)
        signal = (np.sin(2 * np.pi * 1318.5 * t) + 0.3 * np.sin(2 * np.pi * 2637 * t)) * huelle
        daten = (signal / np.max(np.abs(signal)) * 0.5 * 32767).astype(np.int16)
        teil = pfad.with_name(f"{pfad.name}.{os.getpid()}.teil")
        teil.write_bytes(wav_bytes(daten, rate))
        teil.replace(pfad)
    return str(pfad)


def temp_verzeichnis() -> str:
    return tempfile.mkdtemp(prefix="jarvis-tts-")


def aufraeumen(verzeichnis: str) -> None:
    shutil.rmtree(verzeichnis, ignore_errors=True)


__all__ = [
    "Abspieler",
    "CloudTTS",
    "EspeakTTS",
    "KetteTTS",
    "PiperTTS",
    "SapiTTS",
    "einmal_vorlesen",
    "piper_urls",
    "ton_datei",
    "tts_art",
    "SayStimme",
    "SayTTS",
    "aufraeumen",
    "beste_say_stimme",
    "erzeuge_tts",
    "say_stimmen_parsen",
    "temp_verzeichnis",
]

