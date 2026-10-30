"""Manager der Bühne: Flächen anzeigen, befüllen, ändern, schließen; Aktionen zu Rezepten; Stile zuweisen.

Spricht A2UI über das Ereignis ``{"typ": "buehne", "nachricht": {…}}`` zur Oberfläche und nimmt
``buehne_aktion``/``buehne_daten`` entgegen. Werkzeuge laufen über den Rückruf ``werkzeug_ausfuehren`` des
Agenten (mit Freigaberegeln); Aufträge an den Assistenten über ``anfrage``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from .daten import abbildung_anwenden, abbildung_greift, ergebnis_parsen, ist_fehlertext, ist_nur_text, json_pointer_holen, json_pointer_setzen, signatur
from .erzeuger import STILFARBEN, Erzeuger, _hex_norm
from .speicher import KATALOG_ID, PROTOKOLL_VERSION, BuehnenSpeicher, kennung_aus
from .werkzeugflaechen import Werkzeugflaechen, WerkzeugflaechenFehler

log = logging.getLogger("jarvis.buehne")

Senden = Callable[[dict[str, Any]], Awaitable[None]]
WerkzeugAusfuehren = Callable[[str, dict[str, Any]], Awaitable[str]]
Anfrage = Callable[[str], Awaitable[str]]
STANDARD_STIL = "javit-dunkel"
_PLATZHALTER = re.compile(r"\{([a-zA-Z0-9_./]+)\}")


_FUELLWOERTER = {"liste", "uebersicht", "alle", "aktuelle", "aktuell", "meine", "neue", "anzeige", "tabelle", "kacheln", "ansicht", "sicht", "ergebnis", "daten"}


def titel_passt(titel: str, name: str) -> bool:
    """Gleiche Sicht? Kennungen gleich, oder ein tragendes Wort (≥ 4 Zeichen, kein Füllwort) kommt in beiden vor –
    auch als Wortanfang („Immobilien“ ↔ „Immobilienliste“, „Aktuelle Immobilien-Deals“); „Makler“ ↔ „Immobilien“ nicht."""
    a, b = kennung_aus(titel, ""), kennung_aus(name, "")
    if not a or not b:
        return False
    if a == b:
        return True
    woerter_a = [w for w in a.split("-") if len(w) >= 4 and w not in _FUELLWOERTER]
    woerter_b = [w for w in b.split("-") if len(w) >= 4 and w not in _FUELLWOERTER]
    return any(x == y or x.startswith(y) or y.startswith(x) for x in woerter_a for y in woerter_b)


def _datenquelle(werkzeug: str, argumente: dict[str, Any], abbildung: Any) -> dict[str, Any]:
    """Einheitliche Datenquelle einer Vorlagenversion: Werkzeug, Argumente, Abbildung (immer alle drei, immer aktuell)."""
    return {"werkzeug": werkzeug, "argumente": dict(argumente or {}), "abbildung": dict(abbildung) if isinstance(abbildung, dict) else {}}


class BuehnenFehler(RuntimeError):
    pass


class BuehnenManager:
    def __init__(
        self,
        speicher: BuehnenSpeicher,
        erzeuger: Erzeuger,
        senden: Senden,
        werkzeug_ausfuehren: WerkzeugAusfuehren,
        anfrage: Anfrage | None = None,
        aktiv: Callable[[], bool] | None = None,
    ):
        self.speicher = speicher
        self.erzeuger = erzeuger
        self._senden = senden
        self._werkzeug = werkzeug_ausfuehren
        #: Werkzeugflächen (Browser, Shell …) – von der Anwendung gesetzt
        self.werkzeugflaechen: Werkzeugflaechen | None = None
        self._anfrage = anfrage
        self._aktiv = aktiv or (lambda: True)
        self.flaechen: dict[str, dict[str, Any]] = {}
        self._roh: dict[str, Any] = {}  # letztes Werkzeugergebnis je Fläche (für Umbauten ohne neuen Aufruf)
        self._gesendete_stile: set[str] = set()

    # ------------------------------------------------------------------ Zustand
    def laden(self) -> None:
        for f in self.speicher.flaechen_laden():
            if f.get("art") == "werkzeug":
                continue  # Werkzeugflächen (Browser, Shell …) überleben keinen Neustart
            self.flaechen[f["surfaceId"]] = f

    def _speichern(self) -> None:
        self.speicher.flaechen_speichern(list(self.flaechen.values()))

    def zustand(self) -> dict[str, Any]:
        return {"flaechen": list(self.flaechen.values()), "stile": self.speicher.stile(), "zuordnung": self.speicher.zuordnung(), **self.aktionen_stand()}

    def aktionen_stand(self) -> dict[str, Any]:
        """Schnellaktionen (global) und Varianten je offener Vorlage – für GET /api/buehne und die Nachricht `aktionen`."""
        vorlagen = {f.get("vorlage") for f in self.flaechen.values() if f.get("vorlage")}
        return {"schnellaktionen": self.speicher.schnellaktionen(), "varianten": {v: self.speicher.app_varianten(v) for v in sorted(vorlagen)}}

    async def _aktionen_melden(self) -> None:
        await self._nachricht({"aktionen": {"schnell": self.speicher.schnellaktionen(), "varianten": self.aktionen_stand()["varianten"]}})

    async def _nachricht(self, inhalt: dict[str, Any]) -> None:
        await self._senden({"typ": "buehne", "nachricht": {"version": PROTOKOLL_VERSION, **inhalt}})

    def stil_fuer(self, vorlage: dict[str, Any] | None, integration: str | None, werkzeug: str | None = None) -> str:
        if vorlage and vorlage.get("stil") and self.speicher.stil(vorlage["stil"]):
            return str(vorlage["stil"])
        zuordnung = self.speicher.zuordnung()
        kandidat = integration or (werkzeug.split("__")[0] if werkzeug and "__" in werkzeug else None)
        if kandidat and zuordnung.get(kandidat) and self.speicher.stil(zuordnung[kandidat]):
            return zuordnung[kandidat]
        return STANDARD_STIL

    async def _stil_senden(self, stil_id: str) -> None:
        stil = self.speicher.stil(stil_id) or self.speicher.stil(STANDARD_STIL)
        if stil:
            await self._nachricht({"stil": stil})
            self._gesendete_stile.add(stil_id)

    async def _flaeche_senden(
        self,
        surface_id: str,
        titel: str,
        stil_id: str,
        komponenten: list[dict[str, Any]],
        daten: Any,
        vorlage_id: str | None,
        art: str = "daten",
        symbol: str | None = None,
    ) -> dict[str, Any]:
        await self._stil_senden(stil_id)
        erzeugen: dict[str, Any] = {"surfaceId": surface_id, "catalogId": KATALOG_ID, "theme": {"stil": stil_id}, "titel": titel, "vorlage": vorlage_id, "art": art}
        if symbol:
            erzeugen["symbol"] = symbol
        await self._nachricht({"createSurface": erzeugen})
        await self._nachricht({"updateComponents": {"surfaceId": surface_id, "components": komponenten}})
        await self._nachricht({"updateDataModel": {"surfaceId": surface_id, "path": "/", "value": daten}})
        flaeche = {"surfaceId": surface_id, "titel": titel, "catalogId": KATALOG_ID, "stil": stil_id, "components": komponenten, "daten": daten, "vorlage": vorlage_id, "art": art, "symbol": symbol}
        self.flaechen[surface_id] = flaeche
        self._speichern()
        return flaeche

    # ------------------------------------------------------------------ Zeigen und Befüllen
    @staticmethod
    def _datenmodell(abbildung: dict[str, str], daten: Any) -> dict[str, Any]:
        modell = abbildung_anwenden(abbildung, daten)
        if not isinstance(modell, dict):
            modell = {"wert": modell}
        eintraege = modell.get("eintraege")
        if "anzahl" not in modell:
            listen = [v for v in modell.values() if isinstance(v, list)]
            if isinstance(eintraege, list):
                modell["anzahl"] = len(eintraege)
            elif len(listen) == 1:
                modell["anzahl"] = len(listen[0])
        return modell

    def _mischen(self, surface_id: str, modell: dict[str, Any]) -> dict[str, Any]:
        """Neues Datenmodell über das alte legen: Eingaben der Oberfläche (zweiseitige Bindung) bleiben erhalten."""
        alt = (self.flaechen.get(surface_id) or {}).get("daten") or {}
        return {**alt, **modell} if isinstance(alt, dict) else modell

    async def zeigen(
        self,
        werkzeug: str,
        argumente: dict[str, Any] | None = None,
        titel: str | None = None,
        wunsch: str = "",
        integration: str | None = None,
        vorlage: str | None = None,
    ) -> dict[str, Any]:
        """Werkzeug ausführen und das Ergebnis auf die Bühne bringen. Vorlage: explizit (``vorlage``), sonst per
        Signatur – aber nur, wenn der Titel zur Vorlage passt; eine andere Sicht (anderer Titel) bekommt eine eigene
        Vorlage und Fläche, statt die vorhandene umzubauen."""
        if not self._aktiv():
            raise BuehnenFehler("Die Bühne ist in den Einstellungen ausgeschaltet.")
        argumente = dict(argumente or {})
        daten = await self._ergebnis_holen(werkzeug, argumente)
        sig = signatur(werkzeug, daten)
        gewaehlt: dict[str, Any] | None
        if vorlage:
            gewaehlt = self.speicher.vorlage(vorlage)
            if gewaehlt is None:
                raise BuehnenFehler(f"Vorlage „{vorlage}“ gibt es nicht.")
        else:
            kandidaten = self.speicher.vorlagen_fuer_signatur(werkzeug, sig["schluessel"], sig.get("eintrag"))
            if titel:
                kandidaten = [k for k in kandidaten if titel_passt(titel, k["name"])]
            gewaehlt = kandidaten[0] if kandidaten else None
        vorlage = gewaehlt
        neu = vorlage is None
        grund: str | None = None  # „form“ (Ergebnisform geändert) oder „wunsch“ (Umbau nach Wunsch)
        mischen = True
        stil_id = self.stil_fuer(vorlage, integration, werkzeug)
        if vorlage is None:
            # Selbstreparatur: eine frühere Rohtext-Vorlage derselben Sicht (Ergebnis war damals nicht lesbar) weicht der neuen
            if sig["schluessel"] != ["text"]:
                for alt in self.speicher.vorlagen_fuer_signatur(werkzeug, ["text"]):
                    if not titel or titel_passt(titel, alt["name"]):
                        await self.schliessen(alt["id"])
                        self.speicher.verlauf_vergessen(alt["id"])
                        self.speicher.vorlage_loeschen(alt["id"])
                        log.info("Bühne: Rohtext-Vorlage %s durch strukturierte Vorlage ersetzt", alt["id"])
            gebaut = await self.erzeuger.vorlage_bauen(werkzeug, daten, wunsch=wunsch, stil=self.speicher.stil(stil_id), titel=titel)
            vorlage = self.speicher.vorlage_anlegen(
                gebaut["name"] or titel or werkzeug,
                gebaut.get("zweck", ""),
                gebaut["komponenten"],
                gebaut.get("datenschema"),
                _datenquelle(werkzeug, argumente, gebaut.get("abbildung")),
                signatur=sig,
                modell=gebaut.get("modell"),
            )
        elif not abbildung_greift(vorlage["datenquelle"].get("abbildung") or {}, daten):
            if ist_nur_text(daten):
                # Text statt der erwarteten Daten: nie eine gute Vorlage aus einem Text (oft eine Störung) neu bauen
                raise BuehnenFehler(
                    f"„{vorlage['name']}“ erwartet strukturierte Daten, das Werkzeug lieferte nur Text: {str(daten['text'])[:200]} – "
                    "Fläche unverändert. Abfrage prüfen oder die Sicht unter einem anderen Titel neu zeigen."
                )
            # Die Daten haben eine andere Form (andere Schlüssel/Datenquelle): aus dem echten Ergebnis neu bauen,
            # als neue Version derselben Vorlage – statt einer Fläche ohne Werte
            grund, mischen = "form", False
            gebaut = await self.erzeuger.vorlage_bauen(werkzeug, daten, wunsch=wunsch, stil=self.speicher.stil(stil_id), titel=titel or vorlage["name"])
            vorlage = self.speicher.vorlage_neue_version(
                vorlage["id"],
                komponenten=gebaut["komponenten"],
                datenschema=gebaut.get("datenschema"),
                datenquelle=_datenquelle(werkzeug, argumente, gebaut.get("abbildung")),
                modell=gebaut.get("modell"),
                signatur=sig,
                zweck=gebaut.get("zweck"),
            )
            log.info("Bühne: Abbildung der Vorlage %s greift nicht mehr – aus dem Ergebnis neu gebaut (Version %s)", vorlage["id"], vorlage.get("version"))
        elif wunsch:
            grund = "wunsch"
            alt_abbildung = vorlage["datenquelle"].get("abbildung") or {}
            geaendert = await self.erzeuger.vorlage_aendern(vorlage, wunsch, beispiel_daten=self._datenmodell(alt_abbildung, daten))
            abbildung = self._abbildung_pruefen(vorlage["id"], geaendert.get("abbildung"), alt_abbildung, daten)
            vorlage = self.speicher.vorlage_neue_version(
                vorlage["id"],
                komponenten=geaendert["komponenten"],
                datenschema=geaendert.get("datenschema"),
                datenquelle=_datenquelle(werkzeug, argumente, abbildung),
                modell=geaendert.get("modell"),
                signatur=sig,
                zweck=geaendert.get("zweck"),
            )
        modell = self._datenmodell(vorlage["datenquelle"].get("abbildung") or {}, daten)
        if mischen:
            modell = self._mischen(vorlage["id"], modell)
        self._roh[vorlage["id"]] = daten
        flaeche = await self._flaeche_senden(vorlage["id"], titel or vorlage["name"], stil_id, vorlage["komponenten"], modell, vorlage["id"])
        flaeche["argumente"] = argumente
        self.speicher.verlauf_merken(vorlage["id"], flaeche["titel"], werkzeug, argumente)
        self._speichern()
        await self._aktionen_melden()
        return {"surfaceId": flaeche["surfaceId"], "titel": flaeche["titel"], "vorlage": vorlage["id"], "neu": neu, "umgebaut": grund is not None, "grund": grund, "anzahl": modell.get("anzahl"), "stil": stil_id}

    async def _ergebnis_holen(self, werkzeug: str, argumente: dict[str, Any]) -> Any:
        """Werkzeug ausführen und das Ergebnis als Daten liefern; Fehlermeldungen und gekürzte Ergebnisse sind Fehler."""
        daten = ergebnis_parsen(await self._werkzeug(werkzeug, argumente))
        if ist_fehlertext(daten):
            raise BuehnenFehler(str(daten["text"])[:300])
        if ist_nur_text(daten) and "Zeichen ausgelassen)" in str(daten["text"])[-60:]:
            raise BuehnenFehler("Das Ergebnis wurde gekürzt und ist dadurch nicht auswertbar; schränke die Abfrage ein (weniger Einträge).")
        return daten

    @staticmethod
    def _abbildung_pruefen(vorlage_id: str, neu: Any, alt: dict[str, str], daten: Any) -> dict[str, str]:
        """Vom Modell geänderte Abbildung nur übernehmen, wenn sie im echten Ergebnis Werte findet; sonst bleibt die alte."""
        if isinstance(neu, dict) and neu and abbildung_greift(neu, daten):
            return {str(k): str(v) for k, v in neu.items()}
        if isinstance(neu, dict) and neu:
            log.warning("Bühne: geänderte Abbildung der Vorlage %s findet im Ergebnis nichts – alte Abbildung bleibt", vorlage_id)
        return dict(alt)

    async def erneut(self, vorlage_id: str, argumente: dict[str, Any] | None = None, titel: str | None = None) -> dict[str, Any]:
        """Schnellaktion/Variante: Datenwerkzeug der Vorlage mit diesen Argumenten ausführen und die Vorlage befüllen (ohne Modell)."""
        vorlage = self.speicher.vorlage(vorlage_id)
        if vorlage is None:
            raise BuehnenFehler(f"Vorlage „{vorlage_id}“ gibt es nicht.")
        werkzeug = vorlage["datenquelle"].get("werkzeug")
        if not werkzeug:
            raise BuehnenFehler(f"Vorlage „{vorlage_id}“ hat keine Datenquelle.")
        if argumente is None:
            argumente = dict(vorlage["datenquelle"].get("argumente") or {})
        if not titel:
            passende = [e for e in self.speicher.varianten(vorlage_id, 50) if json.dumps(e.get("argumente") or {}, sort_keys=True) == json.dumps(argumente, sort_keys=True)]
            titel = passende[0]["titel"] if passende else vorlage["name"]
        e = await self.zeigen(werkzeug, argumente, titel=titel, vorlage=vorlage_id)
        return {k: e[k] for k in ("surfaceId", "titel", "vorlage", "anzahl")}

    async def daten_setzen(self, surface_id: str, daten: Any = None, path: str = "/", value: Any = None, melden: bool = True) -> dict[str, Any]:
        flaeche = self.flaechen.get(surface_id)
        if flaeche is None:
            raise BuehnenFehler(f"Fläche „{surface_id}“ ist nicht offen.")
        if daten is not None:
            flaeche["daten"] = daten if isinstance(daten, dict) else {"wert": daten}
            if melden:
                await self._nachricht({"updateDataModel": {"surfaceId": surface_id, "path": "/", "value": flaeche["daten"]}})
        else:
            flaeche["daten"] = json_pointer_setzen(flaeche.get("daten") or {}, path, value)
            if melden:
                await self._nachricht({"updateDataModel": {"surfaceId": surface_id, "path": path, "value": value}})
        self._speichern()
        return flaeche

    async def neu_laden(self, surface_id: str) -> dict[str, Any]:
        """Datenquelle der Vorlage erneut ausführen und die Fläche befüllen."""
        flaeche = self.flaechen.get(surface_id)
        if flaeche is None or not flaeche.get("vorlage"):
            raise BuehnenFehler(f"Fläche „{surface_id}“ hat keine Datenquelle.")
        vorlage = self.speicher.vorlage(flaeche["vorlage"])
        if not vorlage or not vorlage["datenquelle"].get("werkzeug"):
            raise BuehnenFehler(f"Vorlage „{flaeche['vorlage']}“ hat keine Datenquelle.")
        quelle = vorlage["datenquelle"]
        # die Fläche zeigt ggf. eine Variante (andere Argumente als die Vorlage) – genau die neu laden
        argumente = flaeche.get("argumente") if isinstance(flaeche.get("argumente"), dict) else dict(quelle.get("argumente") or {})
        daten = await self._ergebnis_holen(str(quelle["werkzeug"]), argumente)
        if not abbildung_greift(quelle.get("abbildung") or {}, daten):
            raise BuehnenFehler(
                "Das Ergebnis der Datenquelle passt nicht mehr zur Vorlage (die Abbildung findet keine Werte) – "
                "die Sicht mit buehne_zeigen neu anzeigen, dann wird die Vorlage aus dem Ergebnis neu gebaut."
            )
        self._roh[vorlage["id"]] = daten
        return await self.daten_setzen(surface_id, self._mischen(surface_id, self._datenmodell(quelle.get("abbildung") or {}, daten)))

    # ------------------------------------------------------------------ Ändern
    async def aendern(self, vorlage_id: str, wunsch: str, neu_bauen: bool = False) -> dict[str, Any]:
        """Vorlage nach Wunsch umbauen (neue Version). ``neu_bauen``: von Grund auf neu entwerfen statt die bestehende
        Komponentenliste anzupassen – für „gefällt mir nicht, bau es anders auf“."""
        vorlage = self.speicher.vorlage(vorlage_id)
        if vorlage is None:
            raise BuehnenFehler(f"Vorlage „{vorlage_id}“ gibt es nicht.")
        flaeche = self.flaechen.get(vorlage_id)
        roh = await self._rohdaten(vorlage)
        if neu_bauen:
            if roh is None:
                raise BuehnenFehler("Zum Neubau fehlen die Daten der Vorlage (Datenquelle nicht ausführbar).")
            stil = self.speicher.stil(self.stil_fuer(vorlage, None, vorlage["datenquelle"].get("werkzeug")))
            geaendert = await self.erzeuger.vorlage_bauen(str(vorlage["datenquelle"].get("werkzeug") or ""), roh, wunsch=wunsch, stil=stil, titel=vorlage["name"])
        else:
            beispiel = flaeche.get("daten") if flaeche else None
            geaendert = await self.erzeuger.vorlage_aendern(vorlage, wunsch, beispiel_daten=beispiel)
        alt_abbildung = vorlage["datenquelle"].get("abbildung") or {}
        abbildung = self._abbildung_pruefen(vorlage_id, geaendert.get("abbildung"), alt_abbildung, roh) if roh is not None else (geaendert.get("abbildung") or alt_abbildung)
        quelle = vorlage["datenquelle"]
        neu = self.speicher.vorlage_neue_version(
            vorlage_id,
            komponenten=geaendert["komponenten"],
            datenschema=geaendert.get("datenschema"),
            datenquelle=_datenquelle(str(quelle.get("werkzeug") or ""), quelle.get("argumente") or {}, abbildung),
            modell=geaendert.get("modell"),
            zweck=geaendert.get("zweck"),
        )
        await self._komponenten_anwenden(neu)
        return {"vorlage": neu["id"], "version": neu["version"]}

    async def zurueck(self, vorlage_id: str) -> dict[str, Any]:
        vorlage = self.speicher.vorlage_zurueck(vorlage_id)
        await self._komponenten_anwenden(vorlage)
        return {"vorlage": vorlage["id"], "version": vorlage["version"]}

    async def _rohdaten(self, vorlage: dict[str, Any], frisch: bool = False) -> Any:
        """Letztes Werkzeugergebnis der Vorlage; nach einem Neustart (oder mit ``frisch``) wird die Datenquelle mit den
        Argumenten der offenen Fläche erneut ausgeführt."""
        roh = self._roh.get(vorlage["id"])
        if roh is not None and not frisch:
            return roh
        quelle = vorlage.get("datenquelle") or {}
        if not quelle.get("werkzeug"):
            return None
        flaeche = self.flaechen.get(vorlage["id"]) or {}
        argumente = flaeche.get("argumente") if isinstance(flaeche.get("argumente"), dict) else dict(quelle.get("argumente") or {})
        try:
            roh = await self._ergebnis_holen(str(quelle["werkzeug"]), argumente)
        except Exception as exc:  # noqa: BLE001
            log.warning("Bühne: Datenquelle von %s nicht ausführbar (%s)", vorlage["id"], exc)
            return None
        self._roh[vorlage["id"]] = roh
        return roh

    async def _komponenten_anwenden(self, vorlage: dict[str, Any]) -> None:
        flaeche = self.flaechen.get(vorlage["id"])
        if flaeche is None:
            return
        flaeche["components"] = vorlage["komponenten"]
        await self._nachricht({"updateComponents": {"surfaceId": vorlage["id"], "components": vorlage["komponenten"]}})
        abbildung = vorlage["datenquelle"].get("abbildung") or {}
        roh = await self._rohdaten(vorlage)
        if roh is not None and not abbildung_greift(abbildung, roh):
            roh = await self._rohdaten(vorlage, frisch=True)  # z. B. nach Rückgängig: alte Abbildung, aber neue Ergebnisform im Speicher
        if roh is not None and not abbildung_greift(abbildung, roh):
            log.warning("Bühne: Abbildung der Vorlage %s findet im aktuellen Ergebnis nichts – Datenmodell unverändert", vorlage["id"])
            roh = None
        if roh is not None:
            flaeche["daten"] = self._mischen(vorlage["id"], self._datenmodell(vorlage["datenquelle"].get("abbildung") or {}, roh))
            await self._nachricht({"updateDataModel": {"surfaceId": vorlage["id"], "path": "/", "value": flaeche["daten"]}})
        self._speichern()

    async def stil_der_vorlage(self, vorlage_id: str, stil_id: str | None) -> dict[str, Any]:
        vorlage = self.speicher.vorlage_aendern(vorlage_id, stil=stil_id or "")
        flaeche = self.flaechen.get(vorlage_id)
        if flaeche is not None:
            neuer = self.stil_fuer(vorlage, None, vorlage["datenquelle"].get("werkzeug"))
            flaeche["stil"] = neuer
            await self._stil_senden(neuer)
            await self._nachricht({"createSurface": {"surfaceId": vorlage_id, "catalogId": KATALOG_ID, "theme": {"stil": neuer}, "titel": flaeche["titel"], "vorlage": vorlage_id}})
            self._speichern()
        return vorlage

    async def schliessen(self, surface_id: str | None = None) -> list[str]:
        ziele = [surface_id] if surface_id else list(self.flaechen)
        geschlossen = []
        for kennung in ziele:
            if kennung in self.flaechen:
                del self.flaechen[kennung]
                self._roh.pop(kennung, None)
                await self._nachricht({"deleteSurface": {"surfaceId": kennung}})
                geschlossen.append(kennung)
                if self.werkzeugflaechen is not None:
                    self.werkzeugflaechen.vergessen(kennung)
        self._speichern()
        if geschlossen:
            await self._aktionen_melden()
        return geschlossen

    # ------------------------------------------------------------------ Aktionen und Rezepte
    @staticmethod
    def _argument(ausdruck: Any, context: dict[str, Any]) -> Any:
        """„context.objekt_id“ → Wert aus dem Kontext (auch verschachtelt), sonst Literal."""
        if isinstance(ausdruck, str) and ausdruck.startswith("context."):
            wert: Any = context
            for teil in ausdruck[len("context."):].split("."):
                wert = wert.get(teil) if isinstance(wert, dict) else None
            return wert
        return ausdruck

    def rezept_anlegen(
        self,
        vorlage_id: str,
        aktion: str,
        art: str,
        name: str | None = None,
        werkzeug: str | None = None,
        argument_abbildung: dict[str, Any] | None = None,
        auftrag: str | None = None,
        risiko: str = "aendern",
        bestaetigung: str | None = None,
        titel: str | None = None,
        vorlage_ziel: str | None = None,
    ) -> dict[str, Any]:
        vorlage = self.speicher.vorlage(vorlage_id)
        if vorlage is None:
            raise BuehnenFehler(f"Vorlage „{vorlage_id}“ gibt es nicht.")
        if art not in ("werkzeug", "agent", "zeigen"):
            raise BuehnenFehler("art muss „werkzeug“, „agent“ oder „zeigen“ sein.")
        if art in ("werkzeug", "zeigen") and not werkzeug:
            raise BuehnenFehler(f"Für art „{art}“ fehlt der Werkzeugname.")
        if art == "agent" and not auftrag:
            raise BuehnenFehler("Für art „agent“ fehlt der Auftrag.")
        if vorlage_ziel and self.speicher.vorlage(vorlage_ziel) is None:
            raise BuehnenFehler(f"Zielvorlage „{vorlage_ziel}“ gibt es nicht.")
        rezept = self.speicher.rezept_anlegen(
            name or aktion.replace("_", " ").capitalize(),
            art,
            vorlage_id,
            risiko="lesen" if art == "zeigen" and risiko != "kritisch" else (risiko if risiko in ("lesen", "aendern", "kritisch") else "aendern"),
            aktion=aktion,
            werkzeug=werkzeug,
            argumentAbbildung=argument_abbildung,
            auftrag=auftrag,
            bestaetigung=bestaetigung,
            titel=titel,
            vorlageZiel=vorlage_ziel,
        )
        altes = (vorlage.get("aktionen") or {}).get(aktion)
        if altes and altes != rezept["id"]:
            self.speicher.rezept_loeschen(altes)  # ein neues Rezept ersetzt das alte für diese Aktion
        self.speicher.aktion_setzen(vorlage_id, aktion, rezept["id"])
        return rezept

    async def aktion(self, nachricht: dict[str, Any]) -> dict[str, Any]:
        name = str(nachricht.get("name") or "").strip()
        surface_id = str(nachricht.get("surfaceId") or "")
        context = nachricht.get("context") if isinstance(nachricht.get("context"), dict) else {}
        flaeche = self.flaechen.get(surface_id)
        if flaeche is None:
            raise BuehnenFehler(f"Fläche „{surface_id}“ ist nicht offen.")
        if not name:
            raise BuehnenFehler("Aktion ohne Namen.")
        if flaeche.get("art") == "werkzeug":
            if self.werkzeugflaechen is None:
                raise BuehnenFehler("Werkzeugflächen sind nicht verfügbar.")
            try:
                return await self.werkzeugflaechen.aktion(flaeche, name, context)
            except WerkzeugflaechenFehler as e:
                raise BuehnenFehler(str(e)) from e
        vorlage = self.speicher.vorlage(flaeche["vorlage"]) if flaeche.get("vorlage") else None
        rezept_id = (vorlage or {}).get("aktionen", {}).get(name)
        rezept = self.speicher.rezept(rezept_id) if rezept_id else None
        if rezept and rezept.get("art") == "werkzeug" and rezept.get("werkzeug"):
            argumente = {k: self._argument(v, context) for k, v in (rezept.get("argumentAbbildung") or {}).items()}
            ergebnis = await self._werkzeug(str(rezept["werkzeug"]), argumente)
            if vorlage and vorlage["datenquelle"].get("werkzeug") and rezept.get("neuLaden", True):
                with contextlib.suppress(BuehnenFehler):
                    await self.neu_laden(surface_id)
            kennung = f"buehne_{uuid.uuid4().hex[:10]}"
            text = f"{rezept.get('name', name)}: {str(ergebnis)[:600]}"
            await self._senden({"typ": "antwort_start", "id": kennung})
            await self._senden({"typ": "antwort_ende", "id": kennung, "text": text})
            return {"ok": True, "rezept": rezept["id"], "ergebnis": str(ergebnis)[:2000]}
        if rezept and rezept.get("art") == "zeigen" and rezept.get("werkzeug"):
            argumente = {k: self._argument(v, context) for k, v in (rezept.get("argumentAbbildung") or {}).items()}
            titel = _PLATZHALTER.sub(lambda m: str(self._argument("context." + m.group(1), context) or m.group(0)), str(rezept.get("titel") or rezept.get("name") or name))
            ziel = rezept.get("vorlageZiel")
            if ziel and self.speicher.vorlage(ziel) is None:
                ziel = None
            e = await self.zeigen(str(rezept["werkzeug"]), argumente, titel=titel, vorlage=ziel)
            if not ziel:
                self.speicher.rezept_aendern(rezept["id"], vorlageZiel=e["vorlage"])
            return {"ok": True, "rezept": rezept["id"], "surfaceId": e["surfaceId"], "vorlage": e["vorlage"]}
        if rezept and rezept.get("art") == "agent" and rezept.get("auftrag") and self._anfrage is not None:
            auftrag = _PLATZHALTER.sub(lambda m: str(self._argument("context." + m.group(1), context) or m.group(0)), str(rezept["auftrag"]))
            auftrag += (
                f"\n(Aktion „{name}“ von der Bühne „{flaeche['titel'] if flaeche else surface_id}“; Daten: {json.dumps(context, ensure_ascii=False)[:1500]}. "
                "Lässt sich das Ergebnis anzeigen, zeige es auf der Bühne (buehne_zeigen, allgemeiner Titel) und lege das Rezept "
                "dieser Aktion neu als Art „zeigen“ an – es ersetzt dieses. Im Chat nur ein Satz.)"
            )
            antwort = await self._anfrage(auftrag)
            return {"ok": True, "rezept": rezept["id"], "antwort": antwort}
        if self._anfrage is None:
            raise BuehnenFehler(f"Für die Aktion „{name}“ gibt es kein Rezept.")
        text = (
            f"Auf der Bühne „{flaeche['titel'] if flaeche else surface_id}“ wurde die Aktion „{name}“ ausgelöst"
            f"{' (Vorlage „' + vorlage['id'] + '“)' if vorlage else ''}. Daten: {json.dumps(context, ensure_ascii=False)[:1500]}\n"
            "Führe die passende Arbeit aus. Soll etwas geöffnet oder angezeigt werden (öffnen, Details, anzeigen), zeige es auf der "
            "Bühne mit buehne_zeigen (Lesewerkzeug mit den Daten aus dem Kontext; allgemeiner Titel wie „Deal-Details“, damit die "
            "Vorlage für alle Einträge gilt) und lege danach mit buehne_rezept_anlegen ein Rezept der Art „zeigen“ an (werkzeug, "
            "argument_abbildung {\"arg\": \"context.feld\"}, titel, vorlage_ziel = Kennung der eben gebauten Vorlage). Sonst lege ein "
            "Rezept der Art „werkzeug“ oder „agent“ an, damit die Aktion beim nächsten Klick direkt läuft. Im Chat nur ein Satz."
        )
        antwort = await self._anfrage(text)
        return {"ok": True, "rezept": None, "antwort": antwort}

    # ------------------------------------------------------------------ Werkzeugflächen
    async def werkzeug_oeffnen(self, kennung: str, modus: str | None = None) -> dict[str, Any]:
        if not self._aktiv():
            raise BuehnenFehler("Die Bühne ist in den Einstellungen ausgeschaltet.")
        if self.werkzeugflaechen is None:
            raise BuehnenFehler("Werkzeugflächen sind nicht verfügbar.")
        try:
            return await self.werkzeugflaechen.oeffnen(kennung, modus)
        except WerkzeugflaechenFehler as e:
            raise BuehnenFehler(str(e)) from e

    async def werkzeug_schliessen(self, kennung: str) -> dict[str, Any]:
        if self.werkzeugflaechen is None:
            raise BuehnenFehler("Werkzeugflächen sind nicht verfügbar.")
        try:
            return await self.werkzeugflaechen.schliessen(kennung)
        except WerkzeugflaechenFehler as e:
            raise BuehnenFehler(str(e)) from e

    # ------------------------------------------------------------------ Stile
    async def stil_ableiten(self, name: str, quelle: dict[str, Any]) -> dict[str, Any]:
        stil = await self.erzeuger.stil_ableiten(name, quelle)
        return self.speicher.stil_speichern(stil)

    def stil_aendern(self, stil_id: str, aenderungen: dict[str, Any], name: str | None = None) -> dict[str, Any]:
        stil = self.speicher.stil(stil_id)
        if stil is None:
            raise BuehnenFehler(f"Stil „{stil_id}“ gibt es nicht.")
        neu = json.loads(json.dumps(stil))
        werte = aenderungen.get("werte") if isinstance(aenderungen.get("werte"), dict) else aenderungen
        farben = werte.get("farben") if isinstance(werte.get("farben"), dict) else {}
        for k in STILFARBEN:
            h = _hex_norm(farben.get(k)) if farben.get(k) else None
            if h:
                neu["werte"]["farben"][k] = h
        for feld in ("schema", "dichte", "schatten"):
            if werte.get(feld):
                neu["werte"][feld] = werte[feld]
        for feld in ("rundung", "abstand"):
            if feld in werte:
                with contextlib.suppress(TypeError, ValueError):
                    neu["werte"][feld] = int(werte[feld])
        if isinstance(werte.get("schrift"), dict):
            neu["werte"]["schrift"].update({k: v for k, v in werte["schrift"].items() if k in ("familie", "basisgroesse")})
        if isinstance(aenderungen.get("vorlieben"), dict):
            neu.setdefault("vorlieben", {}).update(aenderungen["vorlieben"])
        if name:
            neu["name"] = name
        if not stil.get("eigen"):
            neu["id"] = kennung_aus(name or f"{stil['name']} eigen", "stil")
            neu["quelle"] = {"art": "werte"}
        return self.speicher.stil_speichern(neu)

    def stil_zuweisen(self, integration: str, stil_id: str | None) -> dict[str, str]:
        zuordnung = self.speicher.zuordnung()
        if stil_id:
            if self.speicher.stil(stil_id) is None:
                raise BuehnenFehler(f"Stil „{stil_id}“ gibt es nicht.")
            zuordnung[integration] = stil_id
        else:
            zuordnung.pop(integration, None)
        return self.speicher.zuordnung_setzen(zuordnung)

    # ------------------------------------------------------------------ Prompt
    def prompt_abschnitt(self) -> str:
        vorlagen = self.speicher.vorlagen()[:20]
        zeilen = ["## Bühne", "Ergebnisse mit Struktur (Listen, Datensätze, Mails, Wetter, Vergleiche) gehören immer auf die Bühne – auch bei Sprachfragen: rufe buehne_zeigen mit dem Werkzeug und seinen Argumenten auf, statt das Werkzeug selbst aufzurufen (bei mehrstufigen Abfragen wie Wetter erst Vorarbeiten wie die Ortssuche, dann buehne_zeigen mit dem letzten Werkzeug); der Chat fasst in einem Satz zusammen. Zuletzt gezeigte Varianten (z. B. Wetter Stuttgart, Wetter Frankfurt) bietet die Bühne selbst als Knöpfe an. Aktionen auf Knöpfen, die etwas öffnen oder anzeigen, führen zu einer eigenen Fläche (Rezept der Art zeigen) – nicht zu Text im Chat. Wirkt eine Sicht falsch, leer oder gemischt, stelle sie selbst wieder her (buehne_vorlage_zurueck) oder baue sie neu; bitte nie den Nutzer, das zu tun. Jede Sicht (Immobilien, Makler, Mails …) hat ihre eigene Vorlage und Fläche: der Titel entscheidet – gleicher Titel = vorhandene Vorlage wird nur befüllt, anderer Titel = neue Vorlage (oder gib vorlage explizit an). Filtern und Sortieren über die Argumente des Werkzeugs, nicht über den Wunsch. Sagt der Nutzer, die Darstellung gefalle ihm nicht oder sie solle anders aufgebaut werden, rufe sofort buehne_vorlage_aendern mit seinem Wunsch auf (neu_bauen=true für einen kompletten Neuentwurf) – die offene Fläche wird dadurch aktualisiert; Rückgängig mit buehne_vorlage_zurueck. Aktionen von der Bühne kommen als Nachricht; lege danach mit buehne_rezept_anlegen ein Rezept an. Stile: buehne_stil_ableiten (URL/Datei/Klassen), buehne_stil_aendern, buehne_stil_zuweisen."]
        if vorlagen:
            zeilen.append("Vorlagen:")
            for v in vorlagen:
                aktionen = ", ".join(v.get("aktionen") or {}) or "–"
                zeilen.append(f"- {v['id']} („{v['name']}“): {v.get('zweck', '')} – Quelle {v['datenquelle'].get('werkzeug', '?')}, Aktionen: {aktionen}")
        if self.flaechen:
            zeilen.append("Offene Flächen: " + ", ".join(f"{f['surfaceId']} („{f['titel']}“)" for f in self.flaechen.values()))
        if self.werkzeugflaechen is not None:
            zeilen.extend(self.werkzeugflaechen.prompt_zeilen())
        return "\n".join(zeilen)

    def aktuelle_daten(self, surface_id: str) -> Any:
        f = self.flaechen.get(surface_id)
        return f.get("daten") if f else None

    @staticmethod
    def kontextwert(context: dict[str, Any], pfad: str) -> Any:
        return json_pointer_holen(context, pfad)
