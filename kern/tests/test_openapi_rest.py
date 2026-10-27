import base64
import json

import httpx
import pytest

from jarvis.integrationen.openapi import (
    OpenApiFehler,
    basis_url_ermitteln,
    refs_aufloesen,
    spec_parsen,
    werkzeuge_aus_openapi,
)
from jarvis.integrationen.rest import RestFehler, werkzeuge_aus_rest
from jarvis.werkzeuge import WerkzeugFehler
from tests.conftest import mock_fabrik

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Tierladen", "version": "1"},
    "servers": [{"url": "/api/v3"}],
    "paths": {
        "/tiere/{tierId}": {
            "parameters": [{"$ref": "#/components/parameters/TierId"}],
            "get": {"operationId": "getTier", "summary": "Tier abrufen",
                    "parameters": [{"name": "details", "in": "query", "schema": {"type": "boolean"}}]},
            "delete": {"operationId": "deleteTier", "summary": "Tier löschen"},
        },
        "/tiere": {
            "post": {
                "operationId": "addTier",
                "summary": "Tier anlegen",
                "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Tier"}}}},
            },
            "get": {"summary": "Alle Tiere", "parameters": [{"name": "X-Mandant", "in": "header", "schema": {"type": "string"}}]},
        },
        "/kauf": {"post": {"operationId": "purchaseTier", "summary": "Kaufen"}},
    },
    "components": {
        "parameters": {"TierId": {"name": "tierId", "in": "path", "required": True, "schema": {"type": "integer"}, "description": "ID"}},
        "schemas": {
            "Tier": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "id": {"type": "integer", "readOnly": True},
                    "name": {"type": "string", "example": "Rex"},
                    "kategorie": {"$ref": "#/components/schemas/Kategorie"},
                    "eltern": {"type": "array", "items": {"$ref": "#/components/schemas/Tier"}},
                },
            },
            "Kategorie": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    },
}


def test_refs_aufloesen_mit_zyklus():
    aufgeloest = refs_aufloesen(SPEC, {"$ref": "#/components/schemas/Tier"})
    assert aufgeloest["properties"]["kategorie"]["properties"]["name"] == {"type": "string"}
    assert "rekursiv" in aufgeloest["properties"]["eltern"]["items"]["description"]
    with pytest.raises(OpenApiFehler):
        refs_aufloesen(SPEC, {"$ref": "#/components/schemas/Fehlt"})


def test_spec_parsen():
    assert spec_parsen(json.dumps(SPEC))["openapi"] == "3.0.3"
    assert spec_parsen("openapi: 3.1.0\npaths: {}\n")["openapi"] == "3.1.0"
    with pytest.raises(OpenApiFehler, match="Swagger 2.0"):
        spec_parsen('{"swagger": "2.0"}')
    assert basis_url_ermitteln(SPEC, "https://laden.example/openapi.json") == "https://laden.example/api/v3"


async def test_openapi_werkzeuge_und_aufrufe():
    anfragen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        anfragen.append(request)
        if request.method == "DELETE":
            return httpx.Response(404, json={"fehler": "nicht da"})
        return httpx.Response(200, json={"ok": True, "pfad": request.url.path})

    w = {x.name: x for x in werkzeuge_aus_openapi(
        SPEC, "laden", basis_url="https://laden.example/api/v3",
        auth={"art": "bearer", "wert": "TOKEN"}, http_client_fabrik=mock_fabrik(handler),
    )}
    assert set(w) == {"laden__getTier", "laden__deleteTier", "laden__addTier", "laden__get__tiere", "laden__purchaseTier"}
    assert w["laden__getTier"].risiko == "lesen"
    assert w["laden__deleteTier"].risiko == "kritisch"
    assert w["laden__addTier"].risiko == "aendern"
    assert w["laden__purchaseTier"].risiko == "kritisch"
    s = w["laden__getTier"].json_schema
    assert s["required"] == ["tierId"] and s["properties"]["tierId"]["type"] == "integer"
    body = w["laden__addTier"].json_schema["properties"]["body"]
    assert "id" not in body["properties"] and "example" not in body["properties"]["name"]
    assert w["laden__addTier"].json_schema["required"] == ["body"]

    text = await w["laden__getTier"].ausfuehren(tierId=7, details=True)
    r = anfragen[-1]
    assert r.method == "GET" and str(r.url) == "https://laden.example/api/v3/tiere/7?details=true"
    assert r.headers["Authorization"] == "Bearer TOKEN" and "HTTP 200" in text

    await w["laden__addTier"].ausfuehren(body={"name": "Rex"})
    assert anfragen[-1].method == "POST" and json.loads(anfragen[-1].content) == {"name": "Rex"}

    await w["laden__get__tiere"].ausfuehren(**{"X-Mandant": "m1"})
    assert anfragen[-1].headers["X-Mandant"] == "m1"

    with pytest.raises(WerkzeugFehler, match="404"):
        await w["laden__deleteTier"].ausfuehren(tierId=1)
    with pytest.raises(WerkzeugFehler, match="Pflichtparameter"):
        await w["laden__getTier"].ausfuehren()


@pytest.mark.parametrize(
    ("auth", "pruefen"),
    [
        ({"art": "basic", "benutzer": "u", "passwort": "p"},
         lambda r: r.headers["Authorization"] == "Basic " + base64.b64encode(b"u:p").decode()),
        ({"art": "header", "name": "X-API-Key", "wert": "k"}, lambda r: r.headers["X-API-Key"] == "k"),
        ({"art": "query", "name": "apikey", "wert": "q"}, lambda r: r.url.params["apikey"] == "q"),
    ],
)
async def test_openapi_auth_arten(auth, pruefen):
    anfragen = []

    def handler(request):
        anfragen.append(request)
        return httpx.Response(200, text="ok")

    w = {x.name: x for x in werkzeuge_aus_openapi(SPEC, "l", basis_url="https://x", auth=auth, http_client_fabrik=mock_fabrik(handler))}
    await w["l__getTier"].ausfuehren(tierId=1)
    assert pruefen(anfragen[0])


async def test_rest_werkzeuge():
    anfragen = []

    def handler(request):
        anfragen.append(request)
        return httpx.Response(200, json={"current_weather": {"temperature": 21.5}})

    w = {x.name: x for x in werkzeuge_aus_rest(
        [
            {"name": "wetter_abrufen", "methode": "GET", "url": "https://api.open-meteo.com/v1/forecast",
             "parameter": {"latitude": "zahl", "longitude": "zahl", "current_weather": "text"}, "beschreibung": "Wetter"},
            {"name": "licht", "methode": "PUT", "url": "http://bridge/api/u/lights/{licht_id}/state",
             "parameter": {"licht_id": "text", "on": "bool", "bri": {"typ": "ganzzahl", "beschreibung": "Helligkeit"}}},
            {"name": "eintrag_loeschen", "methode": "DELETE", "url": "https://x/e/{id}"},
            {"name": "mit_festen", "url": "https://x/f", "parameter": {"q": {"typ": "text", "pflicht": True, "standard": "a"}},
             "feste_parameter": {"format": "json"}},
        ],
        "test", http_client_fabrik=mock_fabrik(handler), auth={"art": "query", "name": "key", "wert": "K"},
    )}
    assert set(w) == {"test__wetter_abrufen", "test__licht", "test__eintrag_loeschen", "test__mit_festen"}
    assert w["test__wetter_abrufen"].risiko == "lesen" and w["test__licht"].risiko == "aendern"
    assert w["test__eintrag_loeschen"].risiko == "kritisch"
    assert w["test__wetter_abrufen"].json_schema["properties"]["latitude"] == {"type": "number"}
    assert w["test__licht"].json_schema["required"] == ["licht_id"]

    text = await w["test__wetter_abrufen"].ausfuehren(latitude=52.52, longitude=13.4, current_weather="true")
    r = anfragen[-1]
    assert r.url.host == "api.open-meteo.com" and r.url.params["latitude"] == "52.52" and r.url.params["key"] == "K"
    assert "21.5" in text

    await w["test__licht"].ausfuehren(licht_id="3", on=True, bri=200)
    r = anfragen[-1]
    assert r.method == "PUT" and r.url.path == "/api/u/lights/3/state" and json.loads(r.content) == {"on": True, "bri": 200}

    await w["test__mit_festen"].ausfuehren()
    assert anfragen[-1].url.params["q"] == "a" and anfragen[-1].url.params["format"] == "json"


def test_rest_ungueltig():
    with pytest.raises(RestFehler):
        werkzeuge_aus_rest([{"name": "x"}], "t")
    with pytest.raises(RestFehler, match="Unbekannter Parametertyp"):
        werkzeuge_aus_rest([{"name": "x", "url": "https://x", "parameter": {"a": "quark"}}], "t")
