"""Web-Werkzeuge: Webseite lesen (HTML → Text) und Websuche
(DuckDuckGo-HTML ohne Schlüssel; Tavily oder Brave, wenn TAVILY_API_KEY bzw. BRAVE_API_KEY gesetzt)."""

from __future__ import annotations

import os
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from . import FunktionsWerkzeug, Werkzeug, WerkzeugFehler, schema, werkzeug

BENUTZERAGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15 Jarvis/0.1"
)


def http_client_fabrik(**kwargs: Any) -> httpx.AsyncClient:
    """Erzeugt den HTTP-Client (in Tests ersetzbar, z. B. durch MockTransport)."""
    kwargs.setdefault("timeout", 20.0)
    kwargs.setdefault("follow_redirects", True)
    kwargs.setdefault("headers", {"User-Agent": BENUTZERAGENT, "Accept-Language": "de,en;q=0.8"})
    return httpx.AsyncClient(**kwargs)


# ---------------------------------------------------------------------------
# HTML → Text
# ---------------------------------------------------------------------------
class _TextExtraktor(HTMLParser):
    UEBERSPRINGEN = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
    BLOCK = {
        "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header",
        "footer", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr", "main",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.teile: list[str] = []
        self._tiefe_ueberspringen = 0
        self.titel = ""
        self._im_titel = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._im_titel = True
        if tag in self.UEBERSPRINGEN:
            self._tiefe_ueberspringen += 1
        elif tag in self.BLOCK:
            self.teile.append("\n")
        if tag == "li":
            self.teile.append("• ")
        if tag in ("h1", "h2", "h3"):
            self.teile.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._im_titel = False
        if tag in self.UEBERSPRINGEN and self._tiefe_ueberspringen:
            self._tiefe_ueberspringen -= 1
        elif tag in self.BLOCK:
            self.teile.append("\n")

    def handle_data(self, data: str) -> None:
        if self._im_titel:
            self.titel += data
        if not self._tiefe_ueberspringen:
            self.teile.append(data)


def html_zu_text(html: str) -> tuple[str, str]:
    """Gibt (titel, text) zurück."""
    p = _TextExtraktor()
    p.feed(html)
    p.close()
    text = "".join(p.teile)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return p.titel.strip(), text.strip()


@werkzeug(
    "webseite_lesen",
    "Lädt eine Webseite und gibt ihren Text zurück.",
    schema(
        {"url": {"type": "string"}, "max_zeichen": {"type": "integer", "default": 8000}},
        ["url"],
    ),
    risiko="lesen",
)
async def webseite_lesen(url: str, max_zeichen: int = 8000) -> str:
    if not urlparse(url).scheme:
        url = "https://" + url
    if urlparse(url).scheme not in ("http", "https"):
        raise WerkzeugFehler("Nur http- und https-Adressen werden unterstützt.")
    async with http_client_fabrik() as client:
        antwort = await client.get(url)
    if antwort.status_code >= 400:
        raise WerkzeugFehler(f"HTTP {antwort.status_code} beim Abruf von {url}")
    typ = antwort.headers.get("content-type", "")
    if "html" in typ or antwort.text.lstrip().startswith("<"):
        titel, text = html_zu_text(antwort.text)
    else:
        titel, text = "", antwort.text
    max_zeichen = max(500, int(max_zeichen))
    if len(text) > max_zeichen:
        text = text[:max_zeichen] + f"\n… (gekürzt, insgesamt {len(text)} Zeichen)"
    return (f"Titel: {titel}\n\n" if titel else "") + text


# ---------------------------------------------------------------------------
# Websuche
# ---------------------------------------------------------------------------
class _DdgParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ergebnisse: list[dict[str, str]] = []
        self._modus: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        klassen = (a.get("class") or "").split()
        if tag == "a" and "result__a" in klassen:
            self.ergebnisse.append({"titel": "", "url": _ddg_url(a.get("href") or ""), "auszug": ""})
            self._modus = "titel"
        elif "result__snippet" in klassen and self.ergebnisse:
            self._modus = "auszug"

    def handle_endtag(self, tag: str) -> None:
        if tag in ("a", "td", "div") and self._modus:
            self._modus = None

    def handle_data(self, data: str) -> None:
        if self._modus and self.ergebnisse:
            self.ergebnisse[-1][self._modus] += data


def _ddg_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    teile = urlparse(href)
    if "duckduckgo.com" in teile.netloc and teile.path.startswith("/l/"):
        ziel = parse_qs(teile.query).get("uddg")
        if ziel:
            return ziel[0]
    return href


def ddg_ergebnisse_parsen(html: str) -> list[dict[str, str]]:
    p = _DdgParser()
    p.feed(html)
    return [
        {k: unescape(v).strip() for k, v in e.items()}
        for e in p.ergebnisse
        if e["url"] and "duckduckgo.com/y.js" not in e["url"]
    ]


async def _suche_tavily(client: httpx.AsyncClient, anfrage: str, anzahl: int) -> list[dict[str, str]]:
    r = await client.post(
        "https://api.tavily.com/search",
        json={"query": anfrage, "max_results": anzahl},
        headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
    )
    r.raise_for_status()
    return [
        {"titel": e.get("title", ""), "url": e.get("url", ""), "auszug": e.get("content", "")}
        for e in r.json().get("results", [])
    ]


async def _suche_brave(client: httpx.AsyncClient, anfrage: str, anzahl: int) -> list[dict[str, str]]:
    r = await client.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": anfrage, "count": anzahl},
        headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"], "Accept": "application/json"},
    )
    r.raise_for_status()
    return [
        {"titel": e.get("title", ""), "url": e.get("url", ""), "auszug": e.get("description", "")}
        for e in r.json().get("web", {}).get("results", [])
    ]


async def _suche_ddg(client: httpx.AsyncClient, anfrage: str, anzahl: int) -> list[dict[str, str]]:
    r = await client.post("https://html.duckduckgo.com/html/", data={"q": anfrage, "kl": "de-de"})
    r.raise_for_status()
    return ddg_ergebnisse_parsen(r.text)


@werkzeug(
    "websuche",
    "Sucht im Web und liefert Titel, URL und Auszug der besten Treffer.",
    schema(
        {"anfrage": {"type": "string"}, "anzahl": {"type": "integer", "default": 5, "maximum": 10}},
        ["anfrage"],
    ),
    risiko="lesen",
)
async def websuche(anfrage: str, anzahl: int = 5) -> str:
    anzahl = max(1, min(int(anzahl), 10))
    ergebnisse: list[dict[str, str]] = []
    async with http_client_fabrik() as client:
        anbieter = []
        if os.environ.get("TAVILY_API_KEY"):
            anbieter.append(_suche_tavily)
        if os.environ.get("BRAVE_API_KEY"):
            anbieter.append(_suche_brave)
        anbieter.append(_suche_ddg)
        letzter_fehler: Exception | None = None
        for funktion in anbieter:
            try:
                ergebnisse = await funktion(client, anfrage, anzahl)
                if ergebnisse:
                    break
            except (httpx.HTTPError, KeyError, ValueError) as e:
                letzter_fehler = e
    if not ergebnisse:
        if letzter_fehler:
            raise WerkzeugFehler(f"Websuche fehlgeschlagen: {letzter_fehler}")
        return f"Keine Ergebnisse für „{anfrage}“."
    return "\n\n".join(
        f"{i}. {e['titel']}\n{e['url']}\n{e['auszug']}" for i, e in enumerate(ergebnisse[:anzahl], 1)
    )


def werkzeuge() -> list[Werkzeug]:
    return [w for w in globals().values() if isinstance(w, FunktionsWerkzeug)]
