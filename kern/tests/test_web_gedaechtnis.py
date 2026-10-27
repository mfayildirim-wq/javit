import httpx
import pytest

from jarvis.gedaechtnis import Gedaechtnis
from jarvis.werkzeuge import WerkzeugFehler, web
from tests.conftest import mock_fabrik

DDG = """
<div class="result"><h2><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fde.wikipedia.org%2Fwiki%2FJ.A.R.V.I.S.&rut=x">J.A.R.V.I.S. &ndash; Wikipedia</a></h2>
<a class="result__snippet" href="#">Ein <b>KI</b>-Assistent aus Iron Man.</a></div>
<div class="result"><h2><a class="result__a" href="https://example.com/b">Zweiter</a></h2>
<div class="result__snippet">Auszug zwei</div></div>
"""


def test_html_zu_text():
    titel, text = web.html_zu_text("<html><head><title>Titel</title><style>x{}</style></head><body><h1>Kopf</h1><p>Absatz <b>fett</b></p><script>alert(1)</script><ul><li>eins</li></ul></body></html>")
    assert titel == "Titel" and "Kopf" in text and "Absatz fett" in text and "alert" not in text and "• eins" in text


def test_ddg_parsen():
    e = web.ddg_ergebnisse_parsen(DDG)
    assert e[0] == {"titel": "J.A.R.V.I.S. – Wikipedia", "url": "https://de.wikipedia.org/wiki/J.A.R.V.I.S.", "auszug": "Ein KI-Assistent aus Iron Man."}
    assert e[1]["url"] == "https://example.com/b" and e[1]["auszug"] == "Auszug zwei"


async def test_websuche_ddg_und_tavily(monkeypatch):
    anfragen = []

    def handler(request):
        anfragen.append(request)
        if request.url.host == "api.tavily.com":
            return httpx.Response(200, json={"results": [{"title": "T", "url": "https://t", "content": "c"}]})
        return httpx.Response(200, text=DDG)

    monkeypatch.setattr(web, "http_client_fabrik", mock_fabrik(handler))
    text = await web.websuche.ausfuehren(anfrage="Jarvis", anzahl=1)
    assert text.startswith("1. J.A.R.V.I.S.") and "Zweiter" not in text
    assert anfragen[-1].url.host == "html.duckduckgo.com"
    monkeypatch.setenv("TAVILY_API_KEY", "tv")
    text = await web.websuche.ausfuehren(anfrage="Jarvis")
    assert "1. T\nhttps://t\nc" == text and anfragen[-1].headers["Authorization"] == "Bearer tv"


async def test_webseite_lesen(monkeypatch):
    def handler(request):
        if request.url.path == "/404":
            return httpx.Response(404)
        return httpx.Response(200, html="<title>Seite</title><p>" + "Wort " * 5000 + "</p>")

    monkeypatch.setattr(web, "http_client_fabrik", mock_fabrik(handler))
    text = await web.webseite_lesen.ausfuehren(url="example.com", max_zeichen=1000)
    assert text.startswith("Titel: Seite") and "gekürzt" in text
    with pytest.raises(WerkzeugFehler, match="404"):
        await web.webseite_lesen.ausfuehren(url="https://example.com/404")
    with pytest.raises(WerkzeugFehler):
        await web.webseite_lesen.ausfuehren(url="ftp://x")


async def test_gedaechtnis_schluesselwortsuche():
    g = Gedaechtnis()
    await g.erinnern("Meine Frau heißt Pepper.")
    await g.erinnern("Ich trinke Kaffee am liebsten schwarz.")
    await g.erinnern("Mein Auto ist ein Audi R8.")
    treffer = await g.suchen("Wie trinke ich meinen Kaffee?")
    assert treffer[0]["text"].startswith("Ich trinke Kaffee")
    assert all("Audi" not in t["text"] for t in treffer)
    assert await g.suchen("Quantenphysik") == []
    assert len(g.erinnerungen()) == 3
    assert g.erinnerung_loeschen(g.erinnerungen()[0]["id"]) == 1
    assert g.erinnerung_loeschen() == 2


async def test_gedaechtnis_mit_einbettungen():
    vektoren = {"Pepper": [1.0, 0.0, 0.0], "Auto": [0.0, 1.0, 0.0], "Ehefrau": [0.9, 0.1, 0.0]}

    async def einbetten(texte):
        return [next(v for k, v in vektoren.items() if k in t) for t in texte]

    g = Gedaechtnis(einbetten=einbetten)
    await g.erinnern("Name: Pepper")
    await g.erinnern("Auto: Audi")
    treffer = await g.suchen("Wie heißt meine Ehefrau?")
    assert [t["text"] for t in treffer] == ["Name: Pepper"] and treffer[0]["relevanz"] > 0.9


def test_verlauf():
    g = Gedaechtnis()
    for i in range(5):
        g.verlauf_hinzufuegen("nutzer", f"n{i}")
    assert [v["inhalt"] for v in g.verlauf(limit=2)] == ["n3", "n4"]
    g.verlauf_loeschen()
    assert g.verlauf() == []
