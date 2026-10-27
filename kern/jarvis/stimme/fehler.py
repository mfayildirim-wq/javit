"""Verständliche deutsche Fehlermeldungen für das Sprachmodul."""

from __future__ import annotations


HINWEIS_MIKROFON_RECHTE = (
    "Systemeinstellungen → Datenschutz & Sicherheit → Mikrofon → Terminal "
    "(bzw. die App, in der {name} läuft) erlauben und {name} neu starten."
)
HINWEIS_KEIN_MIKROFON = (
    "Bitte ein Mikrofon anschließen bzw. unter Systemeinstellungen → Ton → Eingabe ein Gerät auswählen."
)
HINWEIS_PAKETE = "Sprachpakete installieren: pip install 'jarvis[stimme]'"

HINWEIS_MIKROFON_RECHTE_WINDOWS = (
    "Einstellungen → Datenschutz und Sicherheit → Mikrofon: „Mikrofonzugriff“ und „Desktop-Apps den "
    "Zugriff auf das Mikrofon erlauben“ einschalten und {name} neu starten."
)
HINWEIS_KEIN_MIKROFON_WINDOWS = (
    "Bitte ein Mikrofon anschließen bzw. unter Einstellungen → System → Sound → Eingabe ein Gerät auswählen."
)
HINWEIS_MIKROFON_LINUX = (
    "Unter Linux läuft der Ton über PipeWire bzw. PulseAudio: Eingabegerät in den Toneinstellungen "
    "(oder mit „pavucontrol“) wählen und prüfen, dass es nicht stummgeschaltet ist; bei Flatpak/Snap "
    "den Mikrofonzugriff der App erlauben. Geräteliste: python -m jarvis.stimme --geraete"
)


def _plattform() -> str:
    from ..plattform import aktuelle_plattform

    return aktuelle_plattform()


def assistent_name() -> str:
    """Eingestellter Name des Assistenten (Standard „Javit“) für Meldungen."""
    from ..konfig import aktueller_name

    return aktueller_name()


def hinweis_mikrofon_rechte() -> str:
    """Wo man den Mikrofonzugriff erlaubt – je Plattform."""
    text = {"mac": HINWEIS_MIKROFON_RECHTE, "windows": HINWEIS_MIKROFON_RECHTE_WINDOWS}.get(
        _plattform(), HINWEIS_MIKROFON_LINUX
    )
    return text.replace("{name}", assistent_name())


def hinweis_kein_mikrofon() -> str:
    return {"mac": HINWEIS_KEIN_MIKROFON, "windows": HINWEIS_KEIN_MIKROFON_WINDOWS}.get(
        _plattform(), HINWEIS_MIKROFON_LINUX
    )


def portaudio_hinweis() -> str:
    plattform = _plattform()
    if plattform == "mac":
        return f"PortAudio wurde nicht gefunden. Installieren mit: brew install portaudio (danach {assistent_name()} neu starten)."
    if plattform == "windows":
        return "PortAudio wurde nicht gefunden. Bitte das Paket neu installieren: pip install --force-reinstall sounddevice"
    try:
        from ..plattform.gemeinsam import paketverwaltung

        pv = paketverwaltung()
    except Exception:  # noqa: BLE001
        pv = "apt"
    befehl = {"apt": "sudo apt install libportaudio2", "dnf": "sudo dnf install portaudio",
              "pacman": "sudo pacman -S portaudio", "zypper": "sudo zypper install portaudio"}[pv]
    return f"PortAudio wurde nicht gefunden (Linux: {befehl})."


class StimmFehler(Exception):
    """Fehler mit fertigem, für Menschen lesbarem deutschen Text."""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


def mikrofon_fehlertext(exc: BaseException, geraet=None) -> str:
    """Übersetzt Fehler beim Öffnen des Mikrofons (sounddevice/PortAudio) in einen Hinweis."""
    if isinstance(exc, StimmFehler):
        return exc.text
    meldung = str(exc) or exc.__class__.__name__
    klein = meldung.lower()
    if isinstance(exc, ImportError) or "no module named" in klein:
        return f"Das Paket „sounddevice“ fehlt – Mikrofon nicht nutzbar. {HINWEIS_PAKETE}"
    if "portaudio library not found" in klein:
        return portaudio_hinweis()
    if geraet not in (None, "") and ("no device" in klein or "device" in klein and "match" in klein):
        return f"Mikrofon „{geraet}“ wurde nicht gefunden. {hinweis_kein_mikrofon()}"
    if (
        "querying device -1" in klein
        or "no default input" in klein
        or "invalid device" in klein
        or "device unavailable" in klein
        or "no input" in klein
    ):
        return f"Kein Mikrofon gefunden. {hinweis_kein_mikrofon()}"
    if "permission" in klein or "not permitted" in klein or "-9986" in klein:
        return f"Kein Zugriff auf das Mikrofon. {hinweis_mikrofon_rechte()}"
    zusatz = hinweis_mikrofon_rechte() if _plattform() in ("mac", "windows") else hinweis_kein_mikrofon()
    return f"Mikrofon konnte nicht geöffnet werden ({meldung}). Prüfe: {zusatz}"


def kurz(exc: BaseException, max_laenge: int = 200) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = " ".join(text.split())
    return text if len(text) <= max_laenge else text[: max_laenge - 1] + "…"
