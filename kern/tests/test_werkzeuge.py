import pytest

from jarvis.werkzeuge import (
    FunktionsWerkzeug,
    Werkzeug,
    WerkzeugFehler,
    WerkzeugRegister,
    ergebnis_als_text,
    name_bereinigen,
    risiko_schaetzen,
    schema,
    werkzeug,
)
from jarvis.werkzeuge import dateien, mac, shell, web


@werkzeug("echo", "Gibt Text zurück", schema({"text": {"type": "string"}}, ["text"]), risiko="lesen")
async def echo(text: str) -> str:
    return f"Echo: {text}"


@werkzeug("kaputt", "Wirft immer", schema(), risiko="aendern")
async def kaputt() -> str:
    raise RuntimeError("Boom")


@werkzeug("freundlich_kaputt", "Wirft WerkzeugFehler", schema(), risiko="aendern")
async def freundlich_kaputt() -> str:
    raise WerkzeugFehler("Das ging nicht, Sir.")


async def test_register_grundfunktionen():
    r = WerkzeugRegister()
    r.registrieren(echo)
    r.registrieren(kaputt)
    assert "echo" in r and len(r) == 2
    assert r.holen("echo") is echo
    openai = r.als_openai()
    assert openai[0] == {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Gibt Text zurück",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        },
    }
    assert r.infos()[0] == {"name": "echo", "beschreibung": "Gibt Text zurück", "quelle": "eingebaut", "risiko": "lesen"}
    assert await r.ausfuehren("echo", {"text": "hi"}) == (True, "Echo: hi")
    ok, text = await r.ausfuehren("kaputt", {})
    assert not ok and "RuntimeError" in text and "Boom" in text
    ok, text = await r.ausfuehren("echo", {"falsch": 1})
    assert not ok and "Ungültige Argumente" in text
    ok, text = await r.ausfuehren("gibtsnicht", {})
    assert not ok and "Unbekanntes Werkzeug" in text
    r.registrieren(freundlich_kaputt)
    assert await r.ausfuehren("freundlich_kaputt", {}) == (False, "Das ging nicht, Sir.")
    assert r.entfernen("kaputt") and "kaputt" not in r


async def test_register_integrationen_entfernen():
    async def f() -> str:
        return "x"

    r = WerkzeugRegister()
    for i in range(3):
        r.registrieren(FunktionsWerkzeug(f, f"spotify__w{i}", "x", integration="spotify"))
    r.registrieren(FunktionsWerkzeug(f, "notion__a", "x", integration="notion"))
    assert len(r.von_integration("spotify")) == 3
    assert r.entfernen_integration("spotify") == 3
    assert [w.name for w in r.alle()] == ["notion__a"]
    assert r.infos()[0]["integration"] == "notion"


def test_ungueltige_risikostufe():
    with pytest.raises(ValueError):
        Werkzeug("x", "y", risiko="gefaehrlich")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "erwartet"),
    [
        ("delete_item", "kritisch"),
        ("removeUser", "kritisch"),
        ("send_email", "kritisch"),
        ("sendMessage", "kritisch"),
        ("pay_invoice", "kritisch"),
        ("purchase", "kritisch"),
        ("transfer_funds", "kritisch"),
        ("get_user", "lesen"),
        ("listRepos", "lesen"),
        ("search_tracks", "lesen"),
        ("read_file", "lesen"),
        ("create_page", "aendern"),
        ("update_task", "aendern"),
        ("list_and_delete_old", "kritisch"),  # kritisch hat Vorrang
        ("datei_loeschen", "kritisch"),
    ],
)
def test_risiko_heuristik(name, erwartet):
    assert risiko_schaetzen(name) == erwartet


def test_risiko_heuristik_standard():
    assert risiko_schaetzen("create_page", "lesen") == "lesen"
    assert risiko_schaetzen("frobnicate", "kritisch") == "kritisch"


def test_name_bereinigen_und_kuerzen():
    assert name_bereinigen("Grüße an alle!") == "Gruesse_an_alle"
    assert len(name_bereinigen("x" * 100)) == 64


def test_ergebnis_als_text_kuerzt():
    assert ergebnis_als_text(None) == "OK"
    assert ergebnis_als_text({"a": 1}).startswith("{")
    lang = ergebnis_als_text("x" * 50, max_zeichen=10)
    assert lang.startswith("x" * 10) and "gekürzt" in lang


def test_eingebaute_werkzeuge_risiken():
    alle = {w.name: w for m in (mac, dateien, shell, web) for w in m.werkzeuge()}
    assert alle["shell_befehl"].risiko == "kritisch"
    assert alle["datei_loeschen"].risiko == "kritisch"
    assert alle["datei_lesen"].risiko == "lesen"
    assert alle["websuche"].risiko == "lesen"
    for name in ("app_oeffnen", "musik_steuern", "shortcuts_ausfuehren", "kalender_termine", "termin_anlegen",
                 "notiz_anlegen", "erinnerung_anlegen", "systeminfo", "bildschirmfoto", "zwischenablage_lesen",
                 "zwischenablage_schreiben", "url_oeffnen", "lautstaerke_setzen", "mitteilung_anzeigen",
                 "laufende_apps", "app_beenden", "datei_suchen", "datei_schreiben", "datei_verschieben",
                 "webseite_lesen"):
        assert name in alle, name
    # Alle Namen gültig für alle Anbieter
    import re

    assert all(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", n) for n in alle)


async def test_datei_schreiben_ueberschreiben_ist_kritisch(tmp_path):
    ziel = tmp_path / "a.txt"
    w = dateien.datei_schreiben
    assert w.risiko_fuer({"pfad": str(ziel), "inhalt": "x"}) == "aendern"
    await w.ausfuehren(pfad=str(ziel), inhalt="Hallo")
    assert ziel.read_text() == "Hallo"
    assert w.risiko_fuer({"pfad": str(ziel), "inhalt": "x"}) == "kritisch"
    assert w.risiko_fuer({"pfad": str(ziel), "inhalt": "x", "anhaengen": True}) == "aendern"
    assert "existiert bereits" in w.freigabe_grund({"pfad": str(ziel)})


async def test_dateien_lesen_verschieben_loeschen(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("jarvis.werkzeuge.prozess.ist_mac", lambda: False)
    q = tmp_path / "q.txt"
    q.write_text("Inhalt")
    assert await dateien.datei_lesen.ausfuehren(pfad=str(q)) == "Inhalt"
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02")
    with pytest.raises(WerkzeugFehler):
        await dateien.datei_lesen.ausfuehren(pfad=str(tmp_path / "bin.dat"))
    ziel = tmp_path / "ordner" / "z.txt"
    await dateien.datei_verschieben.ausfuehren(quelle=str(q), ziel=str(ziel))
    assert ziel.exists() and not q.exists()
    text = await dateien.ordner_auflisten.ausfuehren(pfad=str(tmp_path / "ordner"))
    assert "z.txt" in text
    await dateien.datei_loeschen.ausfuehren(pfad=str(ziel))
    assert not ziel.exists()
    assert (tmp_path / "xdg" / "Trash" / "files" / "z.txt").exists()


async def test_datei_suchen_fallback_find(tmp_path, monkeypatch):
    monkeypatch.setattr("jarvis.werkzeuge.prozess.ist_mac", lambda: False)
    (tmp_path / "Urlaubsplanung.txt").write_text("x")
    (tmp_path / "anderes.txt").write_text("x")
    text = await dateien.datei_suchen.ausfuehren(anfrage="urlaub", ordner=str(tmp_path))
    assert "Urlaubsplanung.txt" in text and "anderes" not in text


async def test_shell_befehl(tmp_path):
    text = await shell.shell_befehl.ausfuehren(befehl="echo hallo && echo fehler 1>&2", arbeitsverzeichnis=str(tmp_path))
    assert "Exit-Code: 0" in text and "hallo" in text and "fehler" in text
    assert "Shell-Befehl ausführen: ls" == shell.shell_befehl.freigabe_grund({"befehl": "ls"})
    text = await shell.shell_befehl.ausfuehren(befehl="sleep 5", timeout=1)
    assert "Zeitüberschreitung" in text


def test_sensible_pfade_brauchen_freigabe(tmp_path, monkeypatch):
    """Schreiben in Autostart/Dotfiles/Jarvis-Konfiguration und Lesen von Schlüsseln nur mit Freigabe."""
    home = tmp_path / "nutzer"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JARVIS_HOME", str(home / ".jarvis"))
    s, v, lesen = dateien.datei_schreiben, dateien.datei_verschieben, dateien.datei_lesen
    assert s.risiko_fuer({"pfad": "~/Documents/notiz.txt", "inhalt": "x"}) == "aendern"
    for pfad in (
        "~/Library/LaunchAgents/boese.plist",
        "~/.zprofile",
        "~/.ssh/authorized_keys",
        "~/.jarvis/integrationen.json",
        "~/Documents/start.command",
        "/usr/local/bin/git",
    ):
        assert s.risiko_fuer({"pfad": pfad, "inhalt": "x"}) == "kritisch", pfad
        assert "–" in s.freigabe_grund({"pfad": pfad})
    assert v.risiko_fuer({"quelle": "~/Documents/a.txt", "ziel": "~/Library/LaunchAgents/a.plist"}) == "kritisch"
    assert v.risiko_fuer({"quelle": "~/.ssh/id_rsa", "ziel": "~/Documents/x"}) == "kritisch"
    assert v.risiko_fuer({"quelle": "~/Documents/a.txt", "ziel": "~/Documents/b.txt"}) == "aendern"
    for pfad in ("~/.ssh/id_ed25519", "~/.aws/credentials", "~/projekt/.env", "~/.jarvis/geheimnisse.schluessel"):
        assert lesen.risiko_fuer({"pfad": pfad}) == "kritisch", pfad
    assert lesen.risiko_fuer({"pfad": "~/Documents/notiz.txt"}) == "lesen"
