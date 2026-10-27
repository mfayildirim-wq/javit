#!/usr/bin/env python3
"""Hilfsskript für ein eigenes openWakeWord-Modell „javit“ (Anleitung: scripts/weckwort-trainieren.md).

Zwei Schritte – das eigentliche Training läuft im offiziellen openWakeWord-Notebook (Google Colab
oder eigener Rechner mit GPU), nicht hier:

    python3 scripts/weckwort_trainieren.py konfig [--ziel javit.yml] [--phrase "ja vit" …]
        schreibt eine Trainingskonfiguration für openwakeword/train.py (Schlüssel wie
        examples/custom_model.yml von openWakeWord)

    python3 scripts/weckwort_trainieren.py installieren PFAD/javit.onnx [--kein-umschalten]
        kopiert das trainierte Modell nach ~/.jarvis/modelle/openwakeword/ und stellt die
        Einstellungen um (stimme.weckwort_modell_pfad, stimme.weckwort_engine = openwakeword)

Es werden keine Pakete installiert und nichts heruntergeladen.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

MODELL_ORDNER = Path.home() / ".jarvis" / "modelle" / "openwakeword"

#: Die TTS-Stimmen des Trainings sind englisch – deutsche Aussprache über Lautschrift annähern
STANDARD_PHRASEN = ["javit", "ja vit", "yah veet", "jaa wit"]
#: ähnlich klingende Wörter, auf die das Modell NICHT reagieren soll
STANDARD_NEGATIV = ["david", "java", "ja bitte", "ja wie", "habit", "jarvis", "javelin"]


def konfig_text(name: str, phrasen: list[str], negativ: list[str], proben: int) -> str:
    """YAML für openwakeword/train.py (bewusst ohne PyYAML erzeugt)."""

    def liste(werte: list[str]) -> str:
        return "[" + ", ".join(json.dumps(w, ensure_ascii=False) for w in werte) + "]"

    return f"""# Trainingskonfiguration für openWakeWord (erzeugt von scripts/weckwort_trainieren.py)
# Schlüssel wie examples/custom_model.yml im openWakeWord-Repository.
model_name: "{name}"
target_phrase: {liste(phrasen)}
custom_negative_phrases: {liste(negativ)}
n_samples: {proben}
n_samples_val: {max(1000, proben // 10)}
tts_batch_size: 50
augmentation_batch_size: 16
piper_sample_generator_path: "./piper-sample-generator"
output_dir: "./{name}_modell"
rir_paths: ["./mit_rirs"]
background_paths: ["./audioset_16k", "./fma"]
background_paths_duplication_rate: [1, 1]
false_positive_validation_data_path: "./validation_set_features.npy"
augmentation_rounds: 1
feature_data_files:
  ACAV100M_sample: "./openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
batch_n_per_class:
  ACAV100M_sample: 1024
  adversarial_negative: 50
  positive: 50
model_type: "dnn"
layer_size: 32
steps: 50000
max_negative_weight: 1500
target_false_positives_per_hour: 0.2
"""


def befehl_konfig(args: argparse.Namespace) -> int:
    ziel = Path(args.ziel)
    if ziel.exists() and not args.ueberschreiben:
        print(f"{ziel} existiert bereits (--ueberschreiben zum Ersetzen).", file=sys.stderr)
        return 1
    phrasen = args.phrase or STANDARD_PHRASEN
    ziel.write_text(konfig_text(args.name, phrasen, args.negativ or STANDARD_NEGATIV, args.proben), encoding="utf-8")
    print(f"Konfiguration geschrieben: {ziel}")
    print("Weiter im openWakeWord-Notebook bzw. mit:")
    print(f"  python openwakeword/train.py --training_config {ziel.name} --generate_clips")
    print(f"  python openwakeword/train.py --training_config {ziel.name} --augment_clips")
    print(f"  python openwakeword/train.py --training_config {ziel.name} --train_model")
    return 0


def befehl_installieren(args: argparse.Namespace) -> int:
    quelle = Path(args.modell).expanduser()
    if quelle.suffix.lower() != ".onnx" or not quelle.is_file():
        print(f"Keine .onnx-Datei: {quelle}", file=sys.stderr)
        return 1
    ordner = Path(args.ordner).expanduser()
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / quelle.name
    if quelle.resolve() != ziel.resolve():
        shutil.copy2(quelle, ziel)
    print(f"Modell abgelegt: {ziel}")
    if args.kein_umschalten:
        print(f"Einstellung von Hand setzen: stimme.weckwort_modell_pfad = {ziel}")
        return 0
    kern = Path(__file__).resolve().parents[1] / "kern"
    sys.path.insert(0, str(kern))
    try:
        from jarvis.konfig import KonfigSpeicher  # noqa: PLC0415
    except ImportError:
        print(f"Kern nicht gefunden – Einstellung von Hand setzen: stimme.weckwort_modell_pfad = {ziel}", file=sys.stderr)
        return 1
    speicher = KonfigSpeicher()
    speicher.aktualisieren({"stimme": {"weckwort_modell_pfad": str(ziel), "weckwort_engine": "openwakeword"}})
    print(f"Einstellungen aktualisiert ({speicher.pfad}): Weckwort-Engine openWakeWord mit {ziel.name}.")
    print("Sprache in der Oberfläche aus- und wieder einschalten (oder den Assistenten neu starten).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Eigenes openWakeWord-Modell „javit“ vorbereiten und einbinden")
    sub = p.add_subparsers(dest="befehl", required=True)
    k = sub.add_parser("konfig", help="Trainingskonfiguration (YAML) schreiben")
    k.add_argument("--name", default="javit")
    k.add_argument("--ziel", default="javit.yml")
    k.add_argument("--phrase", action="append", help="Zielphrase (mehrfach möglich)")
    k.add_argument("--negativ", action="append", help="Phrase, auf die NICHT reagiert werden soll (mehrfach)")
    k.add_argument("--proben", type=int, default=20000, help="Anzahl synthetischer Beispiele (Standard 20000)")
    k.add_argument("--ueberschreiben", action="store_true")
    k.set_defaults(funktion=befehl_konfig)
    i = sub.add_parser("installieren", help="trainierte .onnx-Datei ablegen und Einstellungen umstellen")
    i.add_argument("modell")
    i.add_argument("--ordner", default=os.environ.get("JARVIS_OWW_ORDNER", str(MODELL_ORDNER)))
    i.add_argument("--kein-umschalten", action="store_true", help="Einstellungen nicht ändern")
    i.set_defaults(funktion=befehl_installieren)
    args = p.parse_args(argv)
    return int(args.funktion(args))


if __name__ == "__main__":
    raise SystemExit(main())
