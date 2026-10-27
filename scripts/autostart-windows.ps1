<#
  Javit bei der Anmeldung automatisch starten (Windows, Aufgabenplanung):

      powershell -ExecutionPolicy Bypass -File scripts\autostart-windows.ps1 -An      # einrichten und starten
      powershell -ExecutionPolicy Bypass -File scripts\autostart-windows.ps1 -Aus     # entfernen und stoppen
      powershell -ExecutionPolicy Bypass -File scripts\autostart-windows.ps1 -Status

  Die Aufgabe 'Jarvis' startet bei der Anmeldung des aktuellen Benutzers ohne Konsolenfenster
  (pythonw.exe -m jarvis start --kein-browser) und schreibt nach %USERPROFILE%\.jarvis\logs\jarvis.log.
  Kompatibel mit Windows PowerShell 5.1; keine Administratorrechte noetig.
#>
[CmdletBinding()]
param(
    [switch]$An,
    [switch]$Aus,
    [switch]$Status
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Aufgabe = 'Jarvis'  # Name der Aufgabe bleibt (Kompatibilitaet mit bestehendem Autostart)
$JarvisDaten = if ($env:JARVIS_HOME) { $env:JARVIS_HOME } else { Join-Path $env:USERPROFILE '.jarvis' }
$Pythonw = Join-Path $JarvisDaten 'venv\Scripts\pythonw.exe'
$Logs = Join-Path $JarvisDaten 'logs'
$Protokoll = Join-Path $Logs 'jarvis.log'
$Benutzer = "$env:USERDOMAIN\$env:USERNAME"

function Vorhanden { return [bool](Get-ScheduledTask -TaskName $Aufgabe -ErrorAction SilentlyContinue) }

if ($An) {
    if (-not (Test-Path $Pythonw)) {
        Write-Host "Javit ist nicht installiert ($Pythonw fehlt). Bitte zuerst scripts\install-windows.ps1 ausfuehren." -ForegroundColor Red
        exit 1
    }
    New-Item -ItemType Directory -Force -Path $Logs | Out-Null
    $argumente = '-m jarvis start --kein-browser --protokoll "' + $Protokoll + '"'
    $aktion = New-ScheduledTaskAction -Execute $Pythonw -Argument $argumente -WorkingDirectory $env:USERPROFILE
    $ausloeser = New-ScheduledTaskTrigger -AtLogOn -User $Benutzer
    $konto = New-ScheduledTaskPrincipal -UserId $Benutzer -LogonType Interactive -RunLevel Limited
    $optionen = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Aufgabe -Action $aktion -Trigger $ausloeser -Principal $konto -Settings $optionen `
        -Description 'Javit - persoenlicher KI-Assistent (http://127.0.0.1:8765)' -Force | Out-Null
    Start-ScheduledTask -TaskName $Aufgabe
    Write-Host 'Autostart eingerichtet: Javit startet ab jetzt bei jeder Anmeldung (http://127.0.0.1:8765).'
    Write-Host "Protokoll: $Protokoll"
} elseif ($Aus) {
    if (Vorhanden) {
        Stop-ScheduledTask -TaskName $Aufgabe -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $Aufgabe -Confirm:$false
    }
    Write-Host 'Autostart entfernt; Javit wurde gestoppt.'
} elseif ($Status) {
    $aufgabe = Get-ScheduledTask -TaskName $Aufgabe -ErrorAction SilentlyContinue
    if ($aufgabe) { Write-Host "Autostart ist aktiv (Aufgabe '$Aufgabe', Zustand: $($aufgabe.State))." } else { Write-Host 'Autostart ist aus.' }
} else {
    Write-Host 'Verwendung: autostart-windows.ps1 -An | -Aus | -Status'
    exit 2
}
