"""Dauerhafter Speicher der Bühne unter ``~/.jarvis/buehne/``: Vorlagen (mit bis zu 10 Versionen), Rezepte,
Stile (vordefinierte aus dem Paket + eigene), Zuordnung Integration → Stil und die zuletzt offenen Flächen.
Alles gilt global, nicht je Unterhaltung."""

from __future__ import annotations

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
    ) -> dict[str, Any]:
        roh = self._vorlage_roh(kennung)
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

    def vorlage_fuer_signatur(self, werkzeug: str, schluessel: list[str]) -> dict[str, Any] | None:
        gesucht = sorted(schluessel)
        for v in self.vorlagen():
            sig = v.get("signatur") or {}
            if sig.get("werkzeug") == werkzeug and sorted(sig.get("schluessel") or []) == gesucht:
                return self.vorlage(v["id"])
        return None

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

    def flaechen_laden(self) -> list[dict[str, Any]]:
        daten = _lesen(self.ordner / "flaechen.json", [])
        return [f for f in daten if isinstance(f, dict) and f.get("surfaceId")] if isinstance(daten, list) else []

    def flaechen_speichern(self, flaechen: list[dict[str, Any]]) -> None:
        _schreiben(self.ordner / "flaechen.json", list(flaechen))
