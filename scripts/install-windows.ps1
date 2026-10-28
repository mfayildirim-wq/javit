<#
  Javit (Projekt jarvis) - Installation unter Windows 10/11 in einem Schritt.

  Start (PowerShell im Projektordner; die Ausfuehrungsrichtlinie gilt nur fuer diesen Aufruf):
      powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1

  Installiert per winget (falls noetig): Python 3.12, Node.js LTS und Ollama; legt
  %USERPROFILE%\.jarvis\venv an (Fallback: uv), installiert den Kern mit Sprachmodul, baut die
  Oberflaeche, legt die gleichwertigen Befehle 'javit' und 'jarvis' (javit.cmd/jarvis.cmd in
  %USERPROFILE%\.jarvis\bin, Benutzer-PATH) und die Startmenue-Verknuepfung 'Javit' an und laedt das
  Vosk-Modell fuer das Weckwort 'Javit'. Mehrfaches Ausfuehren ist unbedenklich.

  Schalter:
    -OhneOllama     Ollama nicht installieren (nur Cloud-Modelle)
    -OhneModelle    keine Ollama-Modelle laden
    -Modell <name>  anderes lokales Standardmodell (Standard: qwen2.5:7b)
    -KeinPath       Benutzer-PATH nicht anpassen

  Hinweis: Kompatibel mit Windows PowerShell 5.1. Die Datei ist UTF-8 mit BOM gespeichert und
  verwendet bewusst keine typografischen Anfuehrungszeichen (PowerShell wertet sie als Quotes).
#>
[CmdletBinding()]
param(
    [switch]$OhneOllama,
    [switch]$OhneModelle,
    [string]$Modell = 'qwen2.5:7b',
    [switch]$KeinPath
)

Set-StrictMode -Version 2.0
# 'Continue' statt 'Stop': Windows PowerShell 5.1 bricht sonst bei jeder stderr-Zeile nativer
# Programme (winget, pip, npm) ab. Fehler werden ueber $LASTEXITCODE bzw. -ErrorAction Stop geprueft.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$Projekt = Split-Path -Parent $PSScriptRoot
$JarvisDaten = if ($env:JARVIS_HOME) { $env:JARVIS_HOME } else { Join-Path $env:USERPROFILE '.jarvis' }
$Venv = Join-Path $JarvisDaten 'venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$BinOrdner = Join-Path $JarvisDaten 'bin'
$Einbettung = 'nomic-embed-text'

function Fett([string]$Text) { Write-Host $Text -ForegroundColor White }
function Schritt([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Hinweis([string]$Text) { Write-Host "    $Text" }
function Warnung([string]$Text) { Write-Host "Warnung: $Text" -ForegroundColor Yellow }
function Abbruch([string]$Text) {
    Write-Host "Fehler: $Text" -ForegroundColor Red
    Write-Host 'Einfach erneut ausfuehren - bereits Erledigtes wird uebersprungen.'
    exit 1
}
function Pruefe-Exit([string]$Was) {
    if ($LASTEXITCODE -ne 0) { Abbruch "$Was (Exit-Code $LASTEXITCODE)" }
}
function Pfad-Auffrischen {
    # Neu installierte Programme (winget) ohne neues Terminal finden
    $maschine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $nutzer = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$maschine;$nutzer;$env:APPDATA\npm;$env:ProgramFiles\nodejs;$env:LOCALAPPDATA\Programs\Ollama;$env:USERPROFILE\.local\bin"
}
function Hat-Befehl([string]$Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

# ---------------------------------------------------------------- Voraussetzungen
if ($PSVersionTable.PSVersion.Major -lt 5) { Abbruch 'Windows PowerShell 5.1 oder neuer wird benoetigt.' }
if (-not (Test-Path (Join-Path $Projekt 'kern\pyproject.toml')) -or -not (Test-Path (Join-Path $Projekt 'oberflaeche\package.json'))) {
    Abbruch "Projektordner unvollstaendig: $Projekt"
}
Fett "Javit wird installiert (Projekt: $Projekt)"
New-Item -ItemType Directory -Force -Path $JarvisDaten, $BinOrdner -ErrorAction Stop | Out-Null

Schritt 'winget pruefen'
$HatWinget = Hat-Befehl 'winget'
if ($HatWinget) {
    Hinweis 'winget ist vorhanden.'
} else {
    Warnung 'winget fehlt (App-Installer aus dem Microsoft Store). Fehlende Programme bitte selbst installieren:'
    Hinweis 'Python 3.12: https://www.python.org/downloads/windows/  (Haken bei "Add python.exe to PATH")'
    Hinweis 'Node.js LTS: https://nodejs.org/   -   Ollama: https://ollama.com/download/windows'
}

function Winget-Paket([string]$Id, [string]$Titel) {
    if (-not $HatWinget) { Warnung "$Titel fehlt und winget ist nicht verfuegbar."; return }
    Hinweis "Installiere $Titel ($Id) ..."
    & winget install --id $Id --exact --silent --accept-source-agreements --accept-package-agreements --scope user 2>$null
    if ($LASTEXITCODE -ne 0) {
        # manche Pakete gibt es nur maschinenweit
        & winget install --id $Id --exact --silent --accept-source-agreements --accept-package-agreements
    }
    if ($LASTEXITCODE -ne 0) { Warnung "$Titel konnte nicht installiert werden (winget Exit-Code $LASTEXITCODE)." }
    Pfad-Auffrischen
}

# ---------------------------------------------------------------- Python
Schritt 'Python 3.12'
function Finde-Python {
    $kandidaten = @()
    if (Hat-Befehl 'py') {
        foreach ($v in @('3.13', '3.12', '3.11')) {
            $pfad = & py "-$v" -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $pfad) { $kandidaten += $pfad.Trim() }
        }
    }
    foreach ($v in @('313', '312', '311')) {
        $kandidaten += Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"
        $kandidaten += Join-Path $env:ProgramFiles "Python$v\python.exe"
    }
    $befehl = Get-Command 'python' -ErrorAction SilentlyContinue
    if ($befehl -and $befehl.Source -notlike '*WindowsApps*') { $kandidaten += $befehl.Source }  # Store-Platzhalter meiden
    foreach ($k in $kandidaten) {
        if ($k -and (Test-Path $k)) {
            & $k -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { return $k }
        }
    }
    return $null
}
$Python = Finde-Python
if (-not $Python) {
    Winget-Paket 'Python.Python.3.12' 'Python 3.12'
    $Python = Finde-Python
}
if ($Python) { Hinweis "Python: $Python" } else { Warnung 'Kein Python >= 3.11 gefunden - es wird ein eigenstaendiges Python ueber uv geladen.' }

# ---------------------------------------------------------------- Node.js
Schritt 'Node.js LTS'
function Node-Ok {
    if (-not (Hat-Befehl 'node')) { return $false }
    $v = (& node -p 'process.versions.node' 2>$null)
    if (-not $v) { return $false }
    $teile = $v.Trim().Split('.')
    $ma = [int]$teile[0]; $mi = [int]$teile[1]
    return ($ma -gt 22) -or ($ma -eq 22 -and $mi -ge 12) -or ($ma -eq 20 -and $mi -ge 19)
}
if (-not (Node-Ok)) { Winget-Paket 'OpenJS.NodeJS.LTS' 'Node.js LTS' }
$NodeOk = Node-Ok
if ($NodeOk) { Hinweis ('Node.js ' + (& node -p 'process.versions.node')) } else { Warnung 'Node.js 20.19+ bzw. 22.12+ fehlt - die Oberflaeche kann nicht gebaut werden.' }

# ---------------------------------------------------------------- Ollama
Schritt 'Ollama (lokale Sprachmodelle)'
function Ollama-Laeuft {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri 'http://127.0.0.1:11434/api/tags' | Out-Null; return $true } catch { return $false }
}
if ($OhneOllama) {
    Hinweis '-OhneOllama: Ollama wird uebersprungen (Cloud-Modelle: jarvis schluessel ANTHROPIC_API_KEY).'
} else {
    if (-not (Hat-Befehl 'ollama')) { Winget-Paket 'Ollama.Ollama' 'Ollama' }
    if ((Hat-Befehl 'ollama') -and -not $OhneModelle) {
        if (-not (Ollama-Laeuft)) {
            Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
            for ($i = 0; $i -lt 30 -and -not (Ollama-Laeuft); $i++) { Start-Sleep -Seconds 1 }
        }
        if (Ollama-Laeuft) {
            Hinweis "Das Sprachmodell $Modell ist ca. 4-5 GB gross - der erste Download kann einige Minuten dauern."
            & ollama pull $Modell; Pruefe-Exit "ollama pull $Modell"
            Hinweis "Einbettungsmodell $Einbettung (ca. 270 MB) fuer das Gedaechtnis ..."
            & ollama pull $Einbettung; Pruefe-Exit "ollama pull $Einbettung"
        } else {
            Warnung "Ollama antwortet nicht. Spaeter manuell: ollama serve, danach ollama pull $Modell"
        }
    }
}

# ---------------------------------------------------------------- Python-Umgebung
Schritt "Python-Umgebung in $Venv"
Remove-Item Env:PYTHONPATH, Env:PYTHONHOME, Env:PIP_USER, Env:PIP_TARGET, Env:PIP_PREFIX, Env:PIP_REQUIRE_VIRTUALENV -ErrorAction SilentlyContinue
# Stoerende pip.ini (z. B. "user = true") fuer die Einrichtung ausblenden (wie PIP_CONFIG_FILE=/dev/null unter macOS/Linux)
$env:PIP_CONFIG_FILE = 'nul'
function Venv-Ok {
    if (-not (Test-Path $VenvPython)) { return $false }
    & $VenvPython -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    & $VenvPython -m pip --version 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}
function Uv-Bereitstellen {
    if (Hat-Befehl 'uv') { return }
    if ($HatWinget) { Winget-Paket 'astral-sh.uv' 'uv' }
    if (-not (Hat-Befehl 'uv')) {
        Hinweis 'Installiere uv ueber das offizielle Skript von astral.sh ...'
        & powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
        Pfad-Auffrischen
    }
    if (-not (Hat-Befehl 'uv')) { Abbruch 'uv konnte nicht installiert werden.' }
}
if (-not (Venv-Ok)) {
    if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
    $VenvLog = Join-Path $JarvisDaten 'venv-fehler.log'
    $ok = $false
    if ($Python) {
        & $Python -m venv $Venv *> $VenvLog
        $ok = Venv-Ok
    }
    if (-not $ok) {
        Warnung "Python konnte die Umgebung nicht selbst einrichten (Details: $VenvLog) - nutze stattdessen uv."
        if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
        Uv-Bereitstellen
        if ($Python) { & uv venv --seed --python $Python $Venv 2>> $VenvLog }
        if (-not (Venv-Ok)) {
            if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
            & uv venv --seed --python 3.12 --python-preference only-managed $Venv 2>> $VenvLog
        }
    }
}
if (-not (Venv-Ok)) { Abbruch "Python-Umgebung liess sich nicht anlegen. Details: $(Join-Path $JarvisDaten 'venv-fehler.log')" }
& $VenvPython -m pip install --quiet --upgrade pip; Pruefe-Exit 'pip aktualisieren'
Hinweis 'Installiere den Kern mit Sprachmodul (das dauert beim ersten Mal etwas) ...'
& $VenvPython -m pip install --quiet -e "$Projekt\kern[stimme,gedaechtnis]"
if ($LASTEXITCODE -ne 0) {
    Warnung 'Installation mit Sprachmodul fehlgeschlagen - installiere den Kern ohne Sprachmodul.'
    & $VenvPython -m pip install --quiet -e "$Projekt\kern"; Pruefe-Exit 'pip install kern'
}

# ---------------------------------------------------------------- Oberflaeche
Schritt 'Oberflaeche bauen'
$Index = Join-Path $Projekt 'oberflaeche\dist\index.html'
if ($NodeOk) {
    Push-Location (Join-Path $Projekt 'oberflaeche')
    try {
        # npm.cmd statt npm.ps1 (unabhaengig von der Ausfuehrungsrichtlinie)
        & npm.cmd ci --no-audit --no-fund --loglevel=error; Pruefe-Exit 'npm ci'
        & npm.cmd run build --silent; Pruefe-Exit 'npm run build'
    } finally { Pop-Location }
    if (-not (Test-Path $Index)) { Abbruch 'Oberflaeche wurde nicht gebaut.' }
} elseif (Test-Path $Index) {
    Warnung 'Node.js fehlt - die vorhandene, bereits gebaute Oberflaeche wird verwendet.'
} else {
    Warnung 'Oberflaeche nicht gebaut (Node.js fehlt). Javit laeuft trotzdem im Terminal (javit sag ...).'
}

# ---------------------------------------------------------------- Befehle 'javit' und 'jarvis'
Schritt "Befehle 'javit' und 'jarvis' und Startmenue-Verknuepfung einrichten"
foreach ($Befehl in @('javit', 'jarvis')) {
    $Exe = Join-Path $Venv "Scripts\$Befehl.exe"
    $Cmd = Join-Path $BinOrdner "$Befehl.cmd"
    # Relativer Pfad (%~dp0 = Ordner der .cmd): die Datei bleibt reines ASCII, auch wenn der
    # Benutzerordner Umlaute enthaelt (cmd.exe liest .cmd in der OEM-Codepage, nicht als UTF-8)
    $CmdInhalt = "@echo off`r`nrem Von scripts\install-windows.ps1 erzeugt - startet Javit aus ..\venv`r`n`"%~dp0..\venv\Scripts\$Befehl.exe`" %*`r`n"
    [IO.File]::WriteAllText($Cmd, $CmdInhalt, (New-Object Text.ASCIIEncoding))
    Hinweis "$Cmd -> $Exe"
}
$JarvisExe = Join-Path $Venv 'Scripts\javit.exe'
$Cmd = Join-Path $BinOrdner 'javit.cmd'

$PathHinweis = ''
if (-not $KeinPath) {
    # Benutzer-PATH ueber die Registry erweitern (REG_EXPAND_SZ bleibt erhalten)
    $schluessel = Get-Item -Path 'HKCU:\Environment'
    $alt = $schluessel.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    $eintraege = @($alt -split ';' | Where-Object { $_ })
    if ($eintraege -notcontains $BinOrdner) {
        $neu = (@($eintraege) + $BinOrdner) -join ';'
        Set-ItemProperty -Path 'HKCU:\Environment' -Name 'Path' -Value $neu -Type ExpandString -ErrorAction Stop
        # Aenderung allen Programmen mitteilen (WM_SETTINGCHANGE)
        [Environment]::SetEnvironmentVariable('JARVIS_PATH_AKTUALISIERT', '1', 'User')
        [Environment]::SetEnvironmentVariable('JARVIS_PATH_AKTUALISIERT', $null, 'User')
        Hinweis "$BinOrdner wurde zum Benutzer-PATH hinzugefuegt."
        $PathHinweis = "Neues Terminal oeffnen, damit 'javit' gefunden wird."
    }
} else {
    $PathHinweis = "Bitte $BinOrdner zum PATH hinzufuegen oder $Cmd direkt aufrufen."
}

$Programme = [Environment]::GetFolderPath('Programs')
# Fruehere Verknuepfung 'Jarvis' (aus aelteren Installationen) durch 'Javit' ersetzen
$AlteVerknuepfung = Join-Path $Programme 'Jarvis.lnk'
if (Test-Path $AlteVerknuepfung) { Remove-Item -Path $AlteVerknuepfung -Force -ErrorAction SilentlyContinue }
$Verknuepfung = Join-Path $Programme 'Javit.lnk'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($Verknuepfung)
$lnk.TargetPath = $JarvisExe
$lnk.Arguments = 'start'
$lnk.WorkingDirectory = $env:USERPROFILE
$lnk.Description = 'Javit - persoenlicher KI-Assistent (http://127.0.0.1:8765)'
$lnk.Save()
Hinweis "Startmenue: $Verknuepfung"

# ---------------------------------------------------------------- Weckwort-Modelle
# Vosk-Modell fuer das freie Weckwort 'Javit' (vosk-model-small-de-0.15, ca. 45 MB, nach
# %USERPROFILE%\.jarvis\modelle\vosk) und zusaetzlich openWakeWord 'Hey Jarvis'
Schritt "Weckwort-Modelle (Javit ueber Vosk, Hey Jarvis ueber openWakeWord) vorab laden"
& $VenvPython -m jarvis.stimme --modelle-laden --alle
if ($LASTEXITCODE -eq 0) { Hinweis 'Weckwort-Modelle bereit.' } else { Warnung 'Weckwort-Modelle konnten nicht vollstaendig geladen werden (wird beim ersten Einschalten des Mikrofons erneut versucht).' }

# ---------------------------------------------------------------- Abschluss
Write-Host ''
Fett 'Fertig! Javit ist installiert.'
if ($PathHinweis) { Write-Host ''; Write-Host "  $PathHinweis" }
@"

  Starten:              javit start       (oeffnet http://127.0.0.1:8765 im Browser;
                                          'jarvis start' funktioniert genauso)
                        oder Startmenue -> Javit, oder Doppelklick auf scripts\start-windows.cmd
  Automatisch starten:  powershell -ExecutionPolicy Bypass -File scripts\autostart-windows.ps1 -An
                        (wieder aus: ... -Aus)

  Erste Schritte
  1. Mikrofon: in der Oberflaeche auf das Mikrofon klicken und 'Javit' sagen. Falls nichts
     ankommt: Einstellungen -> Datenschutz und Sicherheit -> Mikrofon -> Mikrofonzugriff und
     'Desktop-Apps den Zugriff auf das Mikrofon erlauben' einschalten.
  2. Sprachausgabe: Windows-Sprachausgabe (SAPI) mit deutscher Stimme, z. B. Microsoft Hedda.
     Fehlt sie: Einstellungen -> Zeit und Sprache -> Sprache -> Deutsch -> Sprachausgabe.
  3. Modell wechseln:  javit modell                          (zeigt alle Modelle)
                       javit modell anthropic/claude-sonnet-5-5
                       javit schluessel ANTHROPIC_API_KEY    (landet in der Windows-Anmeldeinformationsverwaltung)
  4. Apps integrieren: javit katalog  -  javit add spotify  -  oder: 'Javit, integriere Notion.'
     Kalender, Erinnerungen und Notizen gibt es unter Windows ueber Integrationen
     (google-kalender, todoist, notion, obsidian).

  Daten, Einstellungen und Protokolle liegen in $JarvisDaten.
"@ | Write-Host
