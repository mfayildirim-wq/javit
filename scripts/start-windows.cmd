@echo off
rem Doppelklick im Explorer: startet Javit und oeffnet die Oberflaeche im Browser.
setlocal
if defined JARVIS_HOME (set "JARVIS_DATEN=%JARVIS_HOME%") else (set "JARVIS_DATEN=%USERPROFILE%\.jarvis")
set "JARVIS=%JARVIS_DATEN%\venv\Scripts\jarvis.exe"
if not exist "%JARVIS%" (
  echo Javit ist noch nicht installiert. Bitte in PowerShell im Projektordner ausfuehren:
  echo   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
  pause
  exit /b 1
)
title Javit
echo Javit startet ... (dieses Fenster offen lassen; beenden mit Strg+C)
"%JARVIS%" start
if errorlevel 1 pause
