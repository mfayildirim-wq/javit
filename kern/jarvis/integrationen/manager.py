"""Integrationsmanager: hinzufügen, persistieren (~/.jarvis/integrationen.json), starten,
Status, neu verbinden, entfernen.

Unterstützte Formen (VERTRAEGE.md):
    {"katalog": "spotify", "werte": {...}}
    {"name": "...", "mcp_befehl": "npx -y …", "umgebung": {...}}
    {"name": "...", "mcp_url": "http://…/mcp", "kopfzeilen": {...}}
    {"name": "...", "openapi_url": "https://…/openapi.json", "auth": {"art": "bearer", "wert": "…"}}
    {"name": "...", "rest": [{...}]}
Geheime Werte (API-Schlüssel, Token, Authorization-Kopfzeilen, auth.wert) landen im
Geheimnisspeicher; in der JSON-Datei stehen nur Platzhalter ${NAME}.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from ..geheimnisse import Geheimnisspeicher, ist_geheimer_name
from ..konfig import jarvis_home
from ..werkzeuge import Risiko, Werkzeug, WerkzeugRegister
from ..werkzeuge.prozess import befehl_zerlegen
from .eingebaut import eingebaute_werkzeuge
from .katalog import Benoetigt, Katalog, platzhalter_ersetzen, platzhalter_finden
from .mcp_hub import McpFehler, McpVerbindung, fehler_text, werkzeuge_aus_mcp
from .openapi import basis_url_ermitteln, spec_parsen, werkzeuge_aus_openapi
from .rest import werkzeuge_aus_rest

Art = Literal["mcp_stdio", "mcp_http", "openapi", "rest", "eingebaut"]
Ereignis = Callable[[dict[str, Any]], Awaitable[None]]


class IntegrationsFehler(ValueError):
    pass


class FehlendeWerte(IntegrationsFehler):
    def __init__(self, eintrag_name: str, fehlend: list[Benoetigt], hinweis: str = ""):
        self.fehlend = fehlend
        self.hinweis = hinweis
        namen = ", ".join(f"{b.titel} ({b.name})" for b in fehlend)
        super().__init__(f"Für {eintrag_name} fehlen noch: {namen}." + (f" {hinweis}" if hinweis else ""))


class IntegrationsKonfig(BaseModel):
    id: str
    name: str
    art: Art
    katalog: str | None = None
    befehl: list[str] | None = None
    url: str | None = None
    kopfzeilen: dict[str, str] = Field(default_factory=dict)
    umgebung: dict[str, str] = Field(default_factory=dict)
    geheimnisse: list[str] = Field(default_factory=list)
    auth: dict[str, str] | None = None
    rest: list[dict[str, Any]] | None = None
    eingebaut: str | None = None
    risiko_standard: Risiko = "aendern"
    werkzeug_risiko: dict[str, Risiko] = Field(default_factory=dict)
    aktiv: bool = True
    hinzugefuegt: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def kennung_aus_name(name: str) -> str:
    s = name.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return (s or "integration")[:40]


def quelle_deuten(quelle: str, katalog: Katalog) -> dict[str, Any]:
    """Freitext („spotify“, „npx -y paket“, URL) → Anfrage-Form für hinzufuegen()."""
    q = quelle.strip()
    if katalog.holen(q):
        return {"katalog": katalog.holen(q).id}  # type: ignore[union-attr]
    if re.match(r"^https?://", q):
        unten = q.lower()
        if unten.endswith((".json", ".yaml", ".yml")) or "openapi" in unten or "swagger" in unten:
            return {"openapi_url": q}
        return {"mcp_url": q}
    if " " in q or q.split("/")[0] in ("npx", "uvx", "node", "python", "python3", "docker", "bunx", "deno"):
        return {"mcp_befehl": q}
    treffer = katalog.suchen(q)
    if len(treffer) == 1:
        return {"katalog": treffer[0].id}
    raise IntegrationsFehler(
        f"„{quelle}“ ist weder ein Katalogeintrag noch ein MCP-Befehl oder eine URL."
        + (f" Meinten Sie: {', '.join(t.id for t in treffer[:5])}?" if treffer else "")
    )


class IntegrationsManager:
    def __init__(
        self,
        register: WerkzeugRegister,
        geheimnisse: Geheimnisspeicher,
        katalog: Katalog,
        ereignis: Ereignis | None = None,
        pfad: Path | None = None,
        http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
    ):
        self.register = register
        self.geheimnisse = geheimnisse
        self.katalog = katalog
        self.ereignis = ereignis
        self.pfad = pfad or (jarvis_home() / "integrationen.json")
        self.http_client_fabrik = http_client_fabrik or (
            lambda **kw: httpx.AsyncClient(timeout=30.0, follow_redirects=True, **kw)
        )
        self.konfigs: dict[str, IntegrationsKonfig] = {}
        self.status: dict[str, str] = {}
        self.fehler: dict[str, str | None] = {}
        self.verbindungen: dict[str, McpVerbindung] = {}
        self._sperren: dict[str, asyncio.Lock] = {}
        self.laden()

    # ---------- Persistenz ----------
    def laden(self) -> None:
        self.konfigs.clear()
        if not self.pfad.exists():
            return
        try:
            daten = json.loads(self.pfad.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        for eintrag in daten.get("integrationen", []):
            try:
                k = IntegrationsKonfig.model_validate(eintrag)
                self.konfigs[k.id] = k
                self.status.setdefault(k.id, "aus")
            except ValueError:
                continue

    def speichern(self) -> None:
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        daten = {"version": 1, "integrationen": [k.model_dump() for k in self.konfigs.values()]}
        tmp = self.pfad.with_suffix(".tmp")
        tmp.write_text(json.dumps(daten, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.pfad)

    # ---------- Informationen ----------
    def info(self, kennung: str) -> dict[str, Any]:
        k = self.konfigs[kennung]
        info: dict[str, Any] = {
            "id": k.id,
            "name": k.name,
            "art": k.art,
            "status": self.status.get(k.id, "aus"),
            "werkzeuge": len(self.register.von_integration(k.id)),
        }
        if k.katalog:
            info["katalog"] = k.katalog
        if self.fehler.get(k.id):
            info["fehler"] = self.fehler[k.id]
        return info

    def liste(self) -> list[dict[str, Any]]:
        return [self.info(k) for k in self.konfigs]

    def verbundene_beschreibungen(self) -> list[str]:
        zeilen = []
        for k in self.konfigs.values():
            if self.status.get(k.id) == "verbunden":
                eintrag = self.katalog.holen(k.katalog) if k.katalog else None
                text = f"{k.name} ({len(self.register.von_integration(k.id))} Werkzeuge, Präfix {k.id}__)"
                if eintrag:
                    text += f": {eintrag.beschreibung}"
                zeilen.append(text)
        return zeilen

    async def _melden(self, kennung: str) -> None:
        if self.ereignis and kennung in self.konfigs:
            try:
                await self.ereignis({"typ": "integration_geaendert", "integration": self.info(kennung)})
            except Exception:  # noqa: BLE001
                pass

    # ---------- Hinzufügen ----------
    def _geheim_ablegen(self, name: str, wert: str) -> str:
        self.geheimnisse.setzen(name, wert)
        return "${" + name + "}"

    def _eindeutige_id(self, basis: str) -> str:
        kennung, i = basis, 2
        while kennung in self.konfigs:
            kennung = f"{basis}_{i}"
            i += 1
        return kennung

    def konfig_aus_anfrage(self, anfrage: dict[str, Any]) -> IntegrationsKonfig:
        """Erzeugt (ohne zu starten) die Konfiguration; legt Geheimnisse ab."""
        if anfrage.get("quelle") and not any(
            anfrage.get(k) for k in ("katalog", "mcp_befehl", "mcp_url", "openapi_url", "rest")
        ):
            anfrage = {**anfrage, **quelle_deuten(str(anfrage["quelle"]), self.katalog)}
        werte: dict[str, str] = {k: str(v) for k, v in (anfrage.get("werte") or {}).items() if v not in (None, "")}

        if anfrage.get("katalog"):
            eintrag = self.katalog.holen(str(anfrage["katalog"]))
            if eintrag is None:
                raise IntegrationsFehler(f"Katalogeintrag „{anfrage['katalog']}“ nicht gefunden.")
            fehlend: list[Benoetigt] = []
            umgebung: dict[str, str] = {}
            geheime: list[str] = []
            for b in eintrag.benoetigt:
                wert = werte.get(b.name)
                if wert is None and b.geheim and self.geheimnisse.hat(b.name):
                    geheime.append(b.name)
                    continue
                if wert is None:
                    wert = b.standard
                if wert is None:
                    if not b.optional:
                        fehlend.append(b)
                    continue
                if b.geheim:
                    self.geheimnisse.setzen(b.name, wert)
                    geheime.append(b.name)
                else:
                    umgebung[b.name] = wert
            if fehlend:
                raise FehlendeWerte(eintrag.name, fehlend, eintrag.hinweis)
            kennung = eintrag.id
            return IntegrationsKonfig(
                id=kennung,
                name=anfrage.get("name") or eintrag.name,
                art=eintrag.art,
                katalog=eintrag.id,
                befehl=befehl_zerlegen(eintrag.befehl) if eintrag.befehl else None,
                url=eintrag.url,
                kopfzeilen=dict(eintrag.kopfzeilen),
                umgebung=umgebung,
                geheimnisse=geheime,
                auth=dict(eintrag.auth) if eintrag.auth else None,
                rest=eintrag.rest,
                eingebaut=eintrag.eingebaut,
                risiko_standard=eintrag.risiko_standard,
                werkzeug_risiko=dict(eintrag.werkzeug_risiko),
            )

        name = str(anfrage.get("name") or "").strip()
        if anfrage.get("mcp_befehl"):
            befehl = anfrage["mcp_befehl"]
            teile = befehl_zerlegen(befehl) if isinstance(befehl, str) else [str(t) for t in befehl]
            if not teile:
                raise IntegrationsFehler("Leerer MCP-Befehl.")
            if not name:
                paket = next((t for t in reversed(teile) if not t.startswith("-")), teile[0])
                name = re.sub(r"^@[^/]+/", "", paket).replace("mcp-server-", "").replace("-mcp", "").replace("server-", "")
            kennung = self._eindeutige_id(kennung_aus_name(name))
            umgebung, geheime = {}, []
            for schluessel, wert in (anfrage.get("umgebung") or {}).items():
                if ist_geheimer_name(schluessel):
                    self.geheimnisse.setzen(schluessel, str(wert))
                    geheime.append(schluessel)
                else:
                    umgebung[schluessel] = str(wert)
            return IntegrationsKonfig(
                id=kennung, name=name, art="mcp_stdio", befehl=teile, umgebung=umgebung, geheimnisse=geheime
            )

        if anfrage.get("mcp_url") or anfrage.get("openapi_url"):
            ist_mcp = bool(anfrage.get("mcp_url"))
            url = str(anfrage.get("mcp_url") or anfrage.get("openapi_url"))
            if not name:
                name = re.sub(r"^https?://", "", url).split("/")[0]
            kennung = self._eindeutige_id(kennung_aus_name(name))
            kopfzeilen = {}
            for kopf, wert in (anfrage.get("kopfzeilen") or {}).items():
                if ist_geheimer_name(kopf):
                    geheimname = f"JARVIS_{kennung.upper()}_{kennung_aus_name(kopf).upper()}"
                    kopfzeilen[kopf] = self._geheim_ablegen(geheimname, str(wert))
                else:
                    kopfzeilen[kopf] = str(wert)
            auth = dict(anfrage.get("auth") or {}) or None
            if auth:
                for feld in ("wert", "passwort"):
                    if auth.get(feld):
                        auth[feld] = self._geheim_ablegen(f"JARVIS_{kennung.upper()}_{feld.upper()}", str(auth[feld]))
            geheime = sorted(platzhalter_finden(kopfzeilen) | platzhalter_finden(auth or {}))
            return IntegrationsKonfig(
                id=kennung, name=name, art="mcp_http" if ist_mcp else "openapi", url=url,
                kopfzeilen=kopfzeilen, auth=auth, geheimnisse=geheime,
            )

        if anfrage.get("rest"):
            if not name:
                raise IntegrationsFehler("Für REST-Integrationen wird ein Name benötigt.")
            kennung = self._eindeutige_id(kennung_aus_name(name))
            auth = dict(anfrage.get("auth") or {}) or None
            if auth and auth.get("wert"):
                auth["wert"] = self._geheim_ablegen(f"JARVIS_{kennung.upper()}_WERT", str(auth["wert"]))
            return IntegrationsKonfig(
                id=kennung, name=name, art="rest", rest=list(anfrage["rest"]), auth=auth,
                geheimnisse=sorted(platzhalter_finden(auth or {})),
            )

        raise IntegrationsFehler(
            "Unbekannte Form. Erwartet: katalog, mcp_befehl, mcp_url, openapi_url oder rest."
        )

    async def hinzufuegen(self, anfrage: dict[str, Any], starten: bool = True) -> dict[str, Any]:
        konfig = self.konfig_aus_anfrage(anfrage)
        if konfig.id in self.konfigs:
            await self._stoppen(konfig.id)
        self.konfigs[konfig.id] = konfig
        self.status[konfig.id] = "aus"
        self.fehler[konfig.id] = None
        self.speichern()
        if starten:
            await self.starten(konfig.id)
        else:
            await self._melden(konfig.id)
        return self.info(konfig.id)

    # ---------- Starten / Stoppen ----------
    def _werte(self, k: IntegrationsKonfig) -> dict[str, str]:
        werte = dict(k.umgebung)
        for name in k.geheimnisse:
            wert = self.geheimnisse.holen(name)
            if wert is not None:
                werte[name] = wert
        # Platzhalter in nicht-geheimen Werten ebenfalls auflösen
        return {n: platzhalter_ersetzen(v, werte) for n, v in werte.items()}

    async def _spec_laden(self, k: IntegrationsKonfig, werte: dict[str, str]) -> tuple[dict[str, Any], str]:
        url = platzhalter_ersetzen(k.url or "", werte)
        cache = jarvis_home() / "openapi" / f"{k.id}.json"
        try:
            async with self.http_client_fabrik() as client:
                r = await client.get(url)
                r.raise_for_status()
                spec = spec_parsen(r.text)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(spec), encoding="utf-8")
        except (httpx.HTTPError, ValueError):
            if not cache.exists():
                raise
            spec = json.loads(cache.read_text(encoding="utf-8"))
        return spec, url

    async def _werkzeuge_erzeugen(self, k: IntegrationsKonfig) -> list[Werkzeug]:
        werte = self._werte(k)
        fehlende = sorted(
            platzhalter_finden([k.befehl or [], k.url or "", k.kopfzeilen, k.auth or {}, k.rest or []]) - set(werte)
        )
        if fehlende:
            raise IntegrationsFehler(f"Fehlende Werte/Geheimnisse: {', '.join(fehlende)}")
        if k.art in ("mcp_stdio", "mcp_http"):
            if k.art == "mcp_stdio":
                verbindung = McpVerbindung(
                    k.id, befehl=platzhalter_ersetzen(k.befehl or [], werte), umgebung=werte
                )
            else:
                verbindung = McpVerbindung(
                    k.id,
                    url=platzhalter_ersetzen(k.url or "", werte),
                    kopfzeilen=platzhalter_ersetzen(k.kopfzeilen, werte),
                )
            self.verbindungen[k.id] = verbindung
            await verbindung.start()
            return werkzeuge_aus_mcp(verbindung, k.risiko_standard, k.werkzeug_risiko)
        if k.art == "openapi":
            spec, url = await self._spec_laden(k, werte)
            return werkzeuge_aus_openapi(
                spec,
                k.id,
                basis_url=basis_url_ermitteln(spec, url),
                auth=platzhalter_ersetzen(k.auth, werte) if k.auth else None,
                http_client_fabrik=self.http_client_fabrik,
                kopfzeilen=platzhalter_ersetzen(k.kopfzeilen, werte),
                werkzeug_risiko=k.werkzeug_risiko,
            )
        if k.art == "rest":
            return werkzeuge_aus_rest(
                platzhalter_ersetzen(k.rest or [], werte),
                k.id,
                auth=platzhalter_ersetzen(k.auth, werte) if k.auth else None,
                http_client_fabrik=self.http_client_fabrik,
                risiko_standard=k.risiko_standard,
            )
        if k.art == "eingebaut":
            return eingebaute_werkzeuge(k.eingebaut or k.id, k.id, werte, http_client_fabrik=self.http_client_fabrik)
        raise IntegrationsFehler(f"Unbekannte Art: {k.art}")

    async def starten(self, kennung: str) -> dict[str, Any]:
        if kennung not in self.konfigs:
            raise IntegrationsFehler(f"Integration „{kennung}“ ist nicht installiert.")
        sperre = self._sperren.setdefault(kennung, asyncio.Lock())
        async with sperre:
            await self._stoppen(kennung)
            k = self.konfigs[kennung]
            self.status[kennung] = "verbindet"
            self.fehler[kennung] = None
            try:
                werkzeuge = await self._werkzeuge_erzeugen(k)
                self.register.entfernen_integration(kennung)
                self.register.alle_registrieren(werkzeuge)
                self.status[kennung] = "verbunden"
            except (McpFehler, IntegrationsFehler) as e:
                self.status[kennung] = "fehler"
                self.fehler[kennung] = str(e)
            except Exception as e:  # noqa: BLE001
                self.status[kennung] = "fehler"
                self.fehler[kennung] = fehler_text(e)
        await self._melden(kennung)
        return self.info(kennung)

    async def _stoppen(self, kennung: str) -> None:
        self.register.entfernen_integration(kennung)
        verbindung = self.verbindungen.pop(kennung, None)
        if verbindung:
            await verbindung.stop()
        if kennung in self.konfigs:
            self.status[kennung] = "aus"

    async def alle_starten(self) -> None:
        aktive = [k for k, konfig in self.konfigs.items() if konfig.aktiv]
        await asyncio.gather(*(self.starten(k) for k in aktive), return_exceptions=True)

    async def alle_stoppen(self) -> None:
        await asyncio.gather(*(self._stoppen(k) for k in list(self.konfigs)), return_exceptions=True)

    async def neu_verbinden(self, kennung: str) -> dict[str, Any]:
        return await self.starten(kennung)

    async def entfernen(self, kennung: str) -> bool:
        if kennung not in self.konfigs:
            return False
        await self._stoppen(kennung)
        del self.konfigs[kennung]
        self.status.pop(kennung, None)
        self.fehler.pop(kennung, None)
        self.speichern()
        if self.ereignis:
            try:
                await self.ereignis(
                    {"typ": "integration_geaendert", "integration": {"id": kennung, "status": "entfernt", "entfernt": True}}
                )
            except Exception:  # noqa: BLE001
                pass
        return True
