"""OAuth-Anmeldung für entfernte MCP-Server.

* ``entdeckung`` (MCP-Standard): Der Server antwortet 401 mit Metadaten, Javit registriert sich dynamisch,
  öffnet den Browser, nimmt den Rückruf unter ``/oauth/rueckruf`` entgegen und tauscht den Code gegen
  Tokens (PKCE). Umgesetzt mit ``mcp.client.auth.OAuthClientProvider`` aus dem MCP-SDK.
* ``manuell`` (z. B. Google Workspace): Der Anbieter erlaubt keine dynamische Registrierung; der Nutzer
  hinterlegt einmal Client-ID und -Secret, Javit führt den Authorization-Code-Flow mit PKCE selbst aus
  (Autorisierungs-URL, Token-URL, Scopes und Zusatzparameter aus dem Katalog) und erneuert Tokens.

Tokens und Client-Registrierungen liegen ausschließlich im Geheimnisspeicher (Schlüsselbund), nie in
``integrationen.json``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import httpx2  # das MCP-SDK (und damit der MCP-HTTP-Client) nutzt httpx2
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import BaseModel, ConfigDict, Field

from ..geheimnisse import Geheimnisspeicher

Melden = Callable[[dict[str, Any]], Awaitable[None]]
RUECKRUF_ZEITLIMIT = 300.0
CLIENT_NAME = "Javit"


class OAuthFehler(RuntimeError):
    pass


class OAuthKonfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modus: Literal["entdeckung", "manuell"] = "entdeckung"
    autorisierung_url: str | None = None
    token_url: str | None = None
    scopes: list[str] = Field(default_factory=list)
    #: Platzhalter ``${NAME}`` auf Katalogfelder (manuell)
    client_id: str | None = None
    client_secret: str | None = None
    #: Zusatzparameter der Autorisierungs-URL, z. B. access_type=offline, prompt=consent (Google)
    extra: dict[str, str] = Field(default_factory=dict)

    def pruefen(self) -> None:
        if self.modus == "manuell" and not (self.autorisierung_url and self.token_url and self.client_id):
            raise ValueError("oauth manuell braucht autorisierung_url, token_url und client_id")


def geheimnis_namen(kennung: str) -> tuple[str, str]:
    basis = "JARVIS_OAUTH_" + "".join(c if c.isalnum() else "_" for c in kennung.upper())
    return f"{basis}_TOKENS", f"{basis}_CLIENT"


class SchluesselbundSpeicher(TokenStorage):
    """Tokens und Client-Registrierung je Integration im Geheimnisspeicher."""

    def __init__(self, geheimnisse: Geheimnisspeicher, kennung: str):
        self.geheimnisse = geheimnisse
        self.name_tokens, self.name_client = geheimnis_namen(kennung)

    def _lesen(self, name: str) -> dict[str, Any] | None:
        roh = self.geheimnisse.holen(name)
        if not roh:
            return None
        try:
            daten = json.loads(roh)
        except json.JSONDecodeError:
            return None
        return daten if isinstance(daten, dict) else None

    async def get_tokens(self) -> OAuthToken | None:
        daten = self._lesen(self.name_tokens)
        if not daten:
            return None
        try:
            return OAuthToken.model_validate({k: v for k, v in daten.items() if k != "ablauf"})
        except ValueError:
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        daten = tokens.model_dump(exclude_none=True)
        if tokens.expires_in:
            daten["ablauf"] = time.time() + float(tokens.expires_in)
        self.geheimnisse.setzen(self.name_tokens, json.dumps(daten))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        daten = self._lesen(self.name_client)
        if not daten:
            return None
        try:
            return OAuthClientInformationFull.model_validate(daten)
        except ValueError:
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.geheimnisse.setzen(self.name_client, client_info.model_dump_json(exclude_none=True))

    # Für den manuellen Flow: Rohdaten inkl. Ablaufzeit
    def tokens_roh(self) -> dict[str, Any] | None:
        return self._lesen(self.name_tokens)

    def tokens_roh_setzen(self, daten: dict[str, Any]) -> None:
        self.geheimnisse.setzen(self.name_tokens, json.dumps(daten))

    def angemeldet(self) -> bool:
        daten = self._lesen(self.name_tokens)
        return bool(daten and daten.get("access_token"))

    def loeschen(self) -> None:
        for name in (self.name_tokens, self.name_client):
            try:
                self.geheimnisse.loeschen(name)
            except Exception:  # noqa: BLE001
                pass


class Rueckrufe:
    """Wartende Browser-Anmeldungen, zugeordnet über den OAuth-``state``."""

    def __init__(self) -> None:
        self._wartend: dict[str, asyncio.Future[AuthorizationCodeResult]] = {}

    def erwarten(self, state: str) -> asyncio.Future[AuthorizationCodeResult]:
        f: asyncio.Future[AuthorizationCodeResult] = asyncio.get_running_loop().create_future()
        self._wartend[state] = f
        return f

    def erfuellen(self, parameter: dict[str, str]) -> bool:
        """Rückruf aus dem Browser; True, wenn ein wartender Flow dazu gehört."""
        state = parameter.get("state") or ""
        f = self._wartend.pop(state, None)
        if f is None or f.done():
            return False
        fehler = parameter.get("error")
        if fehler:
            f.set_exception(OAuthFehler(f"Anmeldung abgelehnt: {fehler} {parameter.get('error_description', '')}".strip()))
        else:
            f.set_result(AuthorizationCodeResult(code=parameter.get("code") or "", state=state, iss=parameter.get("iss")))
        return True

    async def warten(self, state: str, zeitlimit: float = RUECKRUF_ZEITLIMIT) -> AuthorizationCodeResult:
        f = self._wartend.get(state) or self.erwarten(state)
        try:
            return await asyncio.wait_for(f, zeitlimit)
        except asyncio.TimeoutError as e:
            self._wartend.pop(state, None)
            raise OAuthFehler(f"Keine Antwort aus dem Browser innerhalb von {zeitlimit:.0f} s.") from e

    def offen(self) -> int:
        return len(self._wartend)


def state_aus_url(url: str) -> str | None:
    werte = parse_qs(urlparse(url).query).get("state")
    return werte[0] if werte else None


def url_mit_extra(url: str, extra: dict[str, str]) -> str:
    if not extra:
        return url
    return url + ("&" if "?" in url else "?") + urlencode(extra)


def browser_oeffnen(url: str) -> None:
    """Öffnet die Anmeldeseite im Standardbrowser (in Tests ersetzt, mit JARVIS_OHNE_BROWSER abschaltbar)."""
    if os.environ.get("JARVIS_OHNE_BROWSER") == "1":
        return
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()


async def _anmeldung_melden(melden: Melden | None, kennung: str, url: str) -> None:
    if melden is None:
        return
    try:
        await melden({"typ": "oauth_anmeldung", "integration": kennung, "url": url})
    except Exception:  # noqa: BLE001
        pass


def entdeckungs_auth(
    kennung: str,
    server_url: str,
    rueckruf_url: str,
    speicher: SchluesselbundSpeicher,
    rueckrufe: Rueckrufe,
    melden: Melden | None = None,
    konfig: OAuthKonfig | None = None,
) -> OAuthClientProvider:
    """OAuth nach MCP-Standard (Entdeckung + dynamische Registrierung) über das MCP-SDK."""
    konfig = konfig or OAuthKonfig()
    metadata = OAuthClientMetadata(
        client_name=CLIENT_NAME,
        redirect_uris=[rueckruf_url],  # type: ignore[list-item]
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        scope=" ".join(konfig.scopes) or None,
    )
    zustand: dict[str, str] = {}

    async def weiterleiten(url: str) -> None:
        url = url_mit_extra(url, konfig.extra)
        state = state_aus_url(url) or ""
        zustand["state"] = state
        rueckrufe.erwarten(state)
        await _anmeldung_melden(melden, kennung, url)
        browser_oeffnen(url)

    async def rueckruf() -> AuthorizationCodeResult:
        return await rueckrufe.warten(zustand.get("state", ""))

    return OAuthClientProvider(server_url, metadata, speicher, weiterleiten, rueckruf)


class ManuellerOAuth(httpx2.Auth):
    """Authorization-Code-Flow mit PKCE für Anbieter ohne dynamische Registrierung (Google)."""

    requires_response_body = True

    def __init__(
        self,
        kennung: str,
        konfig: OAuthKonfig,
        client_id: str,
        client_secret: str | None,
        rueckruf_url: str,
        speicher: SchluesselbundSpeicher,
        rueckrufe: Rueckrufe,
        melden: Melden | None = None,
        http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
    ):
        konfig.pruefen()
        self.kennung = kennung
        self.konfig = konfig
        self.client_id = client_id
        self.client_secret = client_secret
        self.rueckruf_url = rueckruf_url
        self.speicher = speicher
        self.rueckrufe = rueckrufe
        self.melden = melden
        self._http = http_client_fabrik or (lambda **kw: httpx.AsyncClient(**kw))
        self._sperre = asyncio.Lock()

    async def async_auth_flow(self, request: httpx2.Request) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        token = await self._token_sicherstellen()
        request.headers["Authorization"] = f"Bearer {token}"
        antwort = yield request
        if antwort.status_code == 401:
            token = await self._token_sicherstellen(erzwingen=True)
            request.headers["Authorization"] = f"Bearer {token}"
            yield request

    def sync_auth_flow(self, request: httpx2.Request):  # pragma: no cover - nur asynchron genutzt
        raise RuntimeError("ManuellerOAuth unterstützt nur asynchrone Aufrufe")

    async def _token_sicherstellen(self, erzwingen: bool = False) -> str:
        async with self._sperre:
            daten = self.speicher.tokens_roh() or {}
            gueltig = daten.get("access_token") and time.time() < float(daten.get("ablauf") or 0)
            if gueltig and not erzwingen:
                return str(daten["access_token"])
            if daten.get("refresh_token"):
                try:
                    return await self._erneuern(str(daten["refresh_token"]))
                except OAuthFehler:
                    pass  # Refresh-Token ungültig → neu anmelden
            return await self._anmelden()

    async def _anmelden(self) -> str:
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(24)
        parameter = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.rueckruf_url,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if self.konfig.scopes:
            parameter["scope"] = " ".join(self.konfig.scopes)
        parameter.update(self.konfig.extra)
        url = f"{self.konfig.autorisierung_url}?{urlencode(parameter)}"
        self.rueckrufe.erwarten(state)
        await _anmeldung_melden(self.melden, self.kennung, url)
        browser_oeffnen(url)
        ergebnis = await self.rueckrufe.warten(state)
        if not ergebnis.code:
            raise OAuthFehler("Kein Autorisierungscode erhalten.")
        daten = {
            "grant_type": "authorization_code",
            "code": ergebnis.code,
            "redirect_uri": self.rueckruf_url,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }
        if self.client_secret:
            daten["client_secret"] = self.client_secret
        return await self._token_anfordern(daten)

    async def _erneuern(self, refresh_token: str) -> str:
        daten = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.client_id}
        if self.client_secret:
            daten["client_secret"] = self.client_secret
        return await self._token_anfordern(daten, refresh_token=refresh_token)

    async def _token_anfordern(self, daten: dict[str, str], refresh_token: str | None = None) -> str:
        try:
            async with self._http(timeout=30.0) as client:
                r = await client.post(str(self.konfig.token_url), data=daten, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise OAuthFehler(f"Token-Anfrage fehlgeschlagen: {e}") from e
        if r.status_code >= 400:
            raise OAuthFehler(f"Token-Anfrage abgelehnt ({r.status_code}): {r.text[:200]}")
        try:
            antwort = r.json()
        except ValueError as e:
            raise OAuthFehler("Token-Antwort ist kein JSON.") from e
        token = antwort.get("access_token")
        if not token:
            raise OAuthFehler("Token-Antwort ohne access_token.")
        gespeichert = {
            "access_token": token,
            "token_type": antwort.get("token_type", "Bearer"),
            "refresh_token": antwort.get("refresh_token") or refresh_token,
            "scope": antwort.get("scope"),
            "ablauf": time.time() + float(antwort.get("expires_in") or 3600) - 60,
        }
        self.speicher.tokens_roh_setzen({k: v for k, v in gespeichert.items() if v is not None})
        return str(token)


def auth_fuer(
    kennung: str,
    server_url: str,
    oauth: dict[str, Any] | None,
    werte: dict[str, str],
    geheimnisse: Geheimnisspeicher,
    rueckruf_url: str,
    rueckrufe: Rueckrufe,
    melden: Melden | None = None,
    http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
) -> httpx2.Auth | None:
    """Baut aus der ``oauth``-Konfiguration einer Integration das passende ``httpx2.Auth`` (MCP-Client)."""
    if not oauth:
        return None
    konfig = OAuthKonfig.model_validate(oauth)
    speicher = SchluesselbundSpeicher(geheimnisse, kennung)
    if konfig.modus == "manuell":
        konfig.pruefen()
        from .katalog import platzhalter_ersetzen  # noqa: PLC0415

        client_id = str(platzhalter_ersetzen(konfig.client_id or "", werte)).strip()
        client_secret = str(platzhalter_ersetzen(konfig.client_secret or "", werte)).strip() or None
        if not client_id or client_id.startswith("${"):
            raise OAuthFehler("OAuth-Client-ID fehlt – bitte in den Werten der Integration eintragen.")
        return ManuellerOAuth(kennung, konfig, client_id, client_secret, rueckruf_url, speicher, rueckrufe, melden, http_client_fabrik)
    return entdeckungs_auth(kennung, server_url, rueckruf_url, speicher, rueckrufe, melden, konfig)
