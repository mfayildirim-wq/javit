"""Freies Weckwort (z. B. „Javit“) mit Vosk – offline, ohne eigenes Training.

Problem
-------
Vosk erkennt nur Wörter aus dem Vokabular des Modells. Eine eingeschränkte Grammatik
(``KaldiRecognizer(modell, 16000, '["javit", "[unk]"]')``) hilft bei Fantasienamen nicht: Wörter,
die nicht im Vokabular stehen, verwirft Vosk mit der Warnung „Ignoring word missing in
vocabulary“ – die Grammatik bestünde dann nur noch aus ``[unk]``. „Javit“ steht nicht im
Vokabular von ``vosk-model-small-de-0.15``.

Gewählte Methode (robust, testbar)
---------------------------------
1. **Schreibvarianten aus bekannten Wörtern**: Für das Weckwort gibt es Schreib-/Silbenvarianten
   (für „javit“ u. a. „ja wit“, „ja witt“, „ja vit“, „jawit“, „javid“, „dschawit“; eigene über
   ``weckwort_varianten``). Beim Laden wird jedes Wort mit ``Model.find_word()`` gegen das
   Vokabular geprüft; nur vollständig bekannte Varianten kommen in die Grammatik.
2. **Kleine Grammatik + Füllwörter**: Grammatik = bekannte Varianten + deren Einzelwörter +
   häufige, ähnlich klingende deutsche Wörter („ja“, „bitte“, „mit“, „wie“, „david“ …) +
   ``[unk]``. Die Füllwörter fangen Alltagssprache ab („ja bitte“ wird als „ja bitte“ erkannt und
   nicht in „ja witt“ gezwungen). Der Decoder bleibt klein und CPU-schonend.
   Ist **keine** Variante im Vokabular (z. B. anderes Modell), läuft die Erkennung ohne
   Grammatik (freie Erkennung) – dann entscheidet allein Schritt 3.
3. **Phonetischer Abgleich** auf dem (Teil-)Ergebnis: Aufeinanderfolgende Wörter (Fenster aus
   1–4 Wörtern, ohne ``[unk]``) werden zusammengezogen („ja witt“ → „jawitt“) und mit allen
   Zielen verglichen:

   * exakt gleich einem Weckwort/einer Variante → Score 1,0
   * gleicher Code nach **Kölner Phonetik** (z. B. „jawitt“ = „javit“ = 032) und
     Schreibähnlichkeit (Levenshtein) ≥ 0,5 → Score 0,7 … 1,0 (0,7 + 0,3 × Ähnlichkeit)
   * sonst → höchstens 0,45 × Ähnlichkeit (unter der Standardschwelle 0,5)

   Ausgelöst wird bei Score ≥ ``schwelle`` (Standard 0,5 = exakte oder phonetisch gleiche
   Treffer; 0,9 = nur sehr ähnliche Schreibweisen; < 0,45 = auch unscharfe Treffer).
4. **Teilergebnisse**: Geprüft wird nach jedem 80-ms-Rahmen das partielle Ergebnis. Exakte
   Treffer lösen sofort aus, phonetische erst, wenn sie in zwei aufeinanderfolgenden
   Teilergebnissen (oder im Endergebnis) stehen – das filtert flackernde Hypothesen. Nach
   einem Treffer wird der Erkenner zurückgesetzt.

Modell: ``vosk-model-small-de-0.15`` (≈ 45 MB) wird beim ersten Gebrauch von alphacephei.com nach
``~/.jarvis/modelle/vosk/`` geladen (ZIP-Prüfung, optionale SHA-256, sicheres Entpacken).
``JARVIS_KEIN_DOWNLOAD=1`` verhindert den Download (Tests, Container).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import unicodedata
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np

from .fehler import HINWEIS_PAKETE, StimmFehler, kurz

log = logging.getLogger("jarvis.stimme.weckwort")

STANDARD_VOSK_MODELL = "vosk-model-small-de-0.15"
VOSK_URL = "https://alphacephei.com/vosk/models/{name}.zip"
ABTASTRATE = 16000
MAX_DOWNLOAD_BYTES = 3 * 1024**3
#: Obergrenze der entpackten Größe (Schutz vor ZIP-Bomben; große Vosk-Modelle haben ~4 GB)
MAX_ENTPACKT_BYTES = 8 * 1024**3
#: Modellnamen von alphacephei.com, z. B. vosk-model-small-de-0.15 (kein „.“/„..“, keine Pfade)
_MODELLNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: Bekannte Schreib-/Silbenvarianten je Weckwort (werden beim Laden gegen das Vokabular geprüft)
STANDARD_VARIANTEN: dict[str, list[str]] = {
    "javit": [
        "jawit", "javid", "jawid", "dschawit", "dschavit",
        "ja wit", "ja witt", "ja vit", "ja wid", "ja fit", "ja with",
    ],
}

#: Häufige, ähnlich klingende Wörter: fangen Alltagssprache in der Grammatik ab
FUELLWOERTER = (
    "ja", "nein", "jawohl", "java", "david", "wie", "wir", "wird", "mit", "bitte", "bis", "witz",
    "wissen", "weit", "hey", "hallo", "okay", "und", "die", "der", "das", "ist", "nicht", "was",
    "wo", "da", "zeit", "via", "gibt", "habe", "hat", "dann", "jetzt", "danke", "gut",
)

_UMLAUTE = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s"})


# ---------------------------------------------------------------------------------------
# Textvergleich
# ---------------------------------------------------------------------------------------
def woerter_normalisieren(text: str) -> list[str]:
    """Kleinbuchstaben, nur Buchstaben (inkl. Umlaute); ``[unk]`` bleibt als Trenner erhalten."""
    ergebnis: list[str] = []
    for roh in str(text or "").lower().split():
        if roh in ("[unk]", "<unk>"):
            ergebnis.append("[unk]")
            continue
        wort = "".join(z for z in unicodedata.normalize("NFC", roh) if z.isalpha())
        if wort:
            ergebnis.append(wort)
    return ergebnis


def koelner_phonetik(text: str) -> str:
    """Kölner Phonetik (Postel 1969): ähnlich klingende deutsche Wörter → gleicher Zifferncode."""
    s = "".join(z for z in str(text or "").lower().translate(_UMLAUTE) if "a" <= z <= "z")
    roh: list[str] = []
    for i, z in enumerate(s):
        vor = s[i - 1] if i > 0 else ""
        nach = s[i + 1] if i + 1 < len(s) else ""
        if z in "aeijouy":
            code = "0"
        elif z == "h":
            code = ""
        elif z == "b":
            code = "1"
        elif z == "p":
            code = "3" if nach == "h" else "1"
        elif z in "dt":
            code = "8" if nach in ("c", "s", "z") and nach else "2"
        elif z in "fvw":
            code = "3"
        elif z in "gkq":
            code = "4"
        elif z == "c":
            if i == 0:
                code = "4" if nach in tuple("ahkloqrux") and nach else "8"
            elif vor in ("s", "z"):
                code = "8"
            else:
                code = "4" if nach in tuple("ahkoqux") and nach else "8"
        elif z == "x":
            code = "8" if vor in ("c", "k", "q") and vor else "48"
        elif z == "l":
            code = "5"
        elif z in "mn":
            code = "6"
        elif z == "r":
            code = "7"
        else:  # s, z
            code = "8"
        roh.append(code)
    ziffern = "".join(roh)
    zusammen = ""
    for c in ziffern:
        if not zusammen or zusammen[-1] != c:
            zusammen += c
    if not zusammen:
        return ""
    return zusammen[0] + zusammen[1:].replace("0", "")


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return len(a) + len(b)
    vorher = list(range(len(b) + 1))
    for i, za in enumerate(a, 1):
        aktuell = [i]
        for j, zb in enumerate(b, 1):
            aktuell.append(min(vorher[j] + 1, aktuell[j - 1] + 1, vorher[j - 1] + (za != zb)))
        vorher = aktuell
    return vorher[-1]


def aehnlichkeit(a: str, b: str) -> float:
    """1,0 = gleich, 0,0 = völlig verschieden (normierte Levenshtein-Distanz)."""
    laenge = max(len(a), len(b))
    return 1.0 - levenshtein(a, b) / laenge if laenge else 1.0


def weckwoerter(text: str) -> list[str]:
    """„javit, hey javit“ → ["javit", "hey javit"] (normalisiert)."""
    teile = str(text or "").replace(";", ",").split(",")
    ergebnis = []
    for teil in teile:
        woerter = [w for w in woerter_normalisieren(teil.replace("_", " ")) if w != "[unk]"]
        if woerter and " ".join(woerter) not in ergebnis:
            ergebnis.append(" ".join(woerter))
    return ergebnis


def _vokal(z: str) -> bool:
    return z in "aeiouyäöü"


def varianten_erzeugen(wort: str) -> list[str]:
    """Allgemeine Schreib-/Silbenvarianten eines Wortes: v↔w und Trennung nach Vokalgruppen
    („javit“ → „jawit“, „ja vit“, „ja wit“ …). Bekannte Wörter stehen in ``STANDARD_VARIANTEN``."""
    basis = {wort, wort.replace("v", "w"), wort.replace("w", "v")}
    ergebnis = set(basis) | set(STANDARD_VARIANTEN.get(wort, []))
    for b in basis:
        for i in range(2, len(b) - 1):
            if _vokal(b[i - 1]) and not _vokal(b[i]):
                links, rechts = b[:i], b[i:]
                if len(links) >= 2 and len(rechts) >= 2:
                    ergebnis.add(f"{links} {rechts}")
    return sorted(ergebnis)


def varianten_fuer(phrase: str) -> list[str]:
    """Varianten einer Weckwort-Phrase; bei mehreren Wörtern wird das letzte variiert („hey javit“)."""
    woerter = phrase.split()
    if not woerter:
        return []
    praefix = " ".join(woerter[:-1])
    return [f"{praefix} {v}".strip() for v in varianten_erzeugen(woerter[-1])]


class WeckwortAbgleich:
    """Bewertet erkannten Text gegen Weckwörter und Varianten (Score 0..1, siehe Moduldoku)."""

    def __init__(self, woerter: Iterable[str], varianten: Iterable[str] | None = None):
        self.woerter = [w for w in woerter if w] or ["javit"]
        eigene = [" ".join(woerter_normalisieren(v)) for v in (varianten or [])]
        eigene = [v for v in eigene if v and "[unk]" not in v]
        phrasen: list[str] = []
        for w in self.woerter:
            for p in [w, *(eigene if eigene else varianten_fuer(w))]:
                if p not in phrasen:
                    phrasen.append(p)
        self.phrasen = phrasen
        self._ziele = [(p.replace(" ", ""), koelner_phonetik(p)) for p in phrasen]
        self.max_fenster = min(4, max(len(p.split()) for p in phrasen) + 1)

    def bewerten(self, text: str) -> tuple[float, str | None]:
        """→ (Score, Treffer-Text) für ein Erkennungsergebnis."""
        woerter = woerter_normalisieren(text)
        bester, treffer = 0.0, None
        for start in range(len(woerter)):
            for laenge in range(1, self.max_fenster + 1):
                fenster = woerter[start : start + laenge]
                if len(fenster) < laenge or "[unk]" in fenster:
                    break
                kandidat = "".join(fenster)
                score = self._score(kandidat)
                if score > bester:
                    bester, treffer = score, " ".join(fenster)
                    if bester >= 1.0:
                        return bester, treffer
        return bester, treffer

    def _score(self, kandidat: str) -> float:
        code = koelner_phonetik(kandidat) if len(kandidat) >= 3 else ""
        bester = 0.0
        for ziel, ziel_code in self._ziele:
            if kandidat == ziel:
                return 1.0
            r = aehnlichkeit(kandidat, ziel)
            if code and len(ziel_code) >= 2 and code == ziel_code and r >= 0.5:
                score = 0.7 + 0.3 * r
            else:
                score = 0.45 * r
            bester = max(bester, score)
        return min(bester, 0.99)


def grammatik_bauen(abgleich: WeckwortAbgleich, kennt: Callable[[str], bool]) -> list[str]:
    """Grammatik aus den im Vokabular bekannten Varianten (+ Einzelwörter, Füllwörter, ``[unk]``).
    Leere Liste = keine Variante bekannt → freie Erkennung."""
    bekannte = [p for p in abgleich.phrasen if all(kennt(w) for w in p.split())]
    if not bekannte:
        return []
    liste: list[str] = []
    for eintrag in [*bekannte, *(w for p in bekannte for w in p.split()), *FUELLWOERTER]:
        if eintrag not in liste and all(kennt(w) for w in eintrag.split()):
            liste.append(eintrag)
    liste.append("[unk]")
    return liste


# ---------------------------------------------------------------------------------------
# Modell laden (Download beim ersten Gebrauch)
# ---------------------------------------------------------------------------------------
def modell_vollstaendig(ordner: Path) -> bool:
    return (ordner / "am" / "final.mdl").is_file() and (
        (ordner / "conf" / "model.conf").is_file() or (ordner / "conf" / "mfcc.conf").is_file()
    )


def _sicher_entpacken(zip_datei: Path, ziel: Path) -> None:
    """Entpackt ohne Pfadausbruch (keine absoluten Pfade, kein „..“, keine Links)."""
    try:
        with zipfile.ZipFile(zip_datei) as z:
            defekt = z.testzip()
            if defekt is not None:
                raise StimmFehler(f"Vosk-Modell-Archiv ist beschädigt (Datei {defekt}). Bitte erneut versuchen.")
            basis = ziel.resolve()
            if sum(e.file_size for e in z.infolist()) > MAX_ENTPACKT_BYTES:
                raise StimmFehler("Vosk-Modell-Archiv ist entpackt unerwartet groß – Entpacken abgebrochen.")
            for eintrag in z.infolist():
                name = eintrag.filename.replace("\\", "/")
                teile = Path(name).parts
                if name.startswith("/") or ".." in teile or (teile and ":" in teile[0]):
                    raise StimmFehler(f"Vosk-Modell-Archiv enthält einen unzulässigen Pfad: {name}")
                if (eintrag.external_attr >> 16) & 0o170000 == 0o120000:
                    raise StimmFehler(f"Vosk-Modell-Archiv enthält einen symbolischen Link: {name}")
                zielpfad = (ziel / name).resolve()
                if zielpfad != basis and basis not in zielpfad.parents:
                    raise StimmFehler(f"Vosk-Modell-Archiv enthält einen unzulässigen Pfad: {name}")
            z.extractall(ziel)
    except zipfile.BadZipFile as exc:
        raise StimmFehler(f"Vosk-Modell-Archiv ist kein gültiges ZIP ({kurz(exc)}). Bitte erneut versuchen.") from exc


def _herunterladen(url: str, ziel: Path) -> str:
    """Lädt ``url`` nach ``ziel`` (blockierend) und gibt die SHA-256-Prüfsumme zurück."""
    import httpx  # noqa: PLC0415

    pruefsumme = hashlib.sha256()
    groesse = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as antwort:
        antwort.raise_for_status()
        with open(ziel, "wb") as datei:
            for stueck in antwort.iter_bytes(1 << 20):
                groesse += len(stueck)
                if groesse > MAX_DOWNLOAD_BYTES:
                    raise StimmFehler("Vosk-Modell ist unerwartet groß – Download abgebrochen.")
                pruefsumme.update(stueck)
                datei.write(stueck)
    return pruefsumme.hexdigest()


def vosk_modell_sicherstellen(
    modell: str = STANDARD_VOSK_MODELL,
    verzeichnis: str | os.PathLike | None = None,
    sha256: str = "",
    herunterladen: Callable[[str, Path], str] | None = None,
) -> Path:
    """Gibt den Modellordner zurück; lädt ihn bei Bedarf herunter, prüft und entpackt ihn.

    ``modell`` ist ein Modellname von alphacephei.com oder ein Pfad zu einem eigenen Modellordner.
    """
    basis = Path(verzeichnis or Path.home() / ".jarvis" / "modelle" / "vosk").expanduser()
    modell = (modell or STANDARD_VOSK_MODELL).strip()
    eigener = Path(modell).expanduser()
    if eigener.is_absolute() or "/" in modell or "\\" in modell or modell.startswith("~"):
        if modell_vollstaendig(eigener):
            return eigener
        raise StimmFehler(f"Vosk-Modell nicht gefunden oder unvollständig: {eigener} (erwartet am/final.mdl und conf/).")
    if not _MODELLNAME.fullmatch(modell) or ".." in modell:
        # Schutz: „.“/„..“ o. Ä. würden sonst als Zielordner gelöscht/ersetzt (shutil.rmtree)
        raise StimmFehler(f"Ungültiger Vosk-Modellname „{modell}“ (erwartet z. B. {STANDARD_VOSK_MODELL} oder einen Ordnerpfad).")
    ziel = basis / modell
    if modell_vollstaendig(ziel):
        return ziel
    if os.environ.get("JARVIS_KEIN_DOWNLOAD"):
        raise StimmFehler(
            f"Vosk-Modell „{modell}“ fehlt und Downloads sind abgeschaltet (JARVIS_KEIN_DOWNLOAD). "
            f"Modell von alphacephei.com/vosk/models laden und nach {ziel} entpacken."
        )
    basis.mkdir(parents=True, exist_ok=True)
    zip_datei = basis / f".{modell}.zip.part"
    entpackt = basis / f".{modell}.entpacken"
    url = VOSK_URL.format(name=modell)
    log.info("Lade Vosk-Modell „%s“ herunter (%s) …", modell, url)
    try:
        try:
            summe = (herunterladen or _herunterladen)(url, zip_datei)
        except StimmFehler:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(
                f"Vosk-Modell konnte nicht heruntergeladen werden ({kurz(exc)}). "
                "Beim ersten Start ist eine Internetverbindung nötig (alphacephei.com)."
            ) from exc
        if sha256 and summe.lower() != sha256.lower():
            raise StimmFehler(f"Prüfsumme des Vosk-Modells stimmt nicht (erwartet {sha256[:12]}…, erhalten {summe[:12]}…).")
        shutil.rmtree(entpackt, ignore_errors=True)
        entpackt.mkdir(parents=True)
        _sicher_entpacken(zip_datei, entpackt)
        kandidaten = [entpackt / modell, entpackt, *(p for p in entpackt.iterdir() if p.is_dir())]
        quelle = next((k for k in kandidaten if modell_vollstaendig(k)), None)
        if quelle is None:
            raise StimmFehler(f"Vosk-Modell „{modell}“ ist unvollständig (am/final.mdl oder conf/ fehlt).")
        shutil.rmtree(ziel, ignore_errors=True)
        os.replace(quelle, ziel)
        log.info("Vosk-Modell bereit: %s", ziel)
        return ziel
    finally:
        zip_datei.unlink(missing_ok=True)
        shutil.rmtree(entpackt, ignore_errors=True)


# ---------------------------------------------------------------------------------------
# Detektor
# ---------------------------------------------------------------------------------------
class VoskWeckwortDetektor:
    """Weckwort-Erkennung mit Vosk – gleiche Schnittstelle wie ``OpenWakeWordDetektor``:
    ``laden()``, ``pruefen(rahmen) -> float`` (1280 int16-Samples, 16 kHz), ``zuruecksetzen()``."""

    def __init__(
        self,
        weckwort: str = "javit",
        varianten: Iterable[str] | None = None,
        verzeichnis: str | os.PathLike | None = None,
        modell: str = STANDARD_VOSK_MODELL,
        schwelle: float = 0.5,
        sha256: str = "",
        nur_ganz: bool = False,
    ):
        self.weckwort = (weckwort or "javit").strip()
        #: Treffer nur, wenn die ganze Äußerung das Wort ist (Stoppwort während der eigenen Ausgabe:
        #: das Mikrofon hört Javit selbst, und eine kleine Grammatik bildet fremde Sprache auf ihre Wörter ab)
        self.nur_ganz = nur_ganz
        self.woerter = weckwoerter(self.weckwort) or ["javit"]
        self.abgleich = WeckwortAbgleich(self.woerter, varianten)
        self.verzeichnis = Path(verzeichnis or Path.home() / ".jarvis" / "modelle" / "vosk")
        self.modell_name = modell or STANDARD_VOSK_MODELL
        self.schwelle = float(schwelle)
        self.sha256 = sha256
        self.grammatik: list[str] = []
        self.modus: str | None = None  # "grammatik" | "frei"
        self._modell = None
        self._erkenner = None
        self._vosk = None
        self._letzter_text = ""
        self._letzter_treffer: str | None = None
        self._letzter_score = 0.0
        #: Text des letzten Treffers (für Protokolle, bleibt nach zuruecksetzen erhalten)
        self.letzter_treffer_text = ""

    # -- Laden ---------------------------------------------------------------------------
    def laden(self) -> None:
        """Lädt Paket und Modell (bei Bedarf Download). Blockierend – im Thread aufrufen."""
        try:
            import vosk  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(
                f"Vosk (für das Weckwort „{self.weckwort}“) ist nicht installiert ({kurz(exc)}). Bitte den Installer "
                f"erneut ausführen (er installiert das Paket nach) oder: {HINWEIS_PAKETE}. Alternativ in den "
                "Einstellungen das Weckwort „hey_jarvis“ (openWakeWord) wählen."
            ) from exc
        self._vosk = vosk
        try:
            vosk.SetLogLevel(-1)
        except Exception:  # noqa: BLE001
            pass
        ordner = vosk_modell_sicherstellen(self.modell_name, self.verzeichnis, self.sha256)
        try:
            self._modell = vosk.Model(str(ordner))
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"Vosk-Modell konnte nicht geladen werden ({kurz(exc)}).") from exc
        finde = getattr(self._modell, "find_word", None)

        def kennt(wort: str) -> bool:
            if not callable(finde):
                return True  # ältere Vosk-Versionen: Vosk ignoriert unbekannte Wörter selbst
            try:
                return int(finde(wort)) >= 0
            except Exception:  # noqa: BLE001
                return True

        self.grammatik = grammatik_bauen(self.abgleich, kennt)
        self.modus = "grammatik" if self.grammatik else "frei"
        if self.modus == "frei":
            log.info("Keine Variante von „%s“ im Vosk-Vokabular – freie Erkennung mit phonetischem Abgleich", self.weckwort)
        else:
            log.info("Vosk-Weckwort „%s“: Grammatik mit %d Einträgen", self.weckwort, len(self.grammatik))
        self._erkenner = self._erkenner_erzeugen()

    def _erkenner_erzeugen(self):
        vosk = self._vosk
        try:
            if self.grammatik:
                erkenner = vosk.KaldiRecognizer(self._modell, ABTASTRATE, json.dumps(self.grammatik, ensure_ascii=False))
            else:
                erkenner = vosk.KaldiRecognizer(self._modell, ABTASTRATE)
        except Exception as exc:  # noqa: BLE001
            raise StimmFehler(f"Vosk-Erkenner konnte nicht erstellt werden ({kurz(exc)}).") from exc
        for methode, wert in (("SetWords", False), ("SetPartialWords", False), ("SetMaxAlternatives", 0)):
            try:
                getattr(erkenner, methode)(wert)
            except Exception:  # noqa: BLE001
                pass
        return erkenner

    # -- Erkennung -----------------------------------------------------------------------
    def pruefen(self, rahmen: np.ndarray) -> float:
        if self._erkenner is None:
            self.laden()
        daten = np.asarray(rahmen, dtype=np.int16).tobytes()
        if self._erkenner.AcceptWaveform(daten):
            text = _json_feld(self._erkenner.Result(), "text")
            final = True
        else:
            text = _json_feld(self._erkenner.PartialResult(), "partial")
            final = False
        if not text:
            self._letzter_text, self._letzter_treffer, self._letzter_score = "", None, 0.0
            return 0.0
        if text == self._letzter_text and not final:
            score = self._letzter_score  # unverändertes Teilergebnis gilt jetzt als stabil
        else:
            score, treffer = self.abgleich.bewerten(text)
            if self.nur_ganz and treffer is not None and not ganze_aeusserung(text, treffer):
                score, treffer = 0.0, None
            # nur_ganz (Stoppwort): nie beim ersten Teilergebnis auslösen – ein einzelner Rahmen der eigenen
            # Stimme kann kurz wie „stopp“ klingen; erst wenn das Ergebnis stabil ist oder abgeschlossen wurde
            stabil = final or (score >= 1.0 and not self.nur_ganz) or (treffer is not None and treffer == self._letzter_treffer)
            self._letzter_text, self._letzter_treffer, self._letzter_score = text, treffer, score
            if not stabil:
                return 0.0
        if final:
            self._letzter_text, self._letzter_treffer = "", None
        if score >= self.schwelle:
            self.letzter_treffer_text = text
            log.info("Weckwort erkannt: „%s“ (Score %.2f)", text, score)
            self.zuruecksetzen()
        return score

    def zuruecksetzen(self) -> None:
        self._letzter_text, self._letzter_treffer, self._letzter_score = "", None, 0.0
        if self._erkenner is not None:
            try:
                self._erkenner.Reset()
            except Exception:  # noqa: BLE001
                log.debug("Vosk-Reset fehlgeschlagen", exc_info=True)


def ganze_aeusserung(text: str, treffer: str) -> bool:
    """True, wenn ``text`` (ohne ``[unk]``) nur aus dem Treffer besteht – nichts davor, nichts danach."""
    woerter = [w for w in woerter_normalisieren(text) if w != "[unk]"]
    return " ".join(woerter) == " ".join(woerter_normalisieren(treffer))


def _json_feld(roh: str, feld: str) -> str:
    try:
        return str(json.loads(roh or "{}").get(feld, "") or "").strip()
    except (TypeError, ValueError):
        return ""
