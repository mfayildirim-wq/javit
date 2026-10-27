"""Integrationskatalog: lädt integrationen/katalog/*.yaml (Pfad per Env JARVIS_KATALOG überschreibbar).

Zusätzlich werden eigene Einträge aus ~/.jarvis/katalog/*.yaml geladen.
Platzhalter `${NAME}` in befehl/url/kopfzeilen/rest werden beim Hinzufügen durch Werte ersetzt.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..konfig import jarvis_home

Art = Literal["mcp_stdio", "mcp_http", "openapi", "rest", "eingebaut"]
RisikoStufe = Literal["lesen", "aendern", "kritisch"]


class Benoetigt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    titel: str
    geheim: bool = False
    optional: bool = False
    standard: str | None = None
    beschreibung: str | None = None


class KatalogEintrag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    beschreibung: str
    kategorie: str
    icon: str
    art: Art
    befehl: str | None = None
    url: str | None = None
    kopfzeilen: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, str] | None = None
    rest: list[dict[str, Any]] | None = None
    eingebaut: str | None = None
    benoetigt: list[Benoetigt] = Field(default_factory=list)
    hinweis: str = ""
    webseite: str | None = None
    risiko_standard: RisikoStufe = "aendern"
    werkzeug_risiko: dict[str, RisikoStufe] = Field(default_factory=dict)
    voraussetzungen: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_pruefen(cls, wert: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", wert):
            raise ValueError("id darf nur a-z, 0-9, _ und - enthalten")
        return wert

    @model_validator(mode="after")
    def _art_pruefen(self) -> "KatalogEintrag":
        if self.art == "mcp_stdio" and not self.befehl:
            raise ValueError(f"{self.id}: art mcp_stdio benötigt 'befehl'")
        if self.art in ("mcp_http", "openapi") and not self.url:
            raise ValueError(f"{self.id}: art {self.art} benötigt 'url'")
        if self.art == "rest" and not self.rest:
            raise ValueError(f"{self.id}: art rest benötigt 'rest'")
        if self.art == "eingebaut" and not self.eingebaut:
            raise ValueError(f"{self.id}: art eingebaut benötigt 'eingebaut'")
        return self

    def als_info(self) -> dict[str, Any]:
        """Form gemäß VERTRAEGE.md (GET /api/integrationen/katalog)."""
        return {
            "id": self.id,
            "name": self.name,
            "beschreibung": self.beschreibung,
            "kategorie": self.kategorie,
            "icon": self.icon,
            "art": self.art,
            "benoetigt": [
                {"name": b.name, "titel": b.titel, "geheim": b.geheim, "optional": b.optional}
                for b in self.benoetigt
            ],
            "hinweis": self.hinweis,
        }


def standard_katalog_pfad() -> Path:
    if os.environ.get("JARVIS_KATALOG"):
        return Path(os.environ["JARVIS_KATALOG"]).expanduser()
    # kern/jarvis/integrationen/katalog.py → <projekt>/integrationen/katalog
    return Path(__file__).resolve().parents[3] / "integrationen" / "katalog"


class Katalog:
    def __init__(self, pfade: list[Path] | None = None):
        self.pfade = pfade or [standard_katalog_pfad(), jarvis_home() / "katalog"]
        self.eintraege: dict[str, KatalogEintrag] = {}
        self.fehler: dict[str, str] = {}
        self.laden()

    def laden(self) -> None:
        self.eintraege.clear()
        self.fehler.clear()
        for ordner in self.pfade:
            if not ordner.is_dir():
                continue
            for datei in sorted(ordner.glob("*.y*ml")):
                try:
                    daten = yaml.safe_load(datei.read_text(encoding="utf-8"))
                    eintrag = KatalogEintrag.model_validate(daten)
                    self.eintraege[eintrag.id] = eintrag
                except Exception as e:  # noqa: BLE001
                    self.fehler[str(datei)] = str(e)

    def holen(self, kennung: str) -> KatalogEintrag | None:
        kennung = kennung.strip().lower()
        if kennung in self.eintraege:
            return self.eintraege[kennung]
        for e in self.eintraege.values():
            if e.name.lower() == kennung:
                return e
        return None

    def alle(self) -> list[KatalogEintrag]:
        return sorted(self.eintraege.values(), key=lambda e: (e.kategorie, e.name))

    def suchen(self, begriff: str | None = None) -> list[KatalogEintrag]:
        if not begriff:
            return self.alle()
        b = begriff.lower()
        return [
            e for e in self.alle()
            if b in e.id or b in e.name.lower() or b in e.beschreibung.lower() or b in e.kategorie.lower()
        ]


_PLATZHALTER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def platzhalter_ersetzen(wert: Any, werte: dict[str, str]) -> Any:
    """Ersetzt ${NAME} rekursiv in Strings/Listen/Dicts. Unbekannte Platzhalter bleiben stehen."""
    if isinstance(wert, str):
        return _PLATZHALTER.sub(lambda m: str(werte.get(m.group(1), m.group(0))), wert)
    if isinstance(wert, list):
        return [platzhalter_ersetzen(w, werte) for w in wert]
    if isinstance(wert, dict):
        return {k: platzhalter_ersetzen(v, werte) for k, v in wert.items()}
    return wert


def platzhalter_finden(wert: Any) -> set[str]:
    if isinstance(wert, str):
        return set(_PLATZHALTER.findall(wert))
    if isinstance(wert, list):
        return set().union(*(platzhalter_finden(w) for w in wert)) if wert else set()
    if isinstance(wert, dict):
        return set().union(*(platzhalter_finden(v) for v in wert.values())) if wert else set()
    return set()
