"""Dauerhafter Speicher der Bühne unter ``~/.jarvis/buehne/``: Vorlagen (mit bis zu 10 Versionen), Rezepte,
Stile (vordefinierte aus dem Paket + eigene), Zuordnung Integration → Stil und die zuletzt offenen Flächen.
Alles gilt global, nicht je Unterhaltung."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..konfig import jarvis_home

PROTOKOLL_VERSION = "v0.9.1"
KATALOG_ID = "jarvis:buehne/1"
MAX_VERSIONEN = 10
STILE_PAKET = Path(__file__).with_name("stile")
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def app_von(werkzeug: str | None) -> str:
    """App/Integration eines Werkzeugs: Präfix vor ``__`` (gg__read → gg), sonst der Werkzeugname selbst."""
    w = str(werkzeug or "")
    return w.split("__", 1)[0] if "__" in w else w


def kennung_aus(name: str, standard: str = "vorlage") -> str:
    """„Immobilien Liste“ → „immobilien-liste“ (a–z, 0–9, Bindestrich)."""
    text = (name or "").translate(_UMLAUTE).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:60] or standard


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _lesen(pfad: Path, standard: Any) -> Any:
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return standard


def _schreiben(pfad: Path, daten: Any) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(pfad)


class BuehnenSpeicher:
    def __init__(self, home: Path | None = None):
        self.ordner = Path(home or jarvis_home()) / "buehne"
        for unter in ("vorlagen", "rezepte", "stile"):
            (self.ordner / unter).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ Vorlagen
    def _vorlage_pfad(self, kennung: str) -> Path:
        return self.ordner / "vorlagen" / f"{kennung}.json"

    def _eindeutig(self, ordner: str, kennung: str) -> str:
        basis, n = kennung, 2
        while (self.ordner / ordner / f"{kennung}.json").exists():
            kennung = f"{basis}-{n}"
            n += 1
        return kennung

    @staticmethod
    def _vorlage_sicht(roh: dict[str, Any], mit_komponenten: bool = True) -> dict[str, Any]:
        versionen = roh.get("versionen") or []
        aktuell = versionen[-1] if versionen else {}
        sicht = {
            "id": roh["id"],
            "name": roh.get("name", roh["id"]),
            "zweck": roh.get("zweck", ""),
            "version": int(aktuell.get("version", 1)),
            "protokollVersion": roh.get("protokollVersion", PROTOKOLL_VERSION),
            "katalogId": roh.get("katalogId", KATALOG_ID),
            "datenschema": aktuell.get("datenschema"),
            "datenquelle": aktuell.get("datenquelle") or {},
            "aktionen": dict(roh.get("aktionen") or {}),
            "stil": roh.get("stil"),
            "signatur": roh.get("signatur") or {},
            "erstellt": roh.get("erstellt"),
            "geaendert": aktuell.get("geaendert", roh.get("erstellt")),
            "modell": aktuell.get("modell"),
            "versionen": len(versionen),
        }
        if mit_komponenten:
            sicht["komponenten"] = aktuell.get("komponenten") or []
        return sicht

    def vorlagen(self) -> list[dict[str, Any]]:
        liste = []
        for pfad in sorted(self._vorlage_pfad("").parent.glob("*.json"), key=lambda p: p.stem):
            roh = _lesen(pfad, None)
            if isinstance(roh, dict) and roh.get("id"):
                liste.append(self._vorlage_sicht(roh, mit_komponenten=False))
        return liste

    def vorlage(self, kennung: str) -> dict[str, Any] | None:
        roh = _lesen(self._vorlage_pfad(kennung), None)
        return self._vorlage_sicht(roh) if isinstance(roh, dict) and roh.get("id") else None

    def vorlage_anlegen(
        self,
        name: str,
        zweck: str,
        komponenten: list[dict[str, Any]],
        datenschema: Any,
        datenquelle: dict[str, Any],
        aktionen: dict[str, str] | None = None,
        stil: str | None = None,
        signatur: dict[str, Any] | None = None,
        modell: str | None = None,
    ) -> dict[str, Any]:
        kennung = self._eindeutig("vorlagen", kennung_aus(name))
        roh = {
            "id": kennung,
            "name": name.strip() or kennung,
            "zweck": zweck,
            "protokollVersion": PROTOKOLL_VERSION,
            "katalogId": KATALOG_ID,
            "stil": stil,
            "signatur": signatur or {},
            "aktionen": dict(aktionen or {}),
            "erstellt": _jetzt(),
            "versionen": [
                {"version": 1, "komponenten": komponenten, "datenschema": datenschema, "datenquelle": datenquelle, "geaendert": _jetzt(), "modell": modell}
            ],
        }
        _schreiben(self._vorlage_pfad(kennung), roh)
        return self._vorlage_sicht(roh)

    def _vorlage_roh(self, kennung: str) -> dict[str, Any]:
        roh = _lesen(self._vorlage_pfad(kennung), None)
        if not isinstance(roh, dict) or not roh.get("id"):
            raise KeyError(kennung)
        return roh

    def vorlage_neue_version(
        self,
        kennung: str,
        komponenten: list[dict[str, Any]] | None = None,
        datenschema: Any = None,
        datenquelle: dict[str, Any] | None = None,
        modell: str | None = None,
        signatur: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        roh = self._vorlage_roh(kennung)
        if signatur:
            roh["signatur"] = dict(signatur)  # die Wiedererkennung folgt der aktuellen Datenquelle
        versionen = roh.setdefault("versionen", [])
        letzte = versionen[-1] if versionen else {}
        neu = {
            "version": int(letzte.get("version", 0)) + 1,
            "komponenten": komponenten if komponenten is not None else letzte.get("komponenten", []),
            "datenschema": datenschema if datenschema is not None else letzte.get("datenschema"),
            "datenquelle": datenquelle if datenquelle is not None else letzte.get("datenquelle", {}),
            "geaendert": _jetzt(),
            "modell": modell,
        }
        versionen.append(neu)
        del versionen[:-MAX_VERSIONEN]
        _schreiben(self._vorlage_pfad(kennung), roh)
        return self._vorlage_sicht(roh)

    def vorlage_zurueck(self, kennung: str) -> dict[str, Any]:
        """Verwirft die neueste Version (Rückgängig); bei nur einer Version passiert nichts."""
        roh = self._vorlage_roh(kennung)
        if len(roh.get("versionen") or []) > 1:
            roh["versionen"].pop()
            _schreiben(self._vorlage_pfad(kennung), roh)
        return self._vorlage_sicht(roh)

    def vorlage_aendern(self, kennung: str, name: str | None = None, stil: str | None = None) -> dict[str, Any]:
        roh = self._vorlage_roh(kennung)
        if name is not None and name.strip():
            roh["name"] = name.strip()
        if stil is not None:
            roh["stil"] = stil or None
        _schreiben(self._vorlage_pfad(kennung), roh)
        return self._vorlage_sicht(roh)

    def aktion_setzen(self, kennung: str, aktion: str, rezept_id: str | None) -> dict[str, Any]:
        roh = self._vorlage_roh(kennung)
        aktionen = roh.setdefault("aktionen", {})
        if rezept_id:
            aktionen[aktion] = rezept_id
        else:
            aktionen.pop(aktion, None)
        _schreiben(self._vorlage_pfad(kennung), roh)
        return self._vorlage_sicht(roh)

    def vorlage_loeschen(self, kennung: str) -> bool:
        pfad = self._vorlage_pfad(kennung)
        if not pfad.exists():
            return False
        pfad.unlink()
        return True

    def vorlagen_fuer_signatur(self, werkzeug: str, schluessel: list[str], eintrag: list[str] | None = None) -> list[dict[str, Any]]:
        """Vollständige Vorlagen mit gleichem Werkzeug und gleichen Ergebnisschlüsseln; passender Listeneintrag zuerst."""
        gesucht = sorted(schluessel)
        treffer = [v for v in self.vorlagen() if (v.get("signatur") or {}).get("werkzeug") == werkzeug and sorted((v.get("signatur") or {}).get("schluessel") or []) == gesucht]
        if eintrag is not None:
            treffer.sort(key=lambda v: sorted((v.get("signatur") or {}).get("eintrag") or []) != sorted(eintrag))
        return [v for v in (self.vorlage(t["id"]) for t in treffer) if v is not None]

    def vorlage_fuer_signatur(self, werkzeug: str, schluessel: list[str], eintrag: list[str] | None = None) -> dict[str, Any] | None:
        """Erste passende Vorlage (siehe ``vorlagen_fuer_signatur``) oder None."""
        kandidaten = self.vorlagen_fuer_signatur(werkzeug, schluessel, eintrag)
        return kandidaten[0] if kandidaten else None

    # ------------------------------------------------------------------ Rezepte
    def rezepte(self) -> list[dict[str, Any]]:
        liste = [_lesen(p, None) for p in sorted((self.ordner / "rezepte").glob("*.json"), key=lambda p: p.stem)]
        return [r for r in liste if isinstance(r, dict) and r.get("id")]

    def rezept(self, kennung: str) -> dict[str, Any] | None:
        r = _lesen(self.ordner / "rezepte" / f"{kennung}.json", None)
        return r if isinstance(r, dict) and r.get("id") else None

    def rezept_anlegen(self, name: str, art: str, vorlage: str, risiko: str = "aendern", **felder: Any) -> dict[str, Any]:
        kennung = self._eindeutig("rezepte", kennung_aus(name, "rezept"))
        rezept = {"id": kennung, "name": name.strip() or kennung, "art": art, "vorlage": vorlage, "risiko": risiko, "erstellt": _jetzt()}
        rezept.update({k: v for k, v in felder.items() if v is not None})
        _schreiben(self.ordner / "rezepte" / f"{kennung}.json", rezept)
        return rezept

    def rezept_aendern(self, kennung: str, **felder: Any) -> dict[str, Any] | None:
        r = self.rezept(kennung)
        if r is None:
            return None
        r.update({k: v for k, v in felder.items() if v is not None})
        _schreiben(self.ordner / "rezepte" / f"{kennung}.json", r)
        return r

    def rezept_loeschen(self, kennung: str) -> bool:
        pfad = self.ordner / "rezepte" / f"{kennung}.json"
        if not pfad.exists():
            return False
        pfad.unlink()
        return True

    # ------------------------------------------------------------------ Stile
    def _vordefinierte(self) -> dict[str, dict[str, Any]]:
        stile: dict[str, dict[str, Any]] = {}
        for pfad in sorted(STILE_PAKET.glob("*.json")):
            s = _lesen(pfad, None)
            if isinstance(s, dict) and s.get("id"):
                s["eigen"] = False
                stile[s["id"]] = s
        return stile

    def _eigene(self) -> dict[str, dict[str, Any]]:
        stile: dict[str, dict[str, Any]] = {}
        for pfad in sorted((self.ordner / "stile").glob("*.json")):
            s = _lesen(pfad, None)
            if isinstance(s, dict) and s.get("id"):
                s["eigen"] = True
                stile[s["id"]] = s
        return stile

    def stile(self) -> list[dict[str, Any]]:
        alle = self._vordefinierte()
        alle.update(self._eigene())
        return list(alle.values())

    def stil(self, kennung: str) -> dict[str, Any] | None:
        eigene = self._eigene()
        if kennung in eigene:
            return eigene[kennung]
        return self._vordefinierte().get(kennung)

    def stil_speichern(self, stil: dict[str, Any]) -> dict[str, Any]:
        """Speichert einen eigenen Stil; ein vordefinierter wird als Kopie mit neuer Kennung abgelegt."""
        daten = dict(stil)
        kennung = str(daten.get("id") or kennung_aus(daten.get("name", ""), "stil"))
        if kennung in self._vordefinierte():
            kennung = self._eindeutig("stile", kennung_aus(daten.get("name") or f"{kennung} eigen", "stil"))
            if kennung in self._vordefinierte():
                kennung = self._eindeutig("stile", f"{kennung}-eigen")
        daten["id"] = kennung
        daten["eigen"] = True
        daten.setdefault("name", kennung)
        daten.setdefault("quelle", {"art": "werte"})
        daten["geaendert"] = _jetzt()
        _schreiben(self.ordner / "stile" / f"{kennung}.json", daten)
        return daten

    def stil_loeschen(self, kennung: str) -> bool:
        pfad = self.ordner / "stile" / f"{kennung}.json"
        if not pfad.exists():
            return False
        pfad.unlink()
        return True

    # ------------------------------------------------------------------ Zuordnung und Flächen
    def zuordnung(self) -> dict[str, str]:
        daten = _lesen(self.ordner / "zuordnung.json", {})
        return {str(k): str(v) for k, v in daten.items()} if isinstance(daten, dict) else {}

    def zuordnung_setzen(self, zuordnung: dict[str, str]) -> dict[str, str]:
        sauber = {str(k): str(v) for k, v in (zuordnung or {}).items() if v}
        _schreiben(self.ordner / "zuordnung.json", sauber)
        return sauber

    # ------------------------------------------------------------------ Verlauf (Schnellaktionen, Varianten)
    MAX_VERLAUF = 50

    def verlauf(self) -> list[dict[str, Any]]:
        daten = _lesen(self.ordner / "verlauf.json", [])
        return [e for e in daten if isinstance(e, dict) and e.get("vorlage")] if isinstance(daten, list) else []

    def verlauf_merken(self, vorlage: str, titel: str, werkzeug: str, argumente: dict[str, Any] | None) -> dict[str, Any]:
        """Anzeige merken: gleiche Vorlage + gleiche Argumente = ein Eintrag (Zähler hoch, Titel aktualisiert)."""
        argumente = dict(argumente or {})
        schluessel = json.dumps(argumente, sort_keys=True, ensure_ascii=False)
        eintraege = self.verlauf()
        for e in eintraege:
            if e.get("vorlage") == vorlage and json.dumps(e.get("argumente") or {}, sort_keys=True, ensure_ascii=False) == schluessel:
                e.update({"titel": titel or e.get("titel") or vorlage, "werkzeug": werkzeug, "app": app_von(werkzeug), "zaehler": int(e.get("zaehler") or 0) + 1, "zuletzt": _jetzt()})
                treffer = e
                break
        else:
            treffer = {
                "id": f"{vorlage}-{hashlib.sha1(schluessel.encode('utf-8')).hexdigest()[:8]}",
                "titel": titel or vorlage,
                "vorlage": vorlage,
                "werkzeug": werkzeug,
                "app": app_von(werkzeug),
                "argumente": argumente,
                "zaehler": 1,
                "zuletzt": _jetzt(),
            }
            eintraege.append(treffer)
        # der gerade genutzte Eintrag steht vorn, auch bei gleicher Sekunde
        eintraege = [treffer] + [e for e in eintraege if e is not treffer]
        eintraege.sort(key=lambda e: str(e.get("zuletzt") or ""), reverse=True)
        _schreiben(self.ordner / "verlauf.json", eintraege[: self.MAX_VERLAUF])
        return treffer

    def verlauf_vergessen(self, vorlage: str) -> None:
        rest = [e for e in self.verlauf() if e.get("vorlage") != vorlage]
        _schreiben(self.ordner / "verlauf.json", rest)

    def schnellaktionen(self, limit: int = 8) -> list[dict[str, Any]]:
        """Häufigste und zuletzt genutzte Anzeigen: Rang aus Zähler und Aktualität (jüngere Einträge zuerst bei Gleichstand)."""
        eintraege = sorted(self.verlauf(), key=lambda e: str(e.get("zuletzt") or ""), reverse=True)
        bewertet = [(int(e.get("zaehler") or 0) + max(0, len(eintraege) - i) / max(1, len(eintraege)), e) for i, e in enumerate(eintraege)]
        bewertet.sort(key=lambda p: p[0], reverse=True)
        return [e for _, e in bewertet[:limit]]

    def varianten(self, vorlage: str, limit: int = 8) -> list[dict[str, Any]]:
        """Zuletzt gezeigte Argumentsätze einer Vorlage (z. B. Wetter Stuttgart / Frankfurt), jüngste zuerst."""
        return [e for e in self.verlauf() if e.get("vorlage") == vorlage][:limit]

    def app_varianten(self, vorlage: str, limit: int = 10) -> list[dict[str, Any]]:
        """Anzeigen derselben App wie die Vorlage (gleiche Vorlage zuerst, dann die übrigen Sichten der App, jüngste
        zuerst) – die Leiste einer Wetter-Fläche zeigt nur Wetter, die einer GG-Fläche nur GG."""
        v = self.vorlage(vorlage)
        app = app_von(((v or {}).get("datenquelle") or {}).get("werkzeug")) if v else None
        eigene = self.varianten(vorlage, limit)
        if not app:
            return eigene
        gesehen = {e["id"] for e in eigene}
        andere = [e for e in self.verlauf() if e.get("app") == app and e["id"] not in gesehen]
        return (eigene + andere)[:limit]

    def flaechen_laden(self) -> list[dict[str, Any]]:
        daten = _lesen(self.ordner / "flaechen.json", [])
        return [f for f in daten if isinstance(f, dict) and f.get("surfaceId")] if isinstance(daten, list) else []

    def flaechen_speichern(self, flaechen: list[dict[str, Any]]) -> None:
        _schreiben(self.ordner / "flaechen.json", list(flaechen))
