"""Kommandozeile `jarvis` bzw. `javit` (beide Befehle sind gleichwertig).

    jarvis start [--kein-browser] [--port 8765] [--ohne-integrationen]
    jarvis add <katalog-id | "npx …" | url> [--name NAME] [--wert NAME=WERT …]
    jarvis remove <id>
    jarvis list
    jarvis katalog [suchbegriff]
    jarvis modell [<id>]
    jarvis sag "<text>" [--sprechen] [--ohne-integrationen]
    jarvis schluessel <NAME> [--loeschen]
    jarvis spotify-anmelden
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import html
import json
import sys
import threading
import webbrowser
from typing import Any

import httpx

from . import __version__
from .konfig import KonfigSpeicher


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------
def _name() -> str:
    """Eingestellter Name des Assistenten (Standard „Javit“); robust, falls die Datei fehlt/defekt ist."""
    try:
        return KonfigSpeicher().einstellungen.name
    except Exception:  # noqa: BLE001
        from .konfig import STANDARD_NAME

        return STANDARD_NAME


def _programmname() -> str:
    """„javit“ oder „jarvis“ – je nachdem, mit welchem Befehl aufgerufen wurde."""
    import os

    basis = os.path.basename(sys.argv[0] or "").lower()
    for endung in (".exe", "-script.py", ".py"):
        if basis.endswith(endung):
            basis = basis[: -len(endung)]
    return basis if basis in ("javit", "jarvis") else "jarvis"


def _server_url(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or KonfigSpeicher().einstellungen.port}"


def _server_laeuft(port: int | None = None) -> bool:
    try:
        return httpx.get(_server_url(port) + "/api/status", timeout=0.7).status_code == 200
    except httpx.HTTPError:
        return False


def _werte_parsen(paare: list[str] | None) -> dict[str, str]:
    werte = {}
    for paar in paare or []:
        if "=" not in paar:
            raise SystemExit(f"Ungültiger Wert „{paar}“ – Format NAME=WERT")
        name, wert = paar.split("=", 1)
        werte[name.strip()] = wert
    return werte


def _abfragen(fehlend: list[dict[str, Any]], hinweis: str = "") -> dict[str, str]:
    if hinweis:
        print(f"Hinweis: {hinweis}")
    werte = {}
    for b in fehlend:
        frage = f"{b['titel']} ({b['name']}): "
        wert = getpass.getpass(frage) if b.get("geheim") else input(frage)
        if not wert.strip():
            raise SystemExit("Abgebrochen – Wert fehlt.")
        werte[b["name"]] = wert.strip()
    return werte


def _integration_ausgeben(info: dict[str, Any]) -> None:
    zeile = f"{info['id']:<20} {info['name']:<24} {info['art']:<10} {info['status']:<10} {info['werkzeuge']} Werkzeuge"
    print(zeile)
    if info.get("fehler"):
        print(f"    Fehler: {info['fehler']}")


# ---------------------------------------------------------------------------
# Befehle
# ---------------------------------------------------------------------------
def windows_vorbereiten() -> None:
    """Windows: UTF-8-Konsole (sonst scheitern „…“ an cp1252/cp850) und Proactor-Ereignisschleife
    (nötig für Unterprozesse wie MCP-Server und PowerShell)."""
    if sys.platform != "win32":
        return
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    if sys.version_info < (3, 14):  # ab 3.14 ist Proactor ohnehin Standard und die Policy-API veraltet
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())  # type: ignore[attr-defined]


def protokoll_umleiten(datei: str | None) -> None:
    """Ausgaben in eine Datei schreiben (z. B. Autostart unter Windows mit pythonw.exe ohne Konsole)."""
    if not datei:
        return
    from pathlib import Path

    pfad = Path(datei).expanduser()
    pfad.parent.mkdir(parents=True, exist_ok=True)
    strom = open(pfad, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lebt bis Prozessende
    sys.stdout = sys.stderr = strom


def befehl_start(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import create_app

    protokoll_umleiten(getattr(args, "protokoll", None))

    port = args.port or KonfigSpeicher().einstellungen.port
    if _server_laeuft(port):
        print(f"{_name()} läuft bereits auf {_server_url(port)}")
        if not args.kein_browser:
            webbrowser.open(_server_url(port))
        return 0
    app = create_app(integrationen_starten=not args.ohne_integrationen)
    if not args.kein_browser:
        threading.Timer(1.5, lambda: webbrowser.open(_server_url(port))).start()
    print(f"{_name()} {__version__} startet auf {_server_url(port)} …")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


async def _lokaler_manager() -> Any:
    from .geheimnisse import Geheimnisspeicher
    from .integrationen.katalog import Katalog
    from .integrationen.manager import IntegrationsManager
    from .werkzeuge import WerkzeugRegister

    return IntegrationsManager(WerkzeugRegister(), Geheimnisspeicher(), Katalog())


def befehl_add(args: argparse.Namespace) -> int:
    from .integrationen.katalog import Katalog
    from .integrationen.manager import FehlendeWerte, IntegrationsFehler, quelle_deuten

    werte = _werte_parsen(args.wert)
    try:
        anfrage: dict[str, Any] = quelle_deuten(args.quelle, Katalog())
    except IntegrationsFehler as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1
    if args.name:
        anfrage["name"] = args.name

    if _server_laeuft():
        for _ in range(3):
            r = httpx.post(_server_url() + "/api/integrationen", json={**anfrage, "werte": werte}, timeout=180)
            if r.status_code == 400 and r.json().get("fehlend"):
                d = r.json()
                werte.update(_abfragen(d["fehlend"], d.get("hinweis", "")))
                continue
            if r.status_code >= 400:
                print(f"Fehler: {r.json().get('detail', r.text)}", file=sys.stderr)
                return 1
            _integration_ausgeben(r.json())
            return 0 if r.json()["status"] == "verbunden" else 2
        return 1

    async def lokal() -> int:
        manager = await _lokaler_manager()
        try:
            for _ in range(3):
                try:
                    print("Verbinde … (beim ersten Start lädt npx/uvx ggf. Pakete herunter)")
                    info = await manager.hinzufuegen({**anfrage, "werte": werte})
                    _integration_ausgeben(info)
                    for w in manager.register.von_integration(info["id"]):
                        print(f"    - {w.name} [{w.risiko}]")
                    return 0 if info["status"] == "verbunden" else 2
                except FehlendeWerte as e:
                    werte.update(await asyncio.to_thread(
                        _abfragen,
                        [{"name": b.name, "titel": b.titel, "geheim": b.geheim} for b in e.fehlend],
                        e.hinweis,
                    ))
                except IntegrationsFehler as e:
                    print(f"Fehler: {e}", file=sys.stderr)
                    return 1
            return 1
        finally:
            await manager.alle_stoppen()

    return asyncio.run(lokal())


def befehl_remove(args: argparse.Namespace) -> int:
    if _server_laeuft():
        r = httpx.delete(_server_url() + f"/api/integrationen/{args.id}", timeout=30)
        ok = r.status_code == 200
    else:
        async def lokal() -> bool:
            return await (await _lokaler_manager()).entfernen(args.id)

        ok = asyncio.run(lokal())
    print(f"Integration „{args.id}“ entfernt." if ok else f"Integration „{args.id}“ nicht gefunden.")
    return 0 if ok else 1


def befehl_list(args: argparse.Namespace) -> int:
    if _server_laeuft():
        liste = httpx.get(_server_url() + "/api/integrationen", timeout=10).json()
    else:
        async def lokal() -> list[dict[str, Any]]:
            return (await _lokaler_manager()).liste()

        liste = asyncio.run(lokal())
    if not liste:
        print(f"Keine Integrationen installiert. Katalog ansehen: {_programmname()} katalog")
        return 0
    for info in liste:
        _integration_ausgeben(info)
    return 0


def befehl_katalog(args: argparse.Namespace) -> int:
    from .integrationen.katalog import Katalog

    katalog = Katalog()
    eintraege = katalog.suchen(args.suchbegriff)
    for e in eintraege:
        benoetigt = ", ".join(b.name for b in e.benoetigt if not b.optional)
        print(f"{e.id:<18} {e.name:<22} [{e.kategorie}] {e.beschreibung}")
        if benoetigt:
            print(f"{'':<18} benötigt: {benoetigt}")
    for datei, fehler in katalog.fehler.items():
        print(f"Warnung: {datei}: {fehler}", file=sys.stderr)
    if not eintraege:
        print("Keine Einträge gefunden.")
    return 0


def befehl_modell(args: argparse.Namespace) -> int:
    konfig = KonfigSpeicher()
    if args.id:
        konfig.aktualisieren({"modell": args.id})
        if _server_laeuft():
            httpx.put(_server_url() + "/api/modelle", json={"modell": args.id}, timeout=10)
        print(f"Modell: {args.id}")
        return 0
    from .llm import LLMFassade

    print(f"Aktuelles Modell: {konfig.einstellungen.modell}\n")
    for v in asyncio.run(LLMFassade(konfig.einstellungen).modell_vorschlaege()):
        status = "verfügbar" if v["verfuegbar"] else "nicht verfügbar"
        print(f"  {v['id']:<36} {'lokal' if v['lokal'] else 'Cloud':<6} {status}")
    return 0


def befehl_schluessel(args: argparse.Namespace) -> int:
    from .geheimnisse import Geheimnisspeicher

    speicher = Geheimnisspeicher()
    if args.loeschen:
        speicher.loeschen(args.name)
        print(f"{args.name} gelöscht.")
        return 0
    wert = args.wert if args.wert is not None else getpass.getpass(f"Wert für {args.name}: ")
    if not wert:
        print("Kein Wert eingegeben.", file=sys.stderr)
        return 1
    speicher.setzen(args.name, wert)
    if _server_laeuft():
        httpx.put(_server_url() + f"/api/geheimnisse/{args.name}", json={"wert": wert}, timeout=10)
    print(f"{args.name} gespeichert ({speicher.backend_name}).")
    return 0


def befehl_sag(args: argparse.Namespace) -> int:
    from .anwendung import Jarvis

    async def lauf() -> int:
        j = Jarvis()

        async def ausgabe(e: dict[str, Any]) -> None:
            typ = e.get("typ")
            if typ == "antwort_text":
                print(e["delta"], end="", flush=True)
            elif typ == "antwort_ende":
                print()
            elif typ == "werkzeug_start":
                print(f"  → {e['name']}({json.dumps(e['argumente'], ensure_ascii=False)})", file=sys.stderr)
            elif typ == "werkzeug_ende":
                print(f"  {'✓' if e['ok'] else '✗'} {e['ergebnis'][:200]}", file=sys.stderr)
            elif typ == "freigabe_noetig":
                antwort = await asyncio.to_thread(input, f"Freigabe nötig: {e['grund']} – erlauben? [j/N] ")
                await j.agent.freigabe_beantworten(e["id"], antwort.strip().lower() in ("j", "ja", "y", "yes"))
            elif typ == "fehler":
                print(f"Fehler: {e['text']}", file=sys.stderr)

        j.hoerer_hinzufuegen(ausgabe)
        try:
            await j.starten(integrationen=not args.ohne_integrationen, stimme=False)
            await j.integrationen_abwarten()
            await j.anfrage(" ".join(args.text), sprechen=args.sprechen)
        finally:
            await j.stoppen()
        return 0

    return asyncio.run(lauf())


def befehl_spotify_anmelden(args: argparse.Namespace) -> int:
    """OAuth-Autorisierungscode-Ablauf → SPOTIFY_REFRESH_TOKEN im Schlüsselbund."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    from .geheimnisse import Geheimnisspeicher
    from .integrationen.eingebaut.spotify import STANDARD_RUECKRUF, autorisierungs_url, code_eintauschen

    speicher = Geheimnisspeicher()
    client_id = speicher.holen("SPOTIFY_CLIENT_ID") or input("Spotify Client ID: ").strip()
    secret = speicher.holen("SPOTIFY_CLIENT_SECRET") or getpass.getpass("Spotify Client Secret: ").strip()
    speicher.setzen("SPOTIFY_CLIENT_ID", client_id)
    speicher.setzen("SPOTIFY_CLIENT_SECRET", secret)
    ergebnis: dict[str, str] = {}

    class Rueckruf(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            q = parse_qs(urlparse(self.path).query)
            ergebnis["code"] = (q.get("code") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<h2>{html.escape(_name())}: Spotify verbunden. Sie können dieses Fenster schließen.</h2>".encode())

        def log_message(self, *a: Any) -> None:
            pass

    print(f"Wichtig: In developer.spotify.com muss die Redirect-URI {STANDARD_RUECKRUF} eingetragen sein.")
    server = HTTPServer(("127.0.0.1", 8888), Rueckruf)
    webbrowser.open(autorisierungs_url(client_id))
    print("Browser geöffnet – bitte bei Spotify anmelden …")
    server.handle_request()
    server.server_close()
    if not ergebnis.get("code"):
        print("Keine Autorisierung erhalten.", file=sys.stderr)
        return 1
    token = asyncio.run(code_eintauschen(client_id, secret, ergebnis["code"]))
    speicher.setzen("SPOTIFY_REFRESH_TOKEN", token["refresh_token"])
    print(f"Spotify-Anmeldung gespeichert. Jetzt: {_programmname()} add spotify")
    return 0


# ---------------------------------------------------------------------------
def parser_erstellen() -> argparse.ArgumentParser:
    name, prog = _name(), _programmname()
    p = argparse.ArgumentParser(
        prog=prog,
        description=f"{name} – Ihr persönlicher KI-Assistent (macOS, Windows, Linux). "
        "Die Befehle „javit“ und „jarvis“ sind gleichwertig.",
    )
    p.add_argument("--version", action="version", version=f"{prog} {__version__} ({name})")
    sub = p.add_subparsers(dest="befehl", required=True)

    s = sub.add_parser("start", help=f"{name} starten (Server) und Oberfläche öffnen")
    s.add_argument("--kein-browser", action="store_true", help="Browser nicht öffnen")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--ohne-integrationen", action="store_true")
    s.add_argument("--protokoll", metavar="DATEI", help="Ausgaben an diese Datei anhängen (z. B. für den Autostart)")
    s.set_defaults(funktion=befehl_start)

    s = sub.add_parser("add", help="Integration hinzufügen (Katalog-ID, MCP-Befehl oder URL)")
    s.add_argument("quelle")
    s.add_argument("--name")
    s.add_argument("--wert", action="append", metavar="NAME=WERT")
    s.set_defaults(funktion=befehl_add)

    s = sub.add_parser("remove", help="Integration entfernen")
    s.add_argument("id")
    s.set_defaults(funktion=befehl_remove)

    s = sub.add_parser("list", help="Installierte Integrationen anzeigen")
    s.set_defaults(funktion=befehl_list)

    s = sub.add_parser("katalog", help="Integrationskatalog anzeigen")
    s.add_argument("suchbegriff", nargs="?")
    s.set_defaults(funktion=befehl_katalog)

    s = sub.add_parser("modell", help="Modell anzeigen oder wechseln")
    s.add_argument("id", nargs="?")
    s.set_defaults(funktion=befehl_modell)

    s = sub.add_parser("sag", help=f"Einmalige Anfrage an {name} im Terminal")
    s.add_argument("text", nargs="+")
    s.add_argument("--sprechen", action="store_true", help="Antwort vorlesen")
    s.add_argument("--ohne-integrationen", action="store_true")
    s.set_defaults(funktion=befehl_sag)

    s = sub.add_parser("schluessel", help="API-Schlüssel speichern (Schlüsselbund bzw. Anmeldeinformationsverwaltung)")
    s.add_argument("name")
    s.add_argument("--wert", help="Wert direkt angeben (sonst verdeckte Eingabe)")
    s.add_argument("--loeschen", action="store_true")
    s.set_defaults(funktion=befehl_schluessel)

    s = sub.add_parser("spotify-anmelden", help="Spotify-Konto verbinden (Wiedergabesteuerung per Web-API)")
    s.set_defaults(funktion=befehl_spotify_anmelden)
    return p


def main(argv: list[str] | None = None) -> int:
    windows_vorbereiten()
    args = parser_erstellen().parse_args(argv)
    try:
        return int(args.funktion(args) or 0)
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
