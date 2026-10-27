"""Windows-Implementierung der Systemaktionen (Windows 10/11, Windows PowerShell 5.1).

Sicherheit: Jedes Skript ist ein fester Text (keine String-Interpolation von Werten) und wird per
``-EncodedCommand`` (UTF-16LE, Base64) übergeben. Werte gelangen ausschließlich über
Umgebungsvariablen ``JARVIS_ARG_*`` (kurze Werte) oder Base64 über stdin (beliebig lange Texte)
in das Skript. Ausgaben kommen Base64-kodiert (UTF-8) zurück – unabhängig von der Codepage
der Konsole. Dadurch sind Anführungszeichen, ``;``, ``$()``, Backticks usw. reine Daten.
"""

from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
from urllib.parse import quote

from . import Systemaktionen
from .gemeinsam import python_dateisuche

MAX_UMGEBUNGSWERT = 30000  # Windows erlaubt 32767 Zeichen je Umgebungsvariable
MAX_BEFEHLSZEILE = 32000  # Grenze der Windows-Befehlszeile

# Gemeinsamer Vorspann: Fehler abbrechen, Ein-/Ausgabe Base64 (UTF-8)
VORSPANN = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Jarvis-Eingabe {
  $roh = [Console]::In.ReadToEnd()
  if (-not $roh) { return '' }
  return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($roh.Trim()))
}
function Jarvis-Ausgabe([string]$Text) {
  [Console]::Out.Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Text)))
}
"""


def _fehler(text: str) -> Exception:
    from ..werkzeuge import WerkzeugFehler

    return WerkzeugFehler(text)


def _prozess():
    from ..werkzeuge import prozess

    return prozess


def powershell_programm() -> str:
    """Windows PowerShell 5.1 (immer vorhanden); vollständiger Pfad, falls bekannt."""
    wurzel = os.environ.get("SystemRoot")
    if wurzel:
        pfad = Path(wurzel) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if pfad.exists():
            return str(pfad)
    return "powershell.exe"


def kodieren(skript: str) -> str:
    """PowerShell-``-EncodedCommand``: Base64 von UTF-16LE."""
    return base64.b64encode(skript.encode("utf-16-le")).decode("ascii")


def powershell_befehl(skript: str) -> list[str]:
    return [powershell_programm(), "-NoProfile", "-NonInteractive", "-EncodedCommand", kodieren(VORSPANN + skript)]


def ps_literal(wert: str) -> str:
    """PowerShell-String in einfachen Anführungszeichen (nur für feste Texte gedacht).

    PowerShell wertet auch die typografischen Zeichen ‘ ’ ‚ ‛ als einfache Anführungszeichen –
    sie werden deshalb ebenso verdoppelt. Werte von außen gehen trotzdem nur über Umgebungsvariablen.
    """
    text = str(wert).replace("\x00", "")
    for zeichen in ("'", "‘", "’", "‚", "‛"):
        text = text.replace(zeichen, zeichen * 2)
    return f"'{text}'"


def _umgebung(werte: dict[str, object] | None) -> dict[str, str]:
    umgebung: dict[str, str] = {}
    for name, wert in (werte or {}).items():
        text = "" if wert is None else str(wert).replace("\x00", "")
        if len(text) > MAX_UMGEBUNGSWERT:
            raise _fehler(f"Wert für {name} ist zu lang ({len(text)} Zeichen).")
        umgebung[f"JARVIS_ARG_{name.upper()}"] = text
    return umgebung


def fehlertext(stderr: str) -> str:
    """Erste aussagekräftige Fehlerzeile; versteht auch das CLIXML-Format von PowerShell."""
    text = stderr.strip()
    if text.startswith("#< CLIXML"):
        import html
        import re

        teile = re.findall(r'<S S="Error">(.*?)</S>', text, flags=re.S)
        text = "".join(teile).replace("_x000D_", "").replace("_x000A_", "\n")
        text = html.unescape(text)
    return next((z.strip() for z in text.splitlines() if z.strip()), "")


def _dekodieren(ausgabe: str) -> str:
    roh = ausgabe.strip()
    if not roh:
        return ""
    try:
        return base64.b64decode(roh, validate=True).decode("utf-8", errors="replace")
    except (binascii.Error, ValueError):
        return roh


async def powershell(skript: str, werte: dict[str, object] | None = None, eingabe: str | None = None,
                     timeout: float = 30.0, zweck: str = "PowerShell") -> str:
    """Führt ``skript`` aus; ``werte`` → ``$env:JARVIS_ARG_<NAME>``, ``eingabe`` → ``Jarvis-Eingabe``."""
    befehl = powershell_befehl(skript)
    if sum(len(t) + 3 for t in befehl) > MAX_BEFEHLSZEILE:
        raise _fehler("PowerShell-Skript ist zu lang für die Befehlszeile.")
    erg = await _prozess().ausfuehren(
        *befehl,
        eingabe=base64.b64encode(eingabe.encode("utf-8")).decode("ascii") if eingabe is not None else None,
        timeout=timeout,
        umgebung=_umgebung(werte),
    )
    if not erg.ok:
        erste = fehlertext(erg.fehler) or fehlertext(_dekodieren(erg.ausgabe)) or f"Exit-Code {erg.code}"
        raise _fehler(f"{zweck} fehlgeschlagen: {erste}")
    return _dekodieren(erg.ausgabe)


# ---------------------------------------------------------------------------
# Skripte (fester Text, Werte nur über $env:JARVIS_ARG_*)
# ---------------------------------------------------------------------------
SKRIPT_APP_OEFFNEN = r"""
$name = $env:JARVIS_ARG_NAME
function Passt([string]$Wert) { return $Wert -and $Wert.IndexOf($name, [StringComparison]::OrdinalIgnoreCase) -ge 0 }
$ordner = @("$env:APPDATA\Microsoft\Windows\Start Menu\Programs", "$env:ProgramData\Microsoft\Windows\Start Menu\Programs")
$links = @(Get-ChildItem -Path $ordner -Filter '*.lnk' -Recurse -ErrorAction SilentlyContinue)
$link = $links | Where-Object { $_.BaseName -ieq $name } | Select-Object -First 1
if (-not $link) { $link = $links | Where-Object { Passt $_.BaseName } | Sort-Object { $_.BaseName.Length } | Select-Object -First 1 }
if ($link) { Start-Process -FilePath $link.FullName; Jarvis-Ausgabe $link.BaseName; exit 0 }
$app = $null
try {
  $alle = @(Get-StartApps)
  $app = $alle | Where-Object { $_.Name -ieq $name } | Select-Object -First 1
  if (-not $app) { $app = $alle | Where-Object { Passt $_.Name } | Sort-Object { $_.Name.Length } | Select-Object -First 1 }
} catch { }
if ($app) { Start-Process -FilePath ('shell:AppsFolder\' + $app.AppID); Jarvis-Ausgabe $app.Name; exit 0 }
$exe = Get-Command -Name ($name + '.exe') -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($exe) { Start-Process -FilePath $exe.Source; Jarvis-Ausgabe $name; exit 0 }
Start-Process -FilePath $name
Jarvis-Ausgabe $name
"""

SKRIPT_APP_BEENDEN = r"""
$name = $env:JARVIS_ARG_NAME -replace '\.exe$', ''
$alle = @(Get-Process | Where-Object { $_.MainWindowHandle -ne 0 })
$treffer = @($alle | Where-Object { $_.ProcessName -ieq $name -or $_.Description -ieq $name -or $_.Product -ieq $name })
if ($treffer.Count -eq 0) {
  $treffer = @($alle | Where-Object { $_.ProcessName.IndexOf($name, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
}
if ($treffer.Count -eq 0) { Write-Error "Keine laufende App namens '$name' gefunden."; exit 3 }
$anzahl = 0
foreach ($p in $treffer) { if ($p.CloseMainWindow()) { $anzahl++ } }
Jarvis-Ausgabe ([string]$anzahl)
"""

SKRIPT_LAUFENDE_APPS = r"""
$liste = Get-Process | Where-Object { $_.MainWindowTitle } | Sort-Object ProcessName |
  ForEach-Object { '{0}: {1}' -f $_.ProcessName, $_.MainWindowTitle }
Jarvis-Ausgabe ($liste -join "`n")
"""

# Lautstärke über die Core-Audio-COM-Schnittstelle (IAudioEndpointVolume); Fallback: Medientasten.
# Leere Werte bedeuten „nicht setzen“ (Windows entfernt leere Umgebungsvariablen → $null; nicht
# leere Zeichenketten wie '0' sind in PowerShell wahr – die Zahl 0 dagegen nicht, deshalb wird das
# Ergebnis einer relativen Änderung wieder als Zeichenkette gespeichert).
SKRIPT_LAUTSTAERKE = r"""
$quelle = @'
using System;
using System.Runtime.InteropServices;
namespace JarvisAudio {
  [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IAudioEndpointVolume {
    int f(); int g(); int h(); int i();
    int SetMasterVolumeLevelScalar(float fLevel, Guid pguidEventContext);
    int j();
    int GetMasterVolumeLevelScalar(out float pfLevel);
    int k(); int l(); int m(); int n();
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, Guid pguidEventContext);
    int GetMute(out bool pbMute);
  }
  [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDevice { int Activate(ref Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev); }
  [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IMMDeviceEnumerator { int f(); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint); }
  [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }
  public class Audio {
    static IAudioEndpointVolume Vol() {
      var enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
      IMMDevice dev = null;
      Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(0, 1, out dev));
      IAudioEndpointVolume epv = null;
      var epvid = typeof(IAudioEndpointVolume).GUID;
      Marshal.ThrowExceptionForHR(dev.Activate(ref epvid, 23, 0, out epv));
      return epv;
    }
    public static float Volume {
      get { float v = -1; Marshal.ThrowExceptionForHR(Vol().GetMasterVolumeLevelScalar(out v)); return v; }
      set { Marshal.ThrowExceptionForHR(Vol().SetMasterVolumeLevelScalar(value, Guid.Empty)); }
    }
    public static bool Mute {
      get { bool m; Marshal.ThrowExceptionForHR(Vol().GetMute(out m)); return m; }
      set { Marshal.ThrowExceptionForHR(Vol().SetMute(value, Guid.Empty)); }
    }
  }
}
'@
$prozent = $env:JARVIS_ARG_PROZENT
$aenderung = $env:JARVIS_ARG_AENDERUNG
$stumm = $env:JARVIS_ARG_STUMM
try {
  Add-Type -TypeDefinition $quelle -Language CSharp
  if ($aenderung) { $prozent = [string]([Math]::Round([JarvisAudio.Audio]::Volume * 100) + [int]$aenderung) }
  if ($prozent) { [JarvisAudio.Audio]::Volume = [Math]::Max(0, [Math]::Min(100, [int]$prozent)) / 100.0 }
  if ($stumm) { [JarvisAudio.Audio]::Mute = ($stumm -eq '1') }
  Jarvis-Ausgabe ([string][Math]::Round([JarvisAudio.Audio]::Volume * 100))
} catch {
  # Fallback ohne Add-Type (z. B. eingeschränkter Sprachmodus): Medientasten, je Druck ca. 2 %
  $shell = New-Object -ComObject WScript.Shell
  if ($prozent) {
    1..50 | ForEach-Object { $shell.SendKeys([char]174) }
    $schritte = [int][Math]::Floor([Math]::Max(0, [Math]::Min(100, [int]$prozent)) / 2)
    if ($schritte -gt 0) { 1..$schritte | ForEach-Object { $shell.SendKeys([char]175) } }
  } elseif ($aenderung) {
    $taste = if ([int]$aenderung -ge 0) { [char]175 } else { [char]174 }
    1..([Math]::Max(1, [int]([Math]::Abs([int]$aenderung) / 2))) | ForEach-Object { $shell.SendKeys($taste) }
  }
  if ($stumm) { $shell.SendKeys([char]173) }
  Jarvis-Ausgabe '?'
}
"""

SKRIPT_MITTEILUNG = r"""
$titel = $env:JARVIS_ARG_TITEL
$text = $env:JARVIS_ARG_TEXT
if (Get-Module -ListAvailable -Name BurntToast) {
  Import-Module BurntToast
  New-BurntToastNotification -Text $titel, $text
  Jarvis-Ausgabe 'BurntToast'; exit 0
}
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
  [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
  $vorlage = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
  $felder = $vorlage.GetElementsByTagName('text')
  $felder.Item(0).AppendChild($vorlage.CreateTextNode($titel)) | Out-Null
  $felder.Item(1).AppendChild($vorlage.CreateTextNode($text)) | Out-Null
  $toast = [Windows.UI.Notifications.ToastNotification]::new($vorlage)
  $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
  Jarvis-Ausgabe 'Toast'
} catch {
  Add-Type -AssemblyName System.Windows.Forms, System.Drawing
  $symbol = New-Object System.Windows.Forms.NotifyIcon
  $symbol.Icon = [System.Drawing.SystemIcons]::Information
  $symbol.Visible = $true
  $symbol.ShowBalloonTip(8000, $titel, $text, [System.Windows.Forms.ToolTipIcon]::Info)
  Start-Sleep -Seconds 8
  $symbol.Dispose()
  Jarvis-Ausgabe 'Sprechblase'
}
"""

# Medientasten über keybd_event (Play/Pause 0xB3, Weiter 0xB0, Zurück 0xB1)
SKRIPT_MEDIENTASTE = r"""
Add-Type -Namespace JarvisTasten -Name Tastatur -MemberDefinition '[DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);'
$taste = [byte][int]$env:JARVIS_ARG_TASTE
[JarvisTasten.Tastatur]::keybd_event($taste, 0, 1, [UIntPtr]::Zero)
[JarvisTasten.Tastatur]::keybd_event($taste, 0, 3, [UIntPtr]::Zero)
Jarvis-Ausgabe 'ok'
"""

SKRIPT_SPOTIFY_TITEL = r"""
$fenster = Get-Process -Name Spotify -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle } | Select-Object -First 1
if ($fenster) { Jarvis-Ausgabe $fenster.MainWindowTitle } else { Jarvis-Ausgabe '' }
"""

SKRIPT_URL = r"""
Start-Process -FilePath $env:JARVIS_ARG_URL
Jarvis-Ausgabe 'ok'
"""

SKRIPT_ZWISCHENABLAGE_LESEN = r"""
$text = Get-Clipboard -Raw
if ($null -eq $text) { $text = '' }
Jarvis-Ausgabe $text
"""

SKRIPT_ZWISCHENABLAGE_SCHREIBEN = r"""
$text = Jarvis-Eingabe
Set-Clipboard -Value $text
Jarvis-Ausgabe 'ok'
"""

SKRIPT_BILDSCHIRMFOTO = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
try {
  Add-Type -Namespace JarvisDpi -Name Dpi -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
  [JarvisDpi.Dpi]::SetProcessDPIAware() | Out-Null
} catch { }
$bereich = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bild = New-Object System.Drawing.Bitmap $bereich.Width, $bereich.Height
$grafik = [System.Drawing.Graphics]::FromImage($bild)
$grafik.CopyFromScreen($bereich.Left, $bereich.Top, 0, 0, $bild.Size)
$bild.Save($env:JARVIS_ARG_PFAD, [System.Drawing.Imaging.ImageFormat]::Png)
$grafik.Dispose(); $bild.Dispose()
Jarvis-Ausgabe 'ok'
"""

SKRIPT_SYSTEMINFO = r"""
$zeilen = @()
$os = Get-CimInstance Win32_OperatingSystem
$zeilen += 'System: {0} (Version {1}, Build {2})' -f $os.Caption, $os.Version, $os.BuildNumber
foreach ($akku in @(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)) {
  $zeilen += 'Akku: {0} %' -f $akku.EstimatedChargeRemaining
}
try {
  $wlan = (netsh wlan show interfaces) | Select-String -Pattern '^\s*SSID\s*:' | Select-Object -First 1
  if ($wlan) { $zeilen += 'WLAN: ' + ($wlan.Line -split ':', 2)[1].Trim() }
} catch { }
foreach ($lw in @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3')) {
  $zeilen += 'Laufwerk {0} {1:N0} GB frei von {2:N0} GB' -f $lw.DeviceID, ($lw.FreeSpace / 1GB), ($lw.Size / 1GB)
}
$cs = Get-CimInstance Win32_ComputerSystem
$zeilen += 'Arbeitsspeicher: {0:N0} GB' -f ($cs.TotalPhysicalMemory / 1GB)
$laufzeit = (Get-Date) - $os.LastBootUpTime
$zeilen += 'Laufzeit: {0} Tage, {1} Stunden' -f $laufzeit.Days, $laufzeit.Hours
Jarvis-Ausgabe ($zeilen -join "`n")
"""

SKRIPT_PAPIERKORB = r"""
Add-Type -AssemblyName Microsoft.VisualBasic
$pfad = $env:JARVIS_ARG_PFAD
$ui = [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs
$papierkorb = [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin
if (Test-Path -LiteralPath $pfad -PathType Container) {
  [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($pfad, $ui, $papierkorb)
} else {
  [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($pfad, $ui, $papierkorb)
}
Jarvis-Ausgabe 'ok'
"""

# Windows-Suche (Indexdienst) über OLE DB; SQL wird in Python sicher zusammengesetzt
SKRIPT_SUCHE = r"""
$verbindung = New-Object -ComObject ADODB.Connection
$daten = New-Object -ComObject ADODB.Recordset
$verbindung.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
$daten.Open($env:JARVIS_ARG_SQL, $verbindung)
$liste = @()
while (-not $daten.EOF) { $liste += [string]$daten.Fields.Item('System.ItemPathDisplay').Value; $daten.MoveNext() }
$daten.Close(); $verbindung.Close()
Jarvis-Ausgabe ($liste -join "`n")
"""


def such_sql(anfrage: str, ordner: str, nur_namen: bool, max_treffer: int) -> str:
    """SQL für den Windows-Suchindex. Alle Werte sind maskiert (keine SQL-Injektion).

    * Zeichenketten: ``'`` → ``''``
    * ``LIKE``: ``[``, ``%``, ``_`` werden in eckige Klammern gesetzt
    * ``CONTAINS``: doppelte Anführungszeichen entfernt (Phrase in ``"…"``)
    """
    def sql_text(wert: str) -> str:
        return wert.replace("\x00", "").replace("'", "''")

    like = sql_text(anfrage).replace("[", "[[]").replace("%", "[%]").replace("_", "[_]")
    bereich = sql_text("file:" + ordner.replace("\\", "/"))
    bedingung = f"System.FileName LIKE '%{like}%'"
    if not nur_namen:
        phrase = sql_text(anfrage.replace('"', " ")).strip()
        if phrase:
            bedingung += f" OR CONTAINS(*, '\"{phrase}\"')"
    anzahl = max(1, min(int(max_treffer), 500))
    return (
        f"SELECT TOP {anzahl} System.ItemPathDisplay FROM SYSTEMINDEX "
        f"WHERE SCOPE='{bereich}' AND ({bedingung})"
    )


MEDIENTASTEN = {"play": 0xB3, "pause": 0xB3, "playpause": 0xB3, "weiter": 0xB0, "zurueck": 0xB1}


def _app_name(name: str) -> str:
    from .linux import app_name_pruefen

    return app_name_pruefen(name)


class WindowsAktionen(Systemaktionen):
    plattform = "windows"

    async def app_oeffnen(self, name: str) -> str:
        name = _app_name(name)
        gefunden = await powershell(SKRIPT_APP_OEFFNEN, {"name": name}, timeout=30, zweck="App öffnen")
        return f"{gefunden or name} wurde geöffnet."

    async def app_beenden(self, name: str) -> str:
        name = _app_name(name)
        anzahl = await powershell(SKRIPT_APP_BEENDEN, {"name": name}, timeout=20, zweck="App beenden")
        if anzahl.strip() == "0":
            return f"{name}: Schließen angefordert, die App hat (noch) nicht reagiert (evtl. ungespeicherte Änderungen)."
        return f"{name} wurde beendet."

    async def laufende_apps(self) -> str:
        return await powershell(SKRIPT_LAUFENDE_APPS, zweck="Laufende Apps") or "Keine Apps mit Fenster gefunden."

    async def lautstaerke_setzen(self, prozent: int | None, aenderung: int | None, stumm: bool | None) -> str:
        werte = {
            "prozent": "" if prozent is None else str(max(0, min(100, int(prozent)))),
            "aenderung": "" if aenderung is None or prozent is not None else str(int(aenderung)),
            "stumm": "" if stumm is None else ("1" if stumm else "0"),
        }
        stand = await powershell(SKRIPT_LAUTSTAERKE, werte, timeout=40, zweck="Lautstärke")
        if stand.strip() == "?":
            return "Lautstärke über die Medientasten geändert." + (" (stumm umgeschaltet)" if stumm is not None else "")
        return f"Lautstärke jetzt {stand.strip()} %." + (" (stumm)" if stumm else "")

    async def mitteilung_anzeigen(self, text: str, titel: str) -> str:
        from ..konfig import aktueller_name

        await powershell(SKRIPT_MITTEILUNG, {"titel": titel or aktueller_name(), "text": text}, timeout=30, zweck="Mitteilung")
        return "Mitteilung angezeigt."

    async def musik_steuern(self, aktion: str, app: str, suchbegriff: str | None) -> str:
        if aktion == "suchen":
            if not suchbegriff:
                raise _fehler("Für aktion=suchen wird ein suchbegriff benötigt.")
            await self.url_oeffnen("spotify:search:" + quote(suchbegriff))
            return (
                f"Spotify-Suche nach „{suchbegriff}“ geöffnet. Für gezieltes Abspielen bestimmter "
                "Titel kann die Spotify-Integration aus dem Katalog hinzugefügt werden."
            )
        if aktion in MEDIENTASTEN:
            await powershell(SKRIPT_MEDIENTASTE, {"taste": MEDIENTASTEN[aktion]}, zweck="Medientaste")
            hinweis = " (Medientaste Wiedergabe/Pause)" if aktion in ("play", "pause") else ""
            return f"Medientaste „{aktion}“ gesendet{hinweis}."
        if aktion == "aktuell":
            titel = await powershell(SKRIPT_SPOTIFY_TITEL, zweck="Spotify")
            if not titel or titel.lower().startswith("spotify"):
                return "Es läuft gerade nichts (bzw. Spotify ist pausiert oder nicht geöffnet)."
            return titel
        raise _fehler(f"Unbekannte Aktion: {aktion}")

    async def url_oeffnen(self, url: str) -> str:
        await powershell(SKRIPT_URL, {"url": url}, timeout=20, zweck="URL öffnen")
        return f"{url} geöffnet."

    async def zwischenablage_lesen(self) -> str:
        return await powershell(SKRIPT_ZWISCHENABLAGE_LESEN, zweck="Zwischenablage")

    async def zwischenablage_schreiben(self, text: str) -> str:
        await powershell(SKRIPT_ZWISCHENABLAGE_SCHREIBEN, eingabe=text, zweck="Zwischenablage")
        return "Text in die Zwischenablage kopiert."

    async def bildschirmfoto(self, pfad: str) -> str:
        await powershell(SKRIPT_BILDSCHIRMFOTO, {"pfad": pfad}, timeout=30, zweck="Bildschirmfoto")
        return f"Bildschirmfoto gespeichert: {pfad}"

    async def systeminfo(self) -> str:
        return await powershell(SKRIPT_SYSTEMINFO, timeout=40, zweck="Systeminfo")

    async def in_papierkorb(self, pfad: Path) -> str:
        try:
            from send2trash import send2trash
        except ImportError:
            send2trash = None
        if send2trash is not None:
            send2trash(str(pfad))
        else:
            await powershell(SKRIPT_PAPIERKORB, {"pfad": str(pfad)}, timeout=60, zweck="Papierkorb")
        return f"{pfad} liegt jetzt im Papierkorb."

    async def dateien_suchen(self, anfrage: str, ordner: str, nur_namen: bool, max_treffer: int) -> list[str]:
        try:
            ausgabe = await powershell(
                SKRIPT_SUCHE, {"sql": such_sql(anfrage, ordner, nur_namen, max_treffer)}, timeout=30, zweck="Windows-Suche"
            )
            treffer = [z for z in ausgabe.splitlines() if z.strip()]
        except Exception:  # noqa: BLE001 - Indexdienst aus/nicht verfügbar → Dateinamensuche
            treffer = []
        if not treffer:
            import asyncio

            treffer = await asyncio.to_thread(python_dateisuche, anfrage, ordner, max_treffer)
        return treffer

    def shell_befehl(self, befehl: str) -> list[str]:
        """PowerShell; der Befehl wird als ``-EncodedCommand`` übergeben (keine Quoting-Probleme)."""
        skript = "try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }\n" + befehl
        return [powershell_programm(), "-NoProfile", "-NonInteractive", "-EncodedCommand", kodieren(skript)]


__all__ = ["WindowsAktionen", "kodieren", "powershell", "powershell_befehl", "ps_literal", "such_sql"]
