"""Verzeichnissuche (Phase 2b): Registry-/Smithery-Parsing, Aggregator, Installationsanfragen, Manager,
Einstellungen, Server und Agent-Werkzeuge – alles offline gegen gefälschte Verzeichnisse."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from jarvis.geheimnisse import Geheimnisspeicher
from jarvis.integrationen import verzeichnisse as vz
from jarvis.integrationen.katalog import Katalog
from jarvis.integrationen.manager import FehlendeWerte, IntegrationsManager
from jarvis.konfig import Einstellungen
from jarvis.server import create_app
from jarvis.werkzeuge import WerkzeugRegister
from tests.conftest import mock_fabrik
from tests.helfer import baue_jarvis

pytestmark = pytest.mark.usefixtures("isoliert")


def _meta(status: str = "active", latest: bool = True) -> dict:
    return {"io.modelcontextprotocol.registry/official": {"status": status, "isLatest": latest, "updatedAt": "2026-10-20T00:00:00Z"}}


REGISTRY_SERVER = [
    {  # Remote mit Kopfzeilen-Vorlage (geheim)
        "server": {
            "name": "ai.smithery/smithery-notion", "title": "Notion (Smithery)", "description": "Notion über Smithery.",
            "repository": {"url": "https://github.com/smithery-ai/mcp-servers"},
            "remotes": [{"type": "streamable-http", "url": "https://server.smithery.ai/@smithery/notion/mcp",
                         "headers": [{"name": "Authorization", "value": "Bearer {smithery_api_key}", "isRequired": True, "isSecret": True, "description": "Bearer token for Smithery"}]}],
        },
        "_meta": _meta(),
    },
    {  # npm-Paket mit Umgebungsvariable und Argument-Vorlage
        "server": {
            "name": "io.github.foo/dateien", "description": "Dateien lesen.", "websiteUrl": "https://foo.example",
            "packages": [{"registryType": "npm", "identifier": "@foo/mcp-dateien", "version": "1.2.0", "runtimeHint": "npx",
                          "packageArguments": [{"type": "positional", "value": "{ordner}", "isRequired": True, "description": "Freigegebener Ordner"},
                                               {"type": "named", "name": "--port", "value": "8080"}],
                          "environmentVariables": [{"name": "FOO_API_KEY", "description": "API-Schlüssel von foo.example", "isRequired": True, "isSecret": True},
                                                   {"name": "FOO_LOG", "description": "Log-Level", "isRequired": False, "default": "info"}]}],
        },
        "_meta": _meta(),
    },
    {  # nichtssagender Name → Anzeigename aus dem Namensraum
        "server": {"name": "net.todoist/mcp", "description": "Official Todoist MCP server.", "remotes": [{"type": "streamable-http", "url": "https://ai.todoist.net/mcp"}]},
        "_meta": _meta(),
    },
    {  # pypi-Paket
        "server": {"name": "com.firma/wetter", "title": "Wetter", "description": "Wetterdaten.",
                   "packages": [{"registryType": "pypi", "identifier": "firma-wetter-mcp", "version": "0.3.1"}]},
        "_meta": _meta(),
    },
    {  # nur Docker
        "server": {"name": "com.firma/docker-only", "description": "Nur als Image.",
                   "packages": [{"registryType": "oci", "identifier": "ghcr.io/firma/x:1"}]},
        "_meta": _meta(),
    },
    {  # nur SSE
        "server": {"name": "com.firma/sse-only", "description": "Alt.", "remotes": [{"type": "sse", "url": "https://alt.example/sse"}]},
        "_meta": _meta(),
    },
    {  # veraltet → ausgeblendet
        "server": {"name": "com.firma/alt", "description": "Veraltet.", "remotes": [{"type": "streamable-http", "url": "https://x/mcp"}]},
        "_meta": _meta("deprecated"),
    },
    {  # Duplikat (ältere Version) → nur einmal
        "server": {"name": "com.firma/wetter", "title": "Wetter", "description": "Alt.", "version": "0.1.0",
                   "packages": [{"registryType": "pypi", "identifier": "firma-wetter-mcp", "version": "0.1.0"}]},
        "_meta": _meta(latest=False),
    },
]

SMITHERY_LISTE = {
    "servers": [
        {"qualifiedName": "exa", "displayName": "Exa Search", "description": "Websuche.\n\nMehr Text.", "verified": True, "useCount": 9181,
         "remote": True, "isDeployed": True, "homepage": "https://exa.ai", "bySmithery": False},
        {"qualifiedName": "node2flow/notion", "displayName": "Notion", "description": "Notion-API.", "verified": False, "useCount": 7,
         "remote": True, "isDeployed": True, "homepage": "https://github.com/node2flow/x", "bySmithery": False},
        {"qualifiedName": "lokal/ding", "displayName": "Lokal", "description": "nur stdio", "verified": False, "useCount": 0, "remote": False, "isDeployed": False},
    ],
    "pagination": {"totalCount": 3},
}
SMITHERY_NOTION = {
    "qualifiedName": "node2flow/notion", "displayName": "Notion", "description": "Notion-API.", "remote": True,
    "deploymentUrl": "https://notion--node2flow.run.tools",
    "connections": [{"type": "http", "deploymentUrl": "https://notion--node2flow.run.tools",
                     "configSchema": {"type": "object", "required": ["NOTION_API_KEY"],
                                      "properties": {"NOTION_API_KEY": {"type": "string", "description": "Internal Integration Token"},
                                                     "NOTION_TIMEOUT": {"type": "string", "default": "30000", "description": "Timeout (ms)"}}}}],
}
SMITHERY_EXA = {"qualifiedName": "exa", "displayName": "Exa Search", "remote": True, "deploymentUrl": "https://exa.run.tools",
                "connections": [{"type": "http", "deploymentUrl": "https://exa.run.tools", "configSchema": {}}], "verified": True, "useCount": 9181}


class FakeVerzeichnisse:
    """HTTP-Handler für Registry + Smithery; zählt Aufrufe."""

    def __init__(self, registry_fehler: int | None = None, smithery_langsam: bool = False):
        self.aufrufe: list[str] = []
        self.registry_fehler = registry_fehler
        self.smithery_langsam = smithery_langsam

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.aufrufe.append(url)
        if request.url.host == "registry.modelcontextprotocol.io":
            if self.registry_fehler:
                return httpx.Response(self.registry_fehler, text="kaputt")
            if request.url.path == "/v0/servers":
                q = parse_qs(request.url.query.decode())
                assert q.get("version") == ["latest"]
                begriff = q.get("search", [""])[0].lower()
                return httpx.Response(200, json={"servers": [s for s in REGISTRY_SERVER if begriff in s["server"]["name"] or begriff in s["server"].get("description", "").lower()]})
            if request.url.path.startswith("/v0/servers/"):
                name = unquote(request.url.path.split("/v0/servers/", 1)[1].rsplit("/versions/", 1)[0])
                for s in REGISTRY_SERVER:
                    if s["server"]["name"] == name:
                        return httpx.Response(200, json=s)
                return httpx.Response(404, json={"error": "not found"})
        if request.url.host == "registry.smithery.ai":
            if self.smithery_langsam:
                raise httpx.ReadTimeout("langsam")
            if request.url.path == "/servers":
                q = parse_qs(request.url.query.decode())["q"][0]
                assert q.endswith(" is:deployed")
                begriff = q.rsplit(" is:deployed", 1)[0].lower()
                return httpx.Response(200, json={**SMITHERY_LISTE, "servers": [s for s in SMITHERY_LISTE["servers"] if begriff in s["displayName"].lower() or begriff in s["qualifiedName"]]})
            if request.url.path == "/servers/node2flow/notion":
                return httpx.Response(200, json=SMITHERY_NOTION)
            if request.url.path == "/servers/exa":
                return httpx.Response(200, json=SMITHERY_EXA)
            return httpx.Response(404, json={"error": "Server not found"})
        if request.url.host == "registry.firma.test":
            return httpx.Response(200, json={"servers": [REGISTRY_SERVER[2]]})
        return httpx.Response(500, text=f"unerwartet: {url}")


def _ohne_start(manager: IntegrationsManager) -> None:
    """Verhindert echte MCP-Verbindungen (OAuth-Entdeckung würde 300 s auf den Rückruf warten)."""

    async def kein_start(kennung: str) -> dict:
        manager.status[kennung] = "aus"
        return manager.info(kennung)

    manager.starten = kein_start  # type: ignore[method-assign]


def _verzeichnisse(fake: FakeVerzeichnisse | None = None, eigene: list | None = None, **kw) -> vz.Verzeichnisse:
    fake = fake or FakeVerzeichnisse()
    return vz.Verzeichnisse(lambda: eigene or [], http_client_fabrik=mock_fabrik(fake), **kw)


# ---------------------------------------------------------------- Registry-Parsing


@pytest.mark.asyncio
async def test_registry_parsing_und_herkunft():
    v = _verzeichnisse()
    ergebnis = await v.suchen("firma", limit=10)
    nach = {t["kennung"]: t for t in ergebnis["treffer"]}
    assert set(nach) == {"com.firma/wetter", "com.firma/docker-only", "com.firma/sse-only"}  # deprecated + Duplikat weg
    wetter = nach["com.firma/wetter"]
    assert wetter["name"] == "Wetter" and wetter["art"] == "mcp_stdio" and wetter["laufzeit"] == "uvx"
    assert wetter["herausgeber"] == "Domain firma.com (vom Registry bestätigt)" and wetter["installierbar"] and wetter["verifiziert"]
    assert "bauplan" not in wetter  # interne Bauanleitung nicht in der API
    assert not nach["com.firma/docker-only"]["installierbar"] and "Docker" in nach["com.firma/docker-only"]["warnungen"][0]
    assert not nach["com.firma/sse-only"]["installierbar"] and "SSE" in nach["com.firma/sse-only"]["warnungen"][0]

    t = await v.details("mcp-registry", "io.github.foo/dateien")
    assert t.herausgeber == "GitHub-Konto foo" and not t.verifiziert and t.laufzeit == "npx" and t.webseite == "https://foo.example"
    assert t.bauplan["befehl"] == ["npx", "-y", "@foo/mcp-dateien@1.2.0", "{ORDNER}", "--port", "8080"]
    assert t.bauplan["umgebung"] == {"FOO_API_KEY": "{FOO_API_KEY}", "FOO_LOG": "{FOO_LOG}"}
    felder = {f.name: f for f in t.felder}
    assert felder["ORDNER"].titel == "Freigegebener Ordner" and not felder["ORDNER"].geheim and not felder["ORDNER"].optional
    assert felder["FOO_API_KEY"].geheim and not felder["FOO_API_KEY"].optional
    assert felder["FOO_LOG"].optional and felder["FOO_LOG"].standard == "info"
    assert any("npx" in w for w in t.warnungen)

    notion = await v.details("mcp-registry", "ai.smithery/smithery-notion")
    assert notion.art == "mcp_http" and notion.oauth is False  # Authorization-Kopfzeile vorhanden
    assert notion.bauplan == {"url": "https://server.smithery.ai/@smithery/notion/mcp", "kopfzeilen": {"Authorization": "Bearer {SMITHERY_API_KEY}"}}
    assert [f.name for f in notion.felder] == ["SMITHERY_API_KEY"] and notion.felder[0].geheim

    with pytest.raises(vz.VerzeichnisFehler, match="nicht"):
        await v.details("mcp-registry", "com.firma/gibtsnicht")
    todoist = await v.details("mcp-registry", "net.todoist/mcp")
    assert todoist.name == "Todoist" and todoist.oauth and todoist.verifiziert


@pytest.mark.asyncio
async def test_smithery_suche_und_details():
    v = _verzeichnisse()
    ergebnis = await v.suchen("notion", quelle="smithery")
    assert [t["kennung"] for t in ergebnis["treffer"]] == ["node2flow/notion"]  # nicht-remote ausgeblendet
    t0 = ergebnis["treffer"][0]
    assert t0["herausgeber"] == "Smithery-Konto node2flow" and t0["laufzeit"] == "fern" and not t0["vollstaendig"]
    t = await v.details("smithery", "node2flow/notion")
    assert t.vollstaendig and t.oauth is False
    assert {f.name: (f.geheim, f.optional, f.standard) for f in t.felder} == {
        "NOTION_API_KEY": (True, False, None), "NOTION_TIMEOUT": (False, True, "30000"),
    }
    assert t.bauplan["url"] == "https://notion--node2flow.run.tools"
    exa = await v.details("smithery", "exa")
    assert exa.oauth and exa.felder == [] and exa.verifiziert and exa.nutzungen == 9181
    with pytest.raises(vz.VerzeichnisFehler):
        await v.details("smithery", "gibt/esnicht")


@pytest.mark.asyncio
async def test_aggregator_sortierung_fehler_cache_und_eigene():
    fake = FakeVerzeichnisse(registry_fehler=500)
    eigene = [{"id": "firma", "name": "Firmen-Registry", "url": "https://registry.firma.test"}]
    v = _verzeichnisse(fake, eigene=eigene)
    assert [q["id"] for q in v.quellen_info()] == ["mcp-registry", "smithery", "firma"]
    assert v.quellen_info()[2] == {"id": "firma", "name": "Firmen-Registry", "url": "https://registry.firma.test", "eigen": True}
    ergebnis = await v.suchen("exa")
    assert ergebnis["fehler"] == {"mcp-registry": "HTTP 500"}
    # verifiziert zuerst, dann nach Nutzungen; Firmen-Registry liefert immer „Wetter“
    assert [t["kennung"] for t in ergebnis["treffer"]][:1] == ["exa"]
    assert {t["quelle"] for t in ergebnis["treffer"]} == {"smithery", "firma"}
    vorher = len(fake.aufrufe)
    await v.suchen("exa")  # aus dem Zwischenspeicher
    assert len(fake.aufrufe) == vorher + 1  # nur das fehlgeschlagene Registry wird erneut gefragt
    with pytest.raises(vz.VerzeichnisFehler):
        await v.suchen("x")
    with pytest.raises(vz.VerzeichnisFehler, match="Unbekanntes Verzeichnis"):
        await v.suchen("exa", quelle="nix")
    langsam = _verzeichnisse(FakeVerzeichnisse(smithery_langsam=True))
    e2 = await langsam.suchen("wetter")
    assert "smithery" in e2["fehler"] and [t["kennung"] for t in e2["treffer"]] == ["com.firma/wetter"]


# ---------------------------------------------------------------- Anfragen für den Manager


@pytest.mark.asyncio
async def test_anfrage_remote_mit_geheimen_feldern():
    v = _verzeichnisse()
    with pytest.raises(FehlendeWerte) as info:
        await v.anfrage("smithery", "node2flow/notion", {})
    assert [b.name for b in info.value.fehlend] == ["NOTION_API_KEY"]
    a = await v.anfrage("smithery", "node2flow/notion", {"NOTION_API_KEY": "secret-1"}, name="Mein Notion")
    assert a["mcp_url"] == "https://notion--node2flow.run.tools?NOTION_API_KEY=${NOTION_API_KEY}&NOTION_TIMEOUT=30000"
    assert a["werte"] == {"NOTION_API_KEY": "secret-1", "NOTION_TIMEOUT": "30000"} and a["geheime"] == ["NOTION_API_KEY"]
    assert a["name"] == "Mein Notion" and a["verzeichnis"] == {"quelle": "smithery", "kennung": "node2flow/notion"}
    b = await v.anfrage("mcp-registry", "ai.smithery/smithery-notion", {"SMITHERY_API_KEY": "sk"})
    assert b["kopfzeilen"] == {"Authorization": "Bearer ${SMITHERY_API_KEY}"} and b["werte"] == {"SMITHERY_API_KEY": "sk"}
    with pytest.raises(vz.VerzeichnisFehler, match="nicht installieren"):
        await v.anfrage("mcp-registry", "com.firma/docker-only", {})


@pytest.mark.asyncio
async def test_anfrage_lokal_mit_argumenten_und_umgebung():
    v = _verzeichnisse()
    a = await v.anfrage("mcp-registry", "io.github.foo/dateien", {"ORDNER": "~/Dokumente", "FOO_API_KEY": "k-1"})
    assert a["mcp_befehl"] == ["npx", "-y", "@foo/mcp-dateien@1.2.0", "${ORDNER}", "--port", "8080"]
    assert a["umgebung"] == {"FOO_API_KEY": "k-1", "FOO_LOG": "info", "ORDNER": "~/Dokumente"}
    assert a["geheime"] == ["FOO_API_KEY"] and a["name"] == "dateien"
    w = await v.anfrage("mcp-registry", "com.firma/wetter", {})
    assert w["mcp_befehl"] == ["uvx", "firma-wetter-mcp==0.3.1"] and w["umgebung"] == {}


def test_manager_mcp_url_mit_werten_und_verzeichnis():
    g = Geheimnisspeicher()
    m = IntegrationsManager(WerkzeugRegister(), g, Katalog(), http_client_fabrik=mock_fabrik(lambda r: httpx.Response(500)))
    k = m.konfig_aus_anfrage({
        "name": "Notion", "mcp_url": "https://n.run.tools?NOTION_API_KEY=${NOTION_API_KEY}&T=${T}",
        "kopfzeilen": {"X-Timeout": "${T}", "Authorization": "Bearer ${SMITHERY_API_KEY}"},
        "werte": {"NOTION_API_KEY": "secret-1", "T": "30", "SMITHERY_API_KEY": "sk"},
        "geheime": ["NOTION_API_KEY"], "verzeichnis": {"quelle": "smithery", "kennung": "node2flow/notion"},
    })
    assert k.url == "https://n.run.tools?NOTION_API_KEY=${JARVIS_NOTION_NOTION_API_KEY}&T=30"
    assert k.kopfzeilen == {"X-Timeout": "30", "Authorization": "${JARVIS_NOTION_AUTHORIZATION}"}
    assert set(k.geheimnisse) == {"JARVIS_NOTION_NOTION_API_KEY", "JARVIS_NOTION_AUTHORIZATION", "JARVIS_NOTION_SMITHERY_API_KEY"}
    assert g.holen("JARVIS_NOTION_NOTION_API_KEY") == "secret-1"
    assert g.holen("JARVIS_NOTION_AUTHORIZATION") == "Bearer ${JARVIS_NOTION_SMITHERY_API_KEY}"
    assert k.oauth is None and k.verzeichnis == {"quelle": "smithery", "kennung": "node2flow/notion"}
    # Beim Start werden alle Platzhalter (auch verschachtelt) aufgelöst
    werte = m._werte(k)
    assert werte["JARVIS_NOTION_AUTHORIZATION"] == "Bearer sk"
    from jarvis.integrationen.katalog import platzhalter_ersetzen

    assert platzhalter_ersetzen(k.url, werte) == "https://n.run.tools?NOTION_API_KEY=secret-1&T=30"
    # Kein Geheimnis in der Konfigurationsdatei
    m.konfigs[k.id] = k
    m.speichern()
    from jarvis.konfig import jarvis_home

    text = (jarvis_home() / "integrationen.json").read_text()
    assert "secret-1" not in text and "sk" not in text.replace("JARVIS", "") and '"verzeichnis"' in text
    assert m.details(k.id)["verzeichnis"] == {"quelle": "smithery", "kennung": "node2flow/notion"}
    # mcp_befehl: ausdrücklich geheime Umgebungsvariable landet im Schlüsselbund
    k2 = m.konfig_aus_anfrage({"name": "Lokal", "mcp_befehl": ["npx", "-y", "x"], "umgebung": {"CREDS": "abc", "LOG": "info"}, "geheime": ["CREDS"]})
    assert k2.umgebung == {"LOG": "info"} and k2.geheimnisse == ["CREDS"] and g.holen("CREDS") == "abc"


@pytest.mark.asyncio
async def test_aendern_behaelt_verzeichnis_und_url_geheimnisse():
    g = Geheimnisspeicher()
    m = IntegrationsManager(WerkzeugRegister(), g, Katalog(), http_client_fabrik=mock_fabrik(lambda r: httpx.Response(500)))
    _ohne_start(m)
    await m.hinzufuegen({
        "name": "Notion", "mcp_url": "https://n.run.tools?NOTION_API_KEY=${NOTION_API_KEY}", "werte": {"NOTION_API_KEY": "s"},
        "verzeichnis": {"quelle": "smithery", "kennung": "node2flow/notion"},
    }, starten=False)
    d = m.details("notion")
    assert d["konfig"]["url"] == "https://n.run.tools?NOTION_API_KEY=${JARVIS_NOTION_NOTION_API_KEY}"
    neu = await m.aendern("notion", {"mcp_url": d["konfig"]["url"], "kopfzeilen": {}, "name": "Notion 2"})
    assert neu["name"] == "Notion 2" and neu["verzeichnis"] == {"quelle": "smithery", "kennung": "node2flow/notion"}
    assert m.konfigs["notion"].geheimnisse == ["JARVIS_NOTION_NOTION_API_KEY"]


# ---------------------------------------------------------------- Einstellungen


def test_einstellungen_verzeichnisse_eigene():
    e = Einstellungen(verzeichnisse_eigene=[{"id": "Firma", "name": "Firmen-Registry", "url": "https://registry.firma.test/"}])
    assert e.verzeichnisse_eigene == [{"id": "firma", "name": "Firmen-Registry", "url": "https://registry.firma.test"}]
    for kaputt, text in (
        ({"id": "smithery", "url": "https://x"}, "reserviert"),
        ({"id": "a b", "url": "https://x"}, "Kennung"),
        ({"id": "ok", "url": "http://fremd.example"}, "https"),
    ):
        with pytest.raises(ValueError, match=text):
            Einstellungen(verzeichnisse_eigene=[kaputt])
    with pytest.raises(ValueError, match="doppelt"):
        Einstellungen(verzeichnisse_eigene=[{"id": "a", "url": "https://x"}, {"id": "a", "url": "https://y"}])
    assert Einstellungen(verzeichnisse_eigene=[{"id": "lokal", "url": "http://127.0.0.1:9000"}]).verzeichnisse_eigene[0]["url"] == "http://127.0.0.1:9000"


# ---------------------------------------------------------------- Server + Werkzeuge


def _app():
    fake = FakeVerzeichnisse()
    j, skript = baue_jarvis(http_handler=fake)
    j.konfig.aktualisieren({"verzeichnisse_eigene": [{"id": "firma", "name": "Firma", "url": "https://registry.firma.test"}]})
    _ohne_start(j.manager)
    app = create_app(j, integrationen_starten=False, stimme_starten=False)
    return TestClient(app, base_url="http://127.0.0.1:8765"), j, fake


def test_server_endpunkte():
    client0, j, fake = _app()
    with client0 as client:
        assert [q["id"] for q in client.get("/api/verzeichnisse").json()] == ["mcp-registry", "smithery", "firma"]
        r = client.get("/api/verzeichnisse/suche", params={"q": "notion"})
        assert r.status_code == 200
        kennungen = [t["kennung"] for t in r.json()["treffer"]]
        assert "node2flow/notion" in kennungen and "ai.smithery/smithery-notion" in kennungen and r.json()["fehler"] == {}
        assert client.get("/api/verzeichnisse/suche", params={"q": "n"}).status_code == 400
        r = client.get("/api/verzeichnisse/smithery/node2flow/notion")
        assert r.status_code == 200 and [f["name"] for f in r.json()["felder"]] == ["NOTION_API_KEY", "NOTION_TIMEOUT"]
        assert client.get("/api/verzeichnisse/smithery/nix/da").status_code == 404
        r = client.post("/api/verzeichnisse/installieren", json={"quelle": "smithery", "kennung": "node2flow/notion"})
        assert r.status_code == 400 and r.json()["fehlend"] == [{"name": "NOTION_API_KEY", "titel": "Internal Integration Token", "geheim": True}]
        r = client.post("/api/verzeichnisse/installieren", json={"quelle": "mcp-registry", "kennung": "com.firma/docker-only"})
        assert r.status_code == 400 and "nicht installieren" in r.json()["detail"]
        # Installation legt die Integration an (Start in Tests abgeschaltet)
        r = client.post("/api/verzeichnisse/installieren", json={"quelle": "smithery", "kennung": "node2flow/notion", "werte": {"NOTION_API_KEY": "s"}})
        assert r.status_code == 200 and r.json()["id"] == "notion"
        d = client.get("/api/integrationen/notion").json()
        assert d["verzeichnis"] == {"quelle": "smithery", "kennung": "node2flow/notion"}
        assert "${JARVIS_NOTION_NOTION_API_KEY}" in d["konfig"]["url"]
        assert j.geheimnisse.holen("JARVIS_NOTION_NOTION_API_KEY") == "s"
        # Eigene Registry per Einstellungen änderbar; ungültige werden abgewiesen
        assert client.put("/api/einstellungen", json={"verzeichnisse_eigene": [{"id": "smithery", "url": "https://x"}]}).status_code in (400, 422)
        assert client.put("/api/einstellungen", json={"verzeichnisse_eigene": []}).status_code == 200
        assert [q["id"] for q in client.get("/api/verzeichnisse").json()] == ["mcp-registry", "smithery"]


@pytest.mark.asyncio
async def test_agent_werkzeuge():
    fake = FakeVerzeichnisse()
    j, _ = baue_jarvis(http_handler=fake)
    _ohne_start(j.manager)
    suchen = j.register.holen("verzeichnis_suchen")
    installieren = j.register.holen("verzeichnis_installieren")
    assert suchen is not None and suchen.risiko == "lesen"
    assert installieren is not None and installieren.risiko == "kritisch"
    text = await suchen.ausfuehren(begriff="notion")
    assert "[Katalog] notion:" in text and "offiziell" in text
    assert "[smithery] node2flow/notion" in text and "Smithery-Konto node2flow" in text
    assert "[mcp-registry] ai.smithery/smithery-notion" in text and "benötigt: SMITHERY_API_KEY" in text
    assert "nur nach seiner Zustimmung" in text
    antwort = await installieren.ausfuehren(quelle="smithery", kennung="node2flow/notion")
    assert "fehlen noch Angaben" in antwort and "NOTION_API_KEY" in antwort
    antwort = await installieren.ausfuehren(quelle="smithery", kennung="node2flow/notion", werte={"NOTION_API_KEY": "s"})
    assert "Notion" in antwort and "notion" in j.manager.konfigs
    gespeichert = json.loads(j.manager.pfad.read_text())["integrationen"]
    assert next(i for i in gespeichert if i["id"] == "notion")["verzeichnis"] == {"quelle": "smithery", "kennung": "node2flow/notion"}
