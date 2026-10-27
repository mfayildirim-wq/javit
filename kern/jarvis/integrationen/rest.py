"""Einfache REST-Definitionen → Werkzeuge.

Format (siehe VERTRAEGE.md):
    {"name": "wetter_abrufen", "methode": "GET", "url": "https://api.open-meteo.com/v1/forecast",
     "parameter": {"latitude": "zahl", "longitude": "zahl", "current_weather": "text"},
     "beschreibung": "…"}

Erweiterungen (optional):
    parameter-Wert als Objekt: {"typ": "zahl", "beschreibung": "…", "pflicht": true, "standard": …}
    feste_parameter: {…}  – immer gesendete Query-/Body-Werte
    kopfzeilen: {…}, risiko: lesen|aendern|kritisch, body: json|form
    {param} in der URL wird als Pfadparameter ersetzt.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from ..werkzeuge import Risiko, Werkzeug, WerkzeugFehler, name_bereinigen, risiko_schaetzen
from .openapi import HttpAuth, antwort_text

TYPEN = {
    "zahl": "number",
    "number": "number",
    "ganzzahl": "integer",
    "integer": "integer",
    "int": "integer",
    "text": "string",
    "string": "string",
    "bool": "boolean",
    "boolean": "boolean",
    "wahrheitswert": "boolean",
    "liste": "array",
    "array": "array",
    "objekt": "object",
    "object": "object",
}


class RestFehler(ValueError):
    pass


def _param_schema(definition: Any) -> tuple[dict[str, Any], bool, Any]:
    if isinstance(definition, str):
        typ, beschreibung, pflicht, standard = definition, None, False, None
    elif isinstance(definition, dict):
        typ = definition.get("typ") or definition.get("type") or "text"
        beschreibung = definition.get("beschreibung") or definition.get("description")
        pflicht = bool(definition.get("pflicht") or definition.get("required"))
        standard = definition.get("standard", definition.get("default"))
    else:
        raise RestFehler(f"Ungültige Parameterdefinition: {definition!r}")
    json_typ = TYPEN.get(str(typ).lower())
    if json_typ is None:
        raise RestFehler(f"Unbekannter Parametertyp: {typ}")
    schema: dict[str, Any] = {"type": json_typ}
    if json_typ == "array":
        schema["items"] = {}
    if beschreibung:
        schema["description"] = beschreibung
    if standard is not None:
        schema["default"] = standard
    return schema, pflicht, standard


class RestWerkzeug(Werkzeug):
    def __init__(
        self,
        definition: dict[str, Any],
        integration_id: str,
        *,
        auth: dict[str, Any] | None = None,
        http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
        risiko_standard: Risiko = "aendern",
    ):
        for feld in ("name", "url"):
            if not definition.get(feld):
                raise RestFehler(f"REST-Definition ohne '{feld}'")
        self.methode = str(definition.get("methode") or definition.get("method") or "GET").upper()
        self.url = definition["url"]
        self.pfad_parameter = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", self.url))
        self.feste_parameter = dict(definition.get("feste_parameter") or {})
        self.kopfzeilen = dict(definition.get("kopfzeilen") or {})
        self.body_art = definition.get("body") or "json"
        self.standards: dict[str, Any] = {}
        eigenschaften: dict[str, Any] = {}
        pflicht: list[str] = []
        for pname, pdef in (definition.get("parameter") or {}).items():
            schema, ist_pflicht, standard = _param_schema(pdef)
            eigenschaften[pname] = schema
            if standard is not None:
                self.standards[pname] = standard
            if ist_pflicht or pname in self.pfad_parameter:
                pflicht.append(pname)
        for p in self.pfad_parameter - set(eigenschaften):
            eigenschaften[p] = {"type": "string"}
            pflicht.append(p)
        json_schema: dict[str, Any] = {"type": "object", "properties": eigenschaften}
        if pflicht:
            json_schema["required"] = sorted(set(pflicht))
        if definition.get("risiko"):
            risiko: Risiko = definition["risiko"]
        elif self.methode in ("GET", "HEAD"):
            risiko = "lesen"
        elif self.methode == "DELETE":
            risiko = "kritisch"
        else:
            risiko = risiko_schaetzen(definition["name"], risiko_standard)
        super().__init__(
            name=name_bereinigen(definition["name"]),
            beschreibung=definition.get("beschreibung") or definition.get("description") or f"{self.methode} {self.url}",
            json_schema=json_schema,
            risiko=risiko,
            quelle="rest",
            integration=integration_id,
        )
        self.auth = HttpAuth(auth)
        self.http_client_fabrik = http_client_fabrik or (lambda **kw: httpx.AsyncClient(timeout=30.0, **kw))

    async def ausfuehren(self, **argumente: Any) -> Any:
        werte = {**self.standards, **argumente}
        url = self.url
        for p in self.pfad_parameter:
            if p not in werte:
                raise WerkzeugFehler(f"Pflichtparameter fehlt: {p}")
            url = url.replace("{" + p + "}", quote(str(werte.pop(p)), safe=""))
        daten = {**self.feste_parameter, **werte}
        daten = {k: v for k, v in daten.items() if v is not None}
        kopfzeilen = dict(self.kopfzeilen)
        query: dict[str, Any] = {}
        httpx_auth = self.auth.anwenden(kopfzeilen, query)
        anfrage: dict[str, Any] = {"headers": kopfzeilen}
        if self.methode in ("GET", "HEAD", "DELETE"):
            query.update({k: (str(v).lower() if isinstance(v, bool) else v) for k, v in daten.items()})
        elif self.body_art == "form":
            anfrage["data"] = daten
        else:
            anfrage["json"] = daten
        if query:
            anfrage["params"] = query
        if httpx_auth:
            anfrage["auth"] = httpx_auth
        async with self.http_client_fabrik() as client:
            antwort = await client.request(self.methode, url, **anfrage)
        text = await antwort_text(antwort)
        if antwort.status_code >= 400:
            raise WerkzeugFehler(text)
        return text


def werkzeuge_aus_rest(
    definitionen: list[dict[str, Any]],
    integration_id: str,
    *,
    auth: dict[str, Any] | None = None,
    http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
    risiko_standard: Risiko = "aendern",
    praefix: bool = True,
) -> list[Werkzeug]:
    werkzeuge: list[Werkzeug] = []
    for d in definitionen:
        definition = dict(d)
        if praefix and not str(definition.get("name", "")).startswith(f"{integration_id}__"):
            definition["name"] = f"{integration_id}__{definition.get('name', '')}"
        werkzeuge.append(
            RestWerkzeug(
                definition,
                integration_id,
                auth=auth,
                http_client_fabrik=http_client_fabrik,
                risiko_standard=risiko_standard,
            )
        )
    return werkzeuge
