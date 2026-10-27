"""Gemeinsame Test-Hilfen: isoliertes JARVIS_HOME, Skript-LLM mit echten LiteLLM-Stream-Chunks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from litellm.types.utils import (
    ChatCompletionDeltaToolCall,
    Delta,
    Function,
    ModelResponseStream,
    StreamingChoices,
)

TESTS = Path(__file__).resolve().parent

MINI_SERVER = TESTS / "mini_mcp_server.py"


@pytest.fixture(autouse=True)
def isoliert(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Jeder Test bekommt ein eigenes JARVIS_HOME und Datei-Geheimnisse; os.environ wird wiederhergestellt."""
    sicherung = dict(os.environ)
    home = tmp_path / "jarvis_home"
    monkeypatch.setenv("JARVIS_HOME", str(home))
    monkeypatch.setenv("JARVIS_GEHEIMNIS_BACKEND", "datei")
    monkeypatch.setenv("JARVIS_OBERFLAECHE", str(tmp_path / "keine_oberflaeche"))
    monkeypatch.setenv("JARVIS_KEIN_DOWNLOAD", "1")  # z. B. keine Piper-Stimmen laden
    monkeypatch.setenv("JARVIS_OHNE_BROWSER", "1")  # OAuth-Anmeldungen öffnen in Tests keinen Browser
    monkeypatch.delenv("JARVIS_PLATTFORM", raising=False)
    from jarvis import konfig

    monkeypatch.setattr(konfig, "_aktueller_name", konfig.STANDARD_NAME)  # Name nicht zwischen Tests teilen
    # Auf Windows/Linux-Entwicklerrechnern keine echten Mitteilungen/Sprachausgaben aus Tests
    from jarvis.anwendung import Jarvis

    async def still(self, text):  # noqa: ANN001 - abgefangene Aufrufe: jarvis.stille_aufrufe
        self.__dict__.setdefault("stille_aufrufe", []).append(text)

    monkeypatch.setattr(Jarvis, "_original_vorlesen", Jarvis._vorlesen_ohne_stimmdienst, raising=False)
    monkeypatch.setattr(Jarvis, "_desktop_mitteilung", still)
    monkeypatch.setattr(Jarvis, "_vorlesen_ohne_stimmdienst", still)
    for schluessel in ("TAVILY_API_KEY", "BRAVE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(schluessel, raising=False)
    yield home
    os.environ.clear()
    os.environ.update(sicherung)


# ---------------------------------------------------------------------------
# Stream-Chunks
# ---------------------------------------------------------------------------
def text_chunk(text: str) -> ModelResponseStream:
    return ModelResponseStream(choices=[StreamingChoices(index=0, delta=Delta(content=text))])


def text_chunks(text: str, groesse: int = 5) -> list[ModelResponseStream]:
    return [text_chunk(text[i : i + groesse]) for i in range(0, len(text), groesse)]


def tool_delta(index: int | None, id: str | None = None, name: str | None = None, argumente: str | None = None) -> ModelResponseStream:  # noqa: A002
    return ModelResponseStream(
        choices=[
            StreamingChoices(
                index=0,
                delta=Delta(
                    content=None,
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            index=index, id=id, type="function" if id else None,
                            function=Function(name=name, arguments=argumente or ""),
                        )
                    ],
                ),
            )
        ]
    )


def tool_chunks(id: str, name: str, argumente: dict[str, Any], index: int = 0, teile: int = 3) -> list[ModelResponseStream]:  # noqa: A002
    """Ein Werkzeugaufruf, dessen Argument-JSON über mehrere Deltas verteilt ist."""
    roh = json.dumps(argumente, ensure_ascii=False)
    schritt = max(1, len(roh) // teile + 1)
    stuecke = [roh[i : i + schritt] for i in range(0, len(roh), schritt)] or [""]
    chunks = [tool_delta(index, id=id, name=name, argumente=stuecke[0])]
    chunks += [tool_delta(index, argumente=s) for s in stuecke[1:]]
    return chunks


class SkriptLLM:
    """Ersatz für litellm.acompletion: liefert vorbereitete Chunk-Folgen, merkt sich die Aufrufe."""

    def __init__(self, antworten: list[Any] | None = None):
        self.antworten = list(antworten or [])
        self.aufrufe: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.aufrufe.append(kwargs)
        antwort = self.antworten.pop(0) if self.antworten else text_chunks("Erledigt.")
        if callable(antwort):
            antwort = antwort(kwargs)
        if isinstance(antwort, Exception):
            raise antwort

        async def generator():
            for chunk in antwort:
                yield chunk

        return generator()


def mock_fabrik(handler) -> Any:
    """http_client_fabrik mit httpx.MockTransport."""

    def fabrik(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return fabrik


def offline_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, text="offline")


@pytest.fixture
def python_befehl() -> list[str]:
    return [sys.executable, str(MINI_SERVER)]
