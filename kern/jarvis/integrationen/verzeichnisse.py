"""Verzeichnissuche: MCP-Server in seriösen Verzeichnissen finden und mit einem Klick installieren.

Quellen:
* offizielles MCP-Registry (registry.modelcontextprotocol.io, API ``/v0/servers``),
* Smithery (registry.smithery.ai, nur gehostete Remote-Server),
* eigene Registries mit der API des offiziellen Registry (``Einstellungen.verzeichnisse_eigene``).

Ein ``Treffer`` beschreibt einen Server samt Herkunft, Vertrauensmerkmalen und den Feldern, die der
Nutzer ausfüllen muss. ``Verzeichnisse.anfrage()`` baut daraus die Anfrage-Form für
``IntegrationsManager.hinzufuegen`` (``mcp_url`` mit ``werte``/``geheime`` oder ``mcp_befehl`` mit
``umgebung``). Platzhalter in Vorlagen heißen ``{NAME}``; sie werden beim Installieren durch ``${NAME}``
ersetzt, das der Manager auflöst (geheime Werte landen im Schlüsselbund).
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from typing import Any, Literal, Protocol
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..geheimnisse import ist_geheimer_name
from .katalog import Benoetigt

Art = Literal["mcp_http", "mcp_stdio"]
Laufzeit = Literal["fern", "npx", "uvx"]

REGISTRY_URL = "https://registry.modelcontextprotocol.io"
SMITHERY_URL = "https://registry.smithery.ai"
VERZEICHNIS_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
_VORLAGE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_FELDNAME_ERLAUBT = re.compile(r"[^A-Za-z0-9_]+")
_NICHTSSAGEND = {"mcp", "server", "mcp-server", "mcpserver", "mcp_server"}


class VerzeichnisFehler(ValueError):
    pass


class Feld(BaseModel):
    """Eine Angabe, die der Nutzer vor der Installation macht (Kopfzeile, Umgebungsvariable, Argument)."""

    name: str
    titel: str
    geheim: bool = False
    optional: bool = False
    beschreibung: str = ""
    standard: str | None = None

    def als_benoetigt(self) -> Benoetigt:
        return Benoetigt(name=self.name, titel=self.titel, geheim=self.geheim, optional=self.optional)


class Treffer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quelle: str
    kennung: str
    name: str
    beschreibung: str = ""
    webseite: str | None = None
    repository: str | None = None
    #: Wer den Eintrag veröffentlicht hat, z. B. „GitHub-Konto foo“, „Domain firma.com“, „Smithery“
    herausgeber: str = ""
    #: Vom Verzeichnis geprüft: Smithery „verified“ bzw. Registry-Namensraum mit bestätigter Domain
    verifiziert: bool = False
    nutzungen: int | None = None
    art: Art | None = None
    laufzeit: Laufzeit | None = None
    #: Anmeldung im Browser zu erwarten (Remote-Server ohne eigene Kopfzeile)
    oauth: bool = False
    felder: list[Feld] = Field(default_factory=list)
    warnungen: list[str] = Field(default_factory=list)
    installierbar: bool = True
    #: Felder sind erst nach ``details()`` vollständig (Smithery)
    vollstaendig: bool = True
    aktualisiert: str | None = None
    #: Bauanleitung für die Anfrage (URL-/Kopfzeilen-/Befehlsvorlagen) – nicht Teil der API
    bauplan: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @property
    def rang(self) -> tuple:
        return (not self.verifiziert, not self.installierbar, -(self.nutzungen or 0), self.name.lower())


def feldname(roh: str) -> str:
    name = _FELDNAME_ERLAUBT.sub("_", str(roh)).strip("_").upper()
    return name or "WERT"


def _feld(name: str, beschreibung: str = "", *, geheim: bool | None = None, optional: bool = False, standard: Any = None) -> Feld:
    titel = beschreibung.strip().split(". ")[0][:80] if beschreibung else name
    if geheim is None:
        geheim = ist_geheimer_name(name) or ist_geheimer_name(beschreibung.split(" ")[0] if beschreibung else "")
    return Feld(
        name=feldname(name), titel=titel or name, geheim=bool(geheim), optional=optional,
        beschreibung=beschreibung.strip(), standard=str(standard) if standard not in (None, "") else None,
    )


def vorlage_fuellen(vorlage: Any, werte: dict[str, str]) -> Any:
    """Ersetzt ``{NAME}`` rekursiv durch werte[NAME]; unbekannte Namen bleiben stehen."""
    if isinstance(vorlage, str):
        return _VORLAGE.sub(lambda m: werte.get(m.group(1), m.group(0)), vorlage)
    if isinstance(vorlage, list):
        return [vorlage_fuellen(v, werte) for v in vorlage]
    if isinstance(vorlage, dict):
        return {k: vorlage_fuellen(v, werte) for k, v in vorlage.items()}
    return vorlage


class Verzeichnis(Protocol):
    id: str
    name: str
    url: str
    eigen: bool

    async def suchen(self, client: httpx.AsyncClient, begriff: str, limit: int) -> list[Treffer]: ...

    async def details(self, client: httpx.AsyncClient, kennung: str) -> Treffer: ...


# ---------------------------------------------------------------------------
# Offizielles MCP-Registry (und eigene Registries mit derselben API)
# ---------------------------------------------------------------------------


def _herausgeber_aus_name(name: str) -> tuple[str, bool]:
    """„io.github.foo/bar“ → („GitHub-Konto foo“, False); „com.firma/x“ → („Domain firma.com“, True)."""
    namensraum = name.split("/", 1)[0]
    teile = namensraum.split(".")
    if len(teile) >= 3 and teile[0] == "io" and teile[1] == "github":
        return f"GitHub-Konto {'.'.join(teile[2:])}", False
    if len(teile) >= 2:
        return f"Domain {'.'.join(reversed(teile))}", True
    return namensraum, False


class OffiziellesRegistry:
    """API des offiziellen MCP-Registry (auch für eigene Registries mit derselben API)."""

    def __init__(self, id: str = "mcp-registry", name: str = "MCP-Registry (offiziell)", url: str = REGISTRY_URL, eigen: bool = False):  # noqa: A002
        self.id, self.name, self.url, self.eigen = id, name, url.rstrip("/"), eigen

    async def suchen(self, client: httpx.AsyncClient, begriff: str, limit: int) -> list[Treffer]:
        antwort = await client.get(
            f"{self.url}/v0/servers", params={"search": begriff, "limit": min(max(limit * 3, 10), 100), "version": "latest"}
        )
        antwort.raise_for_status()
        daten = antwort.json()
        gesehen: set[str] = set()
        treffer = []
        for eintrag in daten.get("servers") or []:
            t = self._treffer(eintrag)
            if t is None or t.kennung in gesehen:
                continue
            gesehen.add(t.kennung)
            treffer.append(t)
        return treffer

    async def details(self, client: httpx.AsyncClient, kennung: str) -> Treffer:
        antwort = await client.get(f"{self.url}/v0/servers/{quote(kennung, safe='')}/versions/latest")
        if antwort.status_code == 404:
            raise VerzeichnisFehler(f"„{kennung}“ ist im Verzeichnis {self.name} nicht (mehr) vorhanden.")
        antwort.raise_for_status()
        t = self._treffer(antwort.json(), status_pruefen=False)
        if t is None:
            raise VerzeichnisFehler(f"„{kennung}“ ist im Verzeichnis {self.name} nicht mehr aktiv.")
        return t

    def _treffer(self, eintrag: dict[str, Any], status_pruefen: bool = True) -> Treffer | None:
        server = eintrag.get("server") or eintrag
        meta = (eintrag.get("_meta") or {}).get("io.modelcontextprotocol.registry/official") or {}
        if status_pruefen and meta.get("status", "active") != "active":
            return None
        name = str(server.get("name") or "")
        if not name:
            return None
        herausgeber, domain = _herausgeber_aus_name(name)
        # Anzeigename: title, sonst der Teil nach dem Namensraum; bei nichtssagenden Namen („mcp“, „server“)
        # der letzte Teil des Namensraums (net.todoist/mcp → „todoist“)
        anzeige = str(server.get("title") or "").strip()
        if not anzeige:
            teil = name.split("/", 1)[-1]
            anzeige = teil if teil.lower() not in _NICHTSSAGEND else name.split("/", 1)[0].rsplit(".", 1)[-1].capitalize()
        repo = (server.get("repository") or {}).get("url")
        t = Treffer(
            quelle=self.id,
            kennung=name,
            name=anzeige,
            beschreibung=str(server.get("description") or "").strip(),
            webseite=server.get("websiteUrl") or repo,
            repository=repo,
            herausgeber=herausgeber + (" (vom Registry bestätigt)" if domain else ""),
            # Eigene Domain als Namensraum: das Registry prüft die DNS-Inhaberschaft → gilt als verifiziert
            verifiziert=domain,
            aktualisiert=meta.get("updatedAt") or meta.get("publishedAt"),
        )
        self._installation(t, server)
        return t

    def _installation(self, t: Treffer, server: dict[str, Any]) -> None:
        remotes = [r for r in server.get("remotes") or [] if isinstance(r, dict)]
        http = next((r for r in remotes if str(r.get("type", "")).lower() in ("streamable-http", "http", "streamable_http")), None)
        if http and http.get("url"):
            kopfzeilen: dict[str, str] = {}
            for kopf in http.get("headers") or []:
                self._vorlage_feld(t, kopf, kopfzeilen)
            t.art, t.laufzeit = "mcp_http", "fern"
            t.oauth = not any(k.lower() == "authorization" for k in kopfzeilen)
            t.bauplan = {"url": str(http["url"]), "kopfzeilen": kopfzeilen}
            return
        pakete = [p for p in server.get("packages") or [] if isinstance(p, dict)]
        for art, laufzeit in (("npm", "npx"), ("pypi", "uvx")):
            paket = next((p for p in pakete if str(p.get("registryType", "")).lower() == art), None)
            if paket is None:
                continue
            kennung = str(paket.get("identifier") or "").strip()
            if not kennung:
                continue
            version = str(paket.get("version") or "").strip()
            if laufzeit == "npx":
                befehl = ["npx", "-y", f"{kennung}@{version}" if version and version != "latest" else kennung]
            else:
                befehl = ["uvx", f"{kennung}=={version}" if version and version != "latest" else kennung]
            umgebung: dict[str, str] = {}
            for arg in paket.get("packageArguments") or []:
                self._argument(t, arg, befehl)
            for var in paket.get("environmentVariables") or []:
                self._vorlage_feld(t, var, umgebung)
            t.art, t.laufzeit = "mcp_stdio", laufzeit
            t.warnungen.append(
                f"Lokaler Server: Javit führt das Paket „{kennung}“ mit {laufzeit} auf diesem Rechner aus. "
                "Nur installieren, wenn du dem Herausgeber vertraust."
            )
            t.bauplan = {"befehl": befehl, "umgebung": umgebung}
            return
        t.installierbar = False
        if remotes:
            t.warnungen.append("Dieser Server bietet nur den veralteten SSE-Transport an – wird nicht unterstützt.")
        elif pakete:
            arten = ", ".join(sorted({str(p.get("registryType", "?")) for p in pakete}))
            t.warnungen.append(f"Nur als {arten} verfügbar (Docker-Image/MCPB-Paket) – wird nicht unterstützt.")
        else:
            t.warnungen.append("Der Eintrag enthält keine Verbindungsangaben (weder Remote-URL noch Paket).")

    def _vorlage_feld(self, t: Treffer, angabe: dict[str, Any], ziel: dict[str, str]) -> None:
        """Kopfzeile oder Umgebungsvariable: fester Wert, Vorlage mit {var} oder Feld für den ganzen Wert."""
        name = str(angabe.get("name") or "").strip()
        if not name:
            return
        wert = angabe.get("value")
        beschreibung = str(angabe.get("description") or "")
        geheim = bool(angabe.get("isSecret"))
        pflicht = bool(angabe.get("isRequired", True))
        if wert not in (None, ""):
            variablen = _VORLAGE.findall(str(wert))
            if not variablen:
                ziel[name] = str(wert)
                return
            vorlage = str(wert)
            for var in variablen:
                feld = _feld(var, beschreibung if len(variablen) == 1 else var, geheim=geheim or None, optional=not pflicht)
                vorlage = vorlage.replace("{" + var + "}", "{" + feld.name + "}")
                self._feld_merken(t, feld)
            ziel[name] = vorlage
            return
        feld = _feld(name, beschreibung, geheim=geheim or None, optional=not pflicht, standard=angabe.get("default"))
        self._feld_merken(t, feld)
        ziel[name] = "{" + feld.name + "}"

    def _argument(self, t: Treffer, arg: dict[str, Any], befehl: list[str]) -> None:
        typ = str(arg.get("type") or "positional")
        name = str(arg.get("name") or "")
        wert = arg.get("value")
        if typ == "named" and name:
            if wert in (None, "") and not arg.get("isRequired"):
                return
            befehl.append(name)
        if wert not in (None, ""):
            vorlage = str(wert)
            for var in _VORLAGE.findall(vorlage):
                feld = _feld(var, str(arg.get("description") or ""), geheim=False, optional=not arg.get("isRequired", True))
                vorlage = vorlage.replace("{" + var + "}", "{" + feld.name + "}")
                self._feld_merken(t, feld)
            befehl.append(vorlage)
        elif arg.get("isRequired"):
            feld = _feld(str(arg.get("valueHint") or name or "ARGUMENT"), str(arg.get("description") or ""), geheim=False)
            self._feld_merken(t, feld)
            befehl.append("{" + feld.name + "}")

    @staticmethod
    def _feld_merken(t: Treffer, feld: Feld) -> None:
        if all(f.name != feld.name for f in t.felder):
            t.felder.append(feld)


# ---------------------------------------------------------------------------
# Smithery
# ---------------------------------------------------------------------------


class Smithery:
    def __init__(self, url: str = SMITHERY_URL):
        self.id, self.name, self.url, self.eigen = "smithery", "Smithery", url.rstrip("/"), False

    async def suchen(self, client: httpx.AsyncClient, begriff: str, limit: int) -> list[Treffer]:
        antwort = await client.get(f"{self.url}/servers", params={"q": f"{begriff} is:deployed", "pageSize": min(max(limit, 1), 50)})
        antwort.raise_for_status()
        treffer = []
        for s in antwort.json().get("servers") or []:
            if not s.get("remote") or s.get("unlisted") or s.get("inactive"):
                continue
            kennung = str(s.get("qualifiedName") or "")
            if not kennung:
                continue
            namensraum = kennung.split("/", 1)[0] if "/" in kennung else None
            treffer.append(
                Treffer(
                    quelle=self.id,
                    kennung=kennung,
                    name=str(s.get("displayName") or kennung),
                    beschreibung=_kurz(str(s.get("description") or "")),
                    webseite=s.get("homepage") or f"https://smithery.ai/server/{kennung}",
                    repository=s.get("homepage") if str(s.get("homepage") or "").startswith("https://github.com/") else None,
                    herausgeber="Smithery" if s.get("bySmithery") else (f"Smithery-Konto {namensraum}" if namensraum else "Smithery-Konto"),
                    verifiziert=bool(s.get("verified")),
                    nutzungen=int(s.get("useCount") or 0),
                    art="mcp_http",
                    laufzeit="fern",
                    oauth=True,
                    vollstaendig=False,
                    aktualisiert=s.get("createdAt"),
                )
            )
        return treffer

    async def details(self, client: httpx.AsyncClient, kennung: str) -> Treffer:
        antwort = await client.get(f"{self.url}/servers/{kennung}")
        if antwort.status_code == 404:
            raise VerzeichnisFehler(f"„{kennung}“ ist bei Smithery nicht (mehr) vorhanden.")
        antwort.raise_for_status()
        d = antwort.json()
        verbindung = next((c for c in d.get("connections") or [] if str(c.get("type", "")).lower() == "http"), None)
        url = (verbindung or {}).get("deploymentUrl") or d.get("deploymentUrl")
        namensraum = kennung.split("/", 1)[0] if "/" in kennung else None
        t = Treffer(
            quelle=self.id,
            kennung=kennung,
            name=str(d.get("displayName") or kennung),
            beschreibung=_kurz(str(d.get("description") or "")),
            webseite=d.get("homepage") or f"https://smithery.ai/server/{kennung}",
            herausgeber=f"Smithery-Konto {namensraum}" if namensraum else "Smithery",
            verifiziert=bool(d.get("verified")),
            nutzungen=int(d.get("useCount") or 0) if d.get("useCount") is not None else None,
            art="mcp_http",
            laufzeit="fern",
        )
        if not d.get("remote", True) or not url:
            t.installierbar = False
            t.warnungen.append("Dieser Smithery-Server läuft nicht gehostet – nur über die Smithery-CLI nutzbar.")
            return t
        schema = (verbindung or {}).get("configSchema") or {}
        pflicht = set(schema.get("required") or [])
        teile = []
        for name, eigenschaft in (schema.get("properties") or {}).items():
            if not isinstance(eigenschaft, dict):
                continue
            beschreibung = str(eigenschaft.get("description") or "")
            geheim = ist_geheimer_name(name) or ist_geheimer_name(beschreibung.split(" – ")[0].split(":")[0])
            feld = _feld(name, beschreibung, geheim=geheim, optional=name not in pflicht, standard=eigenschaft.get("default"))
            t.felder.append(feld)
            teile.append((name, feld))
        t.oauth = not any(not f.optional for f in t.felder)
        t.bauplan = {"url": str(url), "parameter": {name: "{" + feld.name + "}" for name, feld in teile}}
        t.warnungen.append(
            "Der Server wird von Smithery gehostet; Anfragen laufen über deren Server. Beim ersten Verbinden "
            "öffnet sich ggf. die Anmeldung bei Smithery im Browser."
        )
        return t


def _kurz(text: str, laenge: int = 280) -> str:
    text = text.strip().split("\n\n")[0].strip()
    return text if len(text) <= laenge else text[: laenge - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def eigenes_verzeichnis(daten: dict[str, Any]) -> OffiziellesRegistry:
    """Validiert einen Eintrag aus ``Einstellungen.verzeichnisse_eigene``."""
    kennung = str(daten.get("id") or "").strip().lower()
    name = str(daten.get("name") or "").strip()
    url = str(daten.get("url") or "").strip().rstrip("/")
    if not VERZEICHNIS_ID.match(kennung):
        raise ValueError("Verzeichnis-Kennung: nur a-z, 0-9, _ und - (max. 31 Zeichen).")
    if kennung in ("mcp-registry", "smithery"):
        raise ValueError(f"Die Kennung „{kennung}“ ist für ein eingebautes Verzeichnis reserviert.")
    if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise ValueError("Verzeichnis-URL muss mit https:// beginnen (http nur für localhost).")
    return OffiziellesRegistry(id=kennung, name=name or kennung, url=url, eigen=True)


class Verzeichnisse:
    """Durchsucht alle Verzeichnisse parallel und baut Installationsanfragen."""

    def __init__(
        self,
        eigene: Callable[[], list[dict[str, Any]]] | None = None,
        http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
        zeitlimit: float = 10.0,
        cache_sekunden: float = 600.0,
    ) -> None:
        self._eigene = eigene or (lambda: [])
        self.http_client_fabrik = http_client_fabrik or (lambda **kw: httpx.AsyncClient(**kw))
        self.zeitlimit = zeitlimit
        self.cache_sekunden = cache_sekunden
        self._cache: dict[tuple[str, str], tuple[float, list[Treffer]]] = {}
        self._eingebaute: list[Verzeichnis] = [OffiziellesRegistry(), Smithery()]

    def quellen(self) -> list[Verzeichnis]:
        eigene = []
        for daten in self._eigene() or []:
            try:
                eigene.append(eigenes_verzeichnis(daten))
            except ValueError:
                continue
        return [*self._eingebaute, *eigene]

    def quellen_info(self) -> list[dict[str, Any]]:
        return [{"id": q.id, "name": q.name, "url": q.url, "eigen": q.eigen} for q in self.quellen()]

    def holen(self, kennung: str) -> Verzeichnis:
        for q in self.quellen():
            if q.id == kennung:
                return q
        raise VerzeichnisFehler(f"Unbekanntes Verzeichnis „{kennung}“.")

    def _client(self) -> httpx.AsyncClient:
        return self.http_client_fabrik(timeout=self.zeitlimit, headers={"User-Agent": "Javit", "Accept": "application/json"})

    async def suchen(self, begriff: str, quelle: str | None = None, limit: int = 8) -> dict[str, Any]:
        begriff = " ".join(str(begriff or "").split())
        if len(begriff) < 2:
            raise VerzeichnisFehler("Bitte mindestens zwei Zeichen eingeben.")
        quellen = [self.holen(quelle)] if quelle else self.quellen()
        fehler: dict[str, str] = {}

        async def eine(q: Verzeichnis) -> list[Treffer]:
            schluessel = (q.id, begriff.lower())
            im_cache = self._cache.get(schluessel)
            if im_cache and time.monotonic() - im_cache[0] < self.cache_sekunden:
                return im_cache[1]
            try:
                async with self._client() as client:
                    treffer = await asyncio.wait_for(q.suchen(client, begriff, limit), self.zeitlimit + 1)
            except asyncio.TimeoutError:
                fehler[q.id] = "keine Antwort (Zeitlimit)"
                return []
            except httpx.HTTPStatusError as e:
                fehler[q.id] = f"HTTP {e.response.status_code}"
                return []
            except (httpx.HTTPError, ValueError) as e:
                fehler[q.id] = str(e) or e.__class__.__name__
                return []
            self._cache[schluessel] = (time.monotonic(), treffer)
            return treffer

        ergebnisse = await asyncio.gather(*(eine(q) for q in quellen))
        alle = [t for liste in ergebnisse for t in liste[:limit]]
        alle.sort(key=lambda t: t.rang)
        return {"treffer": [t.model_dump() for t in alle], "fehler": fehler}

    async def details(self, quelle: str, kennung: str) -> Treffer:
        q = self.holen(quelle)
        try:
            async with self._client() as client:
                return await asyncio.wait_for(q.details(client, kennung), self.zeitlimit + 1)
        except asyncio.TimeoutError as e:
            raise VerzeichnisFehler(f"{q.name} antwortet nicht (Zeitlimit).") from e
        except httpx.HTTPStatusError as e:
            raise VerzeichnisFehler(f"{q.name}: HTTP {e.response.status_code}") from e
        except httpx.HTTPError as e:
            raise VerzeichnisFehler(f"{q.name} nicht erreichbar: {e}") from e

    async def anfrage(self, quelle: str, kennung: str, werte: dict[str, Any] | None = None, name: str | None = None) -> dict[str, Any]:
        """Baut die Anfrage für ``IntegrationsManager.hinzufuegen`` (wirft FehlendeWerte/VerzeichnisFehler)."""
        from .manager import FehlendeWerte  # noqa: PLC0415 (Importzyklus)

        t = await self.details(quelle, kennung)
        if not t.installierbar:
            raise VerzeichnisFehler(f"„{t.name}“ lässt sich nicht installieren: {' '.join(t.warnungen)}")
        werte = {k: str(v) for k, v in (werte or {}).items() if v not in (None, "")}
        fehlend = [f for f in t.felder if not f.optional and not werte.get(f.name) and f.standard is None]
        if fehlend:
            raise FehlendeWerte(t.name, [f.als_benoetigt() for f in fehlend])
        for f in t.felder:
            if f.standard is not None and not werte.get(f.name):
                werte[f.name] = f.standard
        platzhalter = {f.name: "${" + f.name + "}" for f in t.felder if f.name in werte}
        anfrage: dict[str, Any] = {
            "name": name or t.name,
            "verzeichnis": {"quelle": t.quelle, "kennung": t.kennung},
            "geheime": [f.name for f in t.felder if f.geheim],
        }
        if t.art == "mcp_http":
            url = str(t.bauplan.get("url", ""))
            parameter = t.bauplan.get("parameter") or {}
            if parameter:
                # Nicht geheime Werte direkt (URL-kodiert), geheime als Platzhalter für den Schlüsselbund
                teile = []
                for p_name, vorlage in parameter.items():
                    feld = next((f for f in t.felder if "{" + f.name + "}" == vorlage), None)
                    if feld is None or feld.name not in werte:
                        continue
                    teile.append(f"{quote(p_name, safe='')}=" + (vorlage if feld.geheim else quote(werte[feld.name], safe="")))
                if teile:
                    url += ("&" if "?" in url else "?") + "&".join(teile)
            anfrage.update({
                "mcp_url": vorlage_fuellen(url, platzhalter),
                "kopfzeilen": vorlage_fuellen(dict(t.bauplan.get("kopfzeilen") or {}), platzhalter),
                "werte": werte,
            })
        else:
            # Befehlsargumente bekommen ${NAME}-Platzhalter (der Manager löst sie beim Start aus der Umgebung
            # auf); Umgebungsvariablen erhalten die Werte direkt – geheime Namen legt der Manager im
            # Schlüsselbund ab. Enthält eine Variable ein geheimes Feld, gilt sie insgesamt als geheim.
            befehl = vorlage_fuellen(list(t.bauplan.get("befehl") or []), platzhalter)
            vorlagen = dict(t.bauplan.get("umgebung") or {})
            umgebung = vorlage_fuellen(vorlagen, werte)
            geheime = set(anfrage["geheime"])
            for env_name, vorlage in vorlagen.items():
                if any(f.geheim and "{" + f.name + "}" in str(vorlage) for f in t.felder):
                    geheime.add(env_name)
            befehl_text = " ".join(befehl)
            for f in t.felder:
                if f.name in werte and "${" + f.name + "}" in befehl_text:
                    umgebung.setdefault(f.name, werte[f.name])
            anfrage["geheime"] = sorted(geheime)
            anfrage.update({"mcp_befehl": befehl, "umgebung": umgebung})
        return anfrage
