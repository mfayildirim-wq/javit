"""Freigaberegel nach Bereich: technisch ohne Rückfrage (außer Löschen/Zugangsdaten), fachlich ab „ändern“."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from jarvis.geheimnisse import Geheimnisspeicher
from jarvis.integrationen.katalog import Katalog
from jarvis.integrationen.manager import IntegrationsFehler, IntegrationsManager
from jarvis.konfig import Einstellungen
from jarvis.server import create_app
from jarvis.werkzeuge import FunktionsWerkzeug, WerkzeugRegister, freigabe_noetig, schema, werkzeug
from jarvis.werkzeuge.dateien import datei_lesen, datei_loeschen
from jarvis.werkzeuge.shell import shell_befehl
from tests.conftest import mock_fabrik, text_chunks, tool_chunks
from tests.helfer import baue_jarvis
from tests.test_agent import Umgebung

pytestmark = pytest.mark.usefixtures("isoliert")


async def _nichts(**_: object) -> str:
    return "ok"


def _wz(name: str, risiko: str, bereich: str | None = None, schutz: bool = False) -> FunktionsWerkzeug:
    return FunktionsWerkzeug(_nichts, name, "Test", schema(), risiko, bereich=bereich, schutz=schutz)  # type: ignore[arg-type]


def test_regel_technisch_und_fachlich():
    # technisch: nie fragen – auch kritisch (Shell, Installieren)
    assert freigabe_noetig(_wz("shell", "kritisch"), {}) is None
    assert freigabe_noetig(_wz("schreiben", "aendern"), {}) is None
    # … außer bei Schutz-Werkzeugen (Löschen, Zugangsdaten)
    assert freigabe_noetig(_wz("loeschen", "kritisch", schutz=True), {}) == "kritisch"
    # … oder wenn technische Freigaben eingeschaltet sind
    assert freigabe_noetig(_wz("shell", "kritisch"), {}, freigabe_technisch=True) == "kritisch"
    assert freigabe_noetig(_wz("schreiben", "aendern"), {}, freigabe_technisch=True) is None
    # fachlich: alles außer Lesen
    assert freigabe_noetig(_wz("mail_senden", "kritisch", "fachlich"), {}) == "kritisch"
    assert freigabe_noetig(_wz("seite_anlegen", "aendern", "fachlich"), {}) == "aendern"
    assert freigabe_noetig(_wz("seiten_suchen", "lesen", "fachlich"), {}) is None
    assert freigabe_noetig(_wz("seite_anlegen", "aendern", "fachlich"), {}, freigabe_fachlich="kritisch") is None
    assert freigabe_noetig(_wz("mail_senden", "kritisch", "fachlich"), {}, freigabe_fachlich="kritisch") == "kritisch"
    assert freigabe_noetig(_wz("mail_senden", "kritisch", "fachlich"), {}, freigabe_fachlich="nie") is None


def test_eingebaute_werkzeuge_eingeordnet(tmp_path):
    assert shell_befehl.bereich == "technisch" and not shell_befehl.schutz
    assert datei_loeschen.schutz and freigabe_noetig(datei_loeschen, {"pfad": str(tmp_path / "x")}) == "kritisch"
    assert datei_lesen.schutz
    assert freigabe_noetig(datei_lesen, {"pfad": str(tmp_path / "notiz.txt")}) is None
    assert freigabe_noetig(datei_lesen, {"pfad": str(tmp_path / ".env")}) == "kritisch"
    # Kalender/Erinnerung/Notiz gelten als fachlich (gleiche Namen auf allen Plattformen)
    @werkzeug("termin_anlegen", "Termin", schema())
    async def termin() -> str:
        return ""

    assert termin.bereich == "fachlich"
    assert _wz("x", "lesen").als_info()["bereich"] == "technisch"
    with pytest.raises(ValueError):
        _wz("x", "lesen", bereich="egal")  # type: ignore[arg-type]
    assert Einstellungen().freigabe_technisch is False and Einstellungen().freigabe_fachlich == "aendern"
    with pytest.raises(ValueError):
        Einstellungen(freigabe_fachlich="immer")
    assert "fachliche Aktion" in _wz("seite_anlegen", "aendern", "fachlich").freigabe_grund({})


async def test_agent_fragt_nur_fachlich():
    u = Umgebung([tool_chunks("c1", "shell_test", {"befehl": "ls"}), text_chunks("Fertig.")])
    u.register.alle_registrieren([_wz("shell_test", "kritisch"), _wz("notion_anlegen", "aendern", "fachlich")])
    await u.agent.verarbeiten("ls")
    assert "freigabe_noetig" not in u.typen() and u.von("werkzeug_ende")[0]["ok"]

    u2 = Umgebung([tool_chunks("c2", "notion_anlegen", {}), text_chunks("Angelegt.")])
    u2.register.alle_registrieren([_wz("notion_anlegen", "aendern", "fachlich")])

    async def reaktion(e):
        if e["typ"] == "freigabe_noetig":
            assert e["risiko"] == "aendern" and e["bereich"] == "fachlich"
            asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(u2.agent.freigabe_beantworten(e["id"], True)))

    u2.reaktion = reaktion
    await u2.agent.verarbeiten("leg an")
    assert "freigabe_noetig" in u2.typen() and u2.von("werkzeug_ende")[0]["ok"]

    u3 = Umgebung([tool_chunks("c3", "shell_test", {"befehl": "ls"}), text_chunks("Fertig.")], freigabe_technisch=True, freigabe_timeout=0.1)
    u3.register.alle_registrieren([_wz("shell_test", "kritisch")])
    await u3.agent.verarbeiten("ls")
    assert u3.von("freigabe_noetig")[0]["bereich"] == "technisch" and not u3.von("werkzeug_ende")[0]["ok"]


async def test_manager_bereich_aus_katalog_und_umstellen():
    m = IntegrationsManager(WerkzeugRegister(), Geheimnisspeicher(), Katalog(), http_client_fabrik=mock_fabrik(lambda r: httpx.Response(500)))
    k_dateien = m.konfig_aus_anfrage({"katalog": "dateisystem", "werte": {"VERZEICHNIS": "~"}})
    assert k_dateien.bereich is None and m.bereich_von(k_dateien) == "technisch"
    k_todo = m.konfig_aus_anfrage({"katalog": "todoist", "werte": {"TODOIST_API_KEY": "x"}})
    assert m.bereich_von(k_todo) == "fachlich"
    k_eigen = m.konfig_aus_anfrage({"name": "Eigen", "mcp_url": "https://s.test/mcp"})
    assert m.bereich_von(k_eigen) == "fachlich"
    k_tech = m.konfig_aus_anfrage({"name": "Eigen2", "mcp_url": "https://s.test/mcp", "bereich": "technisch"})
    assert k_tech.bereich == "technisch"
    with pytest.raises(IntegrationsFehler, match="Bereich"):
        m.konfig_aus_anfrage({"name": "Eigen3", "mcp_url": "https://s.test/mcp", "bereich": "egal"})
    # Umstellen ohne Neustart markiert registrierte Werkzeuge
    m.konfigs[k_eigen.id] = k_eigen
    m.status[k_eigen.id] = "verbunden"
    w = _wz("eigen__tool", "aendern", "fachlich")
    w.integration = k_eigen.id
    m.register.registrieren(w)
    d = await m.bereich_setzen(k_eigen.id, "technisch")
    assert d["bereich"] == "technisch" and w.bereich == "technisch" and m.konfigs[k_eigen.id].bereich == "technisch"
    with pytest.raises(IntegrationsFehler):
        await m.bereich_setzen(k_eigen.id, "egal")
    with pytest.raises(IntegrationsFehler, match="nicht installiert"):
        await m.bereich_setzen("nix", "technisch")


def test_server_bereich_endpunkt():
    j, _ = baue_jarvis()
    app = create_app(j, integrationen_starten=False, stimme_starten=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        assert c.post("/api/integrationen", json={"name": "Eigen", "mcp_url": "https://s.test/mcp", "oauth": False}).status_code == 200
        assert c.get("/api/integrationen/eigen").json()["bereich"] == "fachlich"
        r = c.put("/api/integrationen/eigen/bereich", json={"bereich": "technisch"})
        assert r.status_code == 200 and r.json()["bereich"] == "technisch"
        assert c.put("/api/integrationen/eigen/bereich", json={"bereich": "x"}).status_code == 400
        assert c.put("/api/integrationen/nix/bereich", json={"bereich": "technisch"}).status_code == 404
        katalog = {e["id"]: e for e in c.get("/api/integrationen/katalog").json()}
        assert katalog["dateisystem"]["bereich"] == "technisch" and katalog["notion"]["bereich"] == "fachlich"
        werkzeuge = {w["name"]: w for w in c.get("/api/werkzeuge").json()}
        assert werkzeuge["shell_befehl"]["bereich"] == "technisch"
        assert c.put("/api/einstellungen", json={"freigabe_technisch": True, "freigabe_fachlich": "kritisch"}).json()["freigabe_fachlich"] == "kritisch"
