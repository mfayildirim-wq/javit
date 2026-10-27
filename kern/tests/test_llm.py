import json

import httpx
import pytest

from jarvis.konfig import Einstellungen
from jarvis.llm import (
    LLMFassade,
    LLMFehler,
    ToolCallSammler,
    argumente_parsen,
    litellm_modell,
    nachrichten_fuer_prompt_modus,
    werkzeug_aufrufe_parsen,
)
from tests.conftest import SkriptLLM, mock_fabrik, text_chunk, text_chunks, tool_chunks, tool_delta

WERKZEUGE = [
    {"type": "function", "function": {"name": "uhrzeit_datum", "description": "Zeit", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "websuche", "description": "Suche", "parameters": {"type": "object", "properties": {"anfrage": {"type": "string"}}, "required": ["anfrage"]}}},
]


def test_sammler_setzt_verschachtelte_deltas_zusammen():
    s = ToolCallSammler()
    # Zwei Aufrufe, Deltas abwechselnd (wie bei OpenAI parallel tool calls)
    for chunk in [
        tool_delta(0, id="call_a", name="websuche", argumente='{"anf'),
        tool_delta(1, id="call_b", name="uhrzeit_datum", argumente=""),
        tool_delta(0, argumente='rage": "Wetter '),
        tool_delta(1, argumente="{}"),
        tool_delta(0, argumente='Berlin"}'),
    ]:
        s.hinzufuegen(chunk.choices[0].delta.tool_calls)
    aufrufe = s.ergebnis()
    assert [(a.id, a.name, a.argumente) for a in aufrufe] == [
        ("call_a", "websuche", {"anfrage": "Wetter Berlin"}),
        ("call_b", "uhrzeit_datum", {}),
    ]


def test_sammler_gleicher_index_neue_id_und_dict_argumente():
    s = ToolCallSammler()
    s.hinzufuegen([{"index": 0, "id": "x1", "function": {"name": "a", "arguments": {"k": 1}}}])
    s.hinzufuegen([{"index": 0, "id": "x2", "function": {"name": "b", "arguments": '{"k": 2}'}}])
    s.hinzufuegen([{"index": None, "id": None, "function": {"name": None, "arguments": ""}}])
    aufrufe = s.ergebnis()
    assert [(a.id, a.name, a.argumente) for a in aufrufe] == [("x1", "a", {"k": 1}), ("x2", "b", {"k": 2})]


def test_argumente_parsen():
    assert argumente_parsen("") == ({}, None)
    assert argumente_parsen('{"a": 1}') == ({"a": 1}, None)
    assert argumente_parsen('```json\n{"a": 2}\n```') == ({"a": 2}, None)
    assert argumente_parsen("[1]")[1] is not None
    args, fehler = argumente_parsen("{kaputt")
    assert args == {} and "kein gültiges JSON" in fehler


def test_prompt_modus_parser():
    rest, aufrufe = werkzeug_aufrufe_parsen('{"werkzeug": "websuche", "argumente": {"anfrage": "x"}}', {"websuche"})
    assert rest == "" and aufrufe[0].name == "websuche" and aufrufe[0].argumente == {"anfrage": "x"}
    rest, aufrufe = werkzeug_aufrufe_parsen(
        'Moment.\n```json\n[{"tool": "uhrzeit_datum", "arguments": {}}, {"name": "websuche", "parameters": {"anfrage": "y"}}]\n```',
        {"websuche", "uhrzeit_datum"},
    )
    assert rest == "Moment." and [a.name for a in aufrufe] == ["uhrzeit_datum", "websuche"]
    # Unbekannte Werkzeuge werden ignoriert, normaler Text bleibt
    rest, aufrufe = werkzeug_aufrufe_parsen('Die Antwort ist {"a": 1}.', {"websuche"})
    assert aufrufe == [] and rest == 'Die Antwort ist {"a": 1}.'


def test_nachrichten_fuer_prompt_modus():
    n = nachrichten_fuer_prompt_modus(
        [
            {"role": "system", "content": "Du bist Jarvis."},
            {"role": "user", "content": "Wie spät?"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "uhrzeit_datum", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "12:00"},
        ],
        WERKZEUGE,
    )
    assert n[0]["role"] == "system" and "uhrzeit_datum" in n[0]["content"] and '"werkzeug"' in n[0]["content"]
    assert n[2] == {"role": "assistant", "content": '{"werkzeug": "uhrzeit_datum", "argumente": {}}'}
    assert n[3] == {"role": "user", "content": "[Ergebnis von uhrzeit_datum]\n12:00"}
    assert all("tool_calls" not in m for m in n)


def test_litellm_modell():
    assert litellm_modell("ollama/qwen2.5:7b") == "ollama_chat/qwen2.5:7b"
    assert litellm_modell("anthropic/claude-sonnet-4-5") == "anthropic/claude-sonnet-4-5"


async def _sammeln(gen):
    teile = [t async for t in gen]
    return [t["delta"] for t in teile if t["typ"] == "text"], teile[-1]


async def test_streaming_nativ_mit_text_und_tool_calls():
    skript = SkriptLLM([
        text_chunks("Ich schaue nach.") + tool_chunks("call_1", "websuche", {"anfrage": "Jarvis Film"}),
    ])
    e = Einstellungen(modell="openai/gpt-4o")
    llm = LLMFassade(e, acompletion=skript)
    deltas, ende = await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}], WERKZEUGE))
    assert "".join(deltas) == "Ich schaue nach."
    assert ende["typ"] == "ende" and ende["modus"] == "nativ"
    assert [(a.name, a.argumente) for a in ende["werkzeug_aufrufe"]] == [("websuche", {"anfrage": "Jarvis Film"})]
    aufruf = skript.aufrufe[0]
    assert aufruf["tools"] == WERKZEUGE and aufruf["stream"] is True and aufruf["model"] == "openai/gpt-4o"


async def test_streaming_ollama_nutzt_api_base_und_ollama_chat():
    skript = SkriptLLM([text_chunks("Hallo")])
    e = Einstellungen(modell="ollama/qwen2.5:7b", werkzeug_modus="nativ", ollama_url="http://localhost:11434")
    llm = LLMFassade(e, acompletion=skript)
    _, ende = await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}], WERKZEUGE))
    assert ende["text"] == "Hallo"
    assert skript.aufrufe[0]["model"] == "ollama_chat/qwen2.5:7b"
    assert skript.aufrufe[0]["api_base"] == "http://localhost:11434"


async def test_streaming_prompt_modus_haelt_json_zurueck():
    antwort = 'Einen Moment, Sir. {"werkzeug": "websuche", "argumente": {"anfrage": "Wetter"}}'
    skript = SkriptLLM([text_chunks(antwort, 4)])
    llm = LLMFassade(Einstellungen(modell="ollama/llama2", werkzeug_modus="prompt"), acompletion=skript)
    deltas, ende = await _sammeln(llm.antwort_streamen([{"role": "system", "content": "S"}, {"role": "user", "content": "x"}], WERKZEUGE))
    gestreamt = "".join(deltas)
    assert "{" not in gestreamt and gestreamt.startswith("Einen Moment")
    assert ende["modus"] == "prompt" and ende["werkzeug_aufrufe"][0].argumente == {"anfrage": "Wetter"}
    assert "tools" not in skript.aufrufe[0]
    assert "Werkzeuge" in skript.aufrufe[0]["messages"][0]["content"]


async def test_streaming_prompt_modus_normaler_text_mit_klammern():
    skript = SkriptLLM([text_chunks("Die Menge {1, 2} ist klein.", 3)])
    llm = LLMFassade(Einstellungen(werkzeug_modus="prompt"), acompletion=skript)
    deltas, ende = await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}], WERKZEUGE))
    assert "".join(deltas) == "Die Menge {1, 2} ist klein."
    assert ende["werkzeug_aufrufe"] == [] and ende["text"] == "Die Menge {1, 2} ist klein."


async def test_fehlertexte():
    llm = LLMFassade(Einstellungen(modell="ollama/qwen2.5:7b", werkzeug_modus="nativ"),
                     acompletion=SkriptLLM([ConnectionError("Connection refused")]))
    with pytest.raises(LLMFehler, match="Ollama ist nicht erreichbar"):
        await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}]))

    class AuthenticationError(Exception):
        pass

    llm = LLMFassade(Einstellungen(modell="anthropic/claude-sonnet-4-5"), acompletion=SkriptLLM([AuthenticationError("invalid x-api-key")]))
    with pytest.raises(LLMFehler, match="jarvis schluessel ANTHROPIC_API_KEY"):
        await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}]))


async def test_ollama_modelle_und_faehigkeiten():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}, {"name": "llama2:latest"}, {"name": "nomic-embed-text:latest"}]})
        if request.url.path == "/api/show":
            name = json.loads(request.content)["model"]
            return httpx.Response(200, json={"capabilities": ["completion", "tools"] if name.startswith("qwen") else ["completion"]})
        return httpx.Response(404)

    llm = LLMFassade(Einstellungen(), http_client_fabrik=mock_fabrik(handler))
    assert await llm.ollama_modelle() == ["qwen2.5:7b", "llama2:latest", "nomic-embed-text:latest"]
    assert await llm.unterstuetzt_werkzeuge("ollama/qwen2.5:7b") is True
    assert await llm.unterstuetzt_werkzeuge("ollama/llama2:latest") is False
    assert await llm.unterstuetzt_werkzeuge("anthropic/claude-sonnet-4-5") is True
    vorschlaege = await llm.modell_vorschlaege()
    ids = {v["id"]: v for v in vorschlaege}
    assert ids["ollama/qwen2.5:7b"]["lokal"] and ids["ollama/qwen2.5:7b"]["verfuegbar"]
    assert ids["openai/gpt-6.1-sol"]["verfuegbar"] is False  # kein OPENAI_API_KEY im Test
    assert ids["anthropic/claude-sonnet-5-5"]["lokal"] is False
    assert "gemini/gemini-4-argon" in ids
    # Einbettungsmodelle sind keine Chatmodelle
    assert not any("embed" in i for i in ids)
    # empfohlene, Tool-fähige lokale Modelle erscheinen als „nicht installiert“
    assert ids["ollama/qwen3:8b"]["verfuegbar"] is False and ids["ollama/llama3.1:8b"]["lokal"]
    assert list(ids).count("ollama/qwen2.5:7b") == 1


async def test_ollama_nicht_erreichbar():
    def handler(request):
        raise httpx.ConnectError("weg")

    llm = LLMFassade(Einstellungen(), http_client_fabrik=mock_fabrik(handler))
    assert await llm.ollama_modelle() == []
    assert await llm.unterstuetzt_werkzeuge("ollama/x") is False
    vorschlaege = await llm.modell_vorschlaege()
    assert any(v["id"] == "ollama/qwen2.5:7b" and v["verfuegbar"] is False for v in vorschlaege)


async def test_einbetten_und_fallback():
    async def einbettung(**kwargs):
        return {"data": [{"embedding": [1.0, 0.0]} for _ in kwargs["input"]]}

    llm = LLMFassade(Einstellungen(), aembedding=einbettung)
    assert await llm.einbetten(["a", "b"]) == [[1.0, 0.0], [1.0, 0.0]]

    async def kaputt(**kwargs):
        raise RuntimeError("kein Modell")

    llm = LLMFassade(Einstellungen(), aembedding=kaputt)
    assert await llm.einbetten(["a"]) is None
    assert await LLMFassade(Einstellungen(einbettungs_modell=None)).einbetten(["a"]) is None


def test_text_chunk_hilfe():
    assert text_chunk("x").choices[0].delta.content == "x"


async def test_api_base_nur_fuer_das_konfigurierte_modell():
    e = Einstellungen(modell="openai/fake", api_basen={"openai/fake": "http://127.0.0.1:9/v1"}, llm_timeout=12)
    skript = SkriptLLM([text_chunks("a"), text_chunks("b")])
    llm = LLMFassade(e, acompletion=skript)
    await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}]))
    assert skript.aufrufe[0]["api_base"] == "http://127.0.0.1:9/v1" and skript.aufrufe[0]["timeout"] == 12
    # Ein anderes Modell (anderer Anbieter-Schlüssel) geht nie an diesen Endpunkt
    await _sammeln(llm.antwort_streamen([{"role": "user", "content": "x"}], modell="anthropic/claude-sonnet-5-5"))
    assert "api_base" not in skript.aufrufe[1]
