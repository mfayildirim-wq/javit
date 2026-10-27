"""FastAPI-Server: REST (/api) und WebSocket (/ws) gemäß VERTRAEGE.md, nur 127.0.0.1.

Liefert die Oberfläche aus oberflaeche/dist statisch aus (mit SPA-Fallback), falls vorhanden.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from .anwendung import Jarvis
from .integrationen.manager import FehlendeWerte, IntegrationsFehler
from .llm import LLMFehler

log = logging.getLogger("jarvis.server")

# Vite-Entwicklung (5173–5179) und Vorschau (4173) auf localhost/127.0.0.1
CORS_REGEX = r"^http://(localhost|127\.0\.0\.1):(517\d|4173)$"
_GEHEIMNIS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,100}$")


def oberflaeche_pfad() -> Path:
    if os.environ.get("JARVIS_OBERFLAECHE"):
        return Path(os.environ["JARVIS_OBERFLAECHE"]).expanduser()
    return Path(__file__).resolve().parents[2] / "oberflaeche" / "dist"


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

    @app.post("/api/integrationen")
    async def integration_hinzufuegen(request: Request, anfrage: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return await j_(request).manager.hinzufuegen(anfrage)
        except FehlendeWerte as e:
            return JSONResponse(  # type: ignore[return-value]
                {
                    "detail": str(e),
                    "fehlend": [{"name": b.name, "titel": b.titel, "geheim": b.geheim} for b in e.fehlend],
                    "hinweis": e.hinweis,
                },
                status_code=400,
            )
        except IntegrationsFehler as e:
            raise HTTPException(400, str(e)) from e

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

        async def nachricht_bearbeiten(text: str, sprechen: bool) -> None:
            try:
                await j.anfrage(text, sprechen=sprechen)
            except Exception as e:  # noqa: BLE001
                log.exception("Fehler bei der Anfrage")
                await verteiler.senden({"typ": "fehler", "text": f"Interner Fehler: {e}"})

        try:
            await ws.send_json({"typ": "zustand", "zustand": j.agent.zustand})
            while True:
                try:
                    daten = await ws.receive_json()
                except (ValueError, KeyError):
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
                else:
                    await ws.send_json({"typ": "fehler", "text": f"Unbekannter Nachrichtentyp: {typ}"})
        except WebSocketDisconnect:
            pass
        finally:
            verteiler.verbindungen.discard(ws)

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
            return FileResponse(datei)
        index = dist / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(404, "index.html fehlt")

    return app
