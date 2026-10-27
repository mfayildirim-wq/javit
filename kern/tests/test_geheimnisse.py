import os
import stat
import subprocess

from jarvis.geheimnisse import Geheimnisspeicher


def test_datei_fallback(isoliert):
    g = Geheimnisspeicher()
    assert g.backend == "datei"
    g.setzen("ANTHROPIC_API_KEY", "sk-ant-123")
    g.setzen("ANDERES", "wert")
    assert g.holen("ANTHROPIC_API_KEY") == "sk-ant-123"
    assert g.namen() == ["ANDERES", "ANTHROPIC_API_KEY"]
    enc = isoliert / "geheimnisse.enc"
    assert b"sk-ant-123" not in enc.read_bytes()
    schluessel = isoliert / "geheimnisse.schluessel"
    assert stat.S_IMODE(schluessel.stat().st_mode) == 0o600
    assert stat.S_IMODE(enc.stat().st_mode) == 0o600
    # neue Instanz liest dieselben Daten
    assert Geheimnisspeicher().holen("ANDERES") == "wert"
    assert g.loeschen("ANDERES") and g.holen("ANDERES") is None and g.namen() == ["ANTHROPIC_API_KEY"]


def test_in_umgebung_laden(isoliert, monkeypatch):
    g = Geheimnisspeicher()
    g.setzen("OPENAI_API_KEY", "sk-1")
    g.setzen("EIGENER_SCHLUESSEL", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "schon-da")
    g.setzen("GEMINI_API_KEY", "neu")
    geladen = g.in_umgebung_laden()
    assert os.environ["OPENAI_API_KEY"] == "sk-1" and os.environ["EIGENER_SCHLUESSEL"] == "x"
    assert os.environ["GEMINI_API_KEY"] == "schon-da" and "GEMINI_API_KEY" not in geladen


def test_schluesselbund_backend_ruft_security_auf(isoliert, monkeypatch):
    aufrufe = []
    eingaben = []
    gespeichert = {}

    def run(befehl, **kwargs):
        aufrufe.append(befehl)
        eingaben.append(kwargs.get("input"))
        if befehl[1] == "-i":
            teile = kwargs["input"].split()
            gespeichert[teile[teile.index("-a") + 1]] = bytes.fromhex(teile[teile.index("-X") + 1]).decode()
            return subprocess.CompletedProcess(befehl, 0, stdout="", stderr="")
        if befehl[1] == "find-generic-password":
            wert = gespeichert.get(befehl[befehl.index("-a") + 1])
            return subprocess.CompletedProcess(befehl, 0 if wert is not None else 44, stdout=f"{wert}\n", stderr="")
        return subprocess.CompletedProcess(befehl, 0, stdout="", stderr="")

    monkeypatch.setattr("jarvis.geheimnisse.subprocess.run", run)
    g = Geheimnisspeicher(backend="schluesselbund")
    wert = 'ge heim"\'$x ü'
    g.setzen("NOTION_TOKEN", wert)
    # Das Geheimnis taucht nie als Prozessargument auf, nur hexkodiert auf stdin
    assert aufrufe[0] == ["security", "-i"]
    assert all(wert not in " ".join(a) and wert.encode().hex() not in " ".join(a) for a in aufrufe)
    assert eingaben[0] == f"add-generic-password -U -s jarvis -a NOTION_TOKEN -X {wert.encode().hex()}\n"
    assert g.holen("NOTION_TOKEN") == wert
    assert ["security", "find-generic-password", "-s", "jarvis", "-a", "NOTION_TOKEN", "-w"] in aufrufe
    g.loeschen("NOTION_TOKEN")
    assert aufrufe[-1][:2] == ["security", "delete-generic-password"]
    assert not (isoliert / "geheimnisse.enc").exists()


def test_schluesselbund_fehler_und_ungueltige_namen(isoliert, monkeypatch):
    def run(befehl, **kwargs):  # speichert nichts → Rücklesen schlägt fehl
        return subprocess.CompletedProcess(befehl, 0 if befehl[1] == "-i" else 44, stdout="", stderr="")

    monkeypatch.setattr("jarvis.geheimnisse.subprocess.run", run)
    g = Geheimnisspeicher(backend="schluesselbund")
    import pytest

    from jarvis.geheimnisse import GeheimnisFehler

    with pytest.raises(GeheimnisFehler):
        g.setzen("TOKEN", "x")
    with pytest.raises(GeheimnisFehler):
        g.setzen("BÖSE -a x", "x")
