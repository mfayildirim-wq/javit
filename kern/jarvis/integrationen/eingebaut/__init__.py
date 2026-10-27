"""Eingebaute Integrationen (Python-Module statt externer MCP-Server)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...werkzeuge import Werkzeug
from . import spotify

# Name → Fabrik(integration_id, werte, http_client_fabrik) → Werkzeuge
EINGEBAUT: dict[str, Callable[..., list[Werkzeug]]] = {
    "spotify": spotify.werkzeuge,
}


def eingebaute_werkzeuge(name: str, integration_id: str, werte: dict[str, str], **kwargs: Any) -> list[Werkzeug]:
    if name not in EINGEBAUT:
        raise ValueError(f"Unbekannte eingebaute Integration: {name}")
    return EINGEBAUT[name](integration_id, werte, **kwargs)
