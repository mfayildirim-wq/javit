"""Installer statisch prüfen (nie ausführen): shellcheck/bash -n für .sh, einfache Syntaxprüfung
für .ps1/.cmd. Ist PowerShell vorhanden (``pwsh`` im PATH oder ``JARVIS_PWSH=<Pfad>``, z. B. das
offizielle Archiv von github.com/PowerShell/PowerShell), werden die .ps1-Dateien und alle
PowerShell-Skripte aus ``plattform/windows.py``/``stimme/tts.py`` zusätzlich mit dem echten Parser
geprüft – nur geparst (``Parser::ParseFile``), nicht ausgeführt."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SKRIPTE = Path(__file__).resolve().parents[2] / "scripts"
SH = sorted(SKRIPTE.glob("*.sh")) + [SKRIPTE / "start.command"]
PS1 = sorted(SKRIPTE.glob("*.ps1"))
TYPOGRAFISCHE_QUOTES = "\u201c\u201d\u201e\u2018\u2019\u201a\u201b"


@pytest.mark.parametrize("skript", SH, ids=lambda p: p.name)
def test_bash_syntax(skript):
    assert subprocess.run(["bash", "-n", str(skript)], capture_output=True).returncode == 0


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck nicht installiert")
@pytest.mark.parametrize("skript", SH, ids=lambda p: p.name)
def test_shellcheck(skript):
    erg = subprocess.run(["shellcheck", str(skript)], capture_output=True, text=True)
    assert erg.returncode == 0, erg.stdout


def _ps_ohne_strings(text: str) -> str:
    """Entfernt Kommentare, Here-Strings und String-Literale (vereinfachter PowerShell-Tokenizer)."""
    text = re.sub(r"<#.*?#>", "", text, flags=re.S)
    text = re.sub(r"@'\r?\n.*?\r?\n'@", "''", text, flags=re.S)
    text = re.sub(r'@"\r?\n.*?\r?\n"@', "''", text, flags=re.S)
    aus, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "'":
            j = i + 1
            while j < n:
                if text[j] == "'" and j + 1 < n and text[j + 1] == "'":
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            aus.append("''")
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "`" else 1
            aus.append("''")
            i = j + 1
        elif c == "#":
            while i < n and text[i] != "\n":
                i += 1
        else:
            aus.append(c)
            i += 1
    return "".join(aus)


@pytest.mark.parametrize("skript", PS1, ids=lambda p: p.name)
def test_powershell_statisch(skript):
    roh = skript.read_bytes()
    assert roh.startswith(b"\xef\xbb\xbf"), "UTF-8 mit BOM (sonst liest PowerShell 5.1 Umlaute als ANSI)"
    text = roh.decode("utf-8-sig")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", ""), "Windows-Zeilenenden"
    assert not any(c in text for c in TYPOGRAFISCHE_QUOTES), "typografische Anführungszeichen sind in PowerShell Quotes"
    code = _ps_ohne_strings(text)
    for auf, zu in ("()", "{}", "[]"):
        assert code.count(auf) == code.count(zu), (skript.name, auf, code.count(auf), code.count(zu))
    # Nur PowerShell 5.1-Syntax: keine Pipeline-Ketten (&&, ||), kein ??, kein ?. und kein Ternär-Operator
    for zeile in code.splitlines():
        assert "&&" not in zeile and "||" not in zeile and "??" not in zeile and "?." not in zeile, zeile
        assert not re.search(r"\s\?\s.+\s:\s", zeile), zeile
    assert re.search(r"(?m)^param\(", text) and "[CmdletBinding()]" in text
    assert "Invoke-Expression" not in code and "iex" not in code.replace("'", "")


def test_powershell_tokenizer_selbsttest():
    assert _ps_ohne_strings("a('{(', \"}`\"\") # (\n<# { #>b") == "a('', '') \nb"


def test_installer_windows_inhalt():
    text = (SKRIPTE / "install-windows.ps1").read_text(encoding="utf-8-sig")
    for paket in ("Python.Python.3.12", "OpenJS.NodeJS.LTS", "Ollama.Ollama"):
        assert paket in text
    assert "$OhneOllama" in text and "jarvis.cmd" in text and "npm.cmd ci" in text and "uv venv" in text
    assert "ExecutionPolicy Bypass" in text and "HKCU:\\Environment" in text and "CreateShortcut" in text
    auto = (SKRIPTE / "autostart-windows.ps1").read_text(encoding="utf-8-sig")
    assert "Register-ScheduledTask" in auto and "-AtLogOn" in auto and "pythonw.exe" in auto and "--protokoll" in auto
    cmd = (SKRIPTE / "start-windows.cmd").read_bytes()
    assert cmd.isascii() and b"\r\n" in cmd and b"jarvis.exe" in cmd


def test_installer_linux_inhalt():
    text = (SKRIPTE / "install-linux.sh").read_text()
    for pv in ("apt-get", "dnf", "pacman", "zypper"):
        assert pv in text
    assert 'JARVIS_OLLAMA:-0}" == "1"' in text and "ollama.com/install.sh" in text
    assert "nvm" in text and "nodesource" in text.lower()
    assert 'kern[stimme,gedaechtnis]' in text and "jarvis.desktop" in text and "uv venv" in text
    # sudo nur für die Paketverwaltung: direkt nur in als_root(), und als_root nur mit Paketverwaltungen
    aufrufe = re.findall(r"(?m)^\s*als_root (\S+)", text)
    assert aufrufe and set(aufrufe) <= {"apt-get", "env", "dnf", "pacman", "zypper"}, aufrufe
    assert len(re.findall(r'then sudo "\$@"', text)) == 1 and not re.findall(r"(?m)^\s*sudo ", text)
    auto = (SKRIPTE / "autostart-linux.sh").read_text()
    assert "systemctl --user" in auto and "graphical-session.target" in auto


def test_mac_installer_leitet_unter_linux_um():
    text = (SKRIPTE / "install.sh").read_text()
    assert 'exec "$PROJEKT/scripts/install-linux.sh"' in text
    assert text.index("install-linux.sh\" \"$@\"") < text.index('== "Darwin" ]]')


def test_installer_javit_befehl_und_vosk_modell():
    """Alle drei Installer: Befehl „javit“ zusätzlich zu „jarvis“, Vosk-Modell vorab, Anleitung mit „Javit“."""
    mac = (SKRIPTE / "install.sh").read_text()
    linux = (SKRIPTE / "install-linux.sh").read_text()
    windows = (SKRIPTE / "install-windows.ps1").read_text(encoding="utf-8-sig")
    for text in (mac, linux):
        assert "for BEFEHL in javit jarvis; do" in text and '"$VENV/bin/$BEFEHL"' in text
        assert '"$VENV/bin/python" -m jarvis.stimme --modelle-laden --alle' in text
        assert "Fertig! Javit ist installiert." in text and "javit start" in text and "„Javit“ sagen" in text
        assert "Hey Jarvis“ sagen" not in text
    assert "foreach ($Befehl in @('javit', 'jarvis'))" in windows and "Scripts\\$Befehl.exe" in windows
    assert "& $VenvPython -m jarvis.stimme --modelle-laden --alle" in windows
    assert "Join-Path $Programme 'Javit.lnk'" in windows and "Fertig! Javit ist installiert." in windows
    assert "'Javit' sagen" in windows and "javit start" in windows
    assert "Name=Javit" in linux and "jarvis.desktop" in linux
    # Dienst-Kennungen bleiben (bestehender Autostart funktioniert weiter), Beschriftungen heißen „Javit“
    assert 'LABEL="de.jarvis.agent"' in (SKRIPTE / "autostart.sh").read_text()
    auto_linux = (SKRIPTE / "autostart-linux.sh").read_text()
    assert "Description=Javit" in auto_linux and "jarvis.service" in auto_linux
    auto_win = (SKRIPTE / "autostart-windows.ps1").read_text(encoding="utf-8-sig")
    assert "$Aufgabe = 'Jarvis'" in auto_win and "-Description 'Javit" in auto_win
    assert b"title Javit" in (SKRIPTE / "start-windows.cmd").read_bytes()
    assert "Javit startet" in (SKRIPTE / "start.command").read_text()


def test_weckwort_training_anleitung_und_hilfsskript_statisch():
    """Nur statisch: das Hilfsskript wird nicht ausgeführt."""
    import ast

    quelltext = (SKRIPTE / "weckwort_trainieren.py").read_text(encoding="utf-8")
    baum = ast.parse(quelltext)
    funktionen = {k.name for k in ast.walk(baum) if isinstance(k, ast.FunctionDef)}
    assert {"konfig_text", "befehl_konfig", "befehl_installieren", "main"} <= funktionen
    for schluessel in ("model_name", "target_phrase", "custom_negative_phrases", "n_samples", "target_false_positives_per_hour"):
        assert schluessel in quelltext
    assert '"weckwort_modell_pfad"' in quelltext and '"weckwort_engine": "openwakeword"' in quelltext
    anleitung = (SKRIPTE / "weckwort-trainieren.md").read_text(encoding="utf-8")
    for teil in ("~/.jarvis/modelle/openwakeword/", "weckwort_modell_pfad", "--train_model", "automatic_model_training.ipynb"):
        assert teil in anleitung


PARSER_SKRIPT = r"""
$fehler = 0
foreach ($d in $args) {
  $tokens = $null; $errs = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseFile($d, [ref]$tokens, [ref]$errs)
  foreach ($e in $errs) { $fehler++; Write-Output ("{0}:{1}: {2}" -f $d, $e.Extent.StartLineNumber, $e.Message) }
  $nur7 = $ast.FindAll({ param($n)
    $n -is [System.Management.Automation.Language.TernaryExpressionAst] -or
    $n -is [System.Management.Automation.Language.PipelineChainAst] -or
    ($n -is [System.Management.Automation.Language.BinaryExpressionAst] -and $n.Operator -eq 'QuestionQuestion') -or
    ($n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Operator -eq 'QuestionQuestionEquals')
  }, $true)
  foreach ($n in $nur7) { $fehler++; Write-Output ("{0}:{1}: nur PowerShell 7: {2}" -f $d, $n.Extent.StartLineNumber, $n.Extent.Text) }
  foreach ($t in $tokens) {
    if ($t.Kind -eq 'QuestionDot' -or $t.Kind -eq 'QuestionLBracket') { $fehler++; Write-Output ("{0}:{1}: nur PowerShell 7: ?. / ?[" -f $d, $t.Extent.StartLineNumber) }
  }
}
exit $fehler
"""


def _pwsh() -> str | None:
    return os.environ.get("JARVIS_PWSH") or shutil.which("pwsh")


@pytest.mark.skipif(not _pwsh(), reason="PowerShell (pwsh) nicht vorhanden – nur die einfache Prüfung oben")
def test_powershell_parser(tmp_path):
    """Echter PowerShell-Parser (nur Parsen, keine Ausführung) für Installer und Laufzeit-Skripte."""
    from jarvis.plattform import windows
    from jarvis.stimme import tts

    dateien = [str(p) for p in PS1]
    for name in dir(windows):
        if name.startswith("SKRIPT_"):
            ziel = tmp_path / f"{name}.ps1"
            ziel.write_text(windows.VORSPANN + getattr(windows, name), encoding="utf-8-sig")
            dateien.append(str(ziel))
    (tmp_path / "SAPI.ps1").write_text(windows.VORSPANN + tts.SKRIPT_SAPI, encoding="utf-8-sig")
    dateien.append(str(tmp_path / "SAPI.ps1"))
    pruefer = tmp_path / "pruefer" / "parse.ps1"
    pruefer.parent.mkdir()
    pruefer.write_text(PARSER_SKRIPT, encoding="utf-8-sig")
    erg = subprocess.run(
        [_pwsh(), "-NoProfile", "-NonInteractive", "-File", str(pruefer), *dateien],
        capture_output=True, text=True, timeout=120, env={**os.environ, "POWERSHELL_TELEMETRY_OPTOUT": "1"},
    )
    assert erg.returncode == 0, erg.stdout + erg.stderr


def test_windows_wrapper_bleiben_ascii():
    """javit.cmd/jarvis.cmd: relativer Pfad über %~dp0 – kein absoluter Pfad mit Umlauten (cmd.exe liest
    .cmd in der OEM-Codepage)."""
    text = (SKRIPTE / "install-windows.ps1").read_text(encoding="utf-8-sig")
    zeile = next(z for z in text.splitlines() if z.strip().startswith("$CmdInhalt ="))
    assert "%~dp0..\\venv\\Scripts\\$Befehl.exe" in zeile and "$Venv" not in zeile and "$Exe" not in zeile
    assert "Text.ASCIIEncoding" in text and "$env:PIP_CONFIG_FILE = 'nul'" in text


def test_linux_installer_node_pakete_und_desktop_datei(tmp_path):
    text = (SKRIPTE / "install-linux.sh").read_text()
    # nodejs/npm aus der Distribution nur, wenn noch kein Node.js da ist (NodeSource-Konflikt mit „npm“)
    assert 'if ! command -v node >/dev/null 2>&1; then' in text
    for zeile in re.findall(r"(?m)^\s*PAKETE=\((.*)$", text):
        assert "nodejs" not in zeile and " npm" not in zeile and '"${NODE_PAKETE[@]}"' in zeile, zeile
    for paket in ("python3-venv", "libportaudio2", "libnotify-bin", "wl-clipboard", "xclip", "playerctl", "espeak-ng",
                  "portaudio", "libnotify", "libnotify-tools", "pulseaudio-utils", "libpulse"):
        assert re.search(rf"[ (]{re.escape(paket)}[ )\n]", text), paket
    # Desktop-Datei mit Leerzeichen im Pfad: Exec in Anführungszeichen (Desktop-Entry-Spezifikation)
    anfang = text.index("desktop_argument() {")
    funktion = text[anfang: text.index("\n}\n", anfang) + 3]
    erg = subprocess.run(["bash", "-c", funktion + 'desktop_argument "$1"', "_", "/home/max m/100%/.local/bin/javit"],
                         capture_output=True, text=True)
    assert erg.stdout == '"/home/max m/100%%/.local/bin/javit"'
    assert "Exec=$DESKTOP_EXEC" in text


def test_linux_autostart_unit_quoting():
    text = (SKRIPTE / "autostart-linux.sh").read_text()
    anfang = text.index("unit_wert()")
    funktionen = text[anfang: text.index('case "${1:-}" in')]
    erg = subprocess.run(["bash", "-c", funktionen + 'unit_quote "$1"', "_", '/home/a b/50%/"x"/jarvis'],
                         capture_output=True, text=True)
    assert erg.stdout == '"/home/a b/50%%/\\"x\\"/jarvis"'
    assert 'ExecStart=$(unit_quote "$JARVIS_BIN")' in text and 'Environment=$(unit_quote "JARVIS_HOME=' in text
