"""Deterministischer, OpenAI-kompatibler Fake-LLM-Server für Ende-zu-Ende-Tests.

POST /v1/chat/completions (mit und ohne Streaming). Regeln anhand der letzten Nachricht:
- letzte Nachricht ist ein Werkzeugergebnis      → Text „Erledigt. Ergebnis: …“
- „Uhrzeit“ / „wie spät“                         → Werkzeug uhrzeit_datum
- „merke …“                                      → Werkzeug erinnern(text=…)
- „lösche Datei <pfad>“                          → Werkzeug datei_loeschen (kritisch → Freigabe)
- „echo <text>“                                  → MCP-Werkzeug *__echo der Mini-Integration
- sonst                                          → Text „Verstanden: <nachricht>“

Start: python3 fake_llm.py <port>
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Fake-LLM")
ANFRAGEN: list[dict[str, Any]] = []


def _text_von(nachricht: dict[str, Any]) -> str:
    inhalt = nachricht.get("content") or ""
    if isinstance(inhalt, list):  # OpenAI-Inhaltsblöcke
        inhalt = " ".join(b.get("text", "") for b in inhalt if isinstance(b, dict))
    return str(inhalt)


def entscheiden(nachrichten: list[dict[str, Any]], werkzeuge: list[dict[str, Any]]) -> dict[str, Any]:
    """→ {"text": str} oder {"werkzeug": name, "argumente": {...}, "text": optionaler Vorspann}."""
    letzte = nachrichten[-1] if nachrichten else {"role": "user", "content": ""}
    if letzte.get("role") == "tool":
        return {"text": f"Erledigt. Ergebnis: {_text_von(letzte)[:300]}"}
    text = _text_von(letzte).strip()
    klein = text.lower()
    namen = [(w.get("function") or {}).get("name", "") for w in werkzeuge]
    if "uhrzeit" in klein or "wie spät" in klein:
        return {"werkzeug": "uhrzeit_datum", "argumente": {}, "text": "Einen Moment, ich sehe nach."}
    if klein.startswith("merke"):
        inhalt = re.sub(r"^merke( dir)?(,)?( dass)?\s*", "", text, flags=re.I).strip() or text
        return {"werkzeug": "erinnern", "argumente": {"text": inhalt}}
    m = re.match(r"lösche (die )?datei\s+(.+)$", text, flags=re.I)
    if m:
        return {"werkzeug": "datei_loeschen", "argumente": {"pfad": m.group(2).strip()}}
    m = re.match(r"echo\s+(.+)$", text, flags=re.I)
    if m:
        name = next((n for n in namen if n.endswith("__echo")), "echo")
        return {"werkzeug": name, "argumente": {"text": m.group(1).strip()}}
    return {"text": f"Verstanden: {text}"}


def _chunk(kennung: str, modell: str, delta: dict[str, Any], ende: str | None = None) -> str:
    daten = {
        "id": kennung,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": modell,
        "choices": [{"index": 0, "delta": delta, "finish_reason": ende}],
    }
    return f"data: {json.dumps(daten, ensure_ascii=False)}\n\n"


def _stream(entscheidung: dict[str, Any], modell: str):
    kennung = f"chatcmpl-{uuid.uuid4().hex[:10]}"
    yield _chunk(kennung, modell, {"role": "assistant", "content": ""})
    text = entscheidung.get("text") or ""
    for i in range(0, len(text), 8):
        yield _chunk(kennung, modell, {"content": text[i : i + 8]})
        time.sleep(0.01)
    if "werkzeug" in entscheidung:
        argumente = json.dumps(entscheidung["argumente"], ensure_ascii=False)
        aufruf_id = f"call_{uuid.uuid4().hex[:8]}"
        haelfte = len(argumente) // 2
        yield _chunk(kennung, modell, {"tool_calls": [{
            "index": 0, "id": aufruf_id, "type": "function",
            "function": {"name": entscheidung["werkzeug"], "arguments": argumente[:haelfte]},
        }]})
        yield _chunk(kennung, modell, {"tool_calls": [{"index": 0, "function": {"arguments": argumente[haelfte:]}}]})
        yield _chunk(kennung, modell, {}, "tool_calls")
    else:
        yield _chunk(kennung, modell, {}, "stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat(request: Request) -> Any:
    daten = await request.json()
    ANFRAGEN.append(daten)
    entscheidung = entscheiden(daten.get("messages") or [], daten.get("tools") or [])
    modell = daten.get("model", "fake")
    if daten.get("stream"):
        return StreamingResponse(_stream(entscheidung, modell), media_type="text/event-stream")
    nachricht: dict[str, Any] = {"role": "assistant", "content": entscheidung.get("text") or None}
    if "werkzeug" in entscheidung:
        nachricht["tool_calls"] = [{
            "id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
            "function": {"name": entscheidung["werkzeug"], "arguments": json.dumps(entscheidung["argumente"])},
        }]
    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:10]}", "object": "chat.completion", "created": int(time.time()),
        "model": modell,
        "choices": [{"index": 0, "message": nachricht, "finish_reason": "tool_calls" if "werkzeug" in entscheidung else "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    })


@app.get("/v1/models")
async def modelle() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": "fake", "object": "model"}]}


@app.get("/anfragen")
async def anfragen() -> list[dict[str, Any]]:
    """Zur Prüfung in Tests: alle empfangenen Anfragen."""
    return ANFRAGEN


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8790, log_level="warning")
