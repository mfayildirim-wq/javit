import json
import re
import shlex
from pathlib import Path

import httpx
import pytest
import yaml

from jarvis.geheimnisse import Geheimnisspeicher
from jarvis.integrationen.katalog import Katalog, KatalogEintrag, platzhalter_ersetzen, platzhalter_finden, standard_katalog_pfad
from jarvis.integrationen.manager import FehlendeWerte, IntegrationsFehler, IntegrationsManager, quelle_deuten
from jarvis.werkzeuge import WerkzeugRegister
from tests.conftest import mock_fabrik

LUCIDE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def test_katalog_laedt_vollstaendig_und_valide():
    k = Katalog([standard_katalog_pfad()])
    assert k.fehler == {}
    assert len(k.eintraege) >= 20
    for datei in standard_katalog_pfad().glob("*.yaml"):
        roh = yaml.safe_load(datei.read_text(encoding="utf-8"))
        e = KatalogEintrag.model_validate(roh)
        assert datei.stem == e.id, f"Dateiname passt nicht zu id: {datei.name}"
        for feld in ("name", "beschreibung", "kategorie", "icon", "hinweis"):
            assert getattr(e, feld).strip(), f"{e.id}: {feld} leer"
        assert LUCIDE.match(e.icon), f"{e.id}: Icon-Name {e.icon}"
        # Alle Platzhalter müssen in benoetigt deklariert sein
        deklariert = {b.name for b in e.benoetigt}
        benutzt = platzhalter_finden([e.befehl or "", e.url or "", e.kopfzeilen, e.rest or []])
        assert benutzt <= deklariert, f"{e.id}: nicht deklariert {benutzt - deklariert}"
        if e.art == "mcp_stdio":
            assert shlex.split(e.befehl)[0] in ("npx", "uvx"), e.id
        for b in e.benoetigt:
            assert b.titel.strip() and re.fullmatch(r"[A-Z][A-Z0-9_]*", b.name), f"{e.id}: {b.name}"
        info = e.als_info()
        assert set(info) >= {"id", "name", "beschreibung", "kategorie", "icon", "art", "benoetigt"}


def test_katalog_suche_und_holen():
    k = Katalog()
    assert k.holen("Spotify").id == "spotify"
    assert k.holen("SPOTIFY").id == "spotify"
    assert {e.id for e in k.suchen("smart home")} >= {"home-assistant", "philips-hue"}
    assert k.holen("gibtsnicht") is None


def test_eigene_katalogeintraege(isoliert):
    ordner = isoliert / "katalog"
    ordner.mkdir(parents=True)
    (ordner / "mein.yaml").write_text("id: mein\nname: Mein\nbeschreibung: x\nkategorie: Eigene\nicon: star\nart: mcp_stdio\nbefehl: npx -y mein-paket\n")
    (ordner / "kaputt.yaml").write_text("id: Kaputt!\nname: x\n")
    k = Katalog()
    assert k.holen("mein") is not None and len(k.fehler) == 1


def test_platzhalter():
    assert platzhalter_ersetzen({"a": ["${X}/api", "${Y}"]}, {"X": "http://h"}) == {"a": ["http://h/api", "${Y}"]}


def test_quelle_deuten():
    k = Katalog()
    assert quelle_deuten("spotify", k) == {"katalog": "spotify"}
    assert quelle_deuten("npx -y @modelcontextprotocol/server-everything", k) == {"mcp_befehl": "npx -y @modelcontextprotocol/server-everything"}
    assert quelle_deuten("http://homeassistant.local:8123/api/mcp", k) == {"mcp_url": "http://homeassistant.local:8123/api/mcp"}
    assert quelle_deuten("https://petstore3.swagger.io/api/v3/openapi.json", k) == {"openapi_url": "https://petstore3.swagger.io/api/v3/openapi.json"}
    with pytest.raises(IntegrationsFehler):
        quelle_deuten("blablubb", k)


def _manager(handler=None, ereignisse=None):
    async def ereignis(e):
        if ereignisse is not None:
            ereignisse.append(e)

    return IntegrationsManager(
        WerkzeugRegister(), Geheimnisspeicher(), Katalog(), ereignis,
        http_client_fabrik=mock_fabrik(handler or (lambda r: httpx.Response(200, json={}))),
    )


async def test_rest_aus_katalog_persistieren_und_entfernen(isoliert):
    ereignisse = []
    m = _manager(ereignisse=ereignisse)
    info = await m.hinzufuegen({"katalog": "wetter"})
    assert info == {"id": "wetter", "name": "Wetter (Open-Meteo)", "art": "rest", "status": "verbunden", "werkzeuge": 2, "katalog": "wetter"}
    assert "wetter__wetter_abrufen" in m.register
    daten = json.loads((isoliert / "integrationen.json").read_text())
    assert daten["integrationen"][0]["id"] == "wetter"
    assert ereignisse[-1] == {"typ": "integration_geaendert", "integration": info}
    # neuer Manager lädt aus Datei
    m2 = _manager()
    assert [i["id"] for i in m2.liste()] == ["wetter"] and m2.liste()[0]["status"] == "aus"
    await m2.alle_starten()
    assert m2.liste()[0]["status"] == "verbunden"
    assert await m2.entfernen("wetter") is True
    assert await m2.entfernen("wetter") is False
    assert json.loads((isoliert / "integrationen.json").read_text())["integrationen"] == []
    assert not m2.register.von_integration("wetter")


async def test_fehlende_werte_und_geheimnisse(isoliert):
    m = _manager()
    with pytest.raises(FehlendeWerte) as fehler:
        await m.hinzufuegen({"katalog": "notion"})
    assert [b.name for b in fehler.value.fehlend] == ["NOTION_TOKEN"]
    assert "notion.so" in fehler.value.hinweis
    # github: geheimer Token landet im Speicher, nicht in der JSON
    info = await m.hinzufuegen({"katalog": "github", "werte": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_supergeheim"}}, starten=False)
    assert info["status"] == "aus"
    inhalt = (isoliert / "integrationen.json").read_text()
    assert "ghp_supergeheim" not in inhalt and "${GITHUB_PERSONAL_ACCESS_TOKEN}" in inhalt
    assert m.geheimnisse.holen("GITHUB_PERSONAL_ACCESS_TOKEN") == "ghp_supergeheim"
    # Ein gespeichertes Geheimnis wird wiederverwendet (z. B. per Sprache „integriere Notion“)
    m.geheimnisse.setzen("NOTION_TOKEN", "ntn_x")
    konfig = m.konfig_aus_anfrage({"katalog": "notion"})
    assert konfig.geheimnisse == ["NOTION_TOKEN"] and konfig.befehl == ["npx", "-y", "@notionhq/notion-mcp-server"]
    # Standardwerte und Platzhalter
    konfig = m.konfig_aus_anfrage({"katalog": "dateisystem"})
    assert konfig.umgebung == {"VERZEICHNIS": "~/Documents"} and konfig.befehl[-1] == "${VERZEICHNIS}"


async def test_openapi_und_mcp_url_formen(isoliert):
    spec = {"openapi": "3.0.0", "servers": [{"url": "/v1"}], "paths": {"/ping": {"get": {"operationId": "ping"}}}}
    anfragen = []

    def handler(request):
        anfragen.append(request)
        if request.url.path.endswith("openapi.json"):
            return httpx.Response(200, json=spec)
        return httpx.Response(200, text="pong")

    m = _manager(handler)
    info = await m.hinzufuegen({"name": "Ping API", "openapi_url": "https://api.example/openapi.json", "auth": {"art": "bearer", "wert": "geheim"}})
    assert info["status"] == "verbunden" and info["werkzeuge"] == 1
    ok, text = await m.register.ausfuehren("ping_api__ping", {})
    assert ok and "pong" in text
    assert str(anfragen[-1].url) == "https://api.example/v1/ping" and anfragen[-1].headers["Authorization"] == "Bearer geheim"
    assert "geheim" not in (isoliert / "integrationen.json").read_text().replace("geheimnisse", "")
    # Spec-Cache: auch offline startbar
    m2 = _manager(lambda r: httpx.Response(503))
    await m2.alle_starten()
    assert m2.liste()[0]["status"] == "verbunden"

    # MCP-URL, nicht erreichbar → Status fehler, aber gespeichert
    m3 = _manager()
    info = await m3.hinzufuegen({"name": "HA", "mcp_url": "http://127.0.0.1:9/mcp", "kopfzeilen": {"Authorization": "Bearer abc"}})
    assert info["status"] == "fehler" and info["fehler"]
    gespeichert = json.loads((isoliert / "integrationen.json").read_text())["integrationen"]
    ha = next(i for i in gespeichert if i["id"] == "ha")
    assert ha["kopfzeilen"]["Authorization"].startswith("${") and "abc" not in json.dumps(ha)


async def test_unbekannte_formen():
    m = _manager()
    with pytest.raises(IntegrationsFehler):
        await m.hinzufuegen({"katalog": "gibtsnicht"})
    with pytest.raises(IntegrationsFehler):
        await m.hinzufuegen({"foo": "bar"})
    with pytest.raises(IntegrationsFehler):
        await m.starten("nichtda")


def test_katalogpfad_env(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_KATALOG", str(tmp_path))
    assert standard_katalog_pfad() == Path(tmp_path)
