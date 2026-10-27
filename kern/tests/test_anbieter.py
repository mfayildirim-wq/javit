"""Anbieter-Register, Übersetzung für OpenAI-kompatible Anbieter und Live-Modelllisten."""

from __future__ import annotations

import httpx
import pytest

from jarvis import anbieter as ab
from tests.helfer import mock_fabrik


def test_eingebaute_anbieter_eindeutig_und_vollstaendig():
    ids = [a.id for a in ab.EINGEBAUTE]
    assert len(ids) == len(set(ids))
    for erwartet in ("ollama", "anthropic", "openai", "gemini", "openrouter", "deepseek", "moonshot", "zai", "opencode", "groq", "mistral", "xai"):
        assert erwartet in ids
    for a in ab.EINGEBAUTE:
        assert ab.ANBIETER_ID.match(a.id)
        assert a.vorschlaege, a.id
        # Anbieter ohne LiteLLM-Präfix brauchen eine Basis-URL
        assert a.praefix is not None or a.api_base


def test_verfuegbar_haengt_am_schluessel(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    a = ab.anbieter_finden("openrouter")
    assert a is not None and a.verfuegbar() is False and a.als_info()["schluessel"] == "OPENROUTER_API_KEY"
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert a.verfuegbar() is True
    assert ab.anbieter_finden("ollama").verfuegbar() is True  # kein Schlüssel nötig


def test_eigener_anbieter_validierung():
    a = ab.eigener_anbieter({"id": "Mein-Server", "name": "Mein Server", "api_base": "http://127.0.0.1:1234/v1/", "schluessel": "MEIN_KEY", "modelle": ["llama"]})
    assert a.id == "mein-server" and a.eigen and a.praefix is None
    assert a.api_base == "http://127.0.0.1:1234/v1" and a.modelle_url == "http://127.0.0.1:1234/v1/models"
    assert a.vorschlaege == (("llama", "llama"),)
    assert ab.eigener_anbieter({"id": "lokal", "api_base": "http://x"}).schluessel is None
    with pytest.raises(ValueError, match="Kennung"):
        ab.eigener_anbieter({"id": "Böse Id", "api_base": "http://x"})
    with pytest.raises(ValueError, match="eingebauter"):
        ab.eigener_anbieter({"id": "openai", "api_base": "http://x"})
    with pytest.raises(ValueError, match="http"):
        ab.eigener_anbieter({"id": "ok", "api_base": "ftp://x"})
    with pytest.raises(ValueError, match="Schlüsselname"):
        ab.eigener_anbieter({"id": "ok", "api_base": "http://x", "schluessel": "klein"})
    # kaputte Einträge werden in der Gesamtliste übersprungen
    assert [a.id for a in ab.alle_anbieter([{"id": "ok", "api_base": "http://x"}, {"id": "!!"}])][-1] == "ok"


def test_anbieter_von_modell_und_aufruf_parameter(monkeypatch):
    assert ab.anbieter_von_modell("ollama_chat/qwen").id == "ollama"
    assert ab.anbieter_von_modell("anthropic/claude-sonnet-5-5").id == "anthropic"
    assert ab.anbieter_von_modell("unbekannt/x") is None
    # Native LiteLLM-Anbieter bleiben unverändert (Schlüssel liest LiteLLM aus der Umgebung)
    assert ab.aufruf_parameter("openrouter/deepseek/deepseek-v4.1-flash") == {"model": "openrouter/deepseek/deepseek-v4.1-flash"}
    assert ab.aufruf_parameter("unbekannt/x") == {"model": "unbekannt/x"}
    # OpenCode → openai/<modell> mit eigener Basis und eigenem Schlüssel (nie OPENAI_API_KEY)
    monkeypatch.setenv("OPENCODE_API_KEY", "oc-1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    p = ab.aufruf_parameter("opencode/kimi-k2.5")
    assert p == {"model": "openai/kimi-k2.5", "api_base": "https://opencode.ai/inference/openai/v1", "api_key": "oc-1"}
    # eigener Anbieter ohne Schlüssel bekommt einen Platzhalter, damit LiteLLM nicht nach OPENAI_API_KEY greift
    eigene = [{"id": "lmstudio", "api_base": "http://127.0.0.1:1234/v1"}]
    p = ab.aufruf_parameter("lmstudio/llama", eigene)
    assert p["model"] == "openai/llama" and p["api_base"] == "http://127.0.0.1:1234/v1" and p["api_key"] == "ohne"


def test_modelle_parsen_openrouter_mit_kostenlos_und_werkzeugen():
    a = ab.anbieter_finden("openrouter")
    daten = {"data": [
        {"id": "deepseek/deepseek-v4.1-flash", "name": "DeepSeek", "pricing": {"prompt": "0.0000002", "completion": "0.000001"}, "supported_parameters": ["tools", "temperature"]},
        {"id": "google/gemma-4-31b-it:free", "name": "Gemma (free)", "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["temperature"]},
        {"id": "openai/text-embedding-3-large", "name": "Embedding", "pricing": {"prompt": "0", "completion": "0"}},
    ]}
    e = {m.id: m for m in ab.modelle_parsen(a, daten)}
    assert e["deepseek/deepseek-v4.1-flash"].kostenlos is False and e["deepseek/deepseek-v4.1-flash"].werkzeuge is True
    assert e["google/gemma-4-31b-it:free"].kostenlos is True and e["google/gemma-4-31b-it:free"].werkzeuge is False
    assert "openai/text-embedding-3-large" not in e
    assert all(m.live for m in e.values())


def test_modelle_parsen_gemini_anthropic_opencode():
    gemini = ab.anbieter_finden("gemini")
    daten = {"models": [
        {"name": "models/gemini-3.8-flash", "displayName": "Gemini 3.8 Flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/embedding-001", "displayName": "Embedding", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/gemini-tts", "displayName": "TTS", "supportedGenerationMethods": ["generateContent"]},
    ]}
    assert [m.id for m in ab.modelle_parsen(gemini, daten)] == ["gemini-3.8-flash"]
    anthropic = ab.anbieter_finden("anthropic")
    m = ab.modelle_parsen(anthropic, {"data": [{"id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5"}]})
    assert m[0].name == "Claude Sonnet 5.5" and m[0].kostenlos is None
    opencode = ab.anbieter_finden("opencode")
    m = ab.modelle_parsen(opencode, {"data": [{"id": "big-pickle"}, {"id": "glm-5.3-flash-free"}, {"id": "glm-5.3-flash"}, {"id": "kimi-k2.5"}]})
    assert [x.id for x in m] == ["glm-5.3-flash", "kimi-k2.5"]
    assert ab.modelle_parsen(opencode, "kaputt") == [] and ab.modelle_parsen(opencode, {"data": [1, {"id": ""}]}) == []


def test_sortiert_vorschlaege_zuerst():
    a = ab.anbieter_finden("deepseek")
    live = [ab.ModellEintrag("zzz", "zzz", live=True), ab.ModellEintrag("deepseek-v4-pro", "deepseek-v4-pro", live=True), ab.ModellEintrag("aaa", "aaa", live=True), ab.ModellEintrag("deepseek-flash", "deepseek-flash", live=True)]
    s = ab.sortiert(a, live)
    assert [m.id for m in s] == ["deepseek-flash", "deepseek-v4-pro", "aaa", "zzz"]
    assert s[0].name == "DeepSeek V4.1 Flash"  # Anzeigename aus den Vorschlägen
    assert [m.id for m in ab.vorschlaege(a)] == ["deepseek-flash", "deepseek-v4-pro"]


async def test_modelllisten_live_cache_und_fehler(monkeypatch):
    aufrufe: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        aufrufe.append(request)
        if request.url.host == "api.deepseek.com":
            return httpx.Response(200, json={"data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]})
        if request.url.host == "api.anthropic.com":
            assert request.headers["x-api-key"] == "ak" and "anthropic-version" in request.headers
            return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5-5", "display_name": "Sonnet"}]})
        if request.url.host == "generativelanguage.googleapis.com":
            assert request.headers["x-goog-api-key"] == "gk"
            return httpx.Response(500)
        if request.url.host == "openrouter.ai":
            assert "authorization" not in request.headers  # öffentlich, ohne Schlüssel abrufbar
            return httpx.Response(200, json={"data": [{"id": "x/y:free", "pricing": {"prompt": "0", "completion": "0"}}]})
        raise httpx.ConnectError("weg")

    listen = ab.ModellListen(mock_fabrik(handler))
    deepseek = ab.anbieter_finden("deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert await listen.laden(deepseek) == []  # ohne Schlüssel keine Abfrage
    assert aufrufe == []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dk")
    erst = await listen.laden(deepseek)
    assert [m.id for m in erst] == ["deepseek-flash", "deepseek-v4-pro"] and aufrufe[-1].headers["authorization"] == "Bearer dk"
    await listen.laden(deepseek)
    assert len(aufrufe) == 1  # aus dem Cache
    await listen.laden(deepseek, neu=True)
    assert len(aufrufe) == 2
    listen.vergessen("deepseek")
    await listen.laden(deepseek)
    assert len(aufrufe) == 3

    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    assert [m.name for m in await listen.laden(ab.anbieter_finden("anthropic"))] == ["Sonnet"]
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    assert await listen.laden(ab.anbieter_finden("gemini")) == []  # HTTP-Fehler → leer (Rückfall auf Vorschläge)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert [m.id for m in await listen.laden(ab.anbieter_finden("openrouter"))] == ["x/y:free"]
    monkeypatch.setenv("XAI_API_KEY", "xk")
    assert await listen.laden(ab.anbieter_finden("xai")) == []  # Verbindungsfehler
    assert await listen.laden(ab.anbieter_finden("ollama")) == []  # Ollama wird in der LLM-Fassade abgefragt


# ---------- Fassade und Schnittstelle ----------

from fastapi.testclient import TestClient  # noqa: E402

from jarvis.konfig import Einstellungen  # noqa: E402
from jarvis.llm import CLOUD_VORSCHLAEGE, LOKALE_VORSCHLAEGE, LLMFassade, LLMFehler  # noqa: E402
from jarvis.server import create_app  # noqa: E402
from tests.conftest import SkriptLLM, text_chunks  # noqa: E402
from tests.helfer import baue_jarvis  # noqa: E402


async def _sammeln(strom):
    return [e async for e in strom]


def test_vorschlagslisten_aus_dem_register():
    ids = [m for m, _, _ in CLOUD_VORSCHLAEGE]
    assert ids[:3] == ["anthropic/claude-sonnet-5-5", "anthropic/claude-opus-5-5", "anthropic/claude-haiku-5-5"]
    assert "openrouter/deepseek/deepseek-v4.1-flash" in ids and "opencode/kimi-k2.5" in ids
    assert all(s for _, _, s in CLOUD_VORSCHLAEGE)
    assert LOKALE_VORSCHLAEGE[0] == ("ollama/qwen2.5:7b", "Qwen 2.5 7B")


async def test_fassade_uebersetzt_opencode_und_eigene_anbieter(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "oc")
    e = Einstellungen(modell="opencode/kimi-k2.5", anbieter_eigene=[{"id": "lmstudio", "api_base": "http://127.0.0.1:1234/v1"}])
    skript = SkriptLLM([text_chunks("a"), text_chunks("b"), text_chunks("c")])
    llm = LLMFassade(e, acompletion=skript)
    await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}]))
    assert skript.aufrufe[0]["model"] == "openai/kimi-k2.5" and skript.aufrufe[0]["api_key"] == "oc"
    assert skript.aufrufe[0]["api_base"] == "https://opencode.ai/inference/openai/v1"
    await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}], modell="lmstudio/llama"))
    assert skript.aufrufe[1]["model"] == "openai/llama" and skript.aufrufe[1]["api_base"] == "http://127.0.0.1:1234/v1"
    await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}], modell="ollama/qwen2.5:7b"))
    assert skript.aufrufe[2]["model"] == "ollama_chat/qwen2.5:7b" and "api_key" not in skript.aufrufe[2]


async def test_fehlertext_nennt_schluessel_des_anbieters():
    class AuthenticationError(Exception):
        pass

    llm = LLMFassade(Einstellungen(modell="opencode/kimi-k2.5"), acompletion=SkriptLLM([AuthenticationError("401")]))
    with pytest.raises(LLMFehler, match="jarvis schluessel OPENCODE_API_KEY"):
        await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}]))


async def test_uebersicht_je_anbieter(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "openrouter.ai":
            return httpx.Response(200, json={"data": [
                {"id": "google/gemma-4-31b-it:free", "name": "Gemma", "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools"]},
                {"id": "deepseek/deepseek-v4.1-flash", "name": "DeepSeek", "pricing": {"prompt": "1", "completion": "1"}},
            ]})
        raise httpx.ConnectError("weg")

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    llm = LLMFassade(Einstellungen(modell="openrouter/x/y"), http_client_fabrik=mock_fabrik(handler))
    u = await llm.modelle_uebersicht("openrouter")
    ids = [v["id"] for v in u["vorschlaege"]]
    # aktives Modell zuerst, dann Vorschläge in Reihenfolge, dann übrige Live-Modelle
    assert ids[:2] == ["openrouter/x/y", "openrouter/deepseek/deepseek-v4.1-flash"] and "openrouter/google/gemma-4-31b-it:free" in ids
    gemma = next(v for v in u["vorschlaege"] if v["id"].endswith(":free"))
    assert gemma["kostenlos"] is True and gemma["werkzeuge"] is True and gemma["live"] is True and gemma["verfuegbar"] is False
    assert gemma["anbieter"] == "openrouter"
    orinfo = next(a for a in u["anbieter"] if a["id"] == "openrouter")
    assert orinfo["verfuegbar"] is False and orinfo["schluessel"] == "OPENROUTER_API_KEY"
    # ohne Schlüssel und ohne Live-Liste: feste Vorschläge, nicht live; aktives Modell gehört nicht dazu
    u = await llm.modelle_uebersicht("deepseek")
    assert [v["id"] for v in u["vorschlaege"]] == ["deepseek/deepseek-flash", "deepseek/deepseek-v4-pro"]
    assert all(v["live"] is False for v in u["vorschlaege"])
    # Ollama nicht erreichbar → Anbieter „ollama“ nicht verfügbar, Vorschläge als „nicht installiert“
    u = await llm.modelle_uebersicht("ollama")
    assert next(a for a in u["anbieter"] if a["id"] == "ollama")["verfuegbar"] is False
    assert u["vorschlaege"][0]["id"] == "ollama/qwen2.5:7b" and u["vorschlaege"][0]["verfuegbar"] is False
    with pytest.raises(LLMFehler, match="Unbekannter Anbieter"):
        await llm.modelle_uebersicht("gibtsnicht")
    # Gesamtliste: alle Anbieter, neue Felder vorhanden
    u = await llm.modelle_uebersicht()
    assert {a["id"] for a in u["anbieter"]} >= {"ollama", "anthropic", "openrouter", "opencode"}
    assert all({"anbieter", "kostenlos", "werkzeuge", "live"} <= set(v) for v in u["vorschlaege"])


def test_server_modelle_und_eigene_anbieter(monkeypatch):
    j, _ = baue_jarvis()
    app = create_app(j, integrationen_starten=False, stimme_starten=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        m = c.get("/api/modelle").json()
        assert m["aktuell"] == "openai/gpt-4o" and any(a["id"] == "openrouter" for a in m["anbieter"])
        assert any(v["id"] == "anthropic/claude-sonnet-5-5" and v["anbieter"] == "anthropic" for v in m["vorschlaege"])
        m = c.get("/api/modelle?anbieter=zai").json()
        assert [v["id"] for v in m["vorschlaege"]] == ["zai/glm-5.3", "zai/glm-5.3-flash"]
        assert c.get("/api/modelle?anbieter=nix").status_code == 404

        # eigener Anbieter anlegen → erscheint in der Anbieterliste, Modelle aus dem Eintrag
        eigene = [{"id": "lmstudio", "name": "LM Studio", "api_base": "http://127.0.0.1:1234/v1", "modelle": ["llama-3"]}]
        e = c.put("/api/einstellungen", json={"anbieter_eigene": eigene}).json()
        assert e["anbieter_eigene"][0]["id"] == "lmstudio" and e["anbieter_eigene"][0]["schluessel"] is None
        m = c.get("/api/modelle?anbieter=lmstudio").json()
        assert next(a for a in m["anbieter"] if a["id"] == "lmstudio")["eigen"] is True
        assert [v["id"] for v in m["vorschlaege"]] == ["lmstudio/llama-3"] and m["vorschlaege"][0]["verfuegbar"] is True
        # ungültige Einträge werden abgewiesen (Kollision, Kennung, URL)
        for kaputt in ({"id": "openai", "api_base": "http://x"}, {"id": "Ä", "api_base": "http://x"}, {"id": "ok", "api_base": "x"}):
            assert c.put("/api/einstellungen", json={"anbieter_eigene": [kaputt]}).status_code == 422
        assert c.put("/api/einstellungen", json={"anbieter_eigene": [eigene[0], eigene[0]]}).status_code == 422
        assert c.put("/api/einstellungen", json={"anbieter_eigene": []}).json()["anbieter_eigene"] == []

        # neuer Schlüssel leert den Listen-Cache
        j.llm.modelllisten._cache["openrouter"] = (0.0, [])
        assert c.put("/api/geheimnisse/OPENROUTER_API_KEY", json={"wert": "or-1"}).json()["gespeichert"]
        assert j.llm.modelllisten._cache == {}
