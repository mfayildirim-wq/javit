import asyncio
import socket
import subprocess
import sys
import time

import httpx
import pytest

from jarvis.geheimnisse import Geheimnisspeicher
from jarvis.integrationen.katalog import Katalog
from jarvis.integrationen.manager import IntegrationsManager
from jarvis.integrationen.mcp_hub import McpVerbindung, bild_aus_ergebnis, ergebnis_zu_text, mcp_werkzeugname, werkzeuge_aus_mcp
from jarvis.werkzeuge import WerkzeugFehler, WerkzeugRegister
from tests.conftest import MINI_SERVER


async def test_stdio_verbindung_direkt(python_befehl):
    v = McpVerbindung("mini", befehl=python_befehl, start_timeout=60)
    try:
        tools = await v.start()
        assert {t.name for t in tools} == {"addieren", "echo", "delete_item", "fehler_werfen"}
        assert v.status == "verbunden"
        werkzeuge = {w.name: w for w in werkzeuge_aus_mcp(v, "aendern", {"echo": "lesen"})}
        assert set(werkzeuge) == {"mini__addieren", "mini__echo", "mini__delete_item", "mini__fehler_werfen"}
        assert werkzeuge["mini__delete_item"].risiko == "kritisch"
        assert werkzeuge["mini__echo"].risiko == "lesen"  # Überschreibung aus dem Katalog
        assert werkzeuge["mini__addieren"].risiko == "aendern"
        assert werkzeuge["mini__addieren"].json_schema["required"] == ["a", "b"]
        assert werkzeuge["mini__addieren"].quelle == "mcp" and werkzeuge["mini__addieren"].integration == "mini"
        assert await werkzeuge["mini__addieren"].ausfuehren(a=2, b=40) == "42"
        assert await werkzeuge["mini__echo"].ausfuehren(text="Grüße „Sir“") == "Echo: Grüße „Sir“"
        with pytest.raises(WerkzeugFehler, match="fehler_werfen"):
            await werkzeuge["mini__fehler_werfen"].ausfuehren()
        # parallele Aufrufe über dieselbe Session
        ergebnisse = await asyncio.gather(*(werkzeuge["mini__addieren"].ausfuehren(a=i, b=i) for i in range(5)))
        assert ergebnisse == [str(2 * i) for i in range(5)]
    finally:
        await v.stop()
    assert v.status == "aus"
    with pytest.raises(WerkzeugFehler, match="nicht verbunden"):
        await v.aufrufen("addieren", {"a": 1, "b": 1})


async def test_stdio_fehlender_befehl():
    v = McpVerbindung("kaputt", befehl=["gibt-es-nicht-xyz-123"], start_timeout=20)
    with pytest.raises(Exception):  # noqa: B017
        await v.start()
    assert v.status == "fehler" and v.fehler


async def test_manager_mit_echtem_mcp_server(python_befehl):
    register = WerkzeugRegister()
    ereignisse = []

    async def ereignis(e):
        ereignisse.append(e)

    m = IntegrationsManager(register, Geheimnisspeicher(), Katalog(), ereignis)
    try:
        befehl = " ".join(f'"{t}"' for t in python_befehl)
        info = await m.hinzufuegen({"name": "Mini Test", "mcp_befehl": befehl, "umgebung": {"MEIN_TOKEN": "geheim123", "MODUS": "x"}})
        assert info["id"] == "mini_test" and info["status"] == "verbunden" and info["werkzeuge"] == 4
        assert "mini_test__addieren" in register
        ok, text = await register.ausfuehren("mini_test__addieren", {"a": 1, "b": 2})
        assert (ok, text) == (True, "3")
        assert ereignisse[-1]["typ"] == "integration_geaendert" and ereignisse[-1]["integration"]["status"] == "verbunden"
        # Geheimnis nicht in der JSON-Datei, aber im Geheimnisspeicher
        inhalt = m.pfad.read_text()
        assert "geheim123" not in inhalt and "MEIN_TOKEN" in inhalt and '"MODUS": "x"' in inhalt
        assert m.geheimnisse.holen("MEIN_TOKEN") == "geheim123"
        # neu verbinden
        info = await m.neu_verbinden("mini_test")
        assert info["status"] == "verbunden" and info["werkzeuge"] == 4
        # Neustart des Managers: lädt aus Datei und startet alle
        await m.alle_stoppen()
        assert "mini_test__addieren" not in register
        m2 = IntegrationsManager(register, Geheimnisspeicher(), Katalog())
        await m2.alle_starten()
        assert m2.liste()[0]["status"] == "verbunden"
        assert await m2.entfernen("mini_test")
        assert "mini_test__addieren" not in register and m2.liste() == []
        await m2.alle_stoppen()
    finally:
        await m.alle_stoppen()


def _freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server():
    port = _freier_port()
    proc = subprocess.Popen([sys.executable, str(MINI_SERVER), "http", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/", timeout=0.2)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(10)


async def test_http_verbindung(http_server):
    v = McpVerbindung("web", url=http_server, kopfzeilen={"Authorization": "Bearer test"}, start_timeout=30)
    try:
        tools = await v.start()
        assert "addieren" in {t.name for t in tools}
        ok, text = await v.aufrufen("addieren", {"a": 20, "b": 22})
        assert ok and text == "42"
    finally:
        await v.stop()


def test_werkzeugname_maximal_64_zeichen():
    assert mcp_werkzeugname("spotify", "play") == "spotify__play"
    lang = mcp_werkzeugname("eine_sehr_lange_integration", "und_ein_noch_viel_laengerer_werkzeugname_mit_mehr")
    assert len(lang) <= 64
    assert lang != mcp_werkzeugname("eine_sehr_lange_integration", "und_ein_noch_viel_laengerer_werkzeugname_mit_meh2")


def test_bild_aus_ergebnis_und_text():
    from types import SimpleNamespace

    ergebnis = SimpleNamespace(content=[SimpleNamespace(type="text", text="Screenshot gespeichert"), SimpleNamespace(type="image", data="aWJn", mime_type="image/png")], structured_content=None, is_error=False)
    assert bild_aus_ergebnis(ergebnis) == "data:image/png;base64,aWJn"
    assert ergebnis_zu_text(ergebnis) == "Screenshot gespeichert\n[Bild: image/png]"
    assert bild_aus_ergebnis(SimpleNamespace(content=[SimpleNamespace(type="text", text="x")])) is None
    v = McpVerbindung("browser", befehl=["npx", "x"])
    assert v.letztes_bild("browser_take_screenshot") is None
