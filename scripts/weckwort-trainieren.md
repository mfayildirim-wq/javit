# Eigenes Weckwort „Javit“ trainieren (optional)

Javit hört standardmäßig ohne Training auf „Javit“: Die Vosk-Engine erkennt das Wort offline über
eine kleine Grammatik aus bekannten Silben („ja witt“, „ja vit“ …) und einen phonetischen Abgleich
(Kölner Phonetik). Das funktioniert sofort, verbraucht aber etwas mehr CPU als ein neuronales
Weckwort-Modell und kann bei sehr ähnlichen Wörtern seltener danebenliegen.

Wer ein **eigenes openWakeWord-Modell** möchte (sehr sparsam, robust gegen Hintergrundgespräche),
trainiert es einmalig mit dem offiziellen Werkzeug von openWakeWord und bindet die `.onnx`-Datei ein.

> Das Training läuft **nicht** im Projekt und nicht auf dem Mac/PC, sondern in Google Colab
> (kostenlose GPU) oder auf einem Linux-Rechner mit NVIDIA-GPU. Dauer: ca. 1 Stunde (einfaches
> Notebook) bis mehrere Stunden (automatisches Training mit 20 000 Beispielen).

## 1. Training vorbereiten

Die Trainingsdaten sind **synthetisch**: openWakeWord erzeugt mit Piper-TTS tausende Aussprachen
des Zielworts, mischt sie mit Raumhall, Musik und Geräuschen und trainiert gegen große Mengen
„Nicht-Weckwort“-Sprache.

Wichtig: Die TTS-Stimmen des Trainings sind **englisch**. „Javit“ würde englisch („Dschäi-wit“)
ausgesprochen. Deshalb mehrere Lautschrift-Varianten als Zielphrasen angeben, die der deutschen
Aussprache nahekommen, z. B. `javit`, `ja vit`, `yah veet`, `jaa wit` – und ähnlich klingende Wörter
als Negativbeispiele (`david`, `java`, `ja bitte`, `jarvis` …).

Konfiguration erzeugen (schreibt nur eine YAML-Datei, lädt nichts):

```bash
python3 scripts/weckwort_trainieren.py konfig --ziel javit.yml
# eigene Varianten:
python3 scripts/weckwort_trainieren.py konfig --ziel javit.yml --phrase "ja vit" --phrase "yah veet" --negativ "david"
```

Die Schlüssel entsprechen `examples/custom_model.yml` im openWakeWord-Repository
(`model_name`, `target_phrase`, `custom_negative_phrases`, `n_samples`, `steps`,
`target_false_positives_per_hour` …).

## 2. Trainieren

**Variante A – einfaches Colab-Notebook** (ohne Programmierkenntnisse, ca. 1 Stunde):

1. Das in der README von openWakeWord verlinkte Colab-Notebook öffnen
   (<https://github.com/dscripka/openWakeWord> → Abschnitt „Training New Models“, Link
   „Google Colab notebook“).
2. Laufzeit → Laufzeittyp ändern → **GPU**.
3. Als Zielwort `ja vit` (bzw. eine der Varianten oben) eintragen, alle Zellen ausführen.
4. Am Ende `javit.onnx` (bzw. `<name>.onnx`) herunterladen.

**Variante B – automatisches Training** (`notebooks/automatic_model_training.ipynb` im Repository,
besser für gute Modelle):

1. Notebook in Colab oder lokal (Linux + GPU) öffnen; es klont openWakeWord und
   `piper-sample-generator`, lädt Raumhall- (MIT RIR), Hintergrund- (AudioSet/FMA) und
   Negativdaten (ACAV100M-Merkmale, Validierungsdaten).
2. Die erzeugte `javit.yml` hochladen bzw. die Werte ins Notebook übernehmen.
3. Die drei Schritte des Trainingsskripts laufen lassen:

   ```bash
   python openwakeword/train.py --training_config javit.yml --generate_clips
   python openwakeword/train.py --training_config javit.yml --augment_clips
   python openwakeword/train.py --training_config javit.yml --train_model
   ```

4. Ergebnis: `javit_modell/javit.onnx` (Ausgabeordner = `output_dir`).

Tipp: Mehr Beispiele (`n_samples` ≥ 20 000) und `target_false_positives_per_hour` 0,2 oder kleiner
ergeben weniger Fehlauslösungen.

## 3. Modell einbinden

```bash
python3 scripts/weckwort_trainieren.py installieren ~/Downloads/javit.onnx
```

Das Skript kopiert die Datei nach `~/.jarvis/modelle/openwakeword/javit.onnx` und setzt in
`~/.jarvis/einstellungen.json`:

```json
"stimme": {
  "weckwort": "javit",
  "weckwort_engine": "openwakeword",
  "weckwort_modell_pfad": "/Users/<name>/.jarvis/modelle/openwakeword/javit.onnx"
}
```

Von Hand geht es genauso (Pfad absolut, mit `~` oder nur Dateiname im Ordner
`~/.jarvis/modelle/openwakeword/`). Die Merkmalsmodelle von openWakeWord (`melspectrogram.onnx`,
`embedding_model.onnx`) werden beim ersten Start automatisch nachgeladen, falls sie fehlen.

Danach in der Oberfläche die Sprache aus- und wieder einschalten. Die **Weckwort-Empfindlichkeit**
(Einstellungen → Stimme) wirkt direkt auf den Score des Modells (0,5 ist ein guter Start; bei
Fehlauslösungen erhöhen).

Zurück zur trainingsfreien Erkennung: `weckwort_modell_pfad` leeren und `weckwort_engine` auf
`auto` oder `vosk` stellen.
