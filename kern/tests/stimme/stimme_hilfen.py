"""Hilfsfunktionen und Fälschungen für die Tests des Sprachmoduls."""

from __future__ import annotations

import asyncio

import numpy as np

ABTASTRATE = 16000
RAHMEN = 1280
WECK_MARKER = 12345


def rahmen_stille(n: int = 1, amplitude: float = 30.0, seed: int = 0) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    return [np.clip(rng.normal(0, amplitude, RAHMEN), -32768, 32767).astype(np.int16) for _ in range(n)]


def rahmen_sprache(n: int = 1, amplitude: float = 6000.0) -> list[np.ndarray]:
    """Sprachähnliches Signal: Grundton 140 Hz + Obertöne, Silbenmodulation 4 Hz."""
    t = np.arange(n * RAHMEN) / ABTASTRATE
    signal = sum((1.0 / k) * np.sin(2 * np.pi * 140 * k * t) for k in range(1, 12))
    huelle = 0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)
    x = signal / np.max(np.abs(signal)) * huelle * amplitude
    x = x.astype(np.int16)
    return [x[i * RAHMEN : (i + 1) * RAHMEN] for i in range(n)]


def rahmen_weckwort() -> np.ndarray:
    r = rahmen_stille(1, seed=99)[0]
    r[0] = WECK_MARKER
    return r


class FakeQuelle:
    """Gefälschte Audioquelle: Tests schieben Rahmen hinein (wie der PortAudio-Thread)."""

    def __init__(self, fehler: Exception | None = None):
        self.fehler = fehler
        self.rueckruf = None
        self.gestartet = 0
        self.gestoppt = 0

    def starten(self, rueckruf):
        if self.fehler is not None:
            raise self.fehler
        self.rueckruf = rueckruf
        self.gestartet += 1

    def stoppen(self):
        self.gestoppt += 1
        self.rueckruf = None

    async def senden(self, rahmen, pause: float = 0.001):
        for r in rahmen:
            if self.rueckruf is None:
                return
            self.rueckruf(r)
            await asyncio.sleep(pause)


class FakeDetektor:
    weckwort = "hey_jarvis"

    def __init__(self):
        self.geprueft = 0
        self.geprueft_markiert = 0
        self.zurueckgesetzt = 0

    def pruefen(self, rahmen) -> float:
        self.geprueft += 1
        if int(rahmen[0]) == WECK_MARKER:
            self.geprueft_markiert += 1
            return 0.99
        return 0.01

    def zuruecksetzen(self):
        self.zurueckgesetzt += 1


class FakeSTT:
    def __init__(self, texte=("Wie spät ist es?",)):
        self.texte = list(texte)
        self.aufrufe: list[int] = []

    async def vorbereiten(self):
        return None

    async def transkribieren(self, audio):
        self.aufrufe.append(len(audio))
        return self.texte.pop(0) if self.texte else ""


class FakeTTS:
    def __init__(self):
        self.texte: list[str] = []

    async def synthetisieren(self, text, ziel):
        self.texte.append(text)
        return ziel + ".wav"


class FakeAbspieler:
    def __init__(self, dauer_schritte: int = 5, schritt_s: float = 0.01):
        self.dauer_schritte = dauer_schritte
        self.schritt_s = schritt_s
        self.gespielt: list[str] = []
        self.abgebrochen = 0
        self.laeuft = asyncio.Event()

    async def abspielen(self, pfad, pegel=None, stopp=None):
        self.gespielt.append(pfad)
        self.laeuft.set()
        try:
            for _ in range(self.dauer_schritte):
                if stopp is not None and stopp.is_set():
                    break
                if pegel is not None:
                    await pegel(0.5)
                await asyncio.sleep(self.schritt_s)
        finally:
            self.laeuft.clear()

    def abbrechen(self):
        self.abgebrochen += 1


class Protokoll:
    """Sammelt die Ereignisse des Dienstes."""

    def __init__(self):
        self.ereignisse: list[dict] = []

    async def __call__(self, ereignis: dict):
        self.ereignisse.append(ereignis)

    def typen(self, *typen):
        return [e for e in self.ereignisse if e["typ"] in typen]

    def zustaende(self) -> list[str]:
        z = [e["zustand"] for e in self.ereignisse if e["typ"] == "zustand"]
        # direkte Wiederholungen zusammenfassen
        return [x for i, x in enumerate(z) if i == 0 or z[i - 1] != x]

    def ohne_pegel(self) -> list[str]:
        aus = []
        for e in self.ereignisse:
            if e["typ"] == "pegel":
                continue
            marke = e["typ"] if e["typ"] != "zustand" else f"zustand:{e['zustand']}"
            aus.append(marke)
        return aus

    def fehlertexte(self) -> list[str]:
        return [e["text"] for e in self.ereignisse if e["typ"] == "fehler"]


async def warte_bis(bedingung, timeout: float = 3.0, schritt: float = 0.005):
    loop = asyncio.get_running_loop()
    ende = loop.time() + timeout
    while loop.time() < ende:
        if bedingung():
            return True
        await asyncio.sleep(schritt)
    raise AssertionError("Bedingung wurde nicht rechtzeitig erfüllt")
