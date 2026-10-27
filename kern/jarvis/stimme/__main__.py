"""Manueller Test (Mac, Windows, Linux):  python -m jarvis.stimme [--sagen TEXT] [--ptt] [--geraete] [--stt cloud] …

Ohne Optionen: lauscht auf das eingestellte Weckwort (Standard „Javit“ über Vosk) und spricht das
Erkannte als Echo zurück. ``--modelle-laden`` lädt nur die Weckwort-Modelle vorab (Installer).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging


async def _main(args) -> None:
    from . import StimmDienst

    async def ereignis(e: dict) -> None:
        if e["typ"] == "pegel":
            balken = "█" * int(e["wert"] * 30)
            print(f"\r  pegel {balken:<30}", end="", flush=True)
        else:
            print("\n" + json.dumps(e, ensure_ascii=False), flush=True)

    async def anfrage(text: str) -> str:
        return f"Du hast gesagt: {text}"

    stimme = _einstellungen(args)
    stimme["aktiv"] = True
    dienst = StimmDienst({"stimme": stimme}, ereignis, anfrage)
    if args.sagen:
        await dienst.sprechen(args.sagen)
        return
    if args.ptt:
        print(await dienst.einmal_zuhoeren(warten=True))
        return
    await dienst.start()
    if not dienst.aktiv:
        return
    print(f"Sag „{dienst.einstellungen.weckwort}“ … (Strg+C beendet)")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await dienst.stop()


_FELDER = ("stt", "stt_modell", "tts", "tts_stimme", "weckwort", "weckwort_engine", "weckwort_modell_pfad", "schwelle")


def _einstellungen(args) -> dict:
    """Gespeicherte Stimm-Einstellungen, überschrieben durch die Kommandozeile."""
    try:
        from ..konfig import KonfigSpeicher

        stimme = KonfigSpeicher().einstellungen.stimme.model_dump()
    except Exception:  # noqa: BLE001
        stimme = {}
    stimme.update({k: v for k, v in vars(args).items() if k in _FELDER and v is not None})
    return stimme


def modelle_laden(args) -> int:
    """Lädt die Weckwort-Modelle der aktuellen Einstellungen vorab (für die Installer)."""
    from .einstellungen import StimmEinstellungen
    from .fehler import StimmFehler
    from .weckwort import OpenWakeWordDetektor, erzeuge_detektor

    e = StimmEinstellungen.aus({"stimme": _einstellungen(args)})
    fehler = 0
    detektoren = [erzeuge_detektor(e)]
    if args.alle:  # zusätzlich die jeweils andere Engine (Vosk „javit“ bzw. openWakeWord „hey_jarvis“)
        from pathlib import Path

        if getattr(detektoren[0], "engine", "") == "openwakeword":
            andere = StimmEinstellungen.aus({"stimme": {**_einstellungen(args), "weckwort": "javit",
                                                        "weckwort_engine": "vosk", "weckwort_modell_pfad": ""}})
            detektoren.append(erzeuge_detektor(andere))
        else:
            detektoren.append(OpenWakeWordDetektor("hey_jarvis", Path(e.modell_verzeichnis) / "openwakeword"))
    for detektor in detektoren:
        art = "Vosk" if "Vosk" in type(detektor).__name__ else "openWakeWord"
        try:
            detektor.laden()
            print(f"{art}: Weckwort-Modell „{detektor.weckwort}“ bereit.")
        except StimmFehler as f:
            print(f"{art}: {f.text}")
            fehler += 1
    return 1 if fehler else 0


def main() -> None:
    from ..konfig import aktueller_name

    p = argparse.ArgumentParser(prog="python -m jarvis.stimme", description=f"Sprachmodul von {aktueller_name()} testen")
    p.add_argument("--sagen", help="nur diesen Text vorlesen")
    p.add_argument("--ptt", action="store_true", help="einmal zuhören (ohne Weckwort)")
    p.add_argument("--geraete", action="store_true", help="Audiogeräte auflisten")
    p.add_argument("--stt", choices=["lokal", "cloud"])
    p.add_argument("--stt-modell", dest="stt_modell")
    p.add_argument("--tts", choices=["auto", "say", "sapi", "piper", "espeak", "cloud", "aus"])
    p.add_argument("--tts-stimme", dest="tts_stimme")
    p.add_argument("--weckwort", help="z. B. javit oder hey_jarvis")
    p.add_argument("--weckwort-engine", dest="weckwort_engine", choices=["auto", "openwakeword", "vosk"])
    p.add_argument("--weckwort-modell-pfad", dest="weckwort_modell_pfad", help="eigenes openWakeWord-Modell (.onnx)")
    p.add_argument("--modelle-laden", action="store_true", help="nur Weckwort-Modelle vorab herunterladen und beenden")
    p.add_argument("--alle", action="store_true", help="mit --modelle-laden: auch die andere Engine (Vosk „javit“ bzw. openWakeWord „hey_jarvis“)")
    p.add_argument("--schwelle", type=float)
    p.add_argument("-v", "--ausfuehrlich", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.ausfuehrlich else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.modelle_laden:
        raise SystemExit(modelle_laden(args))
    if args.geraete:
        import sounddevice as sd

        print(sd.query_devices())
        return
    try:
        asyncio.run(_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
