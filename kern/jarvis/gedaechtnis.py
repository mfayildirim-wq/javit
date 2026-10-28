"""Gedächtnis: SQLite (~/.jarvis/jarvis.db) mit Unterhaltungen, Verlauf und Erinnerungen.

* Der Verlauf ist in **Unterhaltungen** gegliedert; es gibt immer eine aktuelle (Tabelle ``meta``).
* **Erinnerungen** werden mit Einbettungen gespeichert (Modellname je Zeile) und hybrid gesucht:
  Kosinus-Ähnlichkeit (nur bei gleichem Einbettungsmodell) und Volltext (SQLite FTS5, Fallback
  Stichwortmaß). Fehlt FTS5 im SQLite-Build, bleibt das Stichwortmaß allein.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .konfig import jarvis_home

log = logging.getLogger("jarvis.gedaechtnis")

#: Einbetter: ``await einbetten([texte]) -> Vektoren | None``; optionales Attribut ``modell`` (Name)
Einbetter = Callable[[list[str]], Awaitable[list[list[float]] | None]]

STANDARD_TITEL = "Neue Unterhaltung"
MIGRATIONS_TITEL = "Bisheriger Verlauf"
TITEL_MAX = 80

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


def _jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def einbetter_modell(einbetten: Einbetter | None) -> str:
    """Name des Einbettungsmodells eines Einbetters (Attribut ``modell``), sonst „unbekannt“."""
    return str(getattr(einbetten, "modell", None) or "unbekannt")


def titel_pruefen(titel: str) -> str:
    """Bereinigt einen Unterhaltungstitel; leer oder zu lang → ValueError."""
    sauber = " ".join(str(titel or "").split())
    if not sauber or len(sauber) > TITEL_MAX:
        raise ValueError(f"Titel muss 1 bis {TITEL_MAX} Zeichen haben.")
    return sauber


class Gedaechtnis:
    def __init__(self, pfad: Path | None = None, einbetten: Einbetter | None = None):
        self.pfad = pfad or (jarvis_home() / "jarvis.db")
        self._einbetten = einbetten
        self._sperre = threading.Lock()
        self._db = sqlite3.connect(self.pfad, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._fts = False
        self._schema()

    # ------------------------------------------------------------------ Schema
    def _spalten(self, tabelle: str) -> set[str]:
        return {z["name"] for z in self._db.execute(f"PRAGMA table_info({tabelle})").fetchall()}

    def _schema(self) -> None:
        with self._sperre:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS verlauf (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zeit TEXT NOT NULL,
                    rolle TEXT NOT NULL,
                    inhalt TEXT NOT NULL,
                    unterhaltung_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS erinnerungen (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zeit TEXT NOT NULL,
                    text TEXT NOT NULL,
                    einbettung TEXT,
                    einbettung_modell TEXT,
                    quelle TEXT NOT NULL DEFAULT 'nutzer',
                    unterhaltung_id INTEGER,
                    aktualisiert TEXT
                );
                CREATE TABLE IF NOT EXISTS unterhaltungen (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    titel TEXT NOT NULL,
                    titel_fest INTEGER NOT NULL DEFAULT 0,
                    erstellt TEXT NOT NULL,
                    aktualisiert TEXT NOT NULL,
                    zusammenfassung TEXT,
                    nachbereitet TEXT
                );
                CREATE TABLE IF NOT EXISTS meta (
                    schluessel TEXT PRIMARY KEY,
                    wert TEXT
                );
                """
            )
            # Ältere Datenbanken: fehlende Spalten ergänzen
            if "unterhaltung_id" not in self._spalten("verlauf"):
                self._db.execute("ALTER TABLE verlauf ADD COLUMN unterhaltung_id INTEGER")
            vorhanden = self._spalten("erinnerungen")
            for spalte, definition in (
                ("einbettung_modell", "TEXT"),
                ("quelle", "TEXT NOT NULL DEFAULT 'nutzer'"),
                ("unterhaltung_id", "INTEGER"),
                ("aktualisiert", "TEXT"),
            ):
                if spalte not in vorhanden:
                    self._db.execute(f"ALTER TABLE erinnerungen ADD COLUMN {spalte} {definition}")
            self._db.execute("CREATE INDEX IF NOT EXISTS verlauf_unterhaltung ON verlauf(unterhaltung_id, id)")
            # Verlauf ohne Unterhaltung → „Bisheriger Verlauf“
            ohne = self._db.execute("SELECT COUNT(*) FROM verlauf WHERE unterhaltung_id IS NULL").fetchone()[0]
            if ohne:
                zeiten = self._db.execute(
                    "SELECT MIN(zeit), MAX(zeit) FROM verlauf WHERE unterhaltung_id IS NULL"
                ).fetchone()
                cur = self._db.execute(
                    "INSERT INTO unterhaltungen (titel, titel_fest, erstellt, aktualisiert) VALUES (?, 1, ?, ?)",
                    (MIGRATIONS_TITEL, zeiten[0] or _jetzt(), zeiten[1] or _jetzt()),
                )
                self._db.execute(
                    "UPDATE verlauf SET unterhaltung_id = ? WHERE unterhaltung_id IS NULL", (cur.lastrowid,)
                )
                self._meta_setzen("aktuelle_unterhaltung", str(cur.lastrowid))
            self._fts_einrichten()
            self._db.commit()
        self._aktuelle_sicherstellen()

    def _fts_einrichten(self) -> None:
        try:
            self._db.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS erinnerungen_fts USING fts5(
                    text, content='erinnerungen', content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                );
                CREATE TRIGGER IF NOT EXISTS erinnerungen_ai AFTER INSERT ON erinnerungen BEGIN
                    INSERT INTO erinnerungen_fts(rowid, text) VALUES (new.id, new.text);
                END;
                CREATE TRIGGER IF NOT EXISTS erinnerungen_ad AFTER DELETE ON erinnerungen BEGIN
                    INSERT INTO erinnerungen_fts(erinnerungen_fts, rowid, text) VALUES ('delete', old.id, old.text);
                END;
                CREATE TRIGGER IF NOT EXISTS erinnerungen_au AFTER UPDATE OF text ON erinnerungen BEGIN
                    INSERT INTO erinnerungen_fts(erinnerungen_fts, rowid, text) VALUES ('delete', old.id, old.text);
                    INSERT INTO erinnerungen_fts(rowid, text) VALUES (new.id, new.text);
                END;
                """
            )
            if self._meta("fts_aufgebaut") != "1":
                self._db.execute("INSERT INTO erinnerungen_fts(erinnerungen_fts) VALUES ('rebuild')")
                self._meta_setzen("fts_aufgebaut", "1")
            self._fts = True
        except sqlite3.OperationalError as e:  # SQLite ohne FTS5
            log.info("Volltextsuche nicht verfügbar (%s) – Stichwortsuche", e)
            self._fts = False

    def _meta(self, schluessel: str) -> str | None:
        zeile = self._db.execute("SELECT wert FROM meta WHERE schluessel = ?", (schluessel,)).fetchone()
        return zeile["wert"] if zeile else None

    def _meta_setzen(self, schluessel: str, wert: str) -> None:
        self._db.execute(
            "INSERT INTO meta (schluessel, wert) VALUES (?, ?) "
            "ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
            (schluessel, wert),
        )

    def schliessen(self) -> None:
        with self._sperre:
            self._db.close()

    # ------------------------------------------------------------------ Unterhaltungen
    def _aktuelle_id(self) -> int:
        """Kennung der aktuellen Unterhaltung (ohne Sperre; legt bei Bedarf eine an)."""
        wert = self._meta("aktuelle_unterhaltung")
        if wert and self._db.execute("SELECT 1 FROM unterhaltungen WHERE id = ?", (int(wert),)).fetchone():
            return int(wert)
        neueste = self._db.execute(
            "SELECT id FROM unterhaltungen ORDER BY aktualisiert DESC, id DESC LIMIT 1"
        ).fetchone()
        kennung = int(neueste["id"]) if neueste else self._anlegen(STANDARD_TITEL)
        self._meta_setzen("aktuelle_unterhaltung", str(kennung))
        self._db.commit()
        return kennung

    def _aktuelle_sicherstellen(self) -> None:
        with self._sperre:
            self._aktuelle_id()

    def _anlegen(self, titel: str) -> int:
        jetzt = _jetzt()
        cur = self._db.execute(
            "INSERT INTO unterhaltungen (titel, titel_fest, erstellt, aktualisiert) VALUES (?, 0, ?, ?)",
            (titel, jetzt, jetzt),
        )
        return int(cur.lastrowid or 0)

    def _unterhaltung_zeile(self, kennung: int) -> dict[str, Any] | None:
        zeile = self._db.execute(
            "SELECT u.*, (SELECT COUNT(*) FROM verlauf v WHERE v.unterhaltung_id = u.id) AS nachrichten "
            "FROM unterhaltungen u WHERE u.id = ?",
            (int(kennung),),
        ).fetchone()
        if not zeile:
            return None
        return self._als_dict(zeile, self._meta("aktuelle_unterhaltung"))

    @staticmethod
    def _als_dict(zeile: sqlite3.Row, aktuelle: str | None) -> dict[str, Any]:
        return {
            "id": int(zeile["id"]),
            "titel": zeile["titel"],
            "titel_fest": bool(zeile["titel_fest"]),
            "erstellt": zeile["erstellt"],
            "aktualisiert": zeile["aktualisiert"],
            "zusammenfassung": zeile["zusammenfassung"],
            "nachbereitet": zeile["nachbereitet"],
            "nachrichten": int(zeile["nachrichten"]),
            "aktuell": str(zeile["id"]) == str(aktuelle),
        }

    def aktuelle(self) -> dict[str, Any]:
        with self._sperre:
            kennung = self._aktuelle_id()
            zeile = self._unterhaltung_zeile(kennung)
        assert zeile is not None
        return zeile

    def unterhaltung(self, kennung: int) -> dict[str, Any] | None:
        with self._sperre:
            return self._unterhaltung_zeile(kennung)

    def unterhaltungen(self) -> list[dict[str, Any]]:
        with self._sperre:
            aktuelle = self._meta("aktuelle_unterhaltung")
            zeilen = self._db.execute(
                "SELECT u.*, (SELECT COUNT(*) FROM verlauf v WHERE v.unterhaltung_id = u.id) AS nachrichten "
                "FROM unterhaltungen u ORDER BY u.aktualisiert DESC, u.id DESC"
            ).fetchall()
        return [self._als_dict(z, aktuelle) for z in zeilen]

    def unterhaltung_neu(self, titel: str | None = None) -> dict[str, Any]:
        """Legt eine Unterhaltung an und macht sie aktuell."""
        sauber = titel_pruefen(titel) if titel and titel.strip() else STANDARD_TITEL
        with self._sperre:
            kennung = self._anlegen(sauber)
            self._meta_setzen("aktuelle_unterhaltung", str(kennung))
            self._db.commit()
            zeile = self._unterhaltung_zeile(kennung)
        assert zeile is not None
        return zeile

    def unterhaltung_aktivieren(self, kennung: int) -> dict[str, Any]:
        with self._sperre:
            if not self._db.execute("SELECT 1 FROM unterhaltungen WHERE id = ?", (int(kennung),)).fetchone():
                raise KeyError(kennung)
            self._meta_setzen("aktuelle_unterhaltung", str(int(kennung)))
            self._db.commit()
            zeile = self._unterhaltung_zeile(kennung)
        assert zeile is not None
        return zeile

    def unterhaltung_umbenennen(self, kennung: int, titel: str, fest: bool = True) -> dict[str, Any]:
        """Setzt den Titel. ``fest=False`` (automatischer Titel) ändert nur, solange der Nutzer nicht
        selbst umbenannt hat."""
        sauber = titel_pruefen(titel)
        with self._sperre:
            if not self._db.execute("SELECT 1 FROM unterhaltungen WHERE id = ?", (int(kennung),)).fetchone():
                raise KeyError(kennung)
            if fest:
                self._db.execute(
                    "UPDATE unterhaltungen SET titel = ?, titel_fest = 1 WHERE id = ?", (sauber, int(kennung))
                )
            else:
                self._db.execute(
                    "UPDATE unterhaltungen SET titel = ? WHERE id = ? AND titel_fest = 0", (sauber, int(kennung))
                )
            self._db.commit()
            zeile = self._unterhaltung_zeile(kennung)
        assert zeile is not None
        return zeile

    def unterhaltung_loeschen(self, kennung: int) -> dict[str, Any]:
        """Löscht Unterhaltung samt Verlauf; Erinnerungen bleiben (ohne Bezug). Liefert die danach aktuelle."""
        with self._sperre:
            if not self._db.execute("SELECT 1 FROM unterhaltungen WHERE id = ?", (int(kennung),)).fetchone():
                raise KeyError(kennung)
            self._db.execute("DELETE FROM verlauf WHERE unterhaltung_id = ?", (int(kennung),))
            self._db.execute(
                "UPDATE erinnerungen SET unterhaltung_id = NULL WHERE unterhaltung_id = ?", (int(kennung),)
            )
            self._db.execute("DELETE FROM unterhaltungen WHERE id = ?", (int(kennung),))
            if self._meta("aktuelle_unterhaltung") == str(int(kennung)):
                self._db.execute("DELETE FROM meta WHERE schluessel = 'aktuelle_unterhaltung'")
            self._db.commit()
            aktuelle = self._unterhaltung_zeile(self._aktuelle_id())
        return {"geloescht": True, "aktuell": aktuelle}

    def zusammenfassung_setzen(self, kennung: int, zusammenfassung: str) -> None:
        with self._sperre:
            self._db.execute(
                "UPDATE unterhaltungen SET zusammenfassung = ? WHERE id = ?",
                (zusammenfassung.strip() or None, int(kennung)),
            )
            self._db.commit()

    def nachbereitet_setzen(self, kennung: int) -> None:
        with self._sperre:
            self._db.execute("UPDATE unterhaltungen SET nachbereitet = ? WHERE id = ?", (_jetzt(), int(kennung)))
            self._db.commit()

    def letzte_zusammenfassungen(self, anzahl: int = 5) -> list[dict[str, Any]]:
        """Jüngste Unterhaltungen mit Zusammenfassung, ohne die aktuelle."""
        with self._sperre:
            aktuelle = self._aktuelle_id()
            zeilen = self._db.execute(
                "SELECT id, titel, aktualisiert, zusammenfassung FROM unterhaltungen "
                "WHERE zusammenfassung IS NOT NULL AND id != ? ORDER BY aktualisiert DESC, id DESC LIMIT ?",
                (aktuelle, int(anzahl)),
            ).fetchall()
        return [dict(z) for z in zeilen]

    def beitraege_seit(self, kennung: int, zeit: str | None) -> int:
        """Anzahl Verlaufsbeiträge einer Unterhaltung nach ``zeit`` (None → alle)."""
        with self._sperre:
            if zeit:
                zeile = self._db.execute(
                    "SELECT COUNT(*) FROM verlauf WHERE unterhaltung_id = ? AND zeit > ?", (int(kennung), zeit)
                ).fetchone()
            else:
                zeile = self._db.execute(
                    "SELECT COUNT(*) FROM verlauf WHERE unterhaltung_id = ?", (int(kennung),)
                ).fetchone()
        return int(zeile[0])

    # ------------------------------------------------------------------ Verlauf
    def verlauf_hinzufuegen(self, rolle: str, inhalt: str, unterhaltung_id: int | None = None) -> None:
        jetzt = _jetzt()
        with self._sperre:
            kennung = int(unterhaltung_id) if unterhaltung_id else self._aktuelle_id()
            self._db.execute(
                "INSERT INTO verlauf (zeit, rolle, inhalt, unterhaltung_id) VALUES (?, ?, ?, ?)",
                (jetzt, rolle, inhalt, kennung),
            )
            self._db.execute("UPDATE unterhaltungen SET aktualisiert = ? WHERE id = ?", (jetzt, kennung))
            self._db.commit()

    def verlauf(self, limit: int = 50, unterhaltung_id: int | None = None) -> list[dict[str, Any]]:
        with self._sperre:
            kennung = int(unterhaltung_id) if unterhaltung_id else self._aktuelle_id()
            zeilen = self._db.execute(
                "SELECT id, zeit, rolle, inhalt FROM verlauf WHERE unterhaltung_id = ? ORDER BY id DESC LIMIT ?",
                (kennung, int(limit)),
            ).fetchall()
        return [dict(z) for z in reversed(zeilen)]

    def verlauf_loeschen(self) -> None:
        """Leert nur die aktuelle Unterhaltung."""
        with self._sperre:
            kennung = self._aktuelle_id()
            self._db.execute("DELETE FROM verlauf WHERE unterhaltung_id = ?", (kennung,))
            self._db.commit()

    # ------------------------------------------------------------------ Erinnerungen
    async def _vektor(self, text: str) -> tuple[str | None, str]:
        """(JSON-Vektor oder None, Modellname) für einen Text."""
        if not self._einbetten:
            return None, einbetter_modell(None)
        try:
            vektoren = await self._einbetten([text])
        except Exception:  # noqa: BLE001
            log.warning("Einbettung fehlgeschlagen", exc_info=True)
            vektoren = None
        vektor = vektoren[0] if vektoren else None
        return (json.dumps(vektor) if vektor else None), einbetter_modell(self._einbetten)

    async def erinnern(self, text: str, quelle: str = "nutzer", unterhaltung_id: int | None = None) -> int:
        text = text.strip()
        vektor, modell = await self._vektor(text)
        with self._sperre:
            cur = self._db.execute(
                "INSERT INTO erinnerungen (zeit, text, einbettung, einbettung_modell, quelle, unterhaltung_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_jetzt(), text, vektor, modell if vektor else None, quelle, unterhaltung_id),
            )
            self._db.commit()
            return int(cur.lastrowid or 0)

    async def erinnerung_aktualisieren(self, kennung: int, text: str) -> None:
        text = text.strip()
        vektor, modell = await self._vektor(text)
        with self._sperre:
            self._db.execute(
                "UPDATE erinnerungen SET text = ?, einbettung = ?, einbettung_modell = ?, aktualisiert = ? WHERE id = ?",
                (text, vektor, modell if vektor else None, _jetzt(), int(kennung)),
            )
            self._db.commit()

    def erinnerungen(self) -> list[dict[str, Any]]:
        with self._sperre:
            zeilen = self._db.execute(
                "SELECT id, zeit, text, quelle, unterhaltung_id, aktualisiert, einbettung_modell "
                "FROM erinnerungen ORDER BY id"
            ).fetchall()
        return [dict(z) for z in zeilen]

    def erinnerung_loeschen(self, erinnerung_id: int | None = None) -> int:
        with self._sperre:
            if erinnerung_id is None:
                cur = self._db.execute("DELETE FROM erinnerungen")
            else:
                cur = self._db.execute("DELETE FROM erinnerungen WHERE id = ?", (int(erinnerung_id),))
            self._db.commit()
            return cur.rowcount

    def fehlende_einbettungen(self, modell: str, limit: int = 200) -> list[int]:
        """Erinnerungen ohne Vektor des angegebenen Modells."""
        with self._sperre:
            zeilen = self._db.execute(
                "SELECT id FROM erinnerungen WHERE einbettung IS NULL OR einbettung_modell IS NOT ? "
                "ORDER BY id DESC LIMIT ?",
                (modell, int(limit)),
            ).fetchall()
        return [int(z["id"]) for z in zeilen]

    async def nachbetten(self, limit: int = 200) -> int:
        """Bettet Erinnerungen ohne Vektor des aktuellen Modells nach; liefert die Anzahl."""
        if not self._einbetten:
            return 0
        modell = einbetter_modell(self._einbetten)
        kennungen = self.fehlende_einbettungen(modell, limit)
        if not kennungen:
            return 0
        with self._sperre:
            zeilen = self._db.execute(
                f"SELECT id, text FROM erinnerungen WHERE id IN ({','.join('?' * len(kennungen))})", kennungen
            ).fetchall()
        try:
            vektoren = await self._einbetten([z["text"] for z in zeilen])
        except Exception:  # noqa: BLE001
            log.warning("Nachbetten fehlgeschlagen", exc_info=True)
            return 0
        if not vektoren or len(vektoren) != len(zeilen):
            return 0
        with self._sperre:
            for zeile, vektor in zip(zeilen, vektoren):
                self._db.execute(
                    "UPDATE erinnerungen SET einbettung = ?, einbettung_modell = ? WHERE id = ?",
                    (json.dumps(vektor), modell, int(zeile["id"])),
                )
            self._db.commit()
        return len(zeilen)

    def _fts_werte(self, anfrage: str) -> dict[int, float]:
        """Volltexttreffer → Wert 0–1 aus dem BM25-Rang (SQLite liefert negative Werte, kleiner = besser)."""
        if not self._fts:
            return {}
        woerter = [w for w in re.findall(r"[\wäöüÄÖÜß]+", anfrage) if len(w) >= 3]
        if not woerter:
            return {}
        match = " OR ".join('"' + w.replace('"', '""') + '"*' for w in woerter)
        try:
            with self._sperre:
                zeilen = self._db.execute(
                    "SELECT rowid, rank FROM erinnerungen_fts WHERE erinnerungen_fts MATCH ? ORDER BY rank LIMIT 50",
                    (match,),
                ).fetchall()
        except sqlite3.OperationalError:
            return {}
        werte: dict[int, float] = {}
        for z in zeilen:
            staerke = abs(float(z["rank"] or 0.0))
            werte[int(z["rowid"])] = 1.0 - 1.0 / (1.0 + staerke)
        return werte

    async def suchen(self, anfrage: str, anzahl: int = 5, mindestwert: float = 0.35) -> list[dict[str, Any]]:
        """Relevante Erinnerungen: Kosinus (gleiches Einbettungsmodell), Volltext und Stichwortmaß – Maximum."""
        with self._sperre:
            zeilen = [dict(z) for z in self._db.execute(
                "SELECT id, zeit, text, quelle, einbettung, einbettung_modell FROM erinnerungen"
            ).fetchall()]
        if not zeilen or not anfrage.strip():
            return []
        modell = einbetter_modell(self._einbetten)
        anfrage_vektor = None
        if self._einbetten and any(z["einbettung"] and z["einbettung_modell"] == modell for z in zeilen):
            try:
                vektoren = await self._einbetten([anfrage])
            except Exception:  # noqa: BLE001
                vektoren = None
            anfrage_vektor = vektoren[0] if vektoren else None
        fts = self._fts_werte(anfrage)
        anfrage_woerter = _woerter(anfrage)
        bewertet = []
        for z in zeilen:
            wert = fts.get(z["id"], 0.0)
            if anfrage_vektor and z["einbettung"] and z["einbettung_modell"] == modell:
                wert = max(wert, _kosinus(anfrage_vektor, json.loads(z["einbettung"])))
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
            {"id": z["id"], "zeit": z["zeit"], "text": z["text"], "quelle": z["quelle"], "relevanz": round(w, 3)}
            for w, z in bewertet[:anzahl]
        ]
