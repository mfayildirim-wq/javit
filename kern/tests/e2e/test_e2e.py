"""Ende-zu-Ende (ohne Browser): echter Jarvis-Server + Fake-LLM (OpenAI-kompatibel, Streaming)
+ projekteigener Mini-MCP-Server als Integration. Alles über HTTP/WebSocket wie die Oberfläche."""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx
import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from tests.e2e.umgebung import MINI_MCP, E2EUmgebung


@pytest.fixture(scope="module")
def umgebung():
    u = E2EUmgebung()
    try:
        u.starten()
    except Exception:
        print(u.protokolle(), file=sys.stderr)
        u.stoppen()
        raise
    yield u
    u.stoppen()


@pytest.fixture(autouse=True)
def isoliert():  # das globale autouse-Fixture (JARVIS_HOME je Test) hier überschreiben
    yield


def _bis(ws: Any, bedingung, max_n: int = 400, timeout: float = 30) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    gesehen = []
    for _ in range(max_n):
        e = json.loads(ws.recv(timeout=timeout))
        gesehen.append(e)
        if bedingung(e):
            return e, gesehen
    raise AssertionError(f"Ereignis nicht empfangen: {gesehen}")


def _antwort(ws: Any, text: str) -> tuple[str, list[dict[str, Any]]]:
    """Sendet eine Nachricht und wartet auf die Schlussantwort (Zustand wieder bereit)."""
    ws.send(json.dumps({"typ": "nachricht", "text": text}))
    _, gesehen = _bis(ws, lambda e: e["typ"] == "zustand" and e["zustand"] == "bereit")
    enden = [e["text"] for e in gesehen if e["typ"] == "antwort_ende"]
    return (enden[-1] if enden else ""), gesehen


def test_status_und_modell(umgebung):
    s = httpx.get(f"{umgebung.url}/api/status").json()
    assert s["modell"] == "openai/fake" and s["werkzeuge"] > 20
    m = httpx.get(f"{umgebung.url}/api/modelle").json()
    assert m["aktuell"] == "openai/fake"
    assert any(v["id"] == "anthropic/claude-sonnet-5-5" for v in m["vorschlaege"])


def test_text_und_werkzeuge(umgebung):
    with connect(umgebung.ws_url, open_timeout=10) as ws:
        assert json.loads(ws.recv(timeout=10))["typ"] == "zustand"
        text, ereignisse = _antwort(ws, "Hallo Jarvis")
        assert text == "Verstanden: Hallo Jarvis"
        assert any(e["typ"] == "antwort_text" for e in ereignisse)  # gestreamt

        text, ereignisse = _antwort(ws, "Wie spät ist es? Sag mir die Uhrzeit")
        start = next(e for e in ereignisse if e["typ"] == "werkzeug_start")
        ende = next(e for e in ereignisse if e["typ"] == "werkzeug_ende")
        assert start["name"] == "uhrzeit_datum" and ende["ok"] and "Uhr" in ende["ergebnis"]
        assert text.startswith("Erledigt. Ergebnis:") and "Kalenderwoche" in text
        assert {"typ": "zustand", "zustand": "arbeitet"} in ereignisse

        text, ereignisse = _antwort(ws, "Merke dir, dass ich Earl Grey mag")
        assert any(e["typ"] == "werkzeug_start" and e["name"] == "erinnern" for e in ereignisse)
    erinnerungen = httpx.get(f"{umgebung.url}/api/gedaechtnis").json()
    assert any("Earl Grey" in e["text"] for e in erinnerungen)
    verlauf = httpx.get(f"{umgebung.url}/api/verlauf?limit=50").json()
    assert any(v["rolle"] == "nutzer" and v["inhalt"] == "Hallo Jarvis" for v in verlauf)


def test_kritisches_werkzeug_braucht_freigabe(umgebung):
    datei = umgebung.basis / "loesch_mich.txt"
    datei.write_text("weg damit")
    with connect(umgebung.ws_url, open_timeout=10) as ws:
        ws.recv(timeout=10)
        # 1) Ablehnen → Datei bleibt
        ws.send(json.dumps({"typ": "nachricht", "text": f"Lösche Datei {datei}"}))
        freigabe, _ = _bis(ws, lambda e: e["typ"] == "freigabe_noetig")
        assert freigabe["werkzeug"] == "datei_loeschen" and freigabe["risiko"] == "kritisch"
        ws.send(json.dumps({"typ": "freigabe", "id": freigabe["id"], "erlaubt": False}))
        ende, _ = _bis(ws, lambda e: e["typ"] == "werkzeug_ende")
        assert ende["ok"] is False and datei.exists()
        _bis(ws, lambda e: e["typ"] == "zustand" and e["zustand"] == "bereit")
        # 2) Falsche Freigabe-ID wird ignoriert, richtige erlaubt → Datei im Papierkorb
        ws.send(json.dumps({"typ": "nachricht", "text": f"Lösche Datei {datei}"}))
        freigabe, _ = _bis(ws, lambda e: e["typ"] == "freigabe_noetig")
        ws.send(json.dumps({"typ": "freigabe", "id": "freigabe_gibtsnicht", "erlaubt": True}))
        ws.send(json.dumps({"typ": "freigabe", "id": freigabe["id"], "erlaubt": True}))
        ende, _ = _bis(ws, lambda e: e["typ"] == "werkzeug_ende")
        assert ende["ok"] is True and not datei.exists()
        _bis(ws, lambda e: e["typ"] == "zustand" and e["zustand"] == "bereit")


def test_abbrechen_waehrend_freigabe(umgebung):
    datei = umgebung.basis / "bleibt.txt"
    datei.write_text("x")
    with connect(umgebung.ws_url, open_timeout=10) as ws:
        ws.recv(timeout=10)
        ws.send(json.dumps({"typ": "nachricht", "text": f"Lösche Datei {datei}"}))
        _bis(ws, lambda e: e["typ"] == "freigabe_noetig")
        ws.send(json.dumps({"typ": "abbrechen"}))
        _bis(ws, lambda e: e["typ"] == "zustand" and e["zustand"] == "bereit")
    assert datei.exists()


def test_mcp_integration_hinzufuegen_und_aufrufen(umgebung):
    r = httpx.post(
        f"{umgebung.url}/api/integrationen",
        # Ohne „bereich“ gälte der Server als fachlich und „echo“ (Stufe ändern) bräuchte eine Freigabe
        json={"name": "Mini Test", "mcp_befehl": f"{sys.executable} {MINI_MCP}", "bereich": "technisch"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["status"] == "verbunden" and info["werkzeuge"] == 4
    werkzeuge = {w["name"]: w for w in httpx.get(f"{umgebung.url}/api/werkzeuge").json()}
    assert werkzeuge["mini_test__echo"]["quelle"] == "mcp" and werkzeuge["mini_test__echo"]["bereich"] == "technisch"
    assert werkzeuge["mini_test__delete_item"]["risiko"] == "kritisch"
    assert httpx.get(f"{umgebung.url}/api/integrationen/mini_test").json()["bereich"] == "technisch"
    assert any(i["id"] == "mini_test" for i in httpx.get(f"{umgebung.url}/api/integrationen").json())
    with connect(umgebung.ws_url, open_timeout=10) as ws:
        ws.recv(timeout=10)
        text, ereignisse = _antwort(ws, "echo Grüße aus dem Test")
        start = next(e for e in ereignisse if e["typ"] == "werkzeug_start")
        assert start["name"] == "mini_test__echo" and start["integration"] == "mini_test"
        assert "Echo: Grüße aus dem Test" in text
    # Entfernen
    assert httpx.delete(f"{umgebung.url}/api/integrationen/mini_test").status_code == 200
    assert "mini_test__echo" not in {w["name"] for w in httpx.get(f"{umgebung.url}/api/werkzeuge").json()}


def test_fremde_herkunft_wird_im_handshake_abgewiesen(umgebung):
    with pytest.raises(InvalidStatus) as fehler:
        with connect(umgebung.ws_url, origin="https://boese.example", open_timeout=10):
            pass
    assert fehler.value.response.status_code == 403
    r = httpx.put(f"{umgebung.url}/api/modelle", json={"modell": "x"}, headers={"Origin": "https://boese.example"})
    assert r.status_code == 403
    r = httpx.get(f"{umgebung.url}/api/verlauf", headers={"Host": "boese.example"})
    assert r.status_code == 421


def test_kaputte_integration_blockiert_nichts(umgebung):
    r = httpx.post(
        f"{umgebung.url}/api/integrationen",
        json={"name": "Kaputt", "mcp_befehl": "/gibt/es/nicht --stdio"},
        timeout=60,
    )
    assert r.status_code == 200 and r.json()["status"] == "fehler"
    assert httpx.get(f"{umgebung.url}/api/status").status_code == 200
    with connect(umgebung.ws_url, open_timeout=10) as ws:
        ws.recv(timeout=10)
        text, _ = _antwort(ws, "Noch da?")
        assert text == "Verstanden: Noch da?"
    httpx.delete(f"{umgebung.url}/api/integrationen/kaputt")
