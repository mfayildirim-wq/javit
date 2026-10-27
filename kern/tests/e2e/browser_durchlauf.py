"""Browser-Durchlauf der gebauten Oberfläche gegen echten Kern + Fake-LLM (Python-Playwright).

Voraussetzung: oberflaeche/dist gebaut (npm run build), Playwright + Chromium installiert.
Aufruf (aus kern/): python3 -m tests.e2e.browser_durchlauf [/tmp/jarvis-e2e]
Erzeugt Screenshots (1440×900) und bricht mit Fehlercode ab, wenn ein Schritt scheitert.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

from tests.e2e.umgebung import MINI_MCP, E2EUmgebung


def main() -> int:
    aus = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/jarvis-e2e")
    aus.mkdir(parents=True, exist_ok=True)
    u = E2EUmgebung(8765, 8790)
    opfer_ordner = Path(tempfile.mkdtemp(prefix="jarvis-e2e-opfer-"))
    try:
        u.starten()
        r = httpx.post(f"{u.url}/api/integrationen",
                       json={"name": "Mini Test", "mcp_befehl": f"{sys.executable} {MINI_MCP}"}, timeout=60)
        assert r.json()["status"] == "verbunden", r.text
        opfer = opfer_ordner / "alte-notiz.txt"
        opfer.write_text("bitte löschen")

        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script("try { sessionStorage.setItem('jarvis.boot', '1') } catch (e) {}")
            page = ctx.new_page()
            fehler: list[str] = []
            page.on("pageerror", lambda e: fehler.append(f"pageerror: {e}"))
            page.on("console", lambda m: fehler.append(f"console: {m.text}") if m.type == "error" else None)

            def ohne_alten_namen(schritt: str) -> None:
                text = page.inner_text("body")
                assert "Jarvis" not in text, f"{schritt}: „Jarvis“ sichtbar"

            # Boot-Animation mit dem Namen (eigener Kontext ohne Überspringen)
            boot = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            boot.goto(u.url + "/")
            expect(boot.locator(".boot-wort")).to_have_text("Javit", timeout=10000)
            boot.wait_for_timeout(500)
            boot.screenshot(path=str(aus / "00-boot.png"))
            boot.context.close()

            page.goto(u.url + "/")
            page.wait_for_selector(".verbindung-offen", timeout=15000)
            expect(page).to_have_title("Javit", timeout=10000)
            expect(page.locator(".marke-wort")).to_have_text("Javit")
            expect(page.get_by_text("Guten Tag, hier ist Javit. Womit kann ich helfen?")).to_be_visible()
            page.wait_for_timeout(800)
            ohne_alten_namen("Start")
            page.screenshot(path=str(aus / "01-start.png"))

            eingabe = page.get_by_label("Nachricht an Javit")
            expect(eingabe).to_have_attribute("placeholder", "Nachricht an Javit …")
            eingabe.fill("Wie spät ist es? Uhrzeit bitte")
            eingabe.press("Enter")
            expect(page.get_by_text("Erledigt. Ergebnis:").first).to_be_visible(timeout=20000)
            expect(page.get_by_text("uhrzeit_datum").first).to_be_visible(timeout=5000)
            page.wait_for_timeout(600)
            page.screenshot(path=str(aus / "02-antwort-aktivitaet.png"))

            eingabe.fill(f"Lösche Datei {opfer}")
            eingabe.press("Enter")
            dialog = page.get_by_role("alertdialog").or_(page.get_by_role("dialog"))
            expect(dialog.first).to_be_visible(timeout=20000)
            expect(page.get_by_text("datei_loeschen").first).to_be_visible()
            expect(page.get_by_role("heading", name="Darf Javit das ausführen?")).to_be_visible()
            ohne_alten_namen("Freigabe")
            page.wait_for_timeout(400)
            page.screenshot(path=str(aus / "03-freigabe-dialog.png"))
            page.get_by_role("button", name="Erlauben").click()
            expect(page.get_by_text("liegt jetzt im Papierkorb").first).to_be_visible(timeout=20000)
            assert not opfer.exists(), "Datei wurde trotz Freigabe nicht gelöscht"
            page.wait_for_timeout(600)
            page.screenshot(path=str(aus / "04-nach-freigabe.png"))

            eingabe.fill("echo Hallo aus dem Browser")
            eingabe.press("Enter")
            expect(page.get_by_text("Echo: Hallo aus dem Browser").first).to_be_visible(timeout=20000)
            page.wait_for_timeout(600)
            page.screenshot(path=str(aus / "05-mcp-werkzeug.png"))

            page.get_by_role("tab", name="Integrationen").click()
            expect(page.get_by_text("Mini Test").first).to_be_visible(timeout=10000)
            page.wait_for_timeout(600)
            page.screenshot(path=str(aus / "06-integrationen.png"))
            page.get_by_role("tab", name="Katalog").click()
            expect(page.get_by_text("Spotify").first).to_be_visible(timeout=10000)
            page.wait_for_timeout(400)
            ohne_alten_namen("Katalog")
            page.screenshot(path=str(aus / "07-katalog.png"))

            # Einstellungen: Name und Weckwort
            page.get_by_role("tab", name="Einstellungen").click()
            name_feld = page.get_by_label("Name des Assistenten")
            expect(name_feld).to_have_value("Javit", timeout=10000)
            weckwort = page.get_by_label("Weckwort", exact=True)
            expect(weckwort).to_have_value("javit")
            weckwort.fill("javit, hey javit")
            page.get_by_role("radiogroup", name="Weckwort-Erkennung").get_by_role("radio", name="Vosk (freies Wort)").click()
            page.get_by_role("button", name="Einstellungen speichern").click()
            expect(page.get_by_text("Einstellungen gespeichert.")).to_be_visible(timeout=10000)
            daten = httpx.get(f"{u.url}/api/einstellungen", timeout=10).json()
            assert daten["name"] == "Javit" and daten["stimme"]["weckwort"] == "javit, hey javit", daten
            assert daten["stimme"]["weckwort_engine"] == "vosk", daten
            status = httpx.get(f"{u.url}/api/status", timeout=10).json()
            assert status["name"] == "Javit" and status["stimme"]["engine"] == "vosk", status
            page.get_by_label("Weckwort", exact=True).scroll_into_view_if_needed()
            ohne_alten_namen("Einstellungen")
            page.wait_for_timeout(400)
            page.screenshot(path=str(aus / "08-einstellungen-stimme.png"))
            name_feld.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            page.screenshot(path=str(aus / "09-einstellungen-name.png"))
            browser.close()

        if fehler:
            print("Browser-Fehler:\n" + "\n".join(fehler))
            return 1
        print(f"OK – Screenshots in {aus}")
        return 0
    except Exception:
        print(u.protokolle())
        raise
    finally:
        u.stoppen()
        shutil.rmtree(opfer_ordner, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
