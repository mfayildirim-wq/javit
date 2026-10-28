"""Gedächtnis-Pflege: lokale Einbettungen, Einbetter-Kette und Nachbereitung von Unterhaltungen.

* ``LokaleEinbettung`` – Einbettungen ohne Ollama/Cloud über ``fastembed`` (ONNX, Extra ``kern[gedaechtnis]``);
  das Modell (ca. 220 MB) wird beim ersten Gebrauch nach ``~/.jarvis/modelle/einbettung`` geladen,
  nicht bei ``JARVIS_KEIN_DOWNLOAD=1``.
* ``EinbetterKette`` – fragt mehrere Einbetter der Reihe nach; ``modell`` nennt den zuletzt erfolgreichen.
* ``Nachbereiter`` – erzeugt Titel für Unterhaltungen und beim Verlassen Zusammenfassung plus dauerhafte
  Fakten (Erinnerungen mit Herkunft „auto“), abgeglichen mit vorhandenen Erinnerungen.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .gedaechtnis import TITEL_MAX, Einbetter, Gedaechtnis, einbetter_modell, titel_pruefen
from .konfig import Einstellungen, jarvis_home

log = logging.getLogger("jarvis.gedaechtnis")

LOKALES_MODELL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MAX_FAKTEN = 8
ZUSAMMENFASSUNG_MAX = 600
#: Fakten mit solchen Wörtern werden nie automatisch gemerkt (Zugangsdaten gehören in den Schlüsselbund)
_GEHEIM = re.compile(r"passw|kennwort|token|api[-_ ]?key|secret|geheimnis", re.I)
_JSON_ZAUN = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


# ---------------------------------------------------------------- Einbetter
class BenannterEinbetter:
    """Hängt an eine Einbettungsfunktion (z. B. ``LLMFassade.einbetten``) einen Modellnamen."""

    def __init__(self, funktion: Einbetter, modell: str | Callable[[], str | None]):
        self._funktion = funktion
        self._modell = modell

    @property
    def modell(self) -> str:
        wert = self._modell() if callable(self._modell) else self._modell
        return str(wert or "unbekannt")

    async def __call__(self, texte: list[str]) -> list[list[float]] | None:
        return await self._funktion(texte)


class LokaleEinbettung:
    """Einbettungen über fastembed (ONNX, CPU). Liefert None, wenn das Paket fehlt oder der Download
    abgeschaltet ist und das Modell noch nicht im Cache liegt."""

    modell = LOKALES_MODELL

    def __init__(self, ordner: Path | None = None):
        self.ordner = ordner or (jarvis_home() / "modelle" / "einbettung")
        self._instanz: Any = None
        self._aus = False
        self._sperre = asyncio.Lock()

    def im_cache(self) -> bool:
        if not self.ordner.is_dir():
            return False
        return any("MiniLM" in p.name for p in self.ordner.iterdir())

    def _laden(self) -> Any:
        if self._instanz is not None or self._aus:
            return self._instanz
        try:
            from fastembed import TextEmbedding  # noqa: PLC0415
        except ImportError:
            log.info("fastembed fehlt – keine lokale Einbettung (pip install -e 'kern[gedaechtnis]')")
            self._aus = True
            return None
        if os.environ.get("JARVIS_KEIN_DOWNLOAD") and not self.im_cache():
            log.info("Einbettungsmodell fehlt und Downloads sind abgeschaltet (JARVIS_KEIN_DOWNLOAD)")
            self._aus = True
            return None
        try:
            self.ordner.mkdir(parents=True, exist_ok=True)
            self._instanz = TextEmbedding(model_name=LOKALES_MODELL, cache_dir=str(self.ordner))
        except Exception:  # noqa: BLE001
            log.warning("Lokales Einbettungsmodell konnte nicht geladen werden", exc_info=True)
            self._aus = True
            return None
        return self._instanz

    async def __call__(self, texte: list[str]) -> list[list[float]] | None:
        if not texte:
            return None
        async with self._sperre:
            instanz = await asyncio.to_thread(self._laden)
        if instanz is None:
            return None
        try:
            return await asyncio.to_thread(lambda: [[float(x) for x in v] for v in instanz.embed(list(texte))])
        except Exception:  # noqa: BLE001
            log.warning("Lokale Einbettung fehlgeschlagen", exc_info=True)
            return None


class EinbetterKette:
    """Fragt Einbetter der Reihe nach; der erste mit Ergebnis gewinnt. ``modell`` = zuletzt erfolgreicher."""

    def __init__(self, *einbetter: Einbetter | None):
        self._einbetter = [e for e in einbetter if e is not None]
        self._zuletzt: Einbetter | None = self._einbetter[0] if self._einbetter else None

    @property
    def modell(self) -> str:
        return einbetter_modell(self._zuletzt)

    async def __call__(self, texte: list[str]) -> list[list[float]] | None:
        for e in self._einbetter:
            try:
                vektoren = await e(texte)
            except Exception:  # noqa: BLE001
                log.debug("Einbetter %s fehlgeschlagen", einbetter_modell(e), exc_info=True)
                vektoren = None
            if vektoren:
                self._zuletzt = e
                return vektoren
        return None


# ---------------------------------------------------------------- Nachbereitung
def json_block(text: str) -> dict[str, Any] | None:
    """Erster JSON-Objektblock aus einer Modellantwort (auch in ```-Zäunen); None bei Unbrauchbarem."""
    kandidaten = [m.group(1) for m in _JSON_ZAUN.finditer(text)] + [text]
    decoder = json.JSONDecoder()
    for k in kandidaten:
        anfang = k.find("{")
        while anfang >= 0:
            try:
                daten, _ = decoder.raw_decode(k[anfang:])
            except json.JSONDecodeError:
                anfang = k.find("{", anfang + 1)
                continue
            if isinstance(daten, dict):
                return daten
            anfang = k.find("{", anfang + 1)
    return None


def kuerzen(text: str, maximum: int) -> str:
    """Kürzt an einem Satzende (sonst Wortgrenze) mit „…“ – Modelle halten Längenvorgaben nicht immer ein."""
    if len(text) <= maximum:
        return text
    kurz = text[:maximum]
    satz = max(kurz.rfind(". "), kurz.rfind("! "), kurz.rfind("? "))
    if satz >= maximum // 2:
        return kurz[: satz + 1]
    wort = kurz.rfind(" ")
    return (kurz[:wort] if wort > 0 else kurz).rstrip(" ,;:") + " …"


def titel_bereinigen(text: str) -> str:
    t = text.strip().splitlines()[0] if text.strip() else ""
    t = re.sub(r"^\W*(titel|title)\s*:\s*", "", t, flags=re.I)
    t = t.strip(" \"'„“‚‘«»`*#.:;!-–—")
    return t[:TITEL_MAX].strip()


def titel_fallback(erste_nachricht: str) -> str:
    t = " ".join(erste_nachricht.split())
    if len(t) > 60:
        t = t[:59].rstrip() + "…"
    return t or "Unterhaltung"


TITEL_SYSTEM = (
    "Du gibst Unterhaltungen einen kurzen deutschen Titel aus drei bis fünf Wörtern. "
    "Antworte nur mit dem Titel: keine Anführungszeichen, kein Punkt, keine Erklärung."
)
NACHBEREITUNG_SYSTEM = (
    "Du fasst eine Unterhaltung zwischen einem Nutzer und seinem Assistenten nach und pflegst das "
    "Langzeitgedächtnis des Assistenten. Antworte ausschließlich mit einem JSON-Objekt:\n"
    '{"zusammenfassung": "zwei bis drei Sätze (höchstens 400 Zeichen), was besprochen und erreicht wurde", '
    '"fakten": ["dauerhafter Fakt über den Nutzer", "..."]}\n'
    "Regeln für fakten: nur dauerhaft Gültiges über den Nutzer (Vorlieben, Lebensumstände, Arbeit, "
    "Projekte, Beziehungen, Absprachen mit dem Assistenten), als ganze deutsche Sätze in der dritten "
    "Person („Der Nutzer …“). Keine Gesprächsdetails, keine Aufgaben von heute, keine Vermutungen, "
    f"keine Zugangsdaten. Höchstens {MAX_FAKTEN} Einträge; gibt es nichts Dauerhaftes, eine leere Liste."
)


class Nachbereiter:
    def __init__(
        self,
        llm: Any,
        gedaechtnis: Gedaechtnis,
        einstellungen: Einstellungen | Callable[[], Einstellungen],
    ):
        self.llm = llm
        self.gedaechtnis = gedaechtnis
        self._einstellungen = einstellungen

    @property
    def einstellungen(self) -> Einstellungen:
        e = self._einstellungen
        return e() if callable(e) else e

    @property
    def automatisch(self) -> bool:
        return bool(getattr(self.einstellungen, "gedaechtnis_automatisch", True))

    async def _vervollstaendigen(self, system: str, nutzer: str, temperatur: float = 0.2) -> str:
        text = ""
        async for ereignis in self.llm.antwort_streamen(
            [{"role": "system", "content": system}, {"role": "user", "content": nutzer}],
            werkzeuge=None,
            temperatur=temperatur,
        ):
            if ereignis.get("typ") == "ende":
                text = str(ereignis.get("text") or "")
        return text.strip()

    @staticmethod
    def _abschrift(verlauf: list[dict[str, Any]], max_zeichen: int = 12000) -> str:
        zeilen = []
        for v in verlauf:
            wer = "Nutzer" if v["rolle"] == "nutzer" else "Assistent"
            inhalt = " ".join(str(v["inhalt"]).split())
            if len(inhalt) > 1500:
                inhalt = inhalt[:1500] + " …"
            zeilen.append(f"{wer}: {inhalt}")
        text = "\n".join(zeilen)
        return text[-max_zeichen:]

    # ---------- Titel ----------
    async def titel_erzeugen(self, kennung: int) -> str | None:
        """Automatischer Titel nach dem ersten Austausch; None, wenn nichts zu tun ist."""
        u = self.gedaechtnis.unterhaltung(kennung)
        if not u or u["titel_fest"]:
            return None
        verlauf = self.gedaechtnis.verlauf(limit=6, unterhaltung_id=kennung)
        nutzer = [v for v in verlauf if v["rolle"] == "nutzer" and v["inhalt"].strip()]
        if not nutzer:
            return None
        titel = ""
        if self.automatisch:
            try:
                antwort = await self._vervollstaendigen(TITEL_SYSTEM, self._abschrift(verlauf, 3000))
                titel = titel_bereinigen(antwort)
            except Exception:  # noqa: BLE001
                log.debug("Titel konnte nicht erzeugt werden", exc_info=True)
        if not titel or len(titel.split()) > 8:
            titel = titel_fallback(nutzer[0]["inhalt"])
        try:
            self.gedaechtnis.unterhaltung_umbenennen(kennung, titel_pruefen(titel), fest=False)
        except (KeyError, ValueError):
            return None
        return titel

    # ---------- Zusammenfassung und Fakten ----------
    async def nachbereiten(self, kennung: int) -> dict[str, Any] | None:
        """Zusammenfassung + Fakten einer verlassenen Unterhaltung; None, wenn nichts zu tun ist."""
        if not self.automatisch:
            return None
        u = self.gedaechtnis.unterhaltung(kennung)
        if not u or u["nachrichten"] < 2 or self.gedaechtnis.beitraege_seit(kennung, u["nachbereitet"]) == 0:
            return None
        verlauf = self.gedaechtnis.verlauf(limit=80, unterhaltung_id=kennung)
        antwort = await self._vervollstaendigen(NACHBEREITUNG_SYSTEM, self._abschrift(verlauf))
        daten = json_block(antwort)
        if not daten:
            log.info("Nachbereitung: keine verwertbare Antwort für Unterhaltung %s", kennung)
            return None
        zusammenfassung = kuerzen(" ".join(str(daten.get("zusammenfassung") or "").split()), ZUSAMMENFASSUNG_MAX)
        if zusammenfassung:
            self.gedaechtnis.zusammenfassung_setzen(kennung, zusammenfassung)
        neu = aktualisiert = 0
        fakten = daten.get("fakten") if isinstance(daten.get("fakten"), list) else []
        for fakt in [str(f).strip() for f in fakten if str(f).strip()][:MAX_FAKTEN]:
            if _GEHEIM.search(fakt):
                continue
            treffer = await self.gedaechtnis.suchen(fakt, anzahl=1, mindestwert=0.0)
            bester = treffer[0] if treffer else None
            if bester and (bester["relevanz"] >= 0.85 or (bester["relevanz"] >= 0.6 and bester["quelle"] == "auto")):
                if bester["text"] != fakt:
                    await self.gedaechtnis.erinnerung_aktualisieren(bester["id"], fakt)
                    aktualisiert += 1
            else:
                await self.gedaechtnis.erinnern(fakt, quelle="auto", unterhaltung_id=kennung)
                neu += 1
        self.gedaechtnis.nachbereitet_setzen(kennung)
        return {"zusammenfassung": zusammenfassung, "neu": neu, "aktualisiert": aktualisiert}

