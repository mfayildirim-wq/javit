"""Werkzeugflächen der Bühne: Browser (live mit Screenshot), Shell (Terminal), Schrittlisten (Dateien …).

Anders als Datenflächen entstehen sie nicht aus Werkzeugergebnissen über das Modell, sondern aus festen Kern-Vorlagen
(A2UI aus dem Katalog), nur auf Kommando des Nutzers (``buehne_werkzeug_oeffnen``). Solange eine Fläche offen ist,
erscheinen die Aufrufe ihrer Werkzeuge dort als Schritte; bei ``live`` holt der Kern nach verändernden Schritten selbst
ein Bild. Werkzeugflächen überleben keinen Neustart.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger("jarvis.buehne")

WerkzeugAusfuehren = Callable[[str, dict[str, Any]], Awaitable[str]]

MAX_SCHRITTE = 40
MAX_ERGEBNIS = 600

#: Eingebaute Werkzeuge mit Werkzeugfläche (Integrationen bringen ihren Block im Katalog mit)
EINGEBAUTE: dict[str, dict[str, Any]] = {
    "shell": {"titel": "Shell", "symbol": "terminal", "art": "terminal", "werkzeuge": ["shell_befehl"], "befehl_werkzeug": "shell_befehl", "befehl_argument": "befehl"},
    "dateien": {
        "titel": "Dateien",
        "symbol": "folder",
        "art": "schritte",
        "werkzeuge": ["datei_suchen", "datei_lesen", "datei_schreiben", "datei_verschieben", "datei_loeschen", "ordner_auflisten"],
    },
}


class WerkzeugflaechenFehler(ValueError):
    pass


def _kurz(text: Any, n: int) -> str:
    t = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    t = t.strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _argumente_kurz(argumente: Any) -> str:
    if not isinstance(argumente, dict) or not argumente:
        return ""
    teile = []
    for k, v in argumente.items():
        if k in ("ref", "element") and isinstance(v, str) and len(v) > 24:
            v = v[:24] + "…"
        teile.append(f"{k}={_kurz(v, 60)}")
    return _kurz(", ".join(teile), 140)


def _zeit() -> str:
    return time.strftime("%H:%M:%S")


# ---------------------------------------------------------------- Kern-Vorlagen (A2UI)
def _schritt_komponenten() -> list[dict[str, Any]]:
    return [
        {"id": "schritte_titel", "component": "Text", "text": "Schritte", "variant": "h5"},
        {"id": "schritte", "component": "List", "children": {"path": "/schritte", "componentId": "schritt"}, "gap": 4},
        {"id": "schritt", "component": "Row", "children": ["schritt_nr", "schritt_text", "schritt_zustand"], "gap": 8, "align": "start"},
        {"id": "schritt_nr", "component": "Text", "text": {"path": "nr"}, "variant": "caption", "ton": "dezent"},
        {"id": "schritt_text", "component": "Text", "text": {"path": "text"}, "variant": "body"},
        {"id": "schritt_zustand", "component": "Badge", "text": {"path": "zustand"}, "ton": "info"},
    ]


def vorlage_live() -> list[dict[str, Any]]:
    return [
        {"id": "root", "component": "Column", "children": ["kopf", "statuszeile", "bild", "schritte_titel", "schritte", "fuss"], "gap": 10},
        {"id": "kopf", "component": "Row", "children": ["adresse", "oeffnen"], "gap": 8, "align": "end"},
        {"id": "adresse", "component": "TextField", "label": "Adresse", "value": {"path": "/adresse"}, "variant": "shortText"},
        {"id": "oeffnen", "component": "Button", "text": "Öffnen", "variant": "primary", "action": {"event": {"name": "werkzeug_oeffnen_url", "context": {"url": {"path": "/adresse"}}}}},
        {"id": "statuszeile", "component": "Row", "children": ["status", "modus", "hinweis"], "gap": 8, "align": "center", "wrap": True},
        {"id": "status", "component": "Badge", "text": {"path": "/status"}, "ton": "info"},
        {"id": "modus", "component": "Badge", "text": {"path": "/modus_text"}, "ton": "neutral"},
        {"id": "hinweis", "component": "Text", "text": {"path": "/hinweis"}, "variant": "caption", "ton": "dezent"},
        {"id": "bild", "component": "Image", "url": {"path": "/bild"}, "alt": "Aktuelle Seite", "fit": "contain", "variant": "screen"},
        *_schritt_komponenten(),
        {"id": "fuss", "component": "Row", "children": ["zurueck", "aktualisieren", "modus_knopf", "schliessen"], "gap": 8, "wrap": True},
        {"id": "zurueck", "component": "Button", "text": "Zurück", "icon": "arrow_back", "action": {"event": {"name": "werkzeug_zurueck", "context": {}}}},
        {"id": "aktualisieren", "component": "Button", "text": "Aktualisieren", "icon": "refresh", "action": {"event": {"name": "werkzeug_aktualisieren", "context": {}}}},
        {"id": "modus_knopf", "component": "Button", "text": {"path": "/modus_knopf"}, "icon": "open_in_new", "action": {"event": {"name": "werkzeug_modus", "context": {}}}},
        {"id": "schliessen", "component": "Button", "text": "Schließen", "variant": "borderless", "action": {"event": {"name": "werkzeug_schliessen", "context": {}}}},
    ]


def vorlage_terminal(titel: str) -> list[dict[str, Any]]:
    return [
        {"id": "root", "component": "Column", "children": ["titel", "statuszeile", "schritte", "formular", "fuss"], "gap": 10},
        {"id": "titel", "component": "Text", "text": titel, "variant": "h3"},
        {"id": "statuszeile", "component": "Row", "children": ["status", "hinweis"], "gap": 8, "align": "center"},
        {"id": "status", "component": "Badge", "text": {"path": "/status"}, "ton": "info"},
        {"id": "hinweis", "component": "Text", "text": {"path": "/hinweis"}, "variant": "caption", "ton": "dezent"},
        {"id": "schritte", "component": "List", "children": {"path": "/schritte", "componentId": "schritt"}, "gap": 6},
        {"id": "schritt", "component": "Card", "child": "schritt_inhalt"},
        {"id": "schritt_inhalt", "component": "Column", "children": ["schritt_kopf", "schritt_ergebnis"], "gap": 4},
        {"id": "schritt_kopf", "component": "Row", "children": ["schritt_text", "schritt_zustand"], "gap": 8, "justify": "spaceBetween"},
        {"id": "schritt_text", "component": "Text", "text": {"path": "text"}, "variant": "h5"},
        {"id": "schritt_zustand", "component": "Badge", "text": {"path": "zustand"}, "ton": "info"},
        {"id": "schritt_ergebnis", "component": "Text", "text": {"path": "ergebnis"}, "variant": "caption"},
        {
            "id": "formular",
            "component": "Formular",
            "schema": {"type": "object", "properties": {"befehl": {"type": "string", "title": "Befehl"}}, "required": ["befehl"]},
            "value": {"path": "/eingabe"},
            "absenden": "Ausführen",
            "action": {"event": {"name": "werkzeug_befehl", "context": {}}},
        },
        {"id": "fuss", "component": "Row", "children": ["schliessen"], "gap": 8, "justify": "end"},
        {"id": "schliessen", "component": "Button", "text": "Schließen", "variant": "borderless", "action": {"event": {"name": "werkzeug_schliessen", "context": {}}}},
    ]


def vorlage_schritte(titel: str) -> list[dict[str, Any]]:
    komponenten = vorlage_terminal(titel)
    return [
        {**k, "children": [c for c in k["children"] if c != "formular"]} if k["id"] == "root" else k
        for k in komponenten
        if k["id"] != "formular"
    ]


class Werkzeugflaechen:
    def __init__(self, manager: Any, register: Any, integrationen: Any, werkzeug_ausfuehren: WerkzeugAusfuehren):
        self.manager = manager
        self.register = register
        self.integrationen = integrationen
        self._werkzeug = werkzeug_ausfuehren
        #: offene Werkzeugflächen je Kennung
        self.offen: dict[str, dict[str, Any]] = {}
        self._bild_tasks: dict[str, asyncio.Task[None]] = {}
        self._aufgaben: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ Definitionen
    def definitionen(self) -> dict[str, dict[str, Any]]:
        defs: dict[str, dict[str, Any]] = {}
        for k, v in EINGEBAUTE.items():
            defs[k] = {**v, "kennung": k, "praefix": "", "katalog": None, "veraendernd": [], "bild": None, "adresse": None}
        if self.integrationen is not None:
            for konfig in self.integrationen.konfigs.values():
                eintrag = self.integrationen.katalog.holen(konfig.katalog) if konfig.katalog else None
                if eintrag is None or eintrag.buehne is None or not konfig.aktiv:
                    continue
                b = eintrag.buehne
                defs[konfig.id] = {
                    "kennung": konfig.id,
                    "katalog": eintrag.id,
                    "titel": b.titel or eintrag.name,
                    "symbol": b.symbol or eintrag.icon,
                    "art": b.art,
                    "bild": b.bild,
                    "adresse": b.adresse,
                    "navigieren": b.navigieren,
                    "zurueck": b.zurueck,
                    "veraendernd": list(b.veraendernd),
                    "unsichtbar_schalter": b.unsichtbar_schalter,
                    "praefix": f"{konfig.id}__",
                    "werkzeuge": [],
                }
        return defs

    def _finden(self, kennung: str) -> dict[str, Any]:
        defs = self.definitionen()
        gesucht = (kennung or "").strip().lower()
        for d in defs.values():
            if gesucht in (d["kennung"].lower(), str(d.get("katalog") or "").lower(), str(d["titel"]).lower()):
                return d
        raise WerkzeugflaechenFehler(f"Keine Werkzeugfläche „{kennung}“. Verfügbar: " + ", ".join(sorted(defs)) + ".")

    def _fuer_werkzeug(self, name: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        for kennung, z in self.offen.items():
            d = z["definition"]
            if (d["praefix"] and name.startswith(d["praefix"])) or name in d.get("werkzeuge", []):
                return d, z
        return None

    @staticmethod
    def _kurzname(d: dict[str, Any], name: str) -> str:
        return name[len(d["praefix"]) :] if d["praefix"] and name.startswith(d["praefix"]) else name

    # ------------------------------------------------------------------ Modus (Bühne ⇄ Fenster)
    def _konfig(self, d: dict[str, Any]) -> Any:
        if self.integrationen is None or not d.get("katalog"):
            return None
        return self.integrationen.konfigs.get(d["kennung"])

    def modus_aktuell(self, d: dict[str, Any]) -> str | None:
        konfig = self._konfig(d)
        schalter = d.get("unsichtbar_schalter")
        if konfig is None or not schalter:
            return None
        return "buehne" if schalter in (konfig.befehl or []) else "fenster"

    async def modus_setzen(self, d: dict[str, Any], modus: str) -> bool:
        """Schalter in der Integrationskonfiguration setzen/entfernen und neu verbinden; True, wenn sich etwas änderte."""
        if modus not in ("buehne", "fenster"):
            raise WerkzeugflaechenFehler("modus muss „buehne“ oder „fenster“ sein.")
        konfig = self._konfig(d)
        schalter = d.get("unsichtbar_schalter")
        if konfig is None or not schalter or not konfig.befehl:
            raise WerkzeugflaechenFehler(f"„{d['titel']}“ kennt keinen Fenster-Modus.")
        if self.modus_aktuell(d) == modus:
            return False
        befehl = [t for t in konfig.befehl if t != schalter]
        if modus == "buehne":
            befehl.append(schalter)
        konfig.befehl = befehl
        self.integrationen.speichern()
        await self.integrationen.neu_verbinden(konfig.id)
        return True

    # ------------------------------------------------------------------ Öffnen / Schließen
    async def oeffnen(self, kennung: str, modus: str | None = None) -> dict[str, Any]:
        d = self._finden(kennung)
        konfig = self._konfig(d)
        if konfig is not None:
            status = self.integrationen.status.get(konfig.id)
            if status != "verbunden" and not (modus or d.get("unsichtbar_schalter")):
                raise WerkzeugflaechenFehler(f"„{d['titel']}“ ist nicht verbunden ({status or 'aus'}): {self.integrationen.fehler.get(konfig.id) or 'Integration prüfen.'}")
        elif not any(self.register.holen(w) for w in d.get("werkzeuge", [])):
            raise WerkzeugflaechenFehler(f"Werkzeuge für „{d['titel']}“ sind nicht verfügbar.")
        existierte = d["kennung"] in self.offen
        z = self.offen.get(d["kennung"]) or {
            "surfaceId": f"werkzeug-{d['kennung']}",
            "schritte": [],
            "adresse": "",
            "bild": None,
            "status": "bereit",
            "hinweis": "",
            "eingabe": {},
        }
        z["definition"] = d
        self.offen[d["kennung"]] = z
        if d.get("unsichtbar_schalter") and konfig is not None:
            # Standard ist die Bühne (unsichtbar); eine schon offene Fläche behält ihren Modus
            ziel = modus or ((self.modus_aktuell(d) or "buehne") if existierte else "buehne")
            try:
                if await self.modus_setzen(d, ziel):
                    self._schritt_hinzu(z, f"Modus: {'Fenster' if ziel == 'fenster' else 'Bühne'} (Browser neu gestartet)", "ok")
            except WerkzeugflaechenFehler:
                pass
            status = self.integrationen.status.get(konfig.id)
            if status != "verbunden":
                raise WerkzeugflaechenFehler(f"„{d['titel']}“ ist nicht verbunden ({status or 'aus'}): {self.integrationen.fehler.get(konfig.id) or 'Integration prüfen.'}")
        await self._flaeche_senden(z)
        return {"surfaceId": z["surfaceId"], "titel": d["titel"], "art": d["art"], "modus": self.modus_aktuell(d)}

    async def schliessen(self, kennung: str) -> dict[str, Any]:
        d = self._finden(kennung)
        z = self.offen.pop(d["kennung"], None)
        if z is None:
            return {"geschlossen": []}
        task = self._bild_tasks.pop(d["kennung"], None)
        if task and not task.done():
            task.cancel()
        geschlossen = await self.manager.schliessen(z["surfaceId"])
        return {"geschlossen": geschlossen}

    def vergessen(self, surface_id: str) -> None:
        """Fläche wurde anderswo geschlossen (Reiter, REST)."""
        for kennung, z in list(self.offen.items()):
            if z["surfaceId"] == surface_id:
                self.offen.pop(kennung, None)
                task = self._bild_tasks.pop(kennung, None)
                if task and not task.done():
                    task.cancel()

    # ------------------------------------------------------------------ Darstellung
    def _komponenten(self, d: dict[str, Any]) -> list[dict[str, Any]]:
        if d["art"] == "live":
            return vorlage_live()
        if d["art"] == "terminal":
            return vorlage_terminal(d["titel"])
        return vorlage_schritte(d["titel"])

    def _daten(self, z: dict[str, Any]) -> dict[str, Any]:
        d = z["definition"]
        modus = self.modus_aktuell(d)
        return {
            "adresse": z.get("adresse") or "",
            "bild": z.get("bild"),
            "status": z.get("status") or "bereit",
            "hinweis": z.get("hinweis") or "",
            "modus_text": {"buehne": "Bühne", "fenster": "Fenster"}.get(modus or "", ""),
            "modus_knopf": "Im Fenster zeigen" if modus == "buehne" else "Auf der Bühne zeigen",
            "schritte": list(z.get("schritte") or []),
            "anzahl": len(z.get("schritte") or []),
            "eingabe": z.get("eingabe") or {},
        }

    async def _flaeche_senden(self, z: dict[str, Any]) -> None:
        d = z["definition"]
        stil = self.manager.stil_fuer(None, d["kennung"], None)
        flaeche = await self.manager._flaeche_senden(z["surfaceId"], d["titel"], stil, self._komponenten(d), self._daten(z), None, art="werkzeug", symbol=d.get("symbol"))
        flaeche["werkzeug"] = d["kennung"]
        self.manager._speichern()

    async def _daten_senden(self, z: dict[str, Any]) -> None:
        if z["surfaceId"] in self.manager.flaechen:
            await self.manager.daten_setzen(z["surfaceId"], daten=self._daten(z))

    def _schritt_hinzu(self, z: dict[str, Any], text: str, zustand: str, kennung: str | None = None, ergebnis: str = "") -> dict[str, Any]:
        schritt = {"id": kennung or f"s{len(z['schritte']) + 1}", "nr": f"{len(z['schritte']) + 1}.", "zeit": _zeit(), "text": text, "zustand": zustand, "ergebnis": ergebnis}
        z["schritte"].append(schritt)
        if len(z["schritte"]) > MAX_SCHRITTE:
            del z["schritte"][: len(z["schritte"]) - MAX_SCHRITTE]
        return schritt

    # ------------------------------------------------------------------ Hörer auf Werkzeugereignisse
    async def ereignis(self, e: dict[str, Any]) -> None:
        try:
            typ = e.get("typ")
            if typ == "werkzeug_start":
                await self._start(e)
            elif typ == "werkzeug_ende":
                await self._ende(e)
        except Exception:  # noqa: BLE001 - die Bühne darf den Agenten nie stören
            log.exception("Werkzeugfläche: Ereignis nicht verarbeitet")

    def _ist_hilfsaufruf(self, d: dict[str, Any], e: dict[str, Any]) -> bool:
        return str(e.get("id") or "").startswith("buehne_") and bool(d.get("bild")) and self._kurzname(d, str(e.get("name") or "")) == d["bild"]

    async def _start(self, e: dict[str, Any]) -> None:
        name = str(e.get("name") or "")
        treffer = self._fuer_werkzeug(name)
        if treffer is None:
            return
        d, z = treffer
        if self._ist_hilfsaufruf(d, e):
            return
        kurz = self._kurzname(d, name)
        argumente = e.get("argumente") if isinstance(e.get("argumente"), dict) else {}
        if d.get("adresse") and isinstance(argumente.get(d["adresse"]), str):
            z["adresse"] = argumente[d["adresse"]]
        text = kurz + (f" ({_argumente_kurz(argumente)})" if argumente else "")
        self._schritt_hinzu(z, text, "läuft", kennung=str(e.get("id") or ""))
        z["status"] = "läuft"
        await self._daten_senden(z)

    async def _ende(self, e: dict[str, Any]) -> None:
        kennung = str(e.get("id") or "")
        for z in self.offen.values():
            d = z["definition"]
            schritt = next((s for s in z["schritte"] if s["id"] == kennung), None)
            if schritt is None:
                continue
            ok = bool(e.get("ok"))
            schritt["zustand"] = "ok" if ok else "fehler"
            schritt["ergebnis"] = _kurz(e.get("ergebnis") or "", MAX_ERGEBNIS)
            z["status"] = "bereit" if ok else "fehler"
            z["hinweis"] = "" if ok else schritt["ergebnis"][:200]
            kurz = schritt["text"].split(" (", 1)[0]
            if ok and d["art"] == "live" and d.get("bild") and (not d.get("veraendernd") or kurz in d["veraendernd"]):
                self.bild_anfordern(d, z)
            await self._daten_senden(z)
            return

    # ------------------------------------------------------------------ Bild
    def bild_anfordern(self, d: dict[str, Any], z: dict[str, Any]) -> None:
        if not d.get("bild"):
            return
        laufend = self._bild_tasks.get(d["kennung"])
        if laufend and not laufend.done():
            z["bild_erneut"] = True
            return
        task = asyncio.create_task(self._bild_holen(d, z))
        self._bild_tasks[d["kennung"]] = task

    async def _bild_holen(self, d: dict[str, Any], z: dict[str, Any]) -> None:
        name = f"{d['praefix']}{d['bild']}"
        while True:
            z["bild_erneut"] = False
            try:
                text = await self._werkzeug(name, {})
                w = self.register.holen(name)
                bild = w.letztes_bild() if w is not None and hasattr(w, "letztes_bild") else None
                if bild is None and isinstance(text, str) and text.startswith("data:image/"):
                    bild = text.strip()
                if bild:
                    z["bild"] = bild
                    z["hinweis"] = ""
                else:
                    z["hinweis"] = "Kein Bild erhalten" if not str(text).startswith("FEHLER") else _kurz(text, 200)
            except Exception as exc:  # noqa: BLE001
                z["hinweis"] = f"Bild nicht geholt: {exc}"[:200]
            if d["kennung"] in self.offen:
                await self._daten_senden(z)
            if not z.get("bild_erneut") or d["kennung"] not in self.offen:
                break

    # ------------------------------------------------------------------ Aktionen der Fläche
    async def aktion(self, flaeche: dict[str, Any], name: str, context: dict[str, Any]) -> dict[str, Any]:
        kennung = str(flaeche.get("werkzeug") or "")
        z = self.offen.get(kennung)
        if z is None:
            raise WerkzeugflaechenFehler(f"Werkzeugfläche „{kennung}“ ist nicht offen.")
        d = z["definition"]
        if name == "werkzeug_schliessen":
            return await self.schliessen(kennung)
        if name == "werkzeug_aktualisieren":
            if not d.get("bild"):
                raise WerkzeugflaechenFehler("Diese Fläche hat kein Bild.")
            self.bild_anfordern(d, z)
            return {"ok": True, "aktion": name}
        if name == "werkzeug_modus":
            neu = "fenster" if self.modus_aktuell(d) == "buehne" else "buehne"
            await self.modus_setzen(d, neu)
            self._schritt_hinzu(z, f"Modus: {'Fenster' if neu == 'fenster' else 'Bühne'} (Browser neu gestartet)", "ok")
            await self._daten_senden(z)
            if z.get("adresse") and d.get("navigieren"):
                self._im_hintergrund(self._werkzeug(f"{d['praefix']}{d['navigieren']}", {d.get("adresse") or "url": z["adresse"]}))
            return {"ok": True, "aktion": name, "modus": neu}
        if name == "werkzeug_oeffnen_url":
            url = str(context.get("url") or z.get("adresse") or "").strip()
            if not url:
                raise WerkzeugflaechenFehler("Keine Adresse angegeben.")
            if not url.lower().startswith(("http://", "https://")):
                url = "https://" + url
            if not d.get("navigieren"):
                raise WerkzeugflaechenFehler("Diese Fläche kann keine Adresse öffnen.")
            z["adresse"] = url
            self._im_hintergrund(self._werkzeug(f"{d['praefix']}{d['navigieren']}", {d.get("adresse") or "url": url}))
            return {"ok": True, "aktion": name, "url": url}
        if name == "werkzeug_zurueck":
            if not d.get("zurueck"):
                raise WerkzeugflaechenFehler("Diese Fläche kennt kein Zurück.")
            self._im_hintergrund(self._werkzeug(f"{d['praefix']}{d['zurueck']}", {}))
            return {"ok": True, "aktion": name}
        if name == "werkzeug_befehl":
            werte = context.get("werte") if isinstance(context.get("werte"), dict) else context
            befehl = str(werte.get(d.get("befehl_argument") or "befehl") or "").strip()
            if not befehl or not d.get("befehl_werkzeug"):
                raise WerkzeugflaechenFehler("Kein Befehl angegeben.")
            z["eingabe"] = {}
            self._im_hintergrund(self._werkzeug(d["befehl_werkzeug"], {d.get("befehl_argument") or "befehl": befehl}))
            return {"ok": True, "aktion": name}
        raise WerkzeugflaechenFehler(f"Unbekannte Aktion „{name}“ für eine Werkzeugfläche.")

    def _im_hintergrund(self, aufruf: Awaitable[Any]) -> None:
        """Werkzeug im Hintergrund ausführen (Freigaben können warten); Schritte kommen über die Ereignisse."""
        task = asyncio.create_task(self._abwarten(aufruf))
        self._aufgaben.add(task)
        task.add_done_callback(self._aufgaben.discard)

    @staticmethod
    async def _abwarten(aufruf: Awaitable[Any]) -> None:
        try:
            await aufruf
        except Exception:  # noqa: BLE001
            log.exception("Werkzeugfläche: Aktion fehlgeschlagen")

    # ------------------------------------------------------------------ Prompt
    def prompt_zeilen(self) -> list[str]:
        defs = self.definitionen()
        if not defs:
            return []
        namen = ", ".join(f"{d['kennung']} („{d['titel']}“)" for d in defs.values())
        zeilen = [
            "Werkzeugflächen (nur auf Kommando des Nutzers, z. B. „Browser: …“, „Shell: …“, „öffne das Terminal“): "
            f"{namen}. Dann zuerst buehne_werkzeug_oeffnen(werkzeug), danach die Schritte mit den Werkzeugen dieser Integration ausführen – "
            "sie erscheinen auf der Fläche. „im Fenster“/„sichtbar“ = modus fenster, sonst Bühne. Ohne Kommando bleibt die Bühne unberührt. "
            "Schließen auf Wunsch mit buehne_werkzeug_schliessen."
        ]
        if self.offen:
            zeilen.append("Offene Werkzeugflächen: " + ", ".join(f"{k} (Fläche {z['surfaceId']})" for k, z in self.offen.items()))
        return zeilen
