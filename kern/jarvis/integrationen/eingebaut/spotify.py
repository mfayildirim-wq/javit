"""Eingebaute Spotify-Integration über die Spotify-Web-API (ohne Fremd-SDK).

- Mit SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET (Client-Credentials) kann gesucht werden;
  abgespielt wird dann über die Spotify-Desktop-App per AppleScript (`play track "<uri>"`).
- Mit zusätzlichem SPOTIFY_REFRESH_TOKEN (über `jarvis spotify-anmelden`) wird die Wiedergabe
  direkt über die Web-API gesteuert (auch auf anderen Geräten, Warteschlange, Playlists).
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import httpx

from ...werkzeuge import FunktionsWerkzeug, Werkzeug, WerkzeugFehler, schema

API = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTORISIERUNG_URL = "https://accounts.spotify.com/authorize"
SCOPES = (
    "user-read-playback-state user-modify-playback-state user-read-currently-playing "
    "playlist-read-private playlist-read-collaborative user-library-read"
)
STANDARD_RUECKRUF = "http://127.0.0.1:8888/callback"


def autorisierungs_url(client_id: str, rueckruf: str = STANDARD_RUECKRUF) -> str:
    return AUTORISIERUNG_URL + "?" + urlencode(
        {"client_id": client_id, "response_type": "code", "redirect_uri": rueckruf, "scope": SCOPES}
    )


async def code_eintauschen(
    client_id: str, client_secret: str, code: str, rueckruf: str = STANDARD_RUECKRUF,
    http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
) -> dict[str, Any]:
    fabrik = http_client_fabrik or (lambda **kw: httpx.AsyncClient(timeout=20.0, **kw))
    basis = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    async with fabrik() as client:
        r = await client.post(
            TOKEN_URL,
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": rueckruf},
            headers={"Authorization": f"Basic {basis}"},
        )
    if r.status_code >= 400:
        raise WerkzeugFehler(f"Spotify-Anmeldung fehlgeschlagen: {r.text}")
    return r.json()


class SpotifyKlient:
    def __init__(self, werte: dict[str, str], http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None):
        self.client_id = werte.get("SPOTIFY_CLIENT_ID", "")
        self.client_secret = werte.get("SPOTIFY_CLIENT_SECRET", "")
        self.refresh_token = werte.get("SPOTIFY_REFRESH_TOKEN") or None
        self._fabrik = http_client_fabrik or (lambda **kw: httpx.AsyncClient(timeout=20.0, **kw))
        self._token: str | None = None
        self._ablauf = 0.0

    @property
    def hat_nutzerzugang(self) -> bool:
        return bool(self.refresh_token)

    async def token(self) -> str:
        if self._token and time.time() < self._ablauf - 30:
            return self._token
        if not self.client_id or not self.client_secret:
            raise WerkzeugFehler("SPOTIFY_CLIENT_ID und SPOTIFY_CLIENT_SECRET fehlen.")
        basis = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        daten = (
            {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
            if self.refresh_token
            else {"grant_type": "client_credentials"}
        )
        async with self._fabrik() as client:
            r = await client.post(TOKEN_URL, data=daten, headers={"Authorization": f"Basic {basis}"})
        if r.status_code >= 400:
            raise WerkzeugFehler(f"Spotify-Token konnte nicht geholt werden: HTTP {r.status_code} {r.text[:300]}")
        antwort = r.json()
        self._token = antwort["access_token"]
        self._ablauf = time.time() + float(antwort.get("expires_in", 3600))
        if antwort.get("refresh_token"):
            self.refresh_token = antwort["refresh_token"]
        return self._token

    async def anfrage(self, methode: str, pfad: str, **kwargs: Any) -> Any:
        token = await self.token()
        async with self._fabrik() as client:
            r = await client.request(methode, API + pfad, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        if r.status_code == 204 or not r.content:
            return None
        if r.status_code == 404 and "NO_ACTIVE_DEVICE" in r.text:
            raise WerkzeugFehler("Kein aktives Spotify-Gerät. Bitte Spotify auf einem Gerät öffnen.")
        if r.status_code >= 400:
            raise WerkzeugFehler(f"Spotify-API-Fehler HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    async def suchen(self, anfrage: str, typ: str = "track", anzahl: int = 5) -> list[dict[str, Any]]:
        daten = await self.anfrage("GET", "/search", params={"q": anfrage, "type": typ, "limit": anzahl, "market": "DE"})
        eintraege = (daten or {}).get(f"{typ}s", {}).get("items", [])
        ergebnis = []
        for e in eintraege:
            if not e:
                continue
            kuenstler = ", ".join(a.get("name", "") for a in e.get("artists", []) or [])
            if typ == "playlist":
                kuenstler = (e.get("owner") or {}).get("display_name", "")
            ergebnis.append({"name": e.get("name"), "kuenstler": kuenstler, "uri": e.get("uri")})
        return ergebnis


def werkzeuge(
    integration_id: str,
    werte: dict[str, str],
    http_client_fabrik: Callable[..., httpx.AsyncClient] | None = None,
) -> list[Werkzeug]:
    klient = SpotifyKlient(werte, http_client_fabrik)
    p = f"{integration_id}__"

    async def suchen(anfrage: str, typ: str = "track", anzahl: int = 5) -> str:
        treffer = await klient.suchen(anfrage, typ, max(1, min(int(anzahl), 20)))
        if not treffer:
            return f"Nichts gefunden für „{anfrage}“."
        return "\n".join(f"{t['name']} – {t['kuenstler']} ({t['uri']})" for t in treffer)

    async def abspielen(anfrage: str | None = None, uri: str | None = None, typ: str = "track") -> str:
        beschreibung = uri
        if not uri:
            if not anfrage:
                raise WerkzeugFehler("Bitte anfrage oder uri angeben.")
            treffer = await klient.suchen(anfrage, typ, 1)
            if not treffer:
                return f"Nichts gefunden für „{anfrage}“."
            uri = treffer[0]["uri"]
            beschreibung = f"{treffer[0]['name']} – {treffer[0]['kuenstler']}"
        if klient.hat_nutzerzugang:
            body = {"uris": [uri]} if ":track:" in uri or ":episode:" in uri else {"context_uri": uri}
            await klient.anfrage("PUT", "/me/player/play", json=body)
            return f"Spiele {beschreibung}."
        from ...werkzeuge.mac import as_text, osascript

        await osascript(f'tell application "Spotify" to play track {as_text(uri)}')
        return f"Spiele {beschreibung} in der Spotify-App."

    async def aktuell() -> str:
        if not klient.hat_nutzerzugang:
            from ...werkzeuge.mac import musik_steuern

            return await musik_steuern.ausfuehren(aktion="aktuell", app="spotify")
        daten = await klient.anfrage("GET", "/me/player/currently-playing")
        if not daten or not daten.get("item"):
            return "Es läuft gerade nichts."
        item = daten["item"]
        kuenstler = ", ".join(a["name"] for a in item.get("artists", []))
        return f"{item.get('name')} – {kuenstler}" + ("" if daten.get("is_playing") else " (pausiert)")

    async def steuern(aktion: str) -> str:
        if not klient.hat_nutzerzugang:
            from ...werkzeuge.mac import musik_steuern

            return await musik_steuern.ausfuehren(aktion=aktion, app="spotify")
        wege = {
            "play": ("PUT", "/me/player/play"),
            "pause": ("PUT", "/me/player/pause"),
            "weiter": ("POST", "/me/player/next"),
            "zurueck": ("POST", "/me/player/previous"),
        }
        if aktion not in wege:
            raise WerkzeugFehler(f"Unbekannte Aktion: {aktion}")
        await klient.anfrage(*wege[aktion])
        return f"Spotify: {aktion}."

    async def warteschlange(anfrage: str | None = None, uri: str | None = None) -> str:
        if not klient.hat_nutzerzugang:
            raise WerkzeugFehler("Dafür ist eine Spotify-Anmeldung nötig: jarvis spotify-anmelden")
        if not uri:
            treffer = await klient.suchen(anfrage or "", "track", 1)
            if not treffer:
                return "Nichts gefunden."
            uri = treffer[0]["uri"]
        await klient.anfrage("POST", "/me/player/queue", params={"uri": uri})
        return f"{uri} zur Warteschlange hinzugefügt."

    async def playlists() -> str:
        if not klient.hat_nutzerzugang:
            raise WerkzeugFehler("Dafür ist eine Spotify-Anmeldung nötig: jarvis spotify-anmelden")
        daten = await klient.anfrage("GET", "/me/playlists", params={"limit": 50})
        return "\n".join(f"{p['name']} ({p['uri']})" for p in (daten or {}).get("items", []) if p) or "Keine Playlists."

    typ_schema = {"type": "string", "enum": ["track", "album", "artist", "playlist"], "default": "track"}
    return [
        FunktionsWerkzeug(suchen, p + "suchen", "Sucht auf Spotify nach Titeln, Alben, Künstlern oder Playlists.",
                          schema({"anfrage": {"type": "string"}, "typ": typ_schema, "anzahl": {"type": "integer", "default": 5}}, ["anfrage"]),
                          risiko="lesen", quelle="eingebaut", integration=integration_id),
        FunktionsWerkzeug(abspielen, p + "abspielen", "Spielt einen Titel/ein Album/eine Playlist auf Spotify ab (per Suchbegriff oder URI).",
                          schema({"anfrage": {"type": "string"}, "uri": {"type": "string"}, "typ": typ_schema}),
                          risiko="aendern", quelle="eingebaut", integration=integration_id),
        FunktionsWerkzeug(aktuell, p + "aktueller_titel", "Nennt den aktuell auf Spotify laufenden Titel.",
                          schema(), risiko="lesen", quelle="eingebaut", integration=integration_id),
        FunktionsWerkzeug(steuern, p + "steuern", "Spotify-Wiedergabe steuern: play, pause, weiter, zurueck.",
                          schema({"aktion": {"type": "string", "enum": ["play", "pause", "weiter", "zurueck"]}}, ["aktion"]),
                          risiko="aendern", quelle="eingebaut", integration=integration_id),
        FunktionsWerkzeug(warteschlange, p + "warteschlange", "Fügt einen Titel zur Spotify-Warteschlange hinzu.",
                          schema({"anfrage": {"type": "string"}, "uri": {"type": "string"}}),
                          risiko="aendern", quelle="eingebaut", integration=integration_id),
        FunktionsWerkzeug(playlists, p + "meine_playlists", "Listet die eigenen Spotify-Playlists auf.",
                          schema(), risiko="lesen", quelle="eingebaut", integration=integration_id),
    ]
