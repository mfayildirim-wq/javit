import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from jarvis.server import create_app
from tests.conftest import text_chunks, tool_chunks
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
        assert ws.receive_json()["typ"] == "fehler"


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
