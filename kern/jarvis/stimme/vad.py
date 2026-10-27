"""Sprachaktivitäts-Erkennung (VAD) und Sprachpausen-Erkennung (Endpointing).

* :class:`EnergieVAD` – eigener VAD auf Basis des Signalpegels mit adaptivem Rauschpegel.
* :class:`WebrtcVAD` – nutzt ``webrtcvad`` (falls installiert), kombiniert mit dem Energie-Tor,
  damit gleichmäßiges Rauschen nicht als Sprache zählt.
* :class:`Sprachpausenerkenner` – sammelt Rahmen, erkennt Sprachbeginn und -ende
  (``stille_ms``), begrenzt die Aufnahme (``max_aufnahme_s``).

Alle Rahmen sind int16, mono, 16 kHz (typisch 1280 Samples = 80 ms).
"""

from __future__ import annotations

import enum
from collections import deque

import numpy as np

ABTASTRATE = 16000
RAHMEN = 1280  # 80 ms – Eingangsgröße von openWakeWord
TEILRAHMEN = 320  # 20 ms – Analysefenster des VAD (webrtcvad: 10/20/30 ms)
DBFS_MIN = -96.0


def pegel_dbfs(samples: np.ndarray) -> float:
    """RMS-Pegel in dBFS (0 = Vollaussteuerung)."""
    if samples.size == 0:
        return DBFS_MIN
    x = samples.astype(np.float64)
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < 1e-9:
        return DBFS_MIN
    return max(20.0 * np.log10(rms / 32768.0), DBFS_MIN)


def pegel_anzeige(samples: np.ndarray, unten_db: float = -60.0, oben_db: float = -12.0) -> float:
    """Pegel 0..1 für die Oberfläche (Orb)."""
    db = pegel_dbfs(samples)
    wert = (db - unten_db) / (oben_db - unten_db)
    return round(float(min(max(wert, 0.0), 1.0)), 3)


class EnergieVAD:
    """Energie-basierter VAD mit adaptivem Rauschpegel.

    Der Rauschpegel folgt leisen Abschnitten schnell nach unten und lauten nur sehr langsam
    nach oben – so passt er sich an Lüfter/Raumgeräusch an, ohne Sprache zu „lernen“.
    """

    def __init__(
        self,
        abstand_db: float = 10.0,
        min_db: float = -55.0,
        start_rauschen_db: float = -60.0,
        anteil: float = 0.5,
    ):
        self.abstand_db = abstand_db
        self.min_db = min_db
        self.rauschen_db = start_rauschen_db
        self.anteil = anteil  # Anteil der Teilrahmen mit Sprache, ab dem der Rahmen als Sprache gilt
        self._kalibriert = False

    @property
    def schwelle_db(self) -> float:
        return max(self.rauschen_db + self.abstand_db, self.min_db)

    def _rauschen_nachfuehren(self, db: float, sprache: bool) -> None:
        if db <= DBFS_MIN + 1:
            return  # digitale Stille (z. B. fehlende Mikrofonrechte) nicht lernen
        if not self._kalibriert:
            self.rauschen_db = db
            self._kalibriert = True
            return
        if db < self.rauschen_db:
            self.rauschen_db += 0.3 * (db - self.rauschen_db)  # schnell nach unten
        elif not sprache:
            self.rauschen_db += 0.02 * (db - self.rauschen_db)  # langsam nach oben
        else:
            self.rauschen_db += 0.002 * (db - self.rauschen_db)  # bei Sprache fast gar nicht

    def teil_ist_sprache(self, teil: np.ndarray) -> bool:
        db = pegel_dbfs(teil)
        sprache = db > self.schwelle_db
        self._rauschen_nachfuehren(db, sprache)
        return sprache

    def ist_sprache(self, rahmen: np.ndarray) -> bool:
        teile = _teile(rahmen)
        if not teile:
            return False
        treffer = sum(1 for t in teile if self.teil_ist_sprache(t))
        return treffer / len(teile) >= self.anteil

    def zuruecksetzen(self) -> None:  # Rauschpegel bleibt bewusst erhalten
        pass


class WebrtcVAD(EnergieVAD):
    """webrtcvad + Energie-Tor (Sprache nur, wenn beide zustimmen)."""

    def __init__(self, modus: int = 2, **kwargs):
        super().__init__(**kwargs)
        import webrtcvad  # noqa: PLC0415 – optional

        self._vad = webrtcvad.Vad(modus)
        self._tor_db = 6.0

    def teil_ist_sprache(self, teil: np.ndarray) -> bool:
        db = pegel_dbfs(teil)
        energie_ok = db > max(self.rauschen_db + self._tor_db, self.min_db)
        try:
            webrtc = self._vad.is_speech(teil.astype("<i2").tobytes(), ABTASTRATE)
        except Exception:  # noqa: BLE001
            webrtc = db > self.schwelle_db
        sprache = bool(webrtc and energie_ok)
        self._rauschen_nachfuehren(db, sprache)
        return sprache


def erzeuge_vad(art: str = "auto"):
    """Liefert webrtcvad, wenn gewünscht und installiert, sonst den Energie-VAD."""
    art = (art or "auto").lower()
    if art in ("auto", "webrtc"):
        try:
            return WebrtcVAD()
        except Exception:  # noqa: BLE001 – Paket fehlt oder lädt nicht
            pass
    return EnergieVAD()


def _teile(rahmen: np.ndarray) -> list[np.ndarray]:
    n = len(rahmen) // TEILRAHMEN
    return [rahmen[i * TEILRAHMEN : (i + 1) * TEILRAHMEN] for i in range(n)]


class Status(enum.Enum):
    WARTET = "wartet"  # noch keine Sprache
    SPRICHT = "spricht"  # Sprache läuft
    FERTIG = "fertig"  # Sprachpause erkannt bzw. Höchstdauer erreicht
    KEINE_SPRACHE = "keine_sprache"  # Zeit abgelaufen, ohne dass gesprochen wurde


class Sprachpausenerkenner:
    """Erkennt Anfang und Ende einer Äußerung in einem Strom von Rahmen."""

    def __init__(
        self,
        vad=None,
        stille_ms: int = 900,
        max_aufnahme_s: float = 20.0,
        warte_auf_sprache_s: float = 5.0,
        min_sprache_ms: int = 240,
        vorlauf_ms: int = 400,
        ignoriere_ms: int = 0,
        abtastrate: int = ABTASTRATE,
    ):
        self.vad = vad or EnergieVAD()
        self.abtastrate = abtastrate
        self.stille_ms = stille_ms
        self.max_samples = int(max_aufnahme_s * abtastrate)
        self.warte_samples = int(warte_auf_sprache_s * abtastrate)
        self.min_sprache_samples = int(min_sprache_ms / 1000 * abtastrate)
        self.vorlauf_samples = int(vorlauf_ms / 1000 * abtastrate)
        self.ignoriere_samples = int(ignoriere_ms / 1000 * abtastrate)
        self.status = Status.WARTET
        self._vorlauf: deque[np.ndarray] = deque()
        self._vorlauf_laenge = 0
        self._aufnahme: list[np.ndarray] = []
        self._gesamt = 0  # alle bisher zugeführten Samples
        self._sprache = 0  # Samples mit Sprache
        self._kandidat = 0  # zusammenhängende Sprach-Samples vor dem bestätigten Beginn
        self._stille = 0  # Samples Stille seit der letzten Sprache
        self._aufnahme_laenge = 0

    @property
    def fertig(self) -> bool:
        return self.status in (Status.FERTIG, Status.KEINE_SPRACHE)

    def zufuehren(self, rahmen: np.ndarray) -> Status:
        if self.fertig:
            return self.status
        rahmen = np.asarray(rahmen, dtype=np.int16).reshape(-1)
        n = len(rahmen)
        vorher = self._gesamt
        self._gesamt += n
        ignorieren = vorher < self.ignoriere_samples
        sprache = self.vad.ist_sprache(rahmen) and not ignorieren

        if self.status is Status.WARTET:
            self._vorlauf.append(rahmen)
            self._vorlauf_laenge += n
            while self._vorlauf_laenge - len(self._vorlauf[0]) >= self.vorlauf_samples and len(self._vorlauf) > 1:
                self._vorlauf_laenge -= len(self._vorlauf.popleft())
            if sprache:
                self._kandidat += n
                if self._kandidat >= self.min_sprache_samples:
                    self.status = Status.SPRICHT
                    self._aufnahme = list(self._vorlauf)
                    self._aufnahme_laenge = self._vorlauf_laenge
                    self._vorlauf.clear()
                    self._sprache = self._kandidat
                    self._stille = 0
            else:
                self._kandidat = 0
                if self._gesamt >= self.warte_samples:
                    self.status = Status.KEINE_SPRACHE
            return self.status

        # Status.SPRICHT
        self._aufnahme.append(rahmen)
        self._aufnahme_laenge += n
        if sprache:
            self._sprache += n
            self._stille = 0
        else:
            self._stille += n
        if self._stille * 1000 >= self.stille_ms * self.abtastrate:
            self.status = Status.FERTIG
        elif self._aufnahme_laenge >= self.max_samples:
            self.status = Status.FERTIG
        return self.status

    def audio(self, nachlauf_ms: int = 250) -> np.ndarray | None:
        """Aufgenommene Äußerung (int16) – abschließende Stille bis auf ``nachlauf_ms`` gekürzt."""
        if not self._aufnahme:
            return None
        daten = np.concatenate(self._aufnahme)
        ueberschuss = self._stille - int(nachlauf_ms / 1000 * self.abtastrate)
        if ueberschuss > 0 and ueberschuss < len(daten):
            daten = daten[: len(daten) - ueberschuss]
        return daten

    @property
    def dauer_s(self) -> float:
        return self._aufnahme_laenge / self.abtastrate
