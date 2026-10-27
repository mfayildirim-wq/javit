"""Gedächtnis: SQLite (~/.jarvis/jarvis.db) mit Verlauf und Erinnerungen.

Erinnerungen werden – wenn ein Einbettungsmodell verfügbar ist – mit Embeddings gespeichert
und per Kosinus-Ähnlichkeit gesucht; sonst Schlüsselwortsuche.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .konfig import jarvis_home

Einbetter = Callable[[list[str]], Awaitable[list[list[float]] | None]]

_STOPPWOERTER = {
    "der", "die", "das", "und", "oder", "ein", "eine", "einen", "einem", "ist", "sind", "war",
    "mit", "von", "für", "fuer", "auf", "aus", "bei", "den", "dem", "des", "ich", "du", "mein",
    "meine", "mir", "mich", "wie", "was", "wer", "wo", "wann", "nicht", "auch", "noch", "zu",
    "im", "in", "an", "am", "es", "sie", "er", "wir", "ihr", "hat", "habe", "the", "and", "is",
}


def _woerter(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-zA-Z0-9äöüÄÖÜß]+", text.lower())
        if len(w) >= 3 and w not in _STOPPWOERTER
    }


def _kosinus(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    skalar = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return skalar / (na * nb) if na and nb else 0.0


class Gedaechtnis:
    def __init__(self, pfad: Path | None = None, einbetten: Einbetter | None = None):
        self.pfad = pfad or (jarvis_home() / "jarvis.db")
        self._einbetten = einbetten
        self._sperre = threading.Lock()
        self._db = sqlite3.connect(self.pfad, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS verlauf (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zeit TEXT NOT NULL,
                rolle TEXT NOT NULL,
                inhalt TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS erinnerungen (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zeit TEXT NOT NULL,
                text TEXT NOT NULL,
                einbettung TEXT
            );
            """
        )
        self._db.commit()

    def schliessen(self) -> None:
        with self._sperre:
            self._db.close()

    # ---------- Verlauf ----------
    def verlauf_hinzufuegen(self, rolle: str, inhalt: str) -> None:
        with self._sperre:
            self._db.execute(
                "INSERT INTO verlauf (zeit, rolle, inhalt) VALUES (?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), rolle, inhalt),
            )
            self._db.commit()

    def verlauf(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._sperre:
            zeilen = self._db.execute(
                "SELECT id, zeit, rolle, inhalt FROM verlauf ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(z) for z in reversed(zeilen)]

    def verlauf_loeschen(self) -> None:
        with self._sperre:
            self._db.execute("DELETE FROM verlauf")
            self._db.commit()

    # ---------- Erinnerungen ----------
    async def erinnern(self, text: str) -> int:
        text = text.strip()
        vektor = None
        if self._einbetten:
            vektoren = await self._einbetten([text])
            vektor = vektoren[0] if vektoren else None
        with self._sperre:
            cur = self._db.execute(
                "INSERT INTO erinnerungen (zeit, text, einbettung) VALUES (?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), text, json.dumps(vektor) if vektor else None),
            )
            self._db.commit()
            return int(cur.lastrowid or 0)

    def erinnerungen(self) -> list[dict[str, Any]]:
        with self._sperre:
            zeilen = self._db.execute("SELECT id, zeit, text FROM erinnerungen ORDER BY id").fetchall()
        return [dict(z) for z in zeilen]

    def erinnerung_loeschen(self, erinnerung_id: int | None = None) -> int:
        with self._sperre:
            if erinnerung_id is None:
                cur = self._db.execute("DELETE FROM erinnerungen")
            else:
                cur = self._db.execute("DELETE FROM erinnerungen WHERE id = ?", (int(erinnerung_id),))
            self._db.commit()
            return cur.rowcount

    async def suchen(self, anfrage: str, anzahl: int = 5, mindestwert: float = 0.35) -> list[dict[str, Any]]:
        """Relevante Erinnerungen: Embedding-Ähnlichkeit, sonst/zusätzlich Schlüsselwörter."""
        with self._sperre:
            zeilen = [dict(z) for z in self._db.execute(
                "SELECT id, zeit, text, einbettung FROM erinnerungen"
            ).fetchall()]
        if not zeilen or not anfrage.strip():
            return []
        anfrage_vektor = None
        if self._einbetten and any(z["einbettung"] for z in zeilen):
            vektoren = await self._einbetten([anfrage])
            anfrage_vektor = vektoren[0] if vektoren else None
        anfrage_woerter = _woerter(anfrage)
        bewertet = []
        for z in zeilen:
            wert = 0.0
            if anfrage_vektor and z["einbettung"]:
                wert = _kosinus(anfrage_vektor, json.loads(z["einbettung"]))
            woerter = _woerter(z["text"])
            if anfrage_woerter and woerter:
                treffer = len(anfrage_woerter & woerter)
                # Präfixtreffer (z. B. „Kaffee“ ↔ „Kaffeesorte“)
                treffer += 0.5 * sum(
                    1 for a in anfrage_woerter for w in woerter
                    if a != w and (a.startswith(w) or w.startswith(a)) and min(len(a), len(w)) >= 4
                )
                wert = max(wert, min(1.0, treffer / max(1, len(anfrage_woerter)) + 0.3 * (treffer > 0)))
            if wert >= mindestwert:
                bewertet.append((wert, z))
        bewertet.sort(key=lambda t: t[0], reverse=True)
        return [
            {"id": z["id"], "zeit": z["zeit"], "text": z["text"], "relevanz": round(w, 3)}
            for w, z in bewertet[:anzahl]
        ]
