"""FastAPI-Server: REST (/api) und WebSocket (/ws) gemäß VERTRAEGE.md, nur 127.0.0.1.

Liefert die Oberfläche aus oberflaeche/dist statisch aus (mit SPA-Fallback), falls vorhanden.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import ValidationError

from .anwendung import Jarvis
from .buehne.manager import BuehnenFehler
from .integrationen.einrichtung import Ausfuehrer, EinrichtungsFehler, datei_ablegen, einrichtung_stand
from .integrationen.manager import FehlendeWerte, IntegrationsFehler
from .integrationen.verzeichnisse import VerzeichnisFehler
from .llm import LLMFehler

log = logging.getLogger("jarvis.server")

# Vite-Entwicklung (5173–5179) und Vorschau (4173) auf localhost/127.0.0.1
CORS_REGEX = r"^http://(localhost|127\.0\.0\.1):(517\d|4173)$"
_GEHEIMNIS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,100}$")


def oberflaeche_pfad() -> Path:
    if os.environ.get("JARVIS_OBERFLAECHE"):
        return Path(os.environ["JARVIS_OBERFLAECHE"]).expanduser()
    return Path(__file__).resolve().parents[2] / "oberflaeche" / "dist"


# Feste MIME-Typen für die Vite-Ausgabe. Pythons mimetypes liest unter Windows die Registry und
# liefert für .js dort häufig „text/plain“ – Browser verweigern dann das Modul-Skript und die
# Oberfläche bleibt schwarz. Unter Linux hängt das Ergebnis von /etc/mime.types ab.
MIME_TYPEN = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".wasm": "application/wasm",
    ".webmanifest": "application/manifest+json",
    ".txt": "text/plain",
}


def mime_typ(pfad: Path) -> str | None:
    return MIME_TYPEN.get(pfad.suffix.lower())


# Nur diese Host-Namen werden akzeptiert (Schutz gegen DNS-Rebinding: eine fremde Domain, die auf
# 127.0.0.1 zeigt, hätte sonst Lesezugriff auf Verlauf, Gedächtnis und Einstellungen).
ERLAUBTE_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})


def host_erlaubt(host: str | None, erlaubt: frozenset[str] = ERLAUBTE_HOSTS) -> bool:
    if not host:
        return False
    host = host.strip().lower()
    if host.startswith("["):  # IPv6 mit Port: [::1]:8765
        name = host.split("]", 1)[0] + "]"
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name in erlaubt


def herkunft_erlaubt(herkunft: str | None, port: int, host: str | None = None) -> bool:
    """Erlaubt Anfragen ohne Origin (CLI, curl) sowie von der eigenen Oberfläche und Vite.

    `host` (bereits per host_erlaubt geprüft) erlaubt die gleiche Herkunft auch dann, wenn der
    Server mit `jarvis start --port …` auf einem anderen Port als in den Einstellungen läuft.
    """
    if not herkunft:
        return True
    if re.match(CORS_REGEX, herkunft):
        return True
    if host and host_erlaubt(host) and herkunft.lower() == f"http://{host.lower()}":
        return True
    return herkunft in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")


class WebSocketVerteiler:
    def __init__(self) -> None:
        self.verbindungen: set[WebSocket] = set()

    async def senden(self, ereignis: dict[str, Any]) -> None:
        tot = []
        for ws in list(self.verbindungen):
            try:
                await ws.send_json(ereignis)
            except Exception:  # noqa: BLE001
                tot.append(ws)
        for ws in tot:
            self.verbindungen.discard(ws)


_WECKWORT_FELDER = ("weckwort", "weckwort_engine", "weckwort_varianten", "weckwort_modell_pfad", "vosk_modell", "modell_verzeichnis")


def _weckwort_schluessel(stimme: Any) -> tuple:
    daten = stimme.model_dump() if hasattr(stimme, "model_dump") else dict(stimme or {})
    return tuple(repr(daten.get(f)) for f in _WECKWORT_FELDER)


def create_app(
    jarvis: Jarvis | None = None,
    *,
    integrationen_starten: bool = True,
    stimme_starten: bool = True,
    zusaetzliche_hosts: set[str] | None = None,
) -> FastAPI:
    verteiler = WebSocketVerteiler()
    erlaubte_hosts = ERLAUBTE_HOSTS | frozenset(h.lower() for h in (zusaetzliche_hosts or set()))

    @asynccontextmanager
    async def lebenszyklus(app: FastAPI) -> AsyncIterator[None]:
        j = jarvis or Jarvis()
        app.state.jarvis = j
        j.hoerer_hinzufuegen(verteiler.senden)
        await j.starten(integrationen=integrationen_starten, stimme=stimme_starten)
        try:
            yield
        finally:
            j.hoerer_entfernen(verteiler.senden)
            await j.stoppen()

    app = FastAPI(title="Jarvis", version="0.1.0", lifespan=lebenszyklus)
    app.state.verteiler = verteiler
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=CORS_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    def j_(request: Request | WebSocket) -> Jarvis:
        return request.app.state.jarvis

    @app.middleware("http")
    async def herkunft_pruefen(request: Request, call_next: Any) -> Any:
        if not host_erlaubt(request.headers.get("host"), erlaubte_hosts):
            return JSONResponse({"detail": "Host nicht erlaubt"}, status_code=421)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api"):
            port = getattr(request.app.state, "jarvis", None)
            port_nr = port.einstellungen.port if port else 8765
            if not herkunft_erlaubt(request.headers.get("origin"), port_nr, request.headers.get("host")):
                return JSONResponse({"detail": "Herkunft nicht erlaubt"}, status_code=403)
        return await call_next(request)

    # ------------------------------------------------------------------ REST
    @app.get("/api/status")
    async def status(request: Request) -> dict[str, Any]:
        return j_(request).status()

    @app.get("/api/modelle")
    async def modelle(request: Request, anbieter: str | None = None, neu: bool = False) -> dict[str, Any]:
        try:
            return await j_(request).llm.modelle_uebersicht(anbieter or None, neu=neu)
        except LLMFehler as e:
            raise HTTPException(404, str(e)) from e

    @app.put("/api/modelle")
    async def modell_setzen(request: Request, daten: dict[str, Any] = Body(...)) -> dict[str, Any]:
        modell = str(daten.get("modell") or "").strip()
        if not modell:
            raise HTTPException(400, "Feld 'modell' fehlt")
        j_(request).konfig.aktualisieren({"modell": modell})
        return {"aktuell": modell}

    @app.get("/api/einstellungen")
    async def einstellungen_lesen(request: Request) -> dict[str, Any]:
        j = j_(request)
        daten = j.einstellungen.model_dump()
        daten["geheimnisse_gesetzt"] = j.geheimnisse.namen()
        return daten

    @app.put("/api/einstellungen")
    async def einstellungen_setzen(request: Request, teil: dict[str, Any] = Body(...)) -> dict[str, Any]:
        j = j_(request)
        teil.pop("geheimnisse_gesetzt", None)
        stimme_vorher = j.einstellungen.stimme.aktiv
        weckwort_vorher = _weckwort_schluessel(j.einstellungen.stimme)
        try:
            j.konfig.aktualisieren(teil)
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e
        if j.einstellungen.stimme.aktiv != stimme_vorher:
            await j.stimme_schalten(j.einstellungen.stimme.aktiv)
        elif _weckwort_schluessel(j.einstellungen.stimme) != weckwort_vorher:
            await j.stimme_neu_starten()  # neues Weckwort/Engine sofort wirksam
        return j.einstellungen.model_dump()

    @app.put("/api/geheimnisse/{name}")
    async def geheimnis_setzen(name: str, request: Request, daten: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if not _GEHEIMNIS_NAME.match(name):
            raise HTTPException(400, "Ungültiger Name")
        wert = daten.get("wert")
        if not isinstance(wert, str) or not wert:
            raise HTTPException(400, "Feld 'wert' fehlt")
        j = j_(request)
        j.geheimnisse.setzen(name, wert)
        os.environ[name] = wert
        j.llm.modelllisten_vergessen()  # Modelllisten mit dem neuen Schlüssel neu laden
        return {"name": name, "gespeichert": True}

    @app.get("/api/werkzeuge")
    async def werkzeuge(request: Request) -> list[dict[str, Any]]:
        return j_(request).register.infos()

    @app.get("/api/integrationen")
    async def integrationen(request: Request) -> list[dict[str, Any]]:
        return j_(request).manager.liste()

    @app.get("/api/integrationen/katalog")
    async def katalog(request: Request) -> list[dict[str, Any]]:
        return [e.als_info() for e in j_(request).katalog.alle()]

    def _fehlende_werte(e: FehlendeWerte) -> JSONResponse:
        return JSONResponse(
            {
                "detail": str(e),
                "fehlend": [{"name": b.name, "titel": b.titel, "geheim": b.geheim} for b in e.fehlend],
                "hinweis": e.hinweis,
            },
            status_code=400,
        )

    @app.post("/api/integrationen")
    async def integration_hinzufuegen(request: Request, anfrage: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return await j_(request).manager.hinzufuegen(anfrage)
        except FehlendeWerte as e:
            return _fehlende_werte(e)  # type: ignore[return-value]
        except IntegrationsFehler as e:
            raise HTTPException(400, str(e)) from e

    # ---------- Verzeichnisse (Phase 2b): Suche in MCP-Registry, Smithery, eigenen Registries ----------
    @app.get("/api/verzeichnisse")
    async def verzeichnisse(request: Request) -> list[dict[str, Any]]:
        return j_(request).verzeichnisse.quellen_info()

    @app.get("/api/verzeichnisse/suche")
    async def verzeichnis_suche(request: Request, q: str = "", quelle: str | None = None, limit: int = 8) -> dict[str, Any]:
        try:
            return await j_(request).verzeichnisse.suchen(q, quelle or None, max(1, min(limit, 25)))
        except VerzeichnisFehler as e:
            raise HTTPException(400, str(e)) from e

    @app.post("/api/verzeichnisse/installieren")
    async def verzeichnis_installieren(request: Request, anfrage: dict[str, Any] = Body(...)) -> dict[str, Any]:
        j = j_(request)
        try:
            form = await j.verzeichnisse.anfrage(
                str(anfrage.get("quelle") or ""), str(anfrage.get("kennung") or ""),
                anfrage.get("werte") or {}, anfrage.get("name") or None,
            )
            return await j.manager.hinzufuegen(form)
        except FehlendeWerte as e:
            return _fehlende_werte(e)  # type: ignore[return-value]
        except (VerzeichnisFehler, IntegrationsFehler) as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/verzeichnisse/{quelle}/{kennung:path}")
    async def verzeichnis_details(quelle: str, kennung: str, request: Request) -> dict[str, Any]:
        try:
            treffer = await j_(request).verzeichnisse.details(quelle, kennung)
        except VerzeichnisFehler as e:
            raise HTTPException(404 if "nicht" in str(e) else 400, str(e)) from e
        return treffer.model_dump()

    ausfuehrer = Ausfuehrer()

    def katalog_eintrag(request: Request, kennung: str) -> Any:
        eintrag = j_(request).katalog.holen(kennung)
        if eintrag is None:
            raise HTTPException(404, "Katalogeintrag nicht gefunden")
        return eintrag

    @app.get("/api/integrationen/katalog/{kennung}")
    async def katalog_detail(kennung: str, request: Request) -> dict[str, Any]:
        eintrag = katalog_eintrag(request, kennung)
        return {**eintrag.als_info(), "einrichtung": einrichtung_stand(eintrag), "installiert": kennung in j_(request).manager.konfigs}

    @app.post("/api/integrationen/katalog/{kennung}/einrichtung/{nummer}/datei")
    async def einrichtung_datei(kennung: str, nummer: int, request: Request, daten: dict[str, Any] = Body(...)) -> dict[str, Any]:
        eintrag = katalog_eintrag(request, kennung)
        try:
            pfad = datei_ablegen(eintrag, nummer, str(daten.get("inhalt_base64") or ""))
        except EinrichtungsFehler as e:
            raise HTTPException(400, str(e)) from e
        return {"pfad": str(pfad), "erfuellt": True, "einrichtung": einrichtung_stand(eintrag)}

    @app.post("/api/integrationen/katalog/{kennung}/einrichtung/{nummer}/ausfuehren")
    async def einrichtung_ausfuehren(kennung: str, nummer: int, request: Request) -> dict[str, Any]:
        eintrag = katalog_eintrag(request, kennung)
        try:
            return await ausfuehrer.starten(eintrag, nummer)
        except EinrichtungsFehler as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/integrationen/katalog/{kennung}/einrichtung/{nummer}/stand")
    async def einrichtung_stand_lesen(kennung: str, nummer: int, request: Request) -> dict[str, Any]:
        katalog_eintrag(request, kennung)
        return ausfuehrer.stand(kennung, nummer)

    @app.get("/api/integrationen/{kennung}")
    async def integration_details(kennung: str, request: Request) -> dict[str, Any]:
        try:
            return j_(request).manager.details(kennung)
        except IntegrationsFehler as e:
            raise HTTPException(404, str(e)) from e

    @app.put("/api/integrationen/{kennung}")
    async def integration_aendern(kennung: str, request: Request, anfrage: dict[str, Any] = Body(...)) -> dict[str, Any]:
        manager = j_(request).manager
        if kennung not in manager.konfigs:
            raise HTTPException(404, "Integration nicht gefunden")
        try:
            return await manager.aendern(kennung, anfrage)
        except FehlendeWerte as e:
            return JSONResponse(  # type: ignore[return-value]
                {"detail": str(e), "fehlend": [{"name": b.name, "titel": b.titel, "geheim": b.geheim} for b in e.fehlend], "hinweis": e.hinweis},
                status_code=400,
            )
        except IntegrationsFehler as e:
            raise HTTPException(400, str(e)) from e

    @app.put("/api/integrationen/{kennung}/bereich")
    async def integration_bereich(kennung: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return await j_(request).manager.bereich_setzen(kennung, str(body.get("bereich") or ""))
        except IntegrationsFehler as e:
            raise HTTPException(404 if "nicht installiert" in str(e) else 400, str(e)) from e

    @app.post("/api/integrationen/{kennung}/abmelden")
    async def integration_abmelden(kennung: str, request: Request) -> dict[str, Any]:
        try:
            return await j_(request).manager.abmelden(kennung)
        except IntegrationsFehler as e:
            raise HTTPException(404, str(e)) from e

    @app.post("/api/integrationen/{kennung}/anmelden")
    async def integration_anmelden(kennung: str, request: Request) -> dict[str, Any]:
        try:
            return await j_(request).manager.neu_verbinden(kennung)
        except IntegrationsFehler as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/oauth/rueckruf", response_class=HTMLResponse)
    async def oauth_rueckruf(request: Request) -> HTMLResponse:
        """Rückruf des Autorisierungsservers nach der Anmeldung im Browser (GET, nur state/code)."""
        parameter = {k: v for k, v in request.query_params.items()}
        gefunden = j_(request).manager.rueckrufe.erfuellen(parameter)
        name = j_(request).name
        if parameter.get("error"):
            titel, text = "Anmeldung abgelehnt", f"{parameter.get('error')}: {parameter.get('error_description', '')}"
        elif gefunden:
            titel, text = "Anmeldung abgeschlossen", f"Dieses Fenster kann geschlossen werden – {name} verbindet sich jetzt."
        else:
            titel, text = "Keine wartende Anmeldung", "Bitte die Anmeldung in der Oberfläche erneut starten."
        html = (
            "<!doctype html><html lang='de'><meta charset='utf-8'><title>" + titel + "</title>"
            "<body style='font-family:system-ui;background:#06121d;color:#dbe9f2;display:grid;place-items:center;height:100vh;margin:0'>"
            "<div style='text-align:center'><h1 style='font-weight:500'>" + titel + "</h1><p>" + text + "</p></div></body></html>"
        )
        return HTMLResponse(html, status_code=200 if gefunden or parameter.get("error") else 404)

    @app.get("/api/integrationen/{kennung}/protokoll")
    async def integration_protokoll(kennung: str, request: Request, zeilen: int = 50) -> dict[str, Any]:
        manager = j_(request).manager
        if kennung not in manager.konfigs:
            raise HTTPException(404, "Integration nicht gefunden")
        return {"zeilen": manager.protokoll_zeilen(kennung, zeilen)}

    @app.delete("/api/integrationen/{kennung}")
    async def integration_entfernen(kennung: str, request: Request) -> dict[str, Any]:
        if not await j_(request).manager.entfernen(kennung):
            raise HTTPException(404, "Integration nicht gefunden")
        return {"id": kennung, "entfernt": True}

    @app.post("/api/integrationen/{kennung}/neu-verbinden")
    async def integration_neu(kennung: str, request: Request) -> dict[str, Any]:
        try:
            return await j_(request).manager.neu_verbinden(kennung)
        except IntegrationsFehler as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/verlauf")
    async def verlauf(request: Request, limit: int = 50) -> list[dict[str, Any]]:
        return j_(request).gedaechtnis.verlauf(max(1, min(limit, 1000)))

    # ------------------------------------------------------------------ Stimme
    @app.post("/api/stimme/probe")
    async def stimme_probe(request: Request, daten: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        from .stimme.fehler import StimmFehler

        try:
            return await j_(request).stimme_probe(str(daten.get("text") or ""))
        except StimmFehler as e:
            raise HTTPException(400, e.text) from e
        except ImportError as e:
            raise HTTPException(400, f"Sprachmodul nicht verfügbar: {e}") from e

    @app.get("/api/stimme/modelle")
    async def stimme_modelle(request: Request) -> dict[str, Any]:
        return await j_(request).stimme_modelle()

    # ------------------------------------------------------------------ Unterhaltungen
    @app.get("/api/unterhaltungen")
    async def unterhaltungen(request: Request) -> list[dict[str, Any]]:
        return j_(request).gedaechtnis.unterhaltungen()

    @app.post("/api/unterhaltungen")
    async def unterhaltung_neu(request: Request, daten: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        titel = str(daten.get("titel") or "").strip() or None
        try:
            return await j_(request).unterhaltung_neu(titel)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/unterhaltungen/{kennung}")
    async def unterhaltung(kennung: int, request: Request) -> dict[str, Any]:
        u = j_(request).gedaechtnis.unterhaltung(kennung)
        if not u:
            raise HTTPException(404, "Unterhaltung nicht gefunden")
        return u

    @app.put("/api/unterhaltungen/{kennung}")
    async def unterhaltung_umbenennen(kennung: int, request: Request, daten: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return await j_(request).unterhaltung_umbenennen(kennung, str(daten.get("titel") or ""))
        except KeyError as e:
            raise HTTPException(404, "Unterhaltung nicht gefunden") from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.delete("/api/unterhaltungen/{kennung}")
    async def unterhaltung_loeschen(kennung: int, request: Request) -> dict[str, Any]:
        try:
            return await j_(request).unterhaltung_loeschen(kennung)
        except KeyError as e:
            raise HTTPException(404, "Unterhaltung nicht gefunden") from e

    @app.post("/api/unterhaltungen/{kennung}/aktivieren")
    async def unterhaltung_aktivieren(kennung: int, request: Request) -> dict[str, Any]:
        try:
            return await j_(request).unterhaltung_aktivieren(kennung)
        except KeyError as e:
            raise HTTPException(404, "Unterhaltung nicht gefunden") from e

    @app.get("/api/unterhaltungen/{kennung}/verlauf")
    async def unterhaltung_verlauf(kennung: int, request: Request, limit: int = 200) -> list[dict[str, Any]]:
        j = j_(request)
        if not j.gedaechtnis.unterhaltung(kennung):
            raise HTTPException(404, "Unterhaltung nicht gefunden")
        return j.gedaechtnis.verlauf(max(1, min(limit, 1000)), unterhaltung_id=kennung)

    @app.delete("/api/verlauf")
    async def verlauf_loeschen(request: Request) -> dict[str, Any]:
        j_(request).gedaechtnis.verlauf_loeschen()
        return {"geloescht": True}

    @app.get("/api/gedaechtnis")
    async def gedaechtnis(request: Request) -> list[dict[str, Any]]:
        return j_(request).gedaechtnis.erinnerungen()

    @app.delete("/api/gedaechtnis")
    async def gedaechtnis_loeschen(request: Request, id: int | None = None) -> dict[str, Any]:  # noqa: A002
        return {"geloescht": j_(request).gedaechtnis.erinnerung_loeschen(id)}

    # ------------------------------------------------------------------ WebSocket
    # ------------------------------------------------------------------ Bühne
    def buehne_fehler(e: Exception) -> HTTPException:
        if isinstance(e, KeyError):
            return HTTPException(404, f"Unbekannt: {e.args[0] if e.args else e}")
        if isinstance(e, LLMFehler):
            return HTTPException(502, str(e))
        return HTTPException(400, str(e))

    @app.get("/api/buehne")
    async def buehne_zustand(request: Request) -> dict[str, Any]:
        return j_(request).buehne.zustand()

    @app.get("/api/buehne/vorlagen")
    async def buehne_vorlagen(request: Request) -> list[dict[str, Any]]:
        return j_(request).buehne.speicher.vorlagen()

    @app.get("/api/buehne/vorlagen/{kennung}")
    async def buehne_vorlage(kennung: str, request: Request) -> dict[str, Any]:
        v = j_(request).buehne.speicher.vorlage(kennung)
        if v is None:
            raise HTTPException(404, f"Vorlage „{kennung}“ gibt es nicht")
        return v

    @app.put("/api/buehne/vorlagen/{kennung}")
    async def buehne_vorlage_aendern(kennung: str, request: Request, daten: dict[str, Any] = Body(...)) -> dict[str, Any]:
        j = j_(request)
        try:
            v = j.buehne.speicher.vorlage_aendern(kennung, name=daten.get("name"))
            if "stil" in daten:
                v = await j.buehne.stil_der_vorlage(kennung, daten.get("stil"))
            return v
        except (KeyError, BuehnenFehler, ValueError) as e:
            raise buehne_fehler(e) from e

    @app.delete("/api/buehne/vorlagen/{kennung}")
    async def buehne_vorlage_loeschen(kennung: str, request: Request) -> dict[str, Any]:
        j = j_(request)
        await j.buehne.schliessen(kennung)
        return {"geloescht": j.buehne.speicher.vorlage_loeschen(kennung)}

    @app.post("/api/buehne/vorlagen/{kennung}/zurueck")
    async def buehne_vorlage_zurueck(kennung: str, request: Request) -> dict[str, Any]:
        j = j_(request)
        try:
            await j.buehne.zurueck(kennung)
        except (KeyError, BuehnenFehler) as e:
            raise buehne_fehler(e) from e
        return j.buehne.speicher.vorlage(kennung) or {}

    @app.get("/api/buehne/rezepte")
    async def buehne_rezepte(request: Request) -> list[dict[str, Any]]:
        return j_(request).buehne.speicher.rezepte()

    @app.delete("/api/buehne/rezepte/{kennung}")
    async def buehne_rezept_loeschen(kennung: str, request: Request) -> dict[str, Any]:
        speicher = j_(request).buehne.speicher
        for v in speicher.vorlagen():
            for aktion, rezept_id in (v.get("aktionen") or {}).items():
                if rezept_id == kennung:
                    speicher.aktion_setzen(v["id"], aktion, None)
        return {"geloescht": speicher.rezept_loeschen(kennung)}

    @app.get("/api/buehne/stile")
    async def buehne_stile(request: Request) -> list[dict[str, Any]]:
        return j_(request).buehne.speicher.stile()

    @app.post("/api/buehne/stile")
    async def buehne_stil_anlegen(request: Request, daten: dict[str, Any] = Body(...)) -> dict[str, Any]:
        j = j_(request)
        name = str(daten.get("name") or "").strip()
        quelle = daten.get("quelle") if isinstance(daten.get("quelle"), dict) else {}
        art = str(quelle.get("art") or "werte")
        if not name:
            raise HTTPException(400, "name fehlt")
        try:
            if art == "werte":
                vorlage = j.buehne.speicher.stil(str(daten.get("basis") or "javit-dunkel")) or j.buehne.speicher.stil("javit-dunkel") or {}
                neu = json.loads(json.dumps(vorlage))
                neu.update({"id": None, "name": name, "quelle": {"art": "werte"}, "beschreibung": str(daten.get("beschreibung") or "eigener Stil")})
                neu.pop("id")
                neu.pop("eigen", None)
                gespeichert = j.buehne.speicher.stil_speichern(neu)
                return j.buehne.stil_aendern(gespeichert["id"], {"werte": quelle.get("werte") or daten.get("werte") or {}, "vorlieben": daten.get("vorlieben") or {}})
            if art == "datei":
                import base64  # noqa: PLC0415

                inhalt = base64.b64decode(str(quelle.get("inhalt_base64") or "")).decode("utf-8", "replace") if quelle.get("inhalt_base64") else str(quelle.get("inhalt") or "")
                return await j.buehne.stil_ableiten(name, {"art": "datei", "inhalt": inhalt, "wert": str(quelle.get("wert") or "")})
            if art in ("url", "klassen"):
                return await j.buehne.stil_ableiten(name, {"art": art, "wert": str(quelle.get("wert") or "")})
        except (BuehnenFehler, ValueError, LLMFehler) as e:
            raise buehne_fehler(e) from e
        except Exception as e:  # noqa: BLE001 - Netzfehler beim Laden der Quelle
            raise HTTPException(400, f"Quelle konnte nicht gelesen werden: {e}") from e
        raise HTTPException(400, f"Unbekannte Quellenart „{art}“")

    @app.put("/api/buehne/stile/{kennung}")
    async def buehne_stil_aendern(kennung: str, request: Request, daten: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return j_(request).buehne.stil_aendern(kennung, daten, name=daten.get("name"))
        except (BuehnenFehler, ValueError) as e:
            raise buehne_fehler(e) from e

    @app.delete("/api/buehne/stile/{kennung}")
    async def buehne_stil_loeschen(kennung: str, request: Request) -> dict[str, Any]:
        return {"geloescht": j_(request).buehne.speicher.stil_loeschen(kennung)}

    @app.put("/api/buehne/zuordnung")
    async def buehne_zuordnung(request: Request, daten: dict[str, Any] = Body(...)) -> dict[str, str]:
        j = j_(request)
        for integration, stil in daten.items():
            if stil and j.buehne.speicher.stil(str(stil)) is None:
                raise HTTPException(400, f"Stil „{stil}“ gibt es nicht")
        return j.buehne.speicher.zuordnung_setzen({str(k): str(v) for k, v in daten.items() if v})

    @app.post("/api/buehne/aktion")
    async def buehne_aktion(request: Request, daten: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return await j_(request).buehne.aktion(daten)
        except (BuehnenFehler, LLMFehler) as e:
            raise buehne_fehler(e) from e

    @app.delete("/api/buehne/flaechen/{surface_id}")
    async def buehne_flaeche_schliessen(surface_id: str, request: Request) -> dict[str, Any]:
        return {"geschlossen": await j_(request).buehne.schliessen(surface_id)}

    @app.websocket("/ws")
    async def ws_endpunkt(ws: WebSocket) -> None:
        j = j_(ws)
        # Origin-Prüfung im Handshake: Browser senden bei WebSockets immer Origin, CORS greift hier
        # nicht. Ohne diese Prüfung könnte jede Webseite den Assistenten fernsteuern
        # (Cross-Site-WebSocket-Hijacking). Host-Prüfung gegen DNS-Rebinding.
        if not host_erlaubt(ws.headers.get("host"), erlaubte_hosts) or not herkunft_erlaubt(
            ws.headers.get("origin"), j.einstellungen.port, ws.headers.get("host")
        ):
            log.warning("WebSocket abgewiesen (Origin %r, Host %r)", ws.headers.get("origin"), ws.headers.get("host"))
            await ws.close(code=1008)
            return
        await ws.accept()
        verteiler.verbindungen.add(ws)
        aufgaben: set[asyncio.Task[Any]] = set()

        async def sender(daten: Any) -> None:
            """Audio im Browser: JSON-Ereignisse und PCM-Binärframes an genau diese Verbindung."""
            if isinstance(daten, (bytes, bytearray, memoryview)):
                await ws.send_bytes(bytes(daten))
            else:
                await ws.send_json(daten)

        async def buehne_aktion_bearbeiten(daten: dict[str, Any]) -> None:
            try:
                await j.buehne.aktion(daten)
            except BuehnenFehler as e:
                await ws.send_json({"typ": "fehler", "text": str(e)})
            except Exception as e:  # noqa: BLE001
                log.exception("Fehler bei einer Bühnen-Aktion")
                await verteiler.senden({"typ": "fehler", "text": f"Interner Fehler: {e}"})

        async def nachricht_bearbeiten(text: str, sprechen: bool) -> None:
            try:
                await j.anfrage(text, sprechen=sprechen)
            except Exception as e:  # noqa: BLE001
                log.exception("Fehler bei der Anfrage")
                await verteiler.senden({"typ": "fehler", "text": f"Interner Fehler: {e}"})

        try:
            await ws.send_json({"typ": "zustand", "zustand": j.agent.zustand})
            while True:
                nachricht = await ws.receive()
                if nachricht.get("type") == "websocket.disconnect":
                    break
                if nachricht.get("bytes") is not None:
                    j.browser_audio_daten(sender, nachricht["bytes"])
                    continue
                try:
                    daten = json.loads(nachricht.get("text") or "")
                except (ValueError, TypeError):
                    await ws.send_json({"typ": "fehler", "text": "Ungültige Nachricht (kein JSON)"})
                    continue
                if not isinstance(daten, dict):
                    continue
                typ = daten.get("typ")
                if typ == "nachricht":
                    aufgabe = asyncio.create_task(
                        nachricht_bearbeiten(str(daten.get("text") or ""), bool(daten.get("sprechen")))
                    )
                    aufgaben.add(aufgabe)
                    aufgabe.add_done_callback(aufgaben.discard)
                elif typ == "freigabe":
                    await j.agent.freigabe_beantworten(str(daten.get("id")), bool(daten.get("erlaubt")))
                elif typ == "abbrechen":
                    j.agent.abbrechen()
                elif typ == "stimme":
                    await j.stimme_schalten(bool(daten.get("aktiv")))
                elif typ == "zuhoeren":
                    await j.zuhoeren()
                elif typ == "audio_start":
                    try:
                        rate = int(daten.get("rate") or 48000)
                    except (TypeError, ValueError):
                        rate = 48000
                    await j.browser_audio_start(sender, rate)
                elif typ == "audio_stop":
                    await j.browser_audio_stop(sender)
                elif typ == "buehne_aktion":
                    aufgabe = asyncio.create_task(buehne_aktion_bearbeiten(daten))
                    aufgaben.add(aufgabe)
                    aufgabe.add_done_callback(aufgaben.discard)
                elif typ == "buehne_daten":
                    try:
                        await j.buehne.daten_setzen(
                            str(daten.get("surfaceId") or ""), path=str(daten.get("path") or "/"), value=daten.get("value"), melden=False
                        )
                    except BuehnenFehler as e:
                        await ws.send_json({"typ": "fehler", "text": str(e)})
                else:
                    await ws.send_json({"typ": "fehler", "text": f"Unbekannter Nachrichtentyp: {typ}"})
        except WebSocketDisconnect:
            pass
        finally:
            verteiler.verbindungen.discard(ws)
            try:
                await j.browser_audio_stop(sender)
            except Exception:  # noqa: BLE001
                log.debug("Browser-Audio konnte nicht beendet werden", exc_info=True)

    # ------------------------------------------------------------------ Oberfläche
    dist = oberflaeche_pfad()

    @app.get("/{pfad:path}", include_in_schema=False)
    async def oberflaeche(pfad: str) -> Any:
        if pfad.startswith(("api/", "ws")):
            raise HTTPException(404, "Nicht gefunden")
        if not dist.is_dir():
            return JSONResponse(
                {"jarvis": "läuft", "hinweis": f"Oberfläche nicht gebaut ({dist} fehlt). In oberflaeche/: npm run build"},
            )
        datei = (dist / pfad).resolve()
        if pfad and datei.is_file() and dist.resolve() in datei.parents:
            return FileResponse(datei, media_type=mime_typ(datei))
        index = dist / "index.html"
        if index.exists():
            return FileResponse(index, media_type="text/html")
        raise HTTPException(404, "index.html fehlt")

    return app
