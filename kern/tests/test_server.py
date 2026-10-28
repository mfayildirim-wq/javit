import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from jarvis.server import create_app
from tests.conftest import mock_fabrik, text_chunks, tool_chunks
from tests.helfer import baue_jarvis


WS = "ws://127.0.0.1:8765/ws"


def _client(antworten=None):
    j, skript = baue_jarvis(antworten)
    app = create_app(j, integrationen_starten=False, stimme_starten=False)
    return TestClient(app, base_url="http://127.0.0.1:8765"), j, skript


def _bis(ws, typ, max_n=200):
    gesehen = []
    for _ in range(max_n):
        e = ws.receive_json()
        gesehen.append(e)
        if e["typ"] == typ:
            return e, gesehen
    raise AssertionError(f"{typ} nicht empfangen: {gesehen}")


def test_rest_endpunkte():
    client, j, _ = _client()
    with client as c:
        s = c.get("/api/status").json()
        assert s["modell"] == "openai/gpt-4o" and s["werkzeuge"] > 20 and s["integrationen"] == 0
        assert s["stimme"] == {"aktiv": False, "weckwort": "javit", "hoert": False, "engine": "vosk"}
        assert s["name"] == "Javit"

        m = c.get("/api/modelle").json()
        assert m["aktuell"] == "openai/gpt-4o" and any(v["id"] == "anthropic/claude-sonnet-5-5" for v in m["vorschlaege"])
        assert c.put("/api/modelle", json={"modell": "ollama/llama3.2"}).json() == {"aktuell": "ollama/llama3.2"}
        assert j.einstellungen.modell == "ollama/llama3.2"
        assert c.put("/api/modelle", json={}).status_code == 400

        e = c.get("/api/einstellungen").json()
        assert e["sprache"] == "de" and e["geheimnisse_gesetzt"] == []
        e = c.put("/api/einstellungen", json={"anrede": "Madam", "stimme": {"weckwort": "jarvis"}}).json()
        assert e["anrede"] == "Madam" and e["stimme"]["weckwort"] == "jarvis" and e["stimme"]["aktiv"] is False
        assert c.put("/api/einstellungen", json={"max_werkzeugrunden": "viele"}).status_code == 422

        assert c.put("/api/geheimnisse/OPENAI_API_KEY", json={"wert": "sk-x"}).json()["gespeichert"]
        assert j.geheimnisse.holen("OPENAI_API_KEY") == "sk-x"
        assert "sk-x" not in c.get("/api/einstellungen").text
        assert c.put("/api/geheimnisse/b%C3%B6se name", json={"wert": "x"}).status_code == 400

        w = c.get("/api/werkzeuge").json()
        assert {"name": "shell_befehl", "beschreibung": w[[x["name"] for x in w].index("shell_befehl")]["beschreibung"],
                "quelle": "eingebaut", "risiko": "kritisch", "bereich": "technisch"} in w

        k = c.get("/api/integrationen/katalog").json()
        spotify = next(x for x in k if x["id"] == "spotify")
        assert spotify["icon"] == "music" and spotify["benoetigt"][0]["name"] == "SPOTIFY_CLIENT_ID"

        r = c.post("/api/integrationen", json={"katalog": "github-token"})
        assert r.status_code == 400 and r.json()["fehlend"][0]["name"] == "GITHUB_PERSONAL_ACCESS_TOKEN"
        r = c.post("/api/integrationen", json={"name": "Wetter", "rest": [
            {"name": "wetter_abrufen", "methode": "GET", "url": "https://api.open-meteo.com/v1/forecast",
             "parameter": {"latitude": "zahl", "longitude": "zahl", "current_weather": "text"}, "beschreibung": "Wetter"}]})
        assert r.status_code == 200 and r.json()["status"] == "verbunden" and r.json()["werkzeuge"] == 1
        assert c.get("/api/integrationen").json()[0]["id"] == "wetter"
        assert any(x.get("integration") == "wetter" for x in c.get("/api/werkzeuge").json())
        assert c.post("/api/integrationen/wetter/neu-verbinden").json()["status"] == "verbunden"
        assert c.delete("/api/integrationen/wetter").json() == {"id": "wetter", "entfernt": True}
        assert c.delete("/api/integrationen/wetter").status_code == 404
        assert c.post("/api/integrationen", json={"quatsch": 1}).status_code == 400

        assert c.get("/api/verlauf?limit=5").json() == []
        assert c.get("/api/gedaechtnis").json() == []
        assert c.delete("/api/gedaechtnis").json() == {"geloescht": 0}


def test_herkunftspruefung():
    client, _, _ = _client()
    with client as c:
        assert c.put("/api/modelle", json={"modell": "x"}, headers={"Origin": "https://boese.example"}).status_code == 403
        assert c.put("/api/modelle", json={"modell": "x"}, headers={"Origin": "http://localhost:5173"}).status_code == 200
        r = c.options("/api/modelle", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "PUT"})
        assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
        r = c.get("/api/status", headers={"Origin": "https://boese.example"})
        assert "access-control-allow-origin" not in r.headers
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(WS, headers={"Origin": "https://boese.example"}) as ws:
                ws.receive_json()


@pytest.mark.parametrize(
    "origin",
    ["https://boese.example", "null", "http://127.0.0.1:9999", "http://localhost.boese.example:8765", "file://"],
)
def test_websocket_handshake_weist_fremde_origin_ab(origin):
    """Cross-Site-WebSocket-Hijacking: fremde Seiten dürfen keine Nachrichten/Freigaben senden."""
    client, j, skript = _client()
    with client as c:
        with pytest.raises(WebSocketDisconnect) as fehler:
            with c.websocket_connect(WS, headers={"Origin": origin}) as ws:
                ws.send_json({"typ": "nachricht", "text": "lösche alles"})
                ws.receive_json()
        assert fehler.value.code == 1008
        assert skript.aufrufe == []  # das Modell wurde nie aufgerufen


def test_websocket_eigene_origin_und_ohne_origin_erlaubt():
    client, _, _ = _client()
    with client as c:
        for kopf in ({"Origin": "http://127.0.0.1:8765"}, {"Origin": "http://localhost:8765"}, {}):
            with c.websocket_connect(WS, headers=kopf) as ws:
                assert ws.receive_json()["typ"] == "zustand"


def test_dns_rebinding_host_wird_abgewiesen():
    client, _, _ = _client()
    with client as c:
        assert c.get("/api/verlauf", headers={"Host": "boese.example:8765"}).status_code == 421
        assert c.get("/api/einstellungen", headers={"Host": "localhost:8765"}).status_code == 200
        assert c.get("/api/status", headers={"Host": "[::1]:8765"}).status_code == 200
        # anderer Port per „jarvis start --port 9000“: gleiche Herkunft bleibt erlaubt, fremde nicht
        kopf = {"Host": "127.0.0.1:9000", "Origin": "http://127.0.0.1:9000"}
        assert c.put("/api/modelle", json={"modell": "x"}, headers=kopf).status_code == 200
        kopf = {"Host": "127.0.0.1:9000", "Origin": "http://127.0.0.1:9001"}
        assert c.put("/api/modelle", json={"modell": "x"}, headers=kopf).status_code == 403
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(WS, headers={"Host": "boese.example:8765"}) as ws:
                ws.receive_json()


def test_websocket_ende_zu_ende():
    client, j, skript = _client([
        text_chunks("Einen Moment.") + tool_chunks("call_9", "uhrzeit_datum", {}),
        text_chunks("Es ist spät, Sir."),
    ])
    with client as c, c.websocket_connect(WS) as ws:
        assert ws.receive_json() == {"typ": "zustand", "zustand": "bereit"}
        ws.send_json({"typ": "nachricht", "text": "Wie spät ist es?"})
        werkzeug, gesehen = _bis(ws, "werkzeug_ende")
        assert werkzeug["id"] == "call_9" and werkzeug["ok"] and "Uhr" in werkzeug["ergebnis"]
        ende, rest = _bis(ws, "antwort_ende")
        while ende["text"] != "Es ist spät, Sir.":
            ende, rest2 = _bis(ws, "antwort_ende")
            rest += rest2
        typen = [e["typ"] for e in gesehen + rest]
        assert typen.index("antwort_start") < typen.index("antwort_text") < typen.index("werkzeug_start")
        assert {"typ": "zustand", "zustand": "arbeitet"} in gesehen
        zustand, _ = _bis(ws, "zustand")
        assert zustand["zustand"] == "bereit"
        assert [v["rolle"] for v in c.get("/api/verlauf").json()] == ["nutzer", "jarvis"]
        ws.send_json({"typ": "unbekannt"})
        fehler, _ = _bis(ws, "fehler")  # dazwischen kann „unterhaltung“ (automatischer Titel) kommen
        assert "Unbekannter Nachrichtentyp" in fehler["text"]


def test_websocket_freigabe_und_abbrechen(tmp_path):
    ziel = tmp_path / "weg.txt"
    ziel.write_text("x")
    client, j, skript = _client([
        tool_chunks("c1", "shell_befehl", {"befehl": f"rm {ziel}"}),
        text_chunks("Gelöscht."),
        tool_chunks("c2", "shell_befehl", {"befehl": "echo nie"}),
    ])
    # Shell ist technisch und liefe ohne Rückfrage – für den Freigabe-Test technische Freigaben einschalten
    j.konfig.aktualisieren({"freigabe_technisch": True})
    with client as c, c.websocket_connect(WS) as ws:
        ws.receive_json()
        ws.send_json({"typ": "nachricht", "text": "Lösch die Datei"})
        freigabe, _ = _bis(ws, "freigabe_noetig")
        assert freigabe["werkzeug"] == "shell_befehl" and freigabe["risiko"] == "kritisch" and "rm" in freigabe["grund"]
        ws.send_json({"typ": "freigabe", "id": freigabe["id"], "erlaubt": True})
        ende, _ = _bis(ws, "werkzeug_ende")
        assert ende["ok"] and not ziel.exists()
        _bis(ws, "antwort_ende")

        ws.send_json({"typ": "nachricht", "text": "Noch was"})
        _bis(ws, "freigabe_noetig")
        ws.send_json({"typ": "abbrechen"})
        ende, _ = _bis(ws, "antwort_ende")
        assert ende["typ"] == "antwort_ende"
        zustand, _ = _bis(ws, "zustand")
        assert zustand["zustand"] == "bereit"


def test_stimme_ohne_modul_meldet_fehler(monkeypatch):
    import builtins

    original = builtins.__import__

    def ohne_stimme(name, *a, **kw):
        if name.endswith("stimme") or (a and a[2] and "StimmDienst" in (a[2] or ())):
            raise ImportError("kein Sprachmodul")
        return original(name, *a, **kw)

    client, j, _ = _client()
    with client as c, c.websocket_connect(WS) as ws:
        ws.receive_json()
        monkeypatch.setattr(builtins, "__import__", ohne_stimme)
        ws.send_json({"typ": "stimme", "aktiv": True})
        fehler, _ = _bis(ws, "fehler")
        monkeypatch.setattr(builtins, "__import__", original)
        assert "pip install" in fehler["text"]


def test_oberflaeche_ausliefern(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>Jarvis</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("JARVIS_OBERFLAECHE", str(dist))
    client, _, _ = _client()
    with client as c:
        assert "Jarvis" in c.get("/").text
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert "Jarvis" in c.get("/einstellungen/modelle").text  # SPA-Fallback
        assert c.get("/api/gibtsnicht").status_code == 404
        assert "Jarvis" in c.get("/../../etc/passwd").text


def test_ohne_oberflaeche():
    client, _, _ = _client()
    with client as c:
        assert "npm run build" in c.get("/").json()["hinweis"]


def test_oberflaeche_mime_typen_unabhaengig_vom_system(tmp_path, monkeypatch):
    """Windows: mimetypes liest die Registry und liefert für .js oft text/plain – der Browser
    verweigert dann das Modul-Skript und die Oberfläche bleibt schwarz. Der Server setzt die
    Typen für Vite-Ausgaben deshalb selbst."""
    import starlette.responses

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>Jarvis</html>")
    for name in ("app.js", "app.mjs", "app.css", "logo.svg", "schrift.woff2", "daten.json"):
        (dist / "assets" / name).write_text("x")
    monkeypatch.setenv("JARVIS_OBERFLAECHE", str(dist))
    monkeypatch.setattr(starlette.responses, "guess_type", lambda *_a, **_k: ("text/plain", None))
    client, _, _ = _client()
    with client as c:
        typ = lambda pfad: c.get(pfad).headers["content-type"].split(";")[0]  # noqa: E731
        assert typ("/assets/app.js") == "text/javascript"
        assert typ("/assets/app.mjs") == "text/javascript"
        assert typ("/assets/app.css") == "text/css"
        assert typ("/assets/logo.svg") == "image/svg+xml"
        assert typ("/assets/schrift.woff2") == "font/woff2"
        assert typ("/assets/daten.json") == "application/json"
        assert typ("/") == "text/html"
        assert typ("/einstellungen") == "text/html"


# ---------------------------------------------------------------- Audio im Browser, Stimme-Endpunkte
import json

import httpx

from jarvis.stimme.sprecher import BrowserQuelle, BrowserZiel


class FakeStimmDienst:
    """Ersatz für StimmDienst: merkt sich Quelle/Ziel und spielt beim Start eine Ausgabe über das Ziel."""

    def __init__(self):
        self.quellen: list = []
        self.ziele: list = []
        self.rahmen: list = []
        self.gesprochen: list[str] = []

    def ausgabe_setzen(self, ziel):
        self.ziele.append(ziel)

    async def quelle_setzen(self, quelle, starten=None):
        self.quellen.append((quelle, starten))
        if quelle is not None:
            quelle.starten(self.rahmen.append)
            ziel = self.ziele[-1]
            await ziel.start(24000)
            await ziel.schreiben(b"\x01\x02" * 5000)  # 10000 Bytes → 9600 + 400
            await ziel.ende()

    async def sprechen(self, text):
        self.gesprochen.append(text)

    async def stop(self):
        return None


def test_websocket_browser_audio():
    client, j, _ = _client()
    fake = FakeStimmDienst()
    j.stimme = fake
    with client as c, c.websocket_connect(WS) as ws:
        assert ws.receive_json()["typ"] == "zustand"
        ws.send_json({"typ": "audio_start", "rate": 16000})
        assert ws.receive_json() == {"typ": "sprachausgabe", "zustand": "start", "rate": 24000}
        # Binärframes (9600 + 400 Bytes), dazwischen Pegel-Ereignisse, zum Schluss „ende“
        frames, ereignisse = [], []
        for _ in range(12):
            roh = ws.receive()
            if roh.get("bytes") is not None:
                frames.append(len(roh["bytes"]))
                continue
            e = json.loads(roh["text"])
            ereignisse.append(e)
            if e["typ"] == "sprachausgabe":
                break
        assert frames == [9600, 400]
        assert ereignisse[-1] == {"typ": "sprachausgabe", "zustand": "ende"}
        assert any(e["typ"] == "pegel" for e in ereignisse)
        assert isinstance(fake.quellen[0][0], BrowserQuelle) and fake.quellen[0][1] is True
        assert isinstance(fake.ziele[0], BrowserZiel) and j.browser_audio_aktiv
        # Binärframes vom Browser → 16-kHz-Rahmen (1280 Samples = 2560 Bytes bei 16 kHz)
        ws.send_bytes(b"\x00\x10" * 2560)
        ws.send_json({"typ": "unbekannt"})  # synchronisiert: Antwort kommt nach der Verarbeitung der Bytes
        fehler, _ = _bis(ws, "fehler")
        assert len(fake.rahmen) == 2 and fake.rahmen[0].shape == (1280,)
        ws.send_json({"typ": "audio_stop"})
        ws.send_json({"typ": "unbekannt"})
        _bis(ws, "fehler")
        assert fake.quellen[-1] == (None, False) and fake.ziele[-1] is None and not j.browser_audio_aktiv


def test_stimme_probe_und_modelle(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "openrouter.ai" and request.url.path == "/api/v1/models":
            assert request.url.params["output_modalities"] == "speech"
            return httpx.Response(200, json={"data": [
                {"id": "elevenlabs/eleven-flash-v2.5", "name": "ElevenLabs: Flash v2.5", "supported_voices": ["daniel", "sarah"], "pricing": {"prompt": "0.00004"}},
                {"id": "heygen/heygen-voice-1:free", "name": "frei", "supported_voices": [], "pricing": {"prompt": "0"}},
                {"id": "microsoft/mai-voice-2.1-flash", "name": "MAI Voice", "supported_voices": ["de-DE-Klaus:MAI-Voice-2.1-Flash"], "pricing": {"prompt": "0.000015"}},
            ]})
        return httpx.Response(200, json={})

    client, j, _ = _client()
    j.http_handler = handler
    fake = FakeStimmDienst()
    j.stimme = fake
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    j.konfig.aktualisieren({"stimme": {"tts": "openrouter"}})
    with client as c:
        r = c.post("/api/stimme/probe", json={"text": "Test"})
        assert r.status_code == 400 and "OPENROUTER_API_KEY" in r.json()["detail"]
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
        r = c.post("/api/stimme/probe", json={})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "art": "openrouter", "modell": "elevenlabs/eleven-flash-v2.5", "stimme": "daniel", "ziel": "lautsprecher"}
        assert fake.gesprochen and "Javit" in fake.gesprochen[0]
        from jarvis.stimme import sprecher as sprecher_modul

        sprecher_modul._modell_cache.update(zeit=0.0, daten=None)
        j._http_client_fabrik = mock_fabrik(handler)
        m = c.get("/api/stimme/modelle").json()
        assert [t["id"] for t in m["tts"]] == ["elevenlabs/eleven-flash-v2.5", "microsoft/mai-voice-2.1-flash"]
        assert m["tts"][0] == {"id": "elevenlabs/eleven-flash-v2.5", "name": "ElevenLabs: Flash v2.5", "stimmen": ["daniel", "sarah"], "preis_je_1m_zeichen": 40.0, "standard_stimme": "daniel"}
        assert m["stt"][0]["id"] == "openai/whisper-large-v3" and m["fehler"] is None
