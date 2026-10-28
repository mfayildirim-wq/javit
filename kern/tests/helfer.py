"""Baut eine Jarvis-Instanz mit Skript-LLM (offline)."""

from __future__ import annotations

from typing import Any

import httpx

from jarvis.anwendung import Jarvis
from jarvis.konfig import KonfigSpeicher
from jarvis.llm import LLMFassade
from tests.conftest import SkriptLLM, mock_fabrik


def offline(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("offline")


def baue_jarvis(antworten: list[Any] | None = None, http_handler=None) -> tuple[Jarvis, SkriptLLM]:
    konfig = KonfigSpeicher()
    # Gedächtnis-Pflege (Titel, Nachbereitung) aus: sie würde sonst gescriptete LLM-Antworten verbrauchen
    konfig.aktualisieren({"modell": "openai/gpt-4o", "einbettungs_modell": None, "gedaechtnis_automatisch": False})
    skript = SkriptLLM(antworten)
    llm = LLMFassade(lambda: konfig.einstellungen, acompletion=skript, http_client_fabrik=mock_fabrik(offline))
    j = Jarvis(konfig=konfig, llm=llm, http_client_fabrik=mock_fabrik(http_handler or (lambda r: httpx.Response(200, json={}))))
    return j, skript
