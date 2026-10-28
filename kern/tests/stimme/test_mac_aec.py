"""Mikrofon mit Echounterdrückung (macOS-Helfer): Quelle, Bau, Dienst-Verdrahtung."""

from __future__ import annotations

import io
import subprocess
import sys
import threading
import time

import numpy as np
import pytest

from jarvis.stimme import mac_aec
from jarvis.stimme.fehler import StimmFehler
from jarvis.stimme.mac_aec import MikrofonAEC, helfer_sicherstellen


class Stdin(io.BytesIO):
    gespeichert = b""

    def close(self):
        self.gespeichert = self.getvalue()
        super().close()


class FakeProc:
    """Ersatz für subprocess.Popen: liefert vorbereitetes PCM über stdout."""

    def __init__(self, daten: bytes, code: int = 0, stderr: bytes = b""):
        self.stdout = io.BytesIO(daten)
        self.stdin = Stdin()
        self.stderr = io.BytesIO(stderr)
        self.returncode: int | None = None
        self._code = code
        self.beendet = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = self._code
        return self.returncode

    def terminate(self):
        self.beendet = True

    def kill(self):
        self.beendet = True


def test_mikrofon_aec_liefert_rahmen_und_stoppt(tmp_path):
    helfer = tmp_path / "javit-mikrofon"
    helfer.write_bytes(b"#!/bin/sh\n")
    pcm = (np.sin(np.arange(16000 * 2) / 7) * 9000).astype("<i2").tobytes()  # 2 s bei 16 kHz
    procs: list[FakeProc] = []

    def starter(befehl, **kw):
        assert befehl == [str(helfer)] and kw["stdin"] is subprocess.PIPE
        p = FakeProc(pcm)
        procs.append(p)
        return p

    rahmen: list[np.ndarray] = []
    q = MikrofonAEC(helfer, starter=starter)
    assert q.echo_unterdrueckung is True
    q.starten(rahmen.append)
    for _ in range(50):
        if len(rahmen) >= 25:
            break
        time.sleep(0.02)
    assert len(rahmen) == 25 and rahmen[0].shape == (1280,) and rahmen[0].dtype == np.int16
    q.stoppen()
    assert procs[0].stdin.gespeichert == b"ende\n"
    q.stoppen()  # zweiter Aufruf ist harmlos


def test_mikrofon_aec_ohne_helfer(tmp_path, monkeypatch):
    monkeypatch.setattr(mac_aec, "helfer_sicherstellen", lambda bauen=True: None)
    with pytest.raises(StimmFehler, match="nicht verfügbar"):
        MikrofonAEC().starten(lambda r: None)
    with pytest.raises(StimmFehler, match="nicht verfügbar"):
        MikrofonAEC(tmp_path / "fehlt").starten(lambda r: None)


def test_helfer_sicherstellen_ohne_compiler(tmp_path, monkeypatch):
    monkeypatch.setattr(mac_aec, "jarvis_home", lambda: tmp_path)
    monkeypatch.setattr(mac_aec, "swiftc_vorhanden", lambda: False)
    assert helfer_sicherstellen() is None
    monkeypatch.setattr(mac_aec, "swiftc_vorhanden", lambda: True)
    monkeypatch.setenv("JARVIS_KEIN_DOWNLOAD", "1")
    assert helfer_sicherstellen() is None  # kein Bauen in Tests/Containern
    # vorhandener, aktueller Helfer wird ohne Compiler zurückgegeben
    pfad = tmp_path / "bin" / "javit-mikrofon"
    pfad.parent.mkdir()
    pfad.write_bytes(b"x")
    assert helfer_sicherstellen(bauen=False) == pfad


def test_helfer_bauen_ruft_swiftc(tmp_path, monkeypatch):
    monkeypatch.setattr(mac_aec, "jarvis_home", lambda: tmp_path)
    monkeypatch.setattr(mac_aec, "swiftc_vorhanden", lambda: True)
    monkeypatch.delenv("JARVIS_KEIN_DOWNLOAD", raising=False)
    monkeypatch.setattr(mac_aec.shutil, "which", lambda name: "/usr/bin/swiftc" if name == "swiftc" else None)
    aufrufe = []

    def run(befehl, **kw):
        aufrufe.append(befehl)
        (tmp_path / "bin" / "javit-mikrofon").write_bytes(b"bin")
        return subprocess.CompletedProcess(befehl, 0, "", "")

    monkeypatch.setattr(mac_aec.subprocess, "run", run)
    pfad = helfer_sicherstellen()
    assert pfad == tmp_path / "bin" / "javit-mikrofon" and aufrufe[0][:3] == ["swiftc", "-O", "-o"]
    assert aufrufe[0][-1].endswith("mac_mikrofon.swift")


def test_dienst_waehlt_helfer_auf_dem_mac(monkeypatch, tmp_path):
    from jarvis.stimme.audio import MikrofonQuelle
    from jarvis.stimme.dienst import StimmDienst
    from jarvis.stimme.einstellungen import StimmEinstellungen

    monkeypatch.setenv("JARVIS_PLATTFORM", "mac")
    helfer = tmp_path / "javit-mikrofon"
    helfer.write_bytes(b"x")
    monkeypatch.setattr(mac_aec, "helfer_sicherstellen", lambda bauen=True: helfer)
    q = StimmDienst._mikrofon_erzeugen(StimmEinstellungen.aus({}))
    assert isinstance(q, MikrofonAEC)
    assert isinstance(StimmDienst._mikrofon_erzeugen(StimmEinstellungen.aus({"aec": "aus"})), MikrofonQuelle)
    assert isinstance(StimmDienst._mikrofon_erzeugen(StimmEinstellungen.aus({"geraet": "USB"})), MikrofonQuelle)
    monkeypatch.setattr(mac_aec, "helfer_sicherstellen", lambda bauen=True: None)
    assert isinstance(StimmDienst._mikrofon_erzeugen(StimmEinstellungen.aus({})), MikrofonQuelle)
    monkeypatch.setenv("JARVIS_PLATTFORM", "linux")
    monkeypatch.setattr(mac_aec, "helfer_sicherstellen", lambda bauen=True: helfer)
    assert isinstance(StimmDienst._mikrofon_erzeugen(StimmEinstellungen.aus({})), MikrofonQuelle)
