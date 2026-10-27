"""Screenshots der Oberfläche in allen wichtigen Zuständen.

Voraussetzung: `npm run mock` (Port 8765) und `npm run preview` (Port 4173) laufen.
Aufruf: python3 scripts/screenshots.py [ausgabeordner]
"""
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASIS = os.environ.get("JARVIS_UI", "http://127.0.0.1:4173")
MOCK = os.environ.get("JARVIS_MOCK", "http://127.0.0.1:8765")
AUS = sys.argv[1] if len(sys.argv) > 1 else "/tmp/jarvis-ui"
os.makedirs(AUS, exist_ok=True)


def szenario(name: str) -> None:
    req = urllib.request.Request(f"{MOCK}/mock/szenario/{name}", method="POST", data=b"")
    urllib.request.urlopen(req).read()


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        ctx.add_init_script("try { sessionStorage.setItem('jarvis.boot', '1') } catch (e) {}")
        page = ctx.new_page()
        fehler = []
        page.on("pageerror", lambda e: fehler.append(str(e)))
        page.on("console", lambda m: fehler.append(m.text) if m.type == "error" else None)

        def neu():
            szenario("reset")
            page.goto(BASIS)
            page.wait_for_selector(".verbindung-offen", timeout=10000)
            page.wait_for_timeout(600)

        def schuss(name: str):
            pfad = os.path.join(AUS, f"{name}.png")
            page.screenshot(path=pfad)
            print("gespeichert:", pfad)

        neu()
        szenario("gespraech")
        page.wait_for_timeout(1200)
        schuss("01-bereit")

        neu()
        szenario("hoert")
        page.wait_for_timeout(2400)
        schuss("02-hoert")

        neu()
        szenario("denkt")
        page.wait_for_timeout(1500)
        schuss("03-denkt-aktivitaet")

        szenario("arbeitet")
        page.wait_for_timeout(1500)
        schuss("03b-arbeitet")

        neu()
        szenario("freigabe")
        page.wait_for_timeout(1500)
        schuss("04-freigabe")
        page.keyboard.press("Escape")

        neu()
        szenario("gespraech")
        page.wait_for_timeout(300)
        szenario("spricht")
        page.wait_for_timeout(1200)
        schuss("04b-spricht")

        neu()
        page.get_by_role("tab", name="Integrationen").click()
        page.wait_for_selector(".kat-kachel")
        page.wait_for_timeout(500)
        schuss("05-integrationen-katalog")

        page.locator(".kat-kachel", has_text="Spotify").click()
        page.wait_for_timeout(400)
        schuss("05b-integrationen-formular")

        page.get_by_role("tab", name="Eigene").click()
        page.wait_for_timeout(400)
        schuss("05c-integrationen-eigene")

        page.get_by_role("tab", name="Installiert", exact=False).click()
        page.wait_for_timeout(400)
        schuss("05d-integrationen-installiert")

        page.get_by_role("tab", name="Einstellungen").click()
        page.wait_for_selector(".modell")
        page.wait_for_timeout(600)
        schuss("06-einstellungen")

        page.get_by_role("tab", name="Konsole").click()
        page.keyboard.press("Control+k")
        page.wait_for_timeout(500)
        schuss("07-befehlspalette")
        page.keyboard.press("Escape")

        page.set_viewport_size({"width": 420, "height": 860})
        szenario("gespraech")
        page.wait_for_timeout(800)
        schuss("08-schmal")

        browser.close()
        if fehler:
            print("Browser-Fehler:", json.dumps(fehler, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
