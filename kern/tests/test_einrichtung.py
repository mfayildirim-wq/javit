"""Feldtypen, Details ohne Geheimnisse, Ändern, Einrichtungsschritte, Fehlertexte und Agent-Führung."""

from __future__ import annotations

import base64
import json
import sys

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from jarvis.geheimnisse import Geheimnisspeicher
from jarvis.integrationen import einrichtung as ein
from jarvis.integrationen.katalog import Benoetigt, Katalog, KatalogEintrag
from jarvis.integrationen.manager import IntegrationsFehler, IntegrationsManager, wert_pruefen
from jarvis.server import create_app
from jarvis.werkzeuge import WerkzeugRegister
from tests.conftest import mock_fabrik
from tests.helfer import baue_jarvis


def _manager(handler=None):
    return IntegrationsManager(
        WerkzeugRegister(), Geheimnisspeicher(), Katalog(),
        http_client_fabrik=mock_fabrik(handler or (lambda r: httpx.Response(200, json={}))),
    )


def test_feldtypen_und_pruefung(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Dokumente").mkdir()
    (tmp_path / "schluessel.json").write_text("{}")
    ordner = Benoetigt(name="VERZEICHNIS", titel="Ordner", typ="ordner")
    assert wert_pruefen(ordner, " ~/Dokumente ") == "~/Dokumente"
    with pytest.raises(IntegrationsFehler, match="Ordner nicht gefunden"):
        wert_pruefen(ordner, "~/Gibtsnicht")
    with pytest.raises(IntegrationsFehler, match="Platzhalter"):
        wert_pruefen(ordner, "Documents/*")
    datei = Benoetigt(name="D", titel="Datei", typ="datei")
    assert wert_pruefen(datei, "~/schluessel.json") == "~/schluessel.json"
    with pytest.raises(IntegrationsFehler, match="Datei nicht gefunden"):
        wert_pruefen(datei, "~/Dokumente")
    with pytest.raises(IntegrationsFehler, match="http"):
        wert_pruefen(Benoetigt(name="U", titel="URL", typ="url"), "homeassistant.local")
    # Typ wird abgeleitet; „geheim“ als Typ setzt geheim
    assert Benoetigt(name="A", titel="a").typ == "text" and Benoetigt(name="A", titel="a", geheim=True).typ == "geheim"
    assert Benoetigt(name="A", titel="a", typ="geheim").geheim is True
    k = Katalog()
    info = k.holen("dateisystem").als_info()
    assert info["benoetigt"][0]["typ"] == "ordner" and info["benoetigt"][0]["standard"] == "~/Documents"
    assert [s["titel"] for s in k.holen("gmail").als_info()["einrichtung"]][2:] == ["OAuth-Datei ablegen", "Bei Google anmelden"]


async def test_hinzufuegen_prueft_ordner(isoliert, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    m = _manager()
    with pytest.raises(IntegrationsFehler, match="Ordner nicht gefunden"):
        await m.hinzufuegen({"katalog": "dateisystem", "werte": {"VERZEICHNIS": "Documents/x"}}, starten=False)


async def test_details_ohne_geheimnisse_und_aendern(isoliert):
    m = _manager()
    await m.hinzufuegen({"katalog": "github", "werte": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_geheim"}}, starten=False)
    d = m.details("github")
    assert d["werte"] == {"GITHUB_PERSONAL_ACCESS_TOKEN": "gespeichert"}
    assert d["konfig"]["kopfzeilen"] == {"Authorization": "gespeichert"} and d["konfig"]["geheimnisse"] == ["GITHUB_PERSONAL_ACCESS_TOKEN"]
    assert "ghp_geheim" not in json.dumps(d) and d["katalog"]["id"] == "github" and d["werkzeug_liste"] == []
    # Ändern ohne neuen Token → Token bleibt, Name ändert sich, Kennung bleibt
    d = await m.aendern("github", {"werte": {"GITHUB_PERSONAL_ACCESS_TOKEN": "gespeichert"}, "name": "GitHub Arbeit"})
    assert d["id"] == "github" and d["name"] == "GitHub Arbeit" and m.geheimnisse.holen("GITHUB_PERSONAL_ACCESS_TOKEN") == "ghp_geheim"
    assert "ghp_geheim" not in (isoliert / "integrationen.json").read_text()
    # neuer Token wird übernommen
    await m.aendern("github", {"werte": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_neu"}})
    assert m.geheimnisse.holen("GITHUB_PERSONAL_ACCESS_TOKEN") == "ghp_neu"
    with pytest.raises(IntegrationsFehler):
        await m.aendern("gibtsnicht", {})
    with pytest.raises(IntegrationsFehler):
        m.details("gibtsnicht")


async def test_aendern_eigene_mcp_url_behaelt_geheime_kopfzeile(isoliert):
    m = _manager()
    await m.hinzufuegen({"name": "Mein Server", "mcp_url": "http://127.0.0.1:9/mcp", "kopfzeilen": {"Authorization": "Bearer alt", "X-Org": "acme"}}, starten=False)
    k = m.konfigs["mein_server"]
    assert k.kopfzeilen["Authorization"] == "${JARVIS_MEIN_SERVER_AUTHORIZATION}" and k.geheimnisse == ["JARVIS_MEIN_SERVER_AUTHORIZATION"]
    d = await m.aendern("mein_server", {"mcp_url": "http://127.0.0.1:9/mcp2", "kopfzeilen": {"Authorization": "gespeichert", "X-Org": "neu"}})
    k = m.konfigs["mein_server"]
    assert d["id"] == "mein_server" and k.url == "http://127.0.0.1:9/mcp2" and k.kopfzeilen["X-Org"] == "neu"
    assert k.kopfzeilen["Authorization"] == "${JARVIS_MEIN_SERVER_AUTHORIZATION}" and "JARVIS_MEIN_SERVER_AUTHORIZATION" in k.geheimnisse
    assert m.geheimnisse.holen("JARVIS_MEIN_SERVER_AUTHORIZATION") == "Bearer alt"
    assert list(m.konfigs) == ["mein_server"]
    with pytest.raises(IntegrationsFehler, match="Quelle"):
        await m.aendern("mein_server", {"name": "x"})


def _eintrag(tmp_path, befehl: str | None = None) -> KatalogEintrag:
    return KatalogEintrag.model_validate({
        "id": "testdienst", "name": "Testdienst", "beschreibung": "x", "kategorie": "Test", "icon": "star",
        "art": "mcp_stdio", "befehl": "npx -y test", "hinweis": "h",
        "einrichtung": [
            {"titel": "Konsole", "link": "https://example.org"},
            {"titel": "Datei", "datei": str(tmp_path / "ziel" / "oauth.json")},
            {"titel": "Anmelden", "befehl": befehl or f"{sys.executable} -c \"print('hallo'); print('welt')\""},
        ],
    })


def test_einrichtung_stand_und_datei(tmp_path):
    e = _eintrag(tmp_path)
    stand = ein.einrichtung_stand(e)
    assert [s["erfuellt"] for s in stand] == [None, False, None]
    with pytest.raises(ein.EinrichtungsFehler, match="keine Datei"):
        ein.datei_ablegen(e, 0, base64.b64encode(b"{}").decode())
    with pytest.raises(ein.EinrichtungsFehler, match="JSON"):
        ein.datei_ablegen(e, 1, base64.b64encode(b"kein json").decode())
    with pytest.raises(ein.EinrichtungsFehler, match="Base64"):
        ein.datei_ablegen(e, 1, "%%%")
    with pytest.raises(ein.EinrichtungsFehler, match="zu groß"):
        ein.datei_ablegen(e, 1, base64.b64encode(b"x" * (ein.MAX_DATEI_BYTES + 1)).decode())
    with pytest.raises(ein.EinrichtungsFehler, match="Schritt 9"):
        ein.datei_ablegen(e, 9, "")
    pfad = ein.datei_ablegen(e, 1, base64.b64encode(b'{"installed": {}}').decode())
    assert pfad.read_text() == '{"installed": {}}' and ein.einrichtung_stand(e)[1]["erfuellt"] is True


async def test_einrichtung_befehl_ausfuehren(isoliert, tmp_path):
    e = _eintrag(tmp_path)
    a = ein.Ausfuehrer()
    assert a.stand("testdienst", 2)["status"] == "nie"
    with pytest.raises(ein.EinrichtungsFehler, match="keinen Befehl"):
        await a.starten(e, 0)
    stand = await a.starten(e, 2)
    assert stand["status"] == "laeuft"
    await a.laeufe[("testdienst", 2)].task
    stand = a.stand("testdienst", 2)
    assert stand["status"] == "fertig" and stand["rueckgabe"] == 0 and stand["ausgabe"][-2:] == ["hallo", "welt"]
    assert (isoliert / "logs" / "einrichtung-testdienst.log").exists()
    # fehlschlagender Befehl
    e2 = _eintrag(tmp_path, f"{sys.executable} -c \"import sys; print('kaputt'); sys.exit(3)\"")
    await a.starten(e2, 2)
    await a.laeufe[("testdienst", 2)].task
    assert a.stand("testdienst", 2)["status"] == "fehler" and a.stand("testdienst", 2)["rueckgabe"] == 3
    e3 = _eintrag(tmp_path, "programm-das-es-nicht-gibt-xyz --x")
    await a.starten(e3, 2)
    await a.laeufe[("testdienst", 2)].task
    assert a.stand("testdienst", 2)["status"] == "fehler"


def test_server_details_aendern_einrichtung(isoliert, tmp_path, monkeypatch):
    # eigener Katalogeintrag mit Einrichtung
    ordner = isoliert / "katalog"
    ordner.mkdir(parents=True)
    (ordner / "testdienst.yaml").write_text(yaml.safe_dump(_eintrag(tmp_path).model_dump(exclude_none=True), allow_unicode=True))
    j, _ = baue_jarvis()
    app = create_app(j, integrationen_starten=False, stimme_starten=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        k = c.get("/api/integrationen/katalog/testdienst").json()
        assert k["installiert"] is False and [s["erfuellt"] for s in k["einrichtung"]] == [None, False, None]
        assert c.get("/api/integrationen/katalog/nix").status_code == 404
        r = c.post("/api/integrationen/katalog/testdienst/einrichtung/1/datei", json={"inhalt_base64": base64.b64encode(b"{}").decode()})
        assert r.status_code == 200 and r.json()["einrichtung"][1]["erfuellt"] is True
        assert c.post("/api/integrationen/katalog/testdienst/einrichtung/0/datei", json={"inhalt_base64": "e30="}).status_code == 400
        assert c.get("/api/integrationen/katalog/testdienst/einrichtung/2/stand").json()["status"] == "nie"
        assert c.post("/api/integrationen/katalog/testdienst/einrichtung/0/ausfuehren").status_code == 400
        assert c.post("/api/integrationen/katalog/testdienst/einrichtung/2/ausfuehren").json()["status"] == "laeuft"

        assert c.get("/api/integrationen/github").status_code == 404
        c.post("/api/integrationen", json={"katalog": "github", "werte": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_x"}})
        d = c.get("/api/integrationen/github").json()
        assert d["werte"] == {"GITHUB_PERSONAL_ACCESS_TOKEN": "gespeichert"} and "ghp_x" not in c.get("/api/integrationen/github").text
        d = c.put("/api/integrationen/github", json={"name": "GitHub privat", "werte": {}}).json()
        assert d["name"] == "GitHub privat" and j.geheimnisse.holen("GITHUB_PERSONAL_ACCESS_TOKEN") == "ghp_x"
        assert c.put("/api/integrationen/nix", json={}).status_code == 404
        assert c.get("/api/integrationen/github/protokoll").json() == {"zeilen": []}
        assert c.get("/api/integrationen/nix/protokoll").status_code == 404


async def test_prompt_nennt_fehlerhafte_integrationen(isoliert):
    m = _manager(lambda r: httpx.Response(500))
    await m.hinzufuegen({"katalog": "github", "werte": {"GITHUB_PERSONAL_ACCESS_TOKEN": "x"}}, starten=False)
    m.status["github"] = "fehler"
    m.fehler["github"] = "401 Unauthorized"
    zeilen = m.verbundene_beschreibungen()
    assert zeilen == ["GitHub (github): NICHT VERBUNDEN – 401 Unauthorized"]


async def test_agent_werkzeuge_fuer_einrichtung(isoliert, tmp_path):
    ordner = isoliert / "katalog"
    ordner.mkdir(parents=True)
    (ordner / "testdienst.yaml").write_text(yaml.safe_dump(_eintrag(tmp_path).model_dump(exclude_none=True), allow_unicode=True))
    j, _ = baue_jarvis()
    wz = {w.name: w for w in j.register.alle()}
    for name in ("integration_details", "integration_einrichtung", "integration_konfigurieren", "integration_schritt_ausfuehren"):
        assert name in wz, name
    assert wz["integration_schritt_ausfuehren"].risiko == "kritisch" and wz["integration_details"].risiko == "lesen"
    text = await wz["integration_einrichtung"].ausfuehren(id="testdienst")
    assert "1. Konsole" in text and "✗ offen" in text and "Nächster offener Schritt: Datei" in text
    await j.manager.hinzufuegen({"katalog": "github", "werte": {"GITHUB_PERSONAL_ACCESS_TOKEN": "x"}}, starten=False)
    text = await wz["integration_details"].ausfuehren(id="github")
    assert "GitHub (github, mcp_http)" in text and "x" not in text.split("Werte:")[1].split("\n")[0].replace("gespeichert", "")
    text = await wz["integration_konfigurieren"].ausfuehren(id="github", werte={}, name="GH")
    assert text.startswith("GH: Status")
    text = await wz["integration_schritt_ausfuehren"].ausfuehren(id="testdienst", schritt=3)
    assert "läuft im Hintergrund" in text
    await j.einrichtung_ausfuehrer.laeufe[("testdienst", 2)].task
