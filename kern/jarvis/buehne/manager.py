"""Manager der Bühne: Flächen anzeigen, befüllen, ändern, schließen; Aktionen zu Rezepten; Stile zuweisen.

Spricht A2UI über das Ereignis ``{"typ": "buehne", "nachricht": {…}}`` zur Oberfläche und nimmt
``buehne_aktion``/``buehne_daten`` entgegen. Werkzeuge laufen über den Rückruf ``werkzeug_ausfuehren`` des
Agenten (mit Freigaberegeln); Aufträge an den Assistenten über ``anfrage``.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Awaitable, Callable

from .daten import abbildung_anwenden, ergebnis_parsen, json_pointer_holen, json_pointer_setzen, signatur
from .erzeuger import STILFARBEN, Erzeuger, _hex_norm
from .speicher import KATALOG_ID, PROTOKOLL_VERSION, BuehnenSpeicher, kennung_aus

log = logging.getLogger("jarvis.buehne")

Senden = Callable[[dict[str, Any]], Awaitable[None]]
WerkzeugAusfuehren = Callable[[str, dict[str, Any]], Awaitable[str]]
Anfrage = Callable[[str], Awaitable[str]]
STANDARD_STIL = "javit-dunkel"
_PLATZHALTER = re.compile(r"\{([a-zA-Z0-9_./]+)\}")


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
        self._anfrage = anfrage
        self._aktiv = aktiv or (lambda: True)
        self.flaechen: dict[str, dict[str, Any]] = {}
        self._roh: dict[str, Any] = {}  # letztes Werkzeugergebnis je Fläche (für Umbauten ohne neuen Aufruf)
        self._gesendete_stile: set[str] = set()

    # ------------------------------------------------------------------ Zustand
    def laden(self) -> None:
        for f in self.speicher.flaechen_laden():
            self.flaechen[f["surfaceId"]] = f

    def _speichern(self) -> None:
        self.speicher.flaechen_speichern(list(self.flaechen.values()))

    def zustand(self) -> dict[str, Any]:
        return {"flaechen": list(self.flaechen.values()), "stile": self.speicher.stile(), "zuordnung": self.speicher.zuordnung()}

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

    async def _flaeche_senden(self, surface_id: str, titel: str, stil_id: str, komponenten: list[dict[str, Any]], daten: Any, vorlage_id: str | None) -> dict[str, Any]:
        await self._stil_senden(stil_id)
        await self._nachricht({"createSurface": {"surfaceId": surface_id, "catalogId": KATALOG_ID, "theme": {"stil": stil_id}, "titel": titel, "vorlage": vorlage_id}})
        await self._nachricht({"updateComponents": {"surfaceId": surface_id, "components": komponenten}})
        await self._nachricht({"updateDataModel": {"surfaceId": surface_id, "path": "/", "value": daten}})
        flaeche = {"surfaceId": surface_id, "titel": titel, "catalogId": KATALOG_ID, "stil": stil_id, "components": komponenten, "daten": daten, "vorlage": vorlage_id}
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
    ) -> dict[str, Any]:
        """Werkzeug ausführen und das Ergebnis auf die Bühne bringen; Vorlage wiederverwenden, sonst bauen."""
        if not self._aktiv():
            raise BuehnenFehler("Die Bühne ist in den Einstellungen ausgeschaltet.")
        argumente = dict(argumente or {})
        text = await self._werkzeug(werkzeug, argumente)
        daten = ergebnis_parsen(text)
        if isinstance(daten, dict) and set(daten) == {"text"} and str(daten["text"]).lower().startswith(("fehler", "nicht ausgeführt", "unbekanntes werkzeug")):
            raise BuehnenFehler(str(daten["text"])[:300])
        sig = signatur(werkzeug, daten)
        vorlage = self.speicher.vorlage_fuer_signatur(werkzeug, sig["schluessel"], sig.get("eintrag"))
        neu = vorlage is None
        stil_id = self.stil_fuer(vorlage, integration, werkzeug)
        if vorlage is None:
            gebaut = await self.erzeuger.vorlage_bauen(werkzeug, daten, wunsch=wunsch, stil=self.speicher.stil(stil_id), titel=titel)
            vorlage = self.speicher.vorlage_anlegen(
                gebaut["name"] or titel or werkzeug,
                gebaut.get("zweck", ""),
                gebaut["komponenten"],
                gebaut.get("datenschema"),
                {"werkzeug": werkzeug, "argumente": argumente, "abbildung": gebaut.get("abbildung") or {}},
                signatur=sig,
                modell=gebaut.get("modell"),
            )
        elif wunsch:
            geaendert = await self.erzeuger.vorlage_aendern(vorlage, wunsch, beispiel_daten=self._datenmodell(vorlage["datenquelle"].get("abbildung") or {}, daten))
            vorlage = self.speicher.vorlage_neue_version(
                vorlage["id"],
                komponenten=geaendert["komponenten"],
                datenschema=geaendert.get("datenschema"),
                datenquelle={**vorlage["datenquelle"], "argumente": argumente, "abbildung": geaendert.get("abbildung") or {}},
                modell=geaendert.get("modell"),
            )
        modell = self._mischen(vorlage["id"], self._datenmodell(vorlage["datenquelle"].get("abbildung") or {}, daten))
        self._roh[vorlage["id"]] = daten
        flaeche = await self._flaeche_senden(vorlage["id"], titel or vorlage["name"], stil_id, vorlage["komponenten"], modell, vorlage["id"])
        return {"surfaceId": flaeche["surfaceId"], "titel": flaeche["titel"], "vorlage": vorlage["id"], "neu": neu, "anzahl": modell.get("anzahl"), "stil": stil_id}

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
        daten = ergebnis_parsen(await self._werkzeug(quelle["werkzeug"], dict(quelle.get("argumente") or {})))
        self._roh[vorlage["id"]] = daten
        return await self.daten_setzen(surface_id, self._mischen(surface_id, self._datenmodell(quelle.get("abbildung") or {}, daten)))

    # ------------------------------------------------------------------ Ändern
    async def aendern(self, vorlage_id: str, wunsch: str) -> dict[str, Any]:
        vorlage = self.speicher.vorlage(vorlage_id)
        if vorlage is None:
            raise BuehnenFehler(f"Vorlage „{vorlage_id}“ gibt es nicht.")
        flaeche = self.flaechen.get(vorlage_id)
        beispiel = flaeche.get("daten") if flaeche else None
        geaendert = await self.erzeuger.vorlage_aendern(vorlage, wunsch, beispiel_daten=beispiel)
        neu = self.speicher.vorlage_neue_version(
            vorlage_id,
            komponenten=geaendert["komponenten"],
            datenschema=geaendert.get("datenschema"),
            datenquelle={**vorlage["datenquelle"], "abbildung": geaendert.get("abbildung") or vorlage["datenquelle"].get("abbildung") or {}},
            modell=geaendert.get("modell"),
        )
        await self._komponenten_anwenden(neu)
        return {"vorlage": neu["id"], "version": neu["version"]}

    async def zurueck(self, vorlage_id: str) -> dict[str, Any]:
        vorlage = self.speicher.vorlage_zurueck(vorlage_id)
        await self._komponenten_anwenden(vorlage)
        return {"vorlage": vorlage["id"], "version": vorlage["version"]}

    async def _komponenten_anwenden(self, vorlage: dict[str, Any]) -> None:
        flaeche = self.flaechen.get(vorlage["id"])
        if flaeche is None:
            return
        flaeche["components"] = vorlage["komponenten"]
        await self._nachricht({"updateComponents": {"surfaceId": vorlage["id"], "components": vorlage["komponenten"]}})
        roh = self._roh.get(vorlage["id"])
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
        self._speichern()
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
    ) -> dict[str, Any]:
        if self.speicher.vorlage(vorlage_id) is None:
            raise BuehnenFehler(f"Vorlage „{vorlage_id}“ gibt es nicht.")
        if art not in ("werkzeug", "agent"):
            raise BuehnenFehler("art muss „werkzeug“ oder „agent“ sein.")
        if art == "werkzeug" and not werkzeug:
            raise BuehnenFehler("Für art „werkzeug“ fehlt der Werkzeugname.")
        if art == "agent" and not auftrag:
            raise BuehnenFehler("Für art „agent“ fehlt der Auftrag.")
        rezept = self.speicher.rezept_anlegen(
            name or aktion.replace("_", " ").capitalize(),
            art,
            vorlage_id,
            risiko=risiko if risiko in ("lesen", "aendern", "kritisch") else "aendern",
            aktion=aktion,
            werkzeug=werkzeug,
            argumentAbbildung=argument_abbildung,
            auftrag=auftrag,
            bestaetigung=bestaetigung,
        )
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
        vorlage = self.speicher.vorlage(flaeche["vorlage"]) if flaeche.get("vorlage") else None
        rezept_id = (vorlage or {}).get("aktionen", {}).get(name)
        rezept = self.speicher.rezept(rezept_id) if rezept_id else None
        if rezept and rezept.get("art") == "werkzeug" and rezept.get("werkzeug"):
            argumente = {k: self._argument(v, context) for k, v in (rezept.get("argumentAbbildung") or {}).items()}
            ergebnis = await self._werkzeug(str(rezept["werkzeug"]), argumente)
            if vorlage and vorlage["datenquelle"].get("werkzeug") and rezept.get("neuLaden", True):
                try:
                    await self.neu_laden(surface_id)
                except BuehnenFehler:
                    pass
            kennung = f"buehne_{uuid.uuid4().hex[:10]}"
            text = f"{rezept.get('name', name)}: {str(ergebnis)[:600]}"
            await self._senden({"typ": "antwort_start", "id": kennung})
            await self._senden({"typ": "antwort_ende", "id": kennung, "text": text})
            return {"ok": True, "rezept": rezept["id"], "ergebnis": str(ergebnis)[:2000]}
        if rezept and rezept.get("art") == "agent" and rezept.get("auftrag") and self._anfrage is not None:
            auftrag = _PLATZHALTER.sub(lambda m: str(self._argument("context." + m.group(1), context) or m.group(0)), str(rezept["auftrag"]))
            auftrag += f"\n(Aktion „{name}“ von der Bühne „{flaeche['titel'] if flaeche else surface_id}“; Daten: {json.dumps(context, ensure_ascii=False)[:1500]})"
            antwort = await self._anfrage(auftrag)
            return {"ok": True, "rezept": rezept["id"], "antwort": antwort}
        if self._anfrage is None:
            raise BuehnenFehler(f"Für die Aktion „{name}“ gibt es kein Rezept.")
        text = (
            f"Auf der Bühne „{flaeche['titel'] if flaeche else surface_id}“ wurde die Aktion „{name}“ ausgelöst"
            f"{' (Vorlage „' + vorlage['id'] + '“)' if vorlage else ''}. Daten: {json.dumps(context, ensure_ascii=False)[:1500]}\n"
            "Führe die passende Arbeit aus. Lege danach mit buehne_rezept_anlegen ein Rezept für diese Aktion an, "
            "damit sie beim nächsten Klick direkt läuft."
        )
        antwort = await self._anfrage(text)
        return {"ok": True, "rezept": None, "antwort": antwort}

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
                try:
                    neu["werte"][feld] = int(werte[feld])
                except (TypeError, ValueError):
                    pass
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
        zeilen = ["## Bühne", "Ergebnisse mit Struktur (Listen, Datensätze, Mails, Wetter, Vergleiche) gehören auf die Bühne: rufe buehne_zeigen mit dem Werkzeug und seinen Argumenten auf, statt das Werkzeug selbst aufzurufen; der Chat fasst dann kurz zusammen. Vorhandene Vorlagen werden automatisch wiederverwendet; Umbauten auf Wunsch mit buehne_vorlage_aendern, Rückgängig mit buehne_vorlage_zurueck. Aktionen von der Bühne kommen als Nachricht; lege danach mit buehne_rezept_anlegen ein Rezept an. Stile: buehne_stil_ableiten (URL/Datei/Klassen), buehne_stil_aendern, buehne_stil_zuweisen."]
        if vorlagen:
            zeilen.append("Vorlagen:")
            for v in vorlagen:
                aktionen = ", ".join(v.get("aktionen") or {}) or "–"
                zeilen.append(f"- {v['id']} („{v['name']}“): {v.get('zweck', '')} – Quelle {v['datenquelle'].get('werkzeug', '?')}, Aktionen: {aktionen}")
        if self.flaechen:
            zeilen.append("Offene Flächen: " + ", ".join(f"{f['surfaceId']} („{f['titel']}“)" for f in self.flaechen.values()))
        return "\n".join(zeilen)

    def aktuelle_daten(self, surface_id: str) -> Any:
        f = self.flaechen.get(surface_id)
        return f.get("daten") if f else None

    @staticmethod
    def kontextwert(context: dict[str, Any], pfad: str) -> Any:
        return json_pointer_holen(context, pfad)
