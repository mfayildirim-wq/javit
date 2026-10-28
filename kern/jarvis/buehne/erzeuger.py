"""Erzeuger der Bühne: baut und ändert Vorlagen mit dem Modell (Katalog-Prompt, Validierung, ein Reparaturversuch,
deterministischer Fallback) und leitet Stile aus URL, Datei oder Klassen ab. Anbieterunabhängig über ``LLMFassade``."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any, Callable
from urllib.parse import urljoin

from ..gedaechtnis_pflege import json_block
from .daten import abbildung_anwenden, ergebnis_parsen, standardvorlage
from .katalog import Katalog, katalog_laden, komponenten_pruefen, komponenten_saeubern
from .speicher import kennung_aus

log = logging.getLogger("jarvis.buehne")

MAX_AUSZUG = 6000
MAX_SEITE = 1_000_000
STILFARBEN = ("primaer", "akzent", "hintergrund", "flaeche", "text", "dezent", "ok", "warn", "fehler")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_RGB = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")
_VARIABLE = re.compile(r"(--[a-zA-Z0-9_-]+)\s*:\s*([^;}]+)")
_SCHRIFT = re.compile(r"font-family\s*:\s*([^;}]+)", re.I)
_RUNDUNG = re.compile(r"border-radius\s*:\s*(\d+(?:\.\d+)?)px", re.I)
_STYLESHEET = re.compile(r"<link[^>]+rel=[\"']?stylesheet[\"']?[^>]*href=[\"']([^\"']+)[\"']", re.I)
_STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.I | re.S)

SYSTEM_VORLAGE = """Du entwirfst Oberflächen für die Bühne des Assistenten im A2UI-Format. Antworte ausschließlich mit einem JSON-Objekt:
{"name": "kurzer Name", "zweck": "ein Satz, wofür die Vorlage ist", "abbildung": {"/zielpfad": "/quellpfad"}, "datenschema": {JSON-Schema des Datenmodells}, "komponenten": [ … ]}

Regeln:
- komponenten ist eine flache Liste; genau eine Komponente hat die id "root". Kinder werden über IDs referenziert.
- Werte sind Literale, Bindungen {"path": "/pfad"} ins Datenmodell oder Funktionsaufrufe {"call": …, "args": …}.
- Listen: "children": {"path": "/liste", "componentId": "vorlage_id"}; in der Vorlage sind Pfade relativ ("name" = Feld des Eintrags).
- abbildung: Ziel-JSON-Pointer im Datenmodell → Quell-JSON-Pointer im Werkzeugergebnis (optional "|datum", "|waehrung:EUR", "|zahl:1"). Alle in Bindungen verwendeten Pfade müssen aus der Abbildung entstehen.
- Erfinde keine Daten, Bilder oder URLs; nutze nur Felder, die im Ergebnis vorkommen. Bilder nur, wenn das Ergebnis https-URLs enthält.
- Aktionen auf Knöpfen: {"action": {"event": {"name": "kleinschrift_mit_unterstrich", "context": {"id": {"path": "id"}}}}}; gib jedem sinnvollen Eintrag 1–3 Aktionen (öffnen, bearbeiten, kontaktieren …).
- Oben ein Titel (Text h2) und eine Zeile mit Anzahl oder Stand; Listen als Kacheln (Grid+Card) oder Tabelle je nach Stilvorliebe; wichtige Zahlen als Kennzahl.
- Nur Komponenten und Eigenschaften aus dem Katalog. Keine HTML- oder CSS-Angaben. Sprache: Deutsch.
"""

SYSTEM_AENDERN = """Du änderst eine bestehende Vorlage der Bühne (A2UI). Antworte ausschließlich mit einem JSON-Objekt:
{"komponenten": [ … vollständige neue Liste … ], "abbildung": {…} (nur wenn geändert), "datenschema": {…} (nur wenn geändert), "zweck": "…" (nur wenn geändert)}
Behalte alles bei, was der Wunsch nicht berührt (IDs, Aktionen, Bindungen). Regeln wie beim Erstellen: flache Liste, genau eine "root", Bindungen {"path": …}, Listen-Templates mit relativen Pfaden, nur Katalog-Komponenten, keine erfundenen Daten.
"""

SYSTEM_STIL = """Du leitest aus den Gestaltungsmerkmalen einer App einen Stil für die Bühne des Assistenten ab. Antworte ausschließlich mit einem JSON-Objekt:
{"schema": "hell"|"dunkel", "farben": {"primaer": "#rrggbb", "akzent": "#rrggbb", "hintergrund": "#rrggbb", "flaeche": "#rrggbb", "text": "#rrggbb", "dezent": "#rrggbb", "ok": "#rrggbb", "warn": "#rrggbb", "fehler": "#rrggbb"}, "schrift": {"familie": "CSS-font-family", "basisgroesse": 14}, "rundung": 8, "abstand": 12, "dichte": "dicht"|"normal"|"luftig", "schatten": "keiner"|"weich"|"stark", "vorlieben": {"liste": "kacheln"|"zeilen"|"tabelle", "bildgroesse": "klein"|"mittel"|"gross", "kennzahlenOben": true}}
Wähle die Markenfarbe als primaer, eine passende Akzentfarbe, Hintergrund/Fläche/Text mit gutem Kontrast (mind. 4,5:1 Text auf Hintergrund). Fehlen Angaben, ergänze stimmige Werte.
"""


def _auszug(daten: Any, max_zeichen: int = MAX_AUSZUG) -> str:
    """Kompakter JSON-Auszug für den Prompt: Listen auf 5 Einträge, Text auf max_zeichen."""

    def kuerzen(x: Any, tiefe: int = 0) -> Any:
        if isinstance(x, list):
            return [kuerzen(e, tiefe + 1) for e in x[:5]] + ([f"… {len(x) - 5} weitere"] if len(x) > 5 else [])
        if isinstance(x, dict):
            return {k: kuerzen(v, tiefe + 1) for k, v in list(x.items())[:40]}
        if isinstance(x, str) and len(x) > 300:
            return x[:300] + " …"
        return x

    text = json.dumps(kuerzen(daten), ensure_ascii=False, indent=1)
    return text if len(text) <= max_zeichen else text[:max_zeichen] + "\n…"


class Erzeuger:
    def __init__(
        self,
        llm: Any,
        katalog: Katalog | None = None,
        http_client_fabrik: Callable[..., Any] | None = None,
    ):
        self.llm = llm
        self.katalog = katalog or katalog_laden()
        self._fabrik = http_client_fabrik

    # ------------------------------------------------------------------ Modell
    async def _antwort(self, system: str, nutzer: str, temperatur: float = 0.2, verlauf: list[dict[str, str]] | None = None) -> str:
        nachrichten = [{"role": "system", "content": system}, *(verlauf or []), {"role": "user", "content": nutzer}]
        text = ""
        async for teil in self.llm.antwort_streamen(nachrichten, werkzeuge=None, temperatur=temperatur):
            if teil.get("typ") == "ende":
                text = str(teil.get("text") or "")
        return text.strip()

    @property
    def modellname(self) -> str | None:
        try:
            return str(self.llm.einstellungen.modell)
        except Exception:  # noqa: BLE001
            return None

    def _system_vorlage(self, stil: dict[str, Any] | None) -> str:
        teile = [SYSTEM_VORLAGE, "", "# Katalog", self.katalog.beschreibung_fuer_prompt()]
        vorlieben = (stil or {}).get("vorlieben") or {}
        if vorlieben:
            teile += ["", "# Stilvorlieben", json.dumps(vorlieben, ensure_ascii=False)]
        return "\n".join(teile)

    def _pruefen(self, daten: Any, ergebnis: Any) -> tuple[dict[str, Any] | None, list[str]]:
        """→ (gesäuberte Vorlage, Fehler)."""
        if not isinstance(daten, dict):
            return None, ["Antwort ist kein JSON-Objekt"]
        fehler: list[str] = []
        komponenten = daten.get("komponenten")
        if not isinstance(komponenten, list):
            return None, ["komponenten fehlt oder ist keine Liste"]
        komponenten = komponenten_saeubern(komponenten, self.katalog)
        fehler += komponenten_pruefen(komponenten, self.katalog)
        abbildung = daten.get("abbildung")
        if abbildung is not None and not (isinstance(abbildung, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in abbildung.items())):
            fehler.append("abbildung muss ein Objekt aus Text → Text sein")
            abbildung = None
        if not fehler and abbildung:
            modell = abbildung_anwenden(abbildung, ergebnis_parsen(ergebnis))
            if not isinstance(modell, dict) or not modell or all(v is None for v in modell.values()):
                fehler.append("abbildung liefert aus dem Ergebnis keine Daten – Quellpfade prüfen")
        if fehler:
            return None, fehler
        return {
            "name": str(daten.get("name") or "").strip()[:80],
            "zweck": str(daten.get("zweck") or "").strip()[:300],
            "komponenten": komponenten,
            "abbildung": abbildung or {},
            "datenschema": daten.get("datenschema") if isinstance(daten.get("datenschema"), dict) else {"type": "object"},
        }, []

    async def vorlage_bauen(
        self,
        werkzeug: str,
        ergebnis: Any,
        wunsch: str = "",
        stil: dict[str, Any] | None = None,
        titel: str | None = None,
    ) -> dict[str, Any]:
        """Vorlage aus einem Werkzeugergebnis; nach zwei fehlgeschlagenen Versuchen die Standardvorlage."""
        daten = ergebnis_parsen(ergebnis)
        titel = (titel or werkzeug.split("__")[-1].replace("_", " ").capitalize()).strip()
        nutzer = (
            f"Werkzeug: {werkzeug}\nTitel: {titel}\n"
            + (f"Wunsch des Nutzers: {wunsch}\n" if wunsch else "")
            + "Ergebnis (Auszug, echte Struktur):\n"
            + _auszug(daten)
        )
        system = self._system_vorlage(stil)
        verlauf: list[dict[str, str]] = []
        for versuch in range(2):
            try:
                antwort = await self._antwort(system, nutzer if versuch == 0 else nutzer_reparatur, verlauf=verlauf)  # noqa: F821
            except Exception as exc:  # noqa: BLE001
                log.warning("Bühne: Modellaufruf fehlgeschlagen (%s)", exc)
                break
            vorlage, fehler = self._pruefen(json_block(antwort), ergebnis)
            if vorlage is not None:
                vorlage["name"] = vorlage["name"] or titel
                vorlage["modell"] = self.modellname
                return vorlage
            log.info("Bühne: Vorlage ungültig (Versuch %d): %s", versuch + 1, "; ".join(fehler[:5]))
            verlauf = [{"role": "user", "content": nutzer}, {"role": "assistant", "content": antwort[:6000]}]
            nutzer_reparatur = "Die Antwort war ungültig:\n- " + "\n- ".join(fehler[:8]) + "\nGib das vollständige, korrigierte JSON-Objekt aus."
        standard = standardvorlage(werkzeug, ergebnis, titel)
        standard["modell"] = None
        return standard

    async def vorlage_aendern(self, vorlage: dict[str, Any], wunsch: str, beispiel_daten: Any = None) -> dict[str, Any]:
        """Neue Komponentenliste (und ggf. Abbildung/Schema/Zweck) für eine bestehende Vorlage."""
        abbildung_alt = (vorlage.get("datenquelle") or {}).get("abbildung") or {}
        nutzer = (
            f"Vorlage „{vorlage.get('name')}“ ({vorlage.get('zweck', '')}).\nWunsch des Nutzers: {wunsch}\n"
            f"Aktuelle Abbildung: {json.dumps(abbildung_alt, ensure_ascii=False)}\n"
            f"Aktuelle Komponenten:\n{json.dumps(vorlage.get('komponenten') or [], ensure_ascii=False)}\n"
            + (f"Beispieldaten (Datenmodell):\n{_auszug(beispiel_daten, 3000)}\n" if beispiel_daten is not None else "")
        )
        system = "\n".join([SYSTEM_AENDERN, "", "# Katalog", self.katalog.beschreibung_fuer_prompt()])
        verlauf: list[dict[str, str]] = []
        for versuch in range(2):
            antwort = await self._antwort(system, nutzer if versuch == 0 else nutzer_reparatur, verlauf=verlauf)  # noqa: F821
            daten = json_block(antwort)
            if isinstance(daten, dict) and isinstance(daten.get("komponenten"), list):
                komponenten = komponenten_saeubern(daten["komponenten"], self.katalog)
                fehler = komponenten_pruefen(komponenten, self.katalog)
                if not fehler:
                    abbildung = daten.get("abbildung") if isinstance(daten.get("abbildung"), dict) else abbildung_alt
                    return {
                        "komponenten": komponenten,
                        "abbildung": {str(k): str(v) for k, v in abbildung.items()},
                        "datenschema": daten.get("datenschema") if isinstance(daten.get("datenschema"), dict) else vorlage.get("datenschema"),
                        "zweck": str(daten.get("zweck") or vorlage.get("zweck") or "").strip()[:300],
                        "modell": self.modellname,
                    }
            else:
                fehler = ["Antwort ist kein JSON-Objekt mit komponenten"]
            verlauf = [{"role": "user", "content": nutzer}, {"role": "assistant", "content": antwort[:6000]}]
            nutzer_reparatur = "Die Antwort war ungültig:\n- " + "\n- ".join(fehler[:8]) + "\nGib das vollständige, korrigierte JSON-Objekt aus."
        raise ValueError("Die Vorlage konnte nicht geändert werden – die Modellantwort war zweimal ungültig.")

    # ------------------------------------------------------------------ Stile
    async def _quelle_laden(self, quelle: dict[str, Any]) -> tuple[str, str]:
        """→ (Text für Kandidaten, Beschreibung der Quelle)."""
        import httpx  # noqa: PLC0415

        art = str(quelle.get("art") or "werte")
        if art in ("klassen", "datei"):
            return str(quelle.get("inhalt") or quelle.get("wert") or ""), art
        if art != "url":
            return "", art
        url = str(quelle.get("wert") or "").strip()
        if not url.startswith("https://"):
            raise ValueError("Stil ableiten: nur https-Adressen.")
        client = self._fabrik(timeout=20.0, follow_redirects=True) if self._fabrik else httpx.AsyncClient(timeout=20.0, follow_redirects=True)
        texte: list[str] = []
        async with client:
            antwort = await client.get(url)
            antwort.raise_for_status()
            html = antwort.text[:MAX_SEITE]
            texte += [m.group(1) for m in _STYLE.finditer(html)]
            for href in _STYLESHEET.findall(html)[:5]:
                try:
                    css = await client.get(urljoin(url, href))
                    if css.status_code == 200:
                        texte.append(css.text[:MAX_SEITE])
                except Exception:  # noqa: BLE001
                    continue
            # Inline-Styles und Tailwind-Klassen liefern oft die Farben
            texte.append(html)
        return "\n".join(texte), "url"

    def _stil_prompt(self, name: str, kandidaten: dict[str, Any], art: str) -> str:
        return (
            f"App/Stil: {name} (Quelle: {art})\n"
            f"CSS-Variablen: {json.dumps(dict(list(kandidaten['variablen'].items())[:40]), ensure_ascii=False)}\n"
            f"Häufigste Farben: {kandidaten['farben'][:20]}\n"
            f"Schriften: {kandidaten['schriften'][:5]}\n"
            f"Rundungen (px): {kandidaten['rundungen'][:10]}\n"
            f"Dunkler Hintergrund wahrscheinlich: {kandidaten['dunkel']}"
        )

    def _stil_pruefen(self, daten: Any, kandidaten: dict[str, Any], name: str, quelle: dict[str, Any]) -> dict[str, Any]:
        farben_kand = kandidaten["farben"] or ["#7fe8ff"]
        dunkel = bool(kandidaten.get("dunkel"))
        standard = {
            "schema": "dunkel" if dunkel else "hell",
            "farben": {
                "primaer": farben_kand[0],
                "akzent": farben_kand[1] if len(farben_kand) > 1 else "#ffb86b",
                "hintergrund": "#0b1624" if dunkel else "#f5f9fc",
                "flaeche": "#132033" if dunkel else "#ffffff",
                "text": "#e2fbff" if dunkel else "#0f1f2e",
                "dezent": "#8aa4b8" if dunkel else "#5c6f82",
                "ok": "#5de4a0" if dunkel else "#1f9d5a",
                "warn": "#ffc857" if dunkel else "#b7791f",
                "fehler": "#ff6b6b" if dunkel else "#c62828",
            },
            "schrift": {"familie": kandidaten["schriften"][0] if kandidaten["schriften"] else "Sora Variable, system-ui, sans-serif", "basisgroesse": 14},
            "rundung": kandidaten["rundungen"][0] if kandidaten["rundungen"] else 10,
            "abstand": 12,
            "dichte": "normal",
            "schatten": "weich",
        }
        werte = dict(standard)
        vorlieben = {"liste": "kacheln", "bildgroesse": "mittel", "kennzahlenOben": True}
        if isinstance(daten, dict):
            if daten.get("schema") in ("hell", "dunkel"):
                werte["schema"] = daten["schema"]
            farben = daten.get("farben") if isinstance(daten.get("farben"), dict) else {}
            werte["farben"] = {k: (_hex_norm(farben.get(k)) or standard["farben"][k]) for k in STILFARBEN}
            schrift = daten.get("schrift") if isinstance(daten.get("schrift"), dict) else {}
            werte["schrift"] = {
                "familie": str(schrift.get("familie") or standard["schrift"]["familie"])[:120],
                "basisgroesse": int(schrift.get("basisgroesse") or 14) if str(schrift.get("basisgroesse", "")).isdigit() else 14,
            }
            for feld, lo, hi in (("rundung", 0, 32), ("abstand", 4, 32)):
                try:
                    werte[feld] = int(min(max(float(daten.get(feld, standard[feld])), lo), hi))
                except (TypeError, ValueError):
                    werte[feld] = standard[feld]
            if daten.get("dichte") in ("dicht", "normal", "luftig"):
                werte["dichte"] = daten["dichte"]
            if daten.get("schatten") in ("keiner", "weich", "stark"):
                werte["schatten"] = daten["schatten"]
            v = daten.get("vorlieben") if isinstance(daten.get("vorlieben"), dict) else {}
            if v.get("liste") in ("kacheln", "zeilen", "tabelle"):
                vorlieben["liste"] = v["liste"]
            if v.get("bildgroesse") in ("klein", "mittel", "gross"):
                vorlieben["bildgroesse"] = v["bildgroesse"]
            if isinstance(v.get("kennzahlenOben"), bool):
                vorlieben["kennzahlenOben"] = v["kennzahlenOben"]
        return {
            "id": kennung_aus(name, "stil"),
            "name": name.strip() or "Stil",
            "beschreibung": f"abgeleitet ({quelle.get('art')})",
            "quelle": {"art": str(quelle.get("art") or "werte"), **({"wert": quelle["wert"]} if quelle.get("art") == "url" and quelle.get("wert") else {})},
            "werte": werte,
            "vorlieben": vorlieben,
        }

    async def stil_ableiten(self, name: str, quelle: dict[str, Any]) -> dict[str, Any]:
        text, art = await self._quelle_laden(quelle)
        kandidaten = css_kandidaten(text)
        daten: Any = None
        if text.strip():
            try:
                antwort = await self._antwort(SYSTEM_STIL, self._stil_prompt(name, kandidaten, art))
                daten = json_block(antwort)
            except Exception as exc:  # noqa: BLE001
                log.warning("Bühne: Stil-Ableitung über das Modell fehlgeschlagen (%s)", exc)
        return self._stil_pruefen(daten, kandidaten, name, quelle)


# ---------------------------------------------------------------- CSS-Kandidaten
def _hex_norm(wert: Any) -> str | None:
    if not isinstance(wert, str):
        return None
    m = _HEX.search(wert.strip())
    if m:
        h = m.group(0).lower()
        if len(h) == 4:
            h = "#" + "".join(c * 2 for c in h[1:])
        return h
    m = _RGB.search(wert)
    if m:
        r, g, b = (min(int(x), 255) for x in m.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _helligkeit(hexfarbe: str) -> float:
    r, g, b = (int(hexfarbe[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def css_kandidaten(text: str) -> dict[str, Any]:
    """Farben (nach Häufigkeit, ohne Schwarz/Weiß/Grau), CSS-Variablen mit Farben, Schriften, Rundungen."""
    variablen: dict[str, str] = {}
    for name, wert in _VARIABLE.findall(text):
        farbe = _hex_norm(wert)
        if farbe and name not in variablen:
            variablen[name] = farbe
    zaehler: Counter[str] = Counter()
    for m in _HEX.finditer(text):
        farbe = _hex_norm(m.group(0))
        if farbe:
            zaehler[farbe] += 1
    for m in _RGB.finditer(text):
        farbe = _hex_norm(m.group(0) + ")")
        if farbe:
            zaehler[farbe] += 1
    bunt, neutral = [], []
    for farbe, _ in zaehler.most_common():
        r, g, b = (int(farbe[i : i + 2], 16) for i in (1, 3, 5))
        (neutral if max(r, g, b) - min(r, g, b) < 24 else bunt).append(farbe)
    for v in variablen.values():
        if v in bunt:
            bunt.remove(v)
            bunt.insert(0, v)
    schriften: list[str] = []
    for m in _SCHRIFT.findall(text):
        familie = m.strip().strip(";").strip()
        if familie and familie not in schriften and "inherit" not in familie:
            schriften.append(familie[:120])
    rundungen = sorted({int(float(r)) for r in _RUNDUNG.findall(text) if 0 < float(r) <= 40}, key=lambda r: -text.count(f"border-radius: {r}px") - text.count(f"border-radius:{r}px"))
    hintergruende = [f for f in neutral[:3]] or []
    dunkel = bool(hintergruende) and sum(_helligkeit(f) for f in hintergruende) / len(hintergruende) < 110
    return {"variablen": variablen, "farben": bunt[:30], "neutral": neutral[:10], "schriften": schriften[:8], "rundungen": rundungen[:10], "dunkel": dunkel}
