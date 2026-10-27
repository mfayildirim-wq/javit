"""OAuth-Anmeldung: Entdeckung (MCP-Standard, SDK), manueller Flow (Google), Rückrufe, Speicher, Server."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient

from jarvis.geheimnisse import Geheimnisspeicher
from jarvis.integrationen import oauth as oa
from jarvis.integrationen.katalog import Katalog
from jarvis.integrationen.manager import IntegrationsFehler, IntegrationsManager
from jarvis.server import create_app
from jarvis.werkzeuge import WerkzeugRegister
from tests.conftest import mock_fabrik
from tests.helfer import baue_jarvis

RUECKRUF = "http://127.0.0.1:8765/oauth/rueckruf"


def _antwort(status: int, **kw):
    """Antwort passend zur Anfrage-Bibliothek (httpx2 für den MCP-Client, httpx für Token-Anfragen)."""
    return (status, kw)


def _transport(handler, modul):
    def h(r):
        status, kw = handler(r)
        return modul.Response(status, **kw)
    return modul.MockTransport(h)


class FakeAS:
    """Autorisierungs- und Ressourcenserver in einem httpx-Handler (MCP-Standard)."""

    def __init__(self, dcr: bool = True):
        self.dcr = dcr
        self.aufrufe: list[str] = []
        self.token_nr = 0
        self.register_body: dict | None = None

    def __call__(self, r):
        self.aufrufe.append(f"{r.method} {r.url.host}{r.url.path}")
        if r.url.host == "mcp.test":
            if r.url.path == "/.well-known/oauth-protected-resource":
                return _antwort(200, json={"resource": "https://mcp.test", "authorization_servers": ["https://as.test"]})
            if r.headers.get("Authorization", "").startswith("Bearer tok-"):
                return _antwort(200, json={"ok": True, "token": r.headers["Authorization"]})
            return _antwort(401, headers={"WWW-Authenticate": 'Bearer resource_metadata="https://mcp.test/.well-known/oauth-protected-resource"'}, json={"error": "unauthorized"})
        if r.url.host == "as.test":
            if r.url.path == "/.well-known/oauth-authorization-server":
                meta = {"issuer": "https://as.test", "authorization_endpoint": "https://as.test/authorize", "token_endpoint": "https://as.test/token",
                        "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"]}
                if self.dcr:
                    meta["registration_endpoint"] = "https://as.test/register"
                return _antwort(200, json=meta)
            if r.url.path == "/register":
                self.register_body = json.loads(r.content)
                return _antwort(201, json={"client_id": "client-xyz", "redirect_uris": self.register_body["redirect_uris"], "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "client_name": self.register_body.get("client_name")})
            if r.url.path == "/token":
                daten = parse_qs(r.content.decode())
                assert daten["code_verifier"][0] and daten.get("code", [""])[0] == "code-1" or daten.get("grant_type", [""])[0] == "refresh_token"
                self.token_nr += 1
                return _antwort(200, json={"access_token": f"tok-{self.token_nr}", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "ref-1"})
        return _antwort(404)


def _browser_faelschen(monkeypatch, rueckrufe: oa.Rueckrufe, geoeffnet: list[str], code: str = "code-1"):
    """Statt den Browser zu öffnen: URL merken und den Rückruf kurz darauf auslösen."""
    def oeffnen(url: str) -> None:
        geoeffnet.append(url)
        state = oa.state_aus_url(url) or ""
        loop = asyncio.get_running_loop()
        loop.call_later(0.01, lambda: rueckrufe.erfuellen({"code": code, "state": state}))
    monkeypatch.setattr(oa, "browser_oeffnen", oeffnen)


async def test_entdeckung_registriert_sich_und_meldet_an(isoliert, monkeypatch):
    fake = FakeAS()
    rueckrufe = oa.Rueckrufe()
    geoeffnet: list[str] = []
    _browser_faelschen(monkeypatch, rueckrufe, geoeffnet)
    ereignisse: list[dict] = []

    async def melden(e):
        ereignisse.append(e)

    g = Geheimnisspeicher()
    speicher = oa.SchluesselbundSpeicher(g, "mein-server")
    auth = oa.entdeckungs_auth("mein-server", "https://mcp.test/mcp", RUECKRUF, speicher, rueckrufe, melden, oa.OAuthKonfig(extra={"prompt": "consent"}))
    async with httpx2.AsyncClient(transport=_transport(fake, httpx2), auth=auth) as client:
        r = await client.post("https://mcp.test/mcp", json={})
    assert r.status_code == 200 and r.json()["token"] == "Bearer tok-1"
    # Registrierung mit Rückruf-URL und Name, PKCE in der Autorisierungs-URL, Zusatzparameter angehängt
    assert fake.register_body["redirect_uris"] == [RUECKRUF] and fake.register_body["client_name"] == "Javit"
    q = parse_qs(urlparse(geoeffnet[0]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["client-xyz"] and q["prompt"] == ["consent"]
    assert ereignisse[0]["typ"] == "oauth_anmeldung" and ereignisse[0]["integration"] == "mein-server" and ereignisse[0]["url"] == geoeffnet[0]
    # Tokens und Client liegen im Geheimnisspeicher, nicht in Dateien
    assert speicher.angemeldet() and (await speicher.get_client_info()).client_id == "client-xyz"
    assert "tok-1" in (g.holen(speicher.name_tokens) or "")
    # Zweiter Client mit demselben Speicher braucht keine neue Anmeldung
    geoeffnet.clear()
    auth2 = oa.entdeckungs_auth("mein-server", "https://mcp.test/mcp", RUECKRUF, oa.SchluesselbundSpeicher(g, "mein-server"), rueckrufe, melden)
    async with httpx2.AsyncClient(transport=_transport(fake, httpx2), auth=auth2) as client:
        assert (await client.post("https://mcp.test/mcp", json={})).status_code == 200
    assert geoeffnet == []
    speicher.loeschen()
    assert not speicher.angemeldet() and await speicher.get_client_info() is None


async def test_rueckrufe_zeitlimit_und_fehler():
    r = oa.Rueckrufe()
    with pytest.raises(oa.OAuthFehler, match="Keine Antwort"):
        await r.warten("s1", zeitlimit=0.05)
    assert r.offen() == 0
    f = r.erwarten("s2")
    assert r.erfuellen({"state": "falsch", "code": "x"}) is False
    assert r.erfuellen({"state": "s2", "error": "access_denied", "error_description": "Nutzer lehnt ab"}) is True
    with pytest.raises(oa.OAuthFehler, match="abgelehnt"):
        await f
    assert oa.state_aus_url("https://as/authorize?x=1&state=abc") == "abc" and oa.state_aus_url("https://as/") is None
    assert oa.url_mit_extra("https://a/b?x=1", {"access_type": "offline"}) == "https://a/b?x=1&access_type=offline"


class FakeGoogle:
    def __init__(self):
        self.token_aufrufe: list[dict] = []
        self.nr = 0
        self.abgelaufen = False

    def __call__(self, r):
        if r.url.host == "oauth2.test" and r.url.path == "/token":
            daten = {k: v[0] for k, v in parse_qs(r.content.decode()).items()}
            self.token_aufrufe.append(daten)
            self.nr += 1
            return _antwort(200, json={"access_token": f"ya29-{self.nr}", "expires_in": 3600, "refresh_token": "rt-1" if daten["grant_type"] == "authorization_code" else None})
        if r.url.host == "gmailmcp.test":
            tok = r.headers.get("Authorization", "")
            if self.abgelaufen and tok == "Bearer ya29-1":
                return _antwort(401, json={"error": "expired"})
            return _antwort(200, json={"token": tok})
        return _antwort(404)


async def test_manueller_flow_google(isoliert, monkeypatch):
    fake = FakeGoogle()
    rueckrufe = oa.Rueckrufe()
    geoeffnet: list[str] = []
    _browser_faelschen(monkeypatch, rueckrufe, geoeffnet, code="4/abc")
    konfig = oa.OAuthKonfig(modus="manuell", autorisierung_url="https://accounts.test/auth", token_url="https://oauth2.test/token",
                            scopes=["https://www.googleapis.com/auth/gmail.readonly"], client_id="${X}", extra={"access_type": "offline", "prompt": "consent"})
    g = Geheimnisspeicher()
    speicher = oa.SchluesselbundSpeicher(g, "google-gmail")
    auth = oa.ManuellerOAuth("google-gmail", konfig, "cid.apps", "secret-1", RUECKRUF, speicher, rueckrufe, None, lambda **kw: httpx.AsyncClient(transport=_transport(fake, httpx), **kw))
    async with httpx2.AsyncClient(transport=_transport(fake, httpx2), auth=auth) as client:
        r = await client.post("https://gmailmcp.test/mcp/v1", json={})
        assert r.json()["token"] == "Bearer ya29-1"
        q = parse_qs(urlparse(geoeffnet[0]).query)
        assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"] and q["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
        assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["cid.apps"] and q["redirect_uri"] == [RUECKRUF]
        t = fake.token_aufrufe[0]
        assert t["grant_type"] == "authorization_code" and t["code"] == "4/abc" and t["client_secret"] == "secret-1" and t["code_verifier"]
        assert speicher.angemeldet() and speicher.tokens_roh()["refresh_token"] == "rt-1"
        # Token gilt noch → kein neuer Flow
        assert (await client.post("https://gmailmcp.test/mcp/v1", json={})).json()["token"] == "Bearer ya29-1"
        assert len(geoeffnet) == 1
        # Server meldet 401 → Refresh-Token nutzen, Anfrage wiederholen, kein Browser
        fake.abgelaufen = True
        r = await client.post("https://gmailmcp.test/mcp/v1", json={})
        assert r.json()["token"] == "Bearer ya29-2" and fake.token_aufrufe[-1]["grant_type"] == "refresh_token"
        assert len(geoeffnet) == 1 and speicher.tokens_roh()["refresh_token"] == "rt-1"  # Refresh-Token bleibt erhalten


def test_auth_fuer_und_konfig_pruefung(isoliert):
    g = Geheimnisspeicher()
    r = oa.Rueckrufe()
    assert oa.auth_fuer("x", "https://s", None, {}, g, RUECKRUF, r) is None
    a = oa.auth_fuer("x", "https://s", {"modus": "entdeckung"}, {}, g, RUECKRUF, r)
    assert a.__class__.__name__ == "OAuthClientProvider"
    manuell = {"modus": "manuell", "autorisierung_url": "https://a", "token_url": "https://t", "client_id": "${CID}", "client_secret": "${CS}"}
    with pytest.raises(oa.OAuthFehler, match="Client-ID"):
        oa.auth_fuer("x", "https://s", manuell, {}, g, RUECKRUF, r)
    m = oa.auth_fuer("x", "https://s", manuell, {"CID": "id1", "CS": "s1"}, g, RUECKRUF, r)
    assert isinstance(m, oa.ManuellerOAuth) and m.client_id == "id1" and m.client_secret == "s1"
    with pytest.raises(ValueError):
        oa.OAuthKonfig(modus="manuell").pruefen()


def test_katalog_oauth_eintraege_valide():
    k = Katalog()
    assert k.fehler == {}
    notion = k.holen("notion")
    assert notion.oauth.modus == "entdeckung" and notion.vertrauen == "offiziell" and notion.quelle.startswith("https://")
    info = notion.als_info()
    assert info["oauth"] == "entdeckung" and info["vertrauen"] == "offiziell"
    gmail = k.holen("google-gmail")
    assert gmail.gruppe == "google-workspace" and gmail.oauth.modus == "manuell" and gmail.oauth.extra == {"access_type": "offline", "prompt": "consent"}
    assert [b.name for b in gmail.benoetigt] == ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"]
    assert len([e for e in k.alle() if e.gruppe == "google-workspace"]) == 9
    assert k.holen("aws").url.startswith("https://aws-mcp.${AWS_MCP_REGION}") and k.holen("microsoft-learn").oauth is None
    # offiziell vor community innerhalb der Kategorie
    entw = [e.id for e in k.alle() if e.kategorie == "Entwicklung"]
    assert entw.index("github") < entw.index("git")


async def test_manager_mcp_url_bekommt_oauth_und_abmelden(isoliert, monkeypatch):
    fake = FakeAS()
    rueckrufe_gesehen: list[oa.Rueckrufe] = []
    m = IntegrationsManager(WerkzeugRegister(), Geheimnisspeicher(), Katalog(), http_client_fabrik=mock_fabrik(fake))
    # Eigene MCP-URL ohne Authorization → OAuth per Entdeckung; mit Authorization → keins
    k = m.konfig_aus_anfrage({"name": "Mein", "mcp_url": "https://mcp.test/mcp"})
    assert k.oauth == {"modus": "entdeckung"}
    k2 = m.konfig_aus_anfrage({"name": "Mit Token", "mcp_url": "https://mcp.test/mcp", "kopfzeilen": {"Authorization": "Bearer x"}})
    assert k2.oauth is None
    k3 = m.konfig_aus_anfrage({"name": "Ohne", "mcp_url": "https://mcp.test/mcp", "oauth": False})
    assert k3.oauth is None
    # Katalog: Notion übernimmt oauth, Google die manuelle Konfiguration mit Platzhaltern
    n = m.konfig_aus_anfrage({"katalog": "notion"})
    assert n.oauth == {"modus": "entdeckung"} and n.url == "https://mcp.notion.com/mcp"
    g = m.konfig_aus_anfrage({"katalog": "google-gmail", "werte": {"GOOGLE_OAUTH_CLIENT_ID": "cid", "GOOGLE_OAUTH_CLIENT_SECRET": "cs"}})
    assert g.oauth["client_id"] == "${GOOGLE_OAUTH_CLIENT_ID}" and g.geheimnisse == ["GOOGLE_OAUTH_CLIENT_SECRET"] and g.umgebung == {"GOOGLE_OAUTH_CLIENT_ID": "cid"}
    # Google ohne Client-ID → fehlende Werte (vor dem Start)
    with pytest.raises(IntegrationsFehler, match="GOOGLE_OAUTH_CLIENT_ID"):
        await m.hinzufuegen({"katalog": "google-gmail", "werte": {"GOOGLE_OAUTH_CLIENT_ID": "", "GOOGLE_OAUTH_CLIENT_SECRET": "cs"}}, starten=False)
    # Details/Abmelden
    await m.hinzufuegen({"name": "Mein", "mcp_url": "https://mcp.test/mcp"}, starten=False)
    oa.SchluesselbundSpeicher(m.geheimnisse, "mein").tokens_roh_setzen({"access_token": "t"})
    assert m.details("mein")["oauth"] == {"modus": "entdeckung", "angemeldet": True}
    info = await m.abmelden("mein")
    assert info["status"] == "aus" and m.details("mein")["oauth"]["angemeldet"] is False
    with pytest.raises(IntegrationsFehler):
        await m.abmelden("nix")
    assert await m.entfernen("mein") is True


def test_server_rueckruf_und_abmelden(isoliert):
    j, _ = baue_jarvis()
    app = create_app(j, integrationen_starten=False, stimme_starten=False)
    assert j.manager.rueckruf_url() == "http://127.0.0.1:8765/oauth/rueckruf"
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        # ohne wartende Anmeldung
        r = c.get("/oauth/rueckruf?code=x&state=unbekannt")
        assert r.status_code == 404 and "Keine wartende Anmeldung" in r.text
        r = c.get("/oauth/rueckruf?error=access_denied&state=unbekannt")
        assert r.status_code == 200 and "abgelehnt" in r.text
        asyncio.get_event_loop().run_until_complete(j.manager.hinzufuegen({"name": "Mein", "mcp_url": "https://mcp.test/mcp"}, starten=False)) if False else None
        j.manager.konfigs["mein"] = j.manager.konfig_aus_anfrage({"name": "Mein", "mcp_url": "https://mcp.test/mcp"})
        assert c.post("/api/integrationen/mein/abmelden").json()["status"] == "aus"
        assert c.post("/api/integrationen/nix/abmelden").status_code == 404
        assert c.post("/api/integrationen/nix/anmelden").status_code == 404
