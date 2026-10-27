"""OpenAPI 3 → Werkzeuge (eine Operation = ein Werkzeug), inkl. lokaler $ref-Auflösung.

Auth: bearer | basic | header | query.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin

import httpx
import yaml

from ..werkzeuge import Risiko, Werkzeug, WerkzeugFehler, name_bereinigen, risiko_schaetzen

METHODEN = ("get", "put", "post", "delete", "patch", "head", "options")
MAX_ANTWORT = 12000


class OpenApiFehler(ValueError):
    pass


def spec_parsen(text: str) -> dict[str, Any]:
    try:
        daten = json.loads(text)
    except json.JSONDecodeError:
        daten = yaml.safe_load(text)
    if not isinstance(daten, dict):
        raise OpenApiFehler("Keine gültige OpenAPI-Spezifikation")
    if "openapi" not in daten:
        if "swagger" in daten:
            raise OpenApiFehler("Swagger 2.0 wird nicht unterstützt – bitte OpenAPI 3 verwenden.")
        raise OpenApiFehler("Feld 'openapi' fehlt – keine OpenAPI-3-Spezifikation")
    return daten


def _zeiger_aufloesen(spec: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise OpenApiFehler(f"Nur lokale $ref werden unterstützt: {ref}")
    knoten: Any = spec
    for teil in ref[2:].split("/"):
        teil = teil.replace("~1", "/").replace("~0", "~")
        if not isinstance(knoten, dict) or teil not in knoten:
            raise OpenApiFehler(f"$ref nicht gefunden: {ref}")
        knoten = knoten[teil]
    return knoten


def refs_aufloesen(spec: dict[str, Any], knoten: Any, _pfad: tuple[str, ...] = (), _tiefe: int = 0) -> Any:
    """Löst $ref rekursiv auf (Zyklen werden nach Tiefe 12 bzw. bei Wiederholung abgeschnitten)."""
    if _tiefe > 12:
        return {"type": "object", "description": "(verschachtelt, gekürzt)"}
    if isinstance(knoten, dict):
        if "$ref" in knoten and isinstance(knoten["$ref"], str):
            ref = knoten["$ref"]
            if ref in _pfad:
                return {"type": "object", "description": f"(rekursiv: {ref.rsplit('/', 1)[-1]})"}
            ziel = copy.deepcopy(_zeiger_aufloesen(spec, ref))
            rest = {k: v for k, v in knoten.items() if k != "$ref"}
            if isinstance(ziel, dict):
                ziel.update(rest)
            return refs_aufloesen(spec, ziel, (*_pfad, ref), _tiefe + 1)
        return {k: refs_aufloesen(spec, v, _pfad, _tiefe + 1) for k, v in knoten.items()}
    if isinstance(knoten, list):
        return [refs_aufloesen(spec, v, _pfad, _tiefe + 1) for v in knoten]
    return knoten


def _schema_saeubern(schema: Any) -> Any:
    """Entfernt für LLM-Schemas störende Felder (xml, example(s), readOnly-Properties …)."""
    if isinstance(schema, dict):
        ergebnis = {}
        for k, v in schema.items():
            if k in ("xml", "example", "examples", "externalDocs", "discriminator", "deprecated"):
                continue
            ergebnis[k] = _schema_saeubern(v)
        if isinstance(ergebnis.get("properties"), dict):
            ergebnis["properties"] = {
                n: p for n, p in ergebnis["properties"].items()
                if not (isinstance(p, dict) and p.get("readOnly"))
            }
        if ergebnis.get("nullable") is True:
            ergebnis.pop("nullable")
        return ergebnis
    if isinstance(schema, list):
        return [_schema_saeubern(v) for v in schema]
    return schema


def basis_url_ermitteln(spec: dict[str, Any], spec_url: str | None = None) -> str:
    server = (spec.get("servers") or [{}])[0].get("url", "") or ""
    for name, var in ((spec.get("servers") or [{}])[0].get("variables") or {}).items():
        server = server.replace("{" + name + "}", str(var.get("default", "")))
    if spec_url and not server.startswith(("http://", "https://")):
        server = urljoin(spec_url, server or "/")
    return server.rstrip("/")


def risiko_fuer_methode(methode: str, name: str) -> Risiko:
    methode = methode.lower()
    heuristik = risiko_schaetzen(name, "aendern")
    if methode in ("get", "head", "options"):
        return "aendern" if heuristik == "kritisch" else "lesen"
    if methode == "delete":
        return "kritisch"
    return heuristik if heuristik == "kritisch" else "aendern"


class HttpAuth:
    """Authentifizierung für REST/OpenAPI: {"art": "bearer|basic|header|query", ...}."""

    def __init__(self, auth: dict[str, Any] | None):
        self.auth = auth or {}

    def anwenden(self, kopfzeilen: dict[str, str], query: dict[str, Any]) -> httpx.Auth | None:
        art = (self.auth.get("art") or "").lower()
        if art == "bearer":
            kopfzeilen["Authorization"] = f"Bearer {self.auth.get('wert', '')}"
        elif art == "basic":
            return httpx.BasicAuth(self.auth.get("benutzer", ""), self.auth.get("passwort", self.auth.get("wert", "")))
        elif art == "header":
            kopfzeilen[self.auth.get("name") or "X-API-Key"] = self.auth.get("wert", "")
        elif art == "query":
            query[self.auth.get("name") or "api_key"] = self.auth.get("wert", "")
        return None


async def antwort_text(antwort: httpx.Response) -> str:
    text = antwort.text
    try:
        text = json.dumps(antwort.json(), ensure_ascii=False, indent=1)
    except (ValueError, json.JSONDecodeError):
        pass
    if len(text) > MAX_ANTWORT:
        text = text[:MAX_ANTWORT] + "\n… (gekürzt)"
    return f"HTTP {antwort.status_code}\n{text}"


class OpenApiWerkzeug(Werkzeug):
    def __init__(
        self,
        *,
        name: str,
        beschreibung: str,
        json_schema: dict[str, Any],
        risiko: Risiko,
        integration: str,
        methode: str,
        basis_url: str,
        pfad: str,
        parameter: list[dict[str, Any]],
        hat_body: bool,
        auth: HttpAuth,
        http_client_fabrik: Callable[..., httpx.AsyncClient],
        kopfzeilen: dict[str, str] | None = None,
    ):
        super().__init__(name, beschreibung, json_schema, risiko, quelle="openapi", integration=integration)
        self.methode = methode.upper()
        self.basis_url = basis_url
        self.pfad = pfad
        self.parameter = parameter
        self.hat_body = hat_body
        self.auth = auth
        self.http_client_fabrik = http_client_fabrik
        self.kopfzeilen = kopfzeilen or {}

    async def ausfuehren(self, **argumente: Any) -> Any:
        pfad = self.pfad
        query: dict[str, Any] = {}
        kopfzeilen = dict(self.kopfzeilen)
        cookies: dict[str, str] = {}
        for p in self.parameter:
            n, ort = p["name"], p.get("in")
            if n not in argumente:
                if p.get("required"):
                    raise WerkzeugFehler(f"Pflichtparameter fehlt: {n}")
                continue
            wert = argumente[n]
            if ort == "path":
                pfad = pfad.replace("{" + n + "}", str(wert))
            elif ort == "query":
                query[n] = json.dumps(wert) if isinstance(wert, (dict,)) else wert
            elif ort == "header":
                kopfzeilen[n] = str(wert)
            elif ort == "cookie":
                cookies[n] = str(wert)
        httpx_auth = self.auth.anwenden(kopfzeilen, query)
        body = argumente.get("body") if self.hat_body else None
        async with self.http_client_fabrik() as client:
            antwort = await client.request(
                self.methode,
                self.basis_url + pfad,
                params=query or None,
                headers=kopfzeilen,
                cookies=cookies or None,
                json=body,
                auth=httpx_auth or httpx.USE_CLIENT_DEFAULT,
            )
        text = await antwort_text(antwort)
        if antwort.status_code >= 400:
            raise WerkzeugFehler(text)
        return text


def werkzeuge_aus_openapi(
    spec: dict[str, Any],
    integration_id: str,
    *,
    basis_url: str | None = None,
    auth: dict[str, Any] | None = None,
    http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
    kopfzeilen: dict[str, str] | None = None,
    werkzeug_risiko: dict[str, Risiko] | None = None,
    max_werkzeuge: int = 128,
) -> list[Werkzeug]:
    fabrik = http_client_fabrik or (lambda **kw: httpx.AsyncClient(timeout=30.0, **kw))
    basis = (basis_url or basis_url_ermitteln(spec)).rstrip("/")
    http_auth = HttpAuth(auth)
    werkzeuge: list[Werkzeug] = []
    namen: set[str] = set()
    for pfad, pfad_eintrag in (spec.get("paths") or {}).items():
        pfad_eintrag = refs_aufloesen(spec, pfad_eintrag)
        gemeinsame = pfad_eintrag.get("parameters", [])
        for methode in METHODEN:
            op = pfad_eintrag.get(methode)
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId") or f"{methode}_{pfad}"
            name = name_bereinigen(f"{integration_id}__{op_id}")
            basis_name, i = name, 2
            while name in namen:
                name = f"{basis_name[:60]}_{i}"
                i += 1
            namen.add(name)
            # Parameter (Operation überschreibt Pfad-Parameter gleichen Namens/Orts)
            parameter_je_schluessel = {(p.get("name"), p.get("in")): p for p in gemeinsame if isinstance(p, dict)}
            for p in op.get("parameters", []):
                if isinstance(p, dict):
                    parameter_je_schluessel[(p.get("name"), p.get("in"))] = p
            parameter = [p for p in parameter_je_schluessel.values() if p.get("name")]
            eigenschaften: dict[str, Any] = {}
            pflicht: list[str] = []
            for p in parameter:
                s = _schema_saeubern(p.get("schema") or {"type": "string"})
                if p.get("description"):
                    s = {**s, "description": p["description"][:300]}
                eigenschaften[p["name"]] = s
                if p.get("required") or p.get("in") == "path":
                    pflicht.append(p["name"])
            hat_body = False
            body = op.get("requestBody")
            if isinstance(body, dict):
                inhalt = body.get("content") or {}
                medien = inhalt.get("application/json") or next(iter(inhalt.values()), None)
                if isinstance(medien, dict) and "schema" in medien:
                    hat_body = True
                    eigenschaften["body"] = {
                        **_schema_saeubern(medien["schema"]),
                        "description": (body.get("description") or "Anfrage-Body (JSON)")[:300],
                    }
                    if body.get("required"):
                        pflicht.append("body")
            beschreibung = " – ".join(
                t for t in (op.get("summary"), op.get("description")) if t
            ) or f"{methode.upper()} {pfad}"
            json_schema: dict[str, Any] = {"type": "object", "properties": eigenschaften}
            if pflicht:
                json_schema["required"] = sorted(set(pflicht))
            risiko = (werkzeug_risiko or {}).get(op_id) or risiko_fuer_methode(methode, op_id)
            werkzeuge.append(
                OpenApiWerkzeug(
                    name=name,
                    beschreibung=f"{beschreibung[:900]} [{methode.upper()} {pfad}]",
                    json_schema=json_schema,
                    risiko=risiko,
                    integration=integration_id,
                    methode=methode,
                    basis_url=basis,
                    pfad=pfad,
                    parameter=parameter,
                    hat_body=hat_body,
                    auth=http_auth,
                    http_client_fabrik=fabrik,
                    kopfzeilen=kopfzeilen,
                )
            )
            if len(werkzeuge) >= max_werkzeuge:
                return werkzeuge
    return werkzeuge
