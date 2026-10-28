# Flüssige Stimme: Streaming-Sprachausgabe, Stoppwort, Audio im Browser – Design (28.10.2026)

## Ziel

1. **Streaming-Sprachausgabe**: Javit spricht, sobald der erste Satz der Antwort feststeht, während das Modell
   weiterschreibt. Neue Ausgabeart `openrouter` (PCM-Strom, 24 kHz) mit ElevenLabs Flash als Standard; die
   bisherigen Arten bleiben und werden satzweise eingereiht.
2. **Stoppwort** („stopp“, einstellbar): bricht die laufende Ausgabe sofort ab. Weckwort unterbricht weiterhin
   und nimmt die nächste Frage auf.
3. **Audio im Browser**: Mikrofon und Lautsprecher der Oberfläche (Handy, Portal) über den WebSocket; im Kern
   wird der Browser eine Audioquelle wie das Mikrofon; die Ausgabe geht als PCM-Strom zurück.
4. **Einstellungen**: Ausgabeart OpenRouter mit Modell und Stimme, Spracherkennung über OpenRouter, Stoppwort,
   Probe-Knopf; Umschalter „Audio im Browser“.

Nicht enthalten: Sprache-zu-Sprache-Modelle (Realtime), Sprecher-Erkennung, Audio im Portal-Relais.

## Recherche (28.10.2026, live geprüft)

* OpenRouter `POST /api/v1/audio/speech` `{model, input, voice, response_format: pcm|mp3, speed?, instructions?}`
  → roher Byte-Strom, `Content-Type: audio/pcm;rate=24000;channels=1` (int16 mono), chunked. Gemessen mit
  deutschem Satz (8 s Audio): `elevenlabs/eleven-flash-v2.5` Stimme `daniel` erster Byte 0,39 s, gesamt 0,44 s,
  40 $/1M Zeichen; `microsoft/mai-voice-2.1-flash` Stimme `de-DE-Klaus:MAI-Voice-2.1-Flash` 1,0 s, 15 $/1M;
  `google/gemini-3.8-flash-lite-tts` Stimme `Kore` 2,4 s. OpenAI-TTS ist dort nicht verfügbar (400).
  Modelle: `GET /api/v1/models?output_modalities=speech` (`supported_voices`, `pricing.prompt` je Zeichen).
* OpenRouter `POST /api/v1/audio/transcriptions` JSON `{model, input_audio: {data: base64, format: wav}, language}`
  → `{text, usage}`. `openai/whisper-large-v3` 0,96 s für 7 s Audio (0,00018 $), `openai/gpt-4o-mini-transcribe`
  0,66 s. Beide erkannten den Satz korrekt (Name „Javit“ phonetisch).
* Browser: `getUserMedia({audio: {echoCancellation, noiseSuppression, autoGainControl}})`, AudioWorklet liefert
  Float32-Blöcke; Abtastrate des Geräts (44,1/48 kHz) → im Kern `Rahmenbildner` (vorhanden) auf 16 kHz.
  Wiedergabe über `AudioContext` mit `AudioBuffer` (24 kHz) lückenlos geplant.

## Kern

### `stimme/sprecher.py` (neu)

* `Satzstrom`: `einspeisen(delta) -> list[str]` liefert fertige Sätze (Grenze `[.!?…]` + Leerraum + Großbuchstabe/
  Ziffer/Anführungszeichen, wie `text.in_saetze`), hält Zahlen wie „3.5“ und Abkürzungen („z. B.“, „Dr.“, „Nr.“)
  zusammen, gibt den ersten Satz ab 12 Zeichen frei, verschmilzt sehr kurze Folgesätze (< 25 Zeichen) mit dem
  nächsten; `abschliessen() -> str | None` liefert den Rest. Jeder Satz läuft durch `fuer_sprache`.
* `StreamSynthese` (Protokoll): `strom(text) -> AsyncIterator[bytes]` (PCM int16, 24 kHz, mono) und
  `synthetisieren(text, ziel) -> str` (WAV-Datei, für `einmal_vorlesen`/Fallback).
* `OpenRouterTTS(modell, stimme, schluessel, http_client_fabrik=None, geschwindigkeit=1.0)`: ruft
  `/audio/speech` mit `response_format: pcm`; liest `rate`/`channels` aus dem Content-Type (Standard 24000/1),
  wandelt Stereo nach Mono; Fehler → `StimmFehler` mit Status und Kurztext (Schlüssel fehlt, Modell unbekannt,
  Guthaben). Kopfzeilen `HTTP-Referer`/`X-Title` wie `llm.py`.
* `Ausgabeziel` (Protokoll): `start(rate)`, `schreiben(pcm: bytes)`, `ende()` (wartet bis alles gespielt ist),
  `stoppen()` (verwirft Puffer sofort), Pegel über Rückruf (15/s, RMS der geschriebenen Blöcke in Spielzeit).
  * `LautsprecherZiel`: `sounddevice.OutputStream` (int16, Rate des Stroms) mit Ringpuffer-Callback; fehlt
    sounddevice oder das Gerät, schreibt es je Satz eine WAV-Datei und nutzt `Abspieler` (bisheriger Weg).
  * `BrowserZiel(sender)`: sendet `{"typ":"sprachausgabe","zustand":"start","rate":…}`, dann Binärframes
    (≤ 9600 Bytes = 200 ms), `…"ende"` bzw. `…"gestoppt"`; `ende()` wartet die Spieldauer ab (Rate·Bytes), damit
    der Dialog erst danach weiter zuhört.
* `Sprecher(tts, ziel, pegel, stopp_event)`: `beginnen()`, `einspeisen(delta)`, `abschliessen()` (wartet bis
  Warteschlange leer und Ziel fertig), `stoppen()`. Intern: Satzwarteschlange → bis zu 2 Synthesen voraus →
  Wiedergabe in Reihenfolge. Für Synthesen ohne `strom` (say, SAPI, Piper, espeak, cloud): `synthetisieren` in
  Datei und `Abspieler.abspielen` (unverändert). Fehler eines Satzes: `fehler`-Ereignis, weiter mit dem nächsten.

### `stimme/dienst.py`

* `sprecher_beginnen() -> Sprecher`, `sprechen_strom(deltas: AsyncIterator[str])` (für Tests), `sprechen(text)`
  bleibt (nutzt intern `Sprecher` mit dem ganzen Text). Zustand `spricht` ab dem ersten Satz, danach wie heute.
* Dialog: `_anfrage(text)` liefert den Text weiterhin; das Vorlesen passiert jetzt während der Anfrage über den
  Agenten (unten). `_dialog` wartet nach `_anfrage` auf `sprecher.abschliessen()` statt `_sprechen_intern`.
* **Stoppwort**: Einstellung `stoppwort` (Standard „stopp“; mehrere durch Komma; leer = aus). Zweiter
  `VoskWeckwortDetektor` (gleiches Modellverzeichnis, lazy beim ersten Sprechen, Varianten „stop, stopp, halt“
  werden automatisch ergänzt) prüft Rahmen im Modus `SPRICHT` mit Schwelle `min(schwelle + 0.2, 0.95)`.
  Treffer → `_ausgabe_stoppen()`, Ereignis `{"typ":"sprachausgabe","zustand":"gestoppt","grund":"stoppwort"}`,
  Dialog beendet die laufende Antwort, kein Folgemodus, Zustand `bereit`. Weckwort-Barge-in (`unterbrechen`)
  bleibt davon unberührt. Ist das Weckwort openWakeWord, lädt das Stoppwort trotzdem Vosk (Download wie beim
  Weckwort, nicht bei `JARVIS_KEIN_DOWNLOAD`).
* **Browser-Quelle**: `BrowserQuelle(rate)` implementiert `AudioQuelle` (`starten(rueckruf)`, `stoppen()`) plus
  `einspeisen(bytes)` (int16 → `Rahmenbildner` → 16-kHz-Rahmen à 1280). `StimmDienst.quelle_setzen(quelle|None)`:
  wechselt die Audioquelle (laufenden Dialog abbrechen, Quelle schließen, neue öffnen, Weckwort an, wenn vorher an).
  `ausgabe_setzen(ziel|None)`: Browser- statt Lautsprecherziel.

### Agent und Anwendung

* `Agent(..., sprecher: Callable[[], Sprecher | None])`: bei `sprechen=True` holt `_schleife` zu Beginn einen
  Sprecher (`beginnen()`), gibt jeden Text-Delta mit `einspeisen` weiter (auch Zwischentexte vor Werkzeugaufrufen),
  ruft am Ende `abschliessen()` (wartet) bzw. bei Abbruch `stoppen()`. Freigabefragen laufen weiter über
  `vorlesen(frage)`; der Sprecher pausiert währenddessen nicht – Fragen kommen erst nach einem fertigen Delta-Satz.
* `Jarvis.anfrage(text, sprechen=True)` ruft `vorlesen` am Ende nur noch, wenn kein Sprachmodul läuft
  (`_vorlesen_ohne_stimmdienst`). `Jarvis.sprecher()` liefert den Sprecher des StimmDienstes (startet ihn bei
  Bedarf ohne Mikrofon: `StimmDienst` wird erzeugt, aber nicht `start()`; Sprechen braucht keine Quelle).
* `Jarvis.browser_audio_start(sender, rate)` / `browser_audio_stop()`: legt `BrowserQuelle`/`BrowserZiel` an,
  `stimme.quelle_setzen`/`ausgabe_setzen`, startet den StimmDienst (Weckwort an). Pro Kern genau eine
  Browser-Sitzung; eine zweite ersetzt die erste (`sprachausgabe gestoppt` an die alte). Beim Trennen des
  WebSockets wird die Sitzung beendet.
* `POST /api/stimme/probe` `{text?}` → spricht einen Probesatz über den aktuellen Weg (Lautsprecher oder
  Browser) → `{ok, art, modell, stimme}`; 400 bei fehlendem Schlüssel.

### Einstellungen (`konfig.StimmEinstellungen`, `stimme/einstellungen.py`)

| Feld | Standard | Bedeutung |
|---|---|---|
| `tts` | `auto` | zusätzlich `openrouter`; `auto` = `openrouter`, wenn `OPENROUTER_API_KEY` vorhanden, sonst wie bisher (say/sapi/piper) |
| `tts_openrouter_modell` | `elevenlabs/eleven-flash-v2.5` | Modell für `openrouter` |
| `tts_stimme` | `""` | bei `openrouter` leer = `daniel` (ElevenLabs), `de-DE-Klaus:MAI-Voice-2.1-Flash` (Microsoft), `Kore` (Google) |
| `stt` | `auto` (neu) | zusätzlich `openrouter`; `auto` = `openrouter` mit Schlüssel, sonst `lokal` |
| `stt_openrouter_modell` | `openai/whisper-large-v3` | Modell für `openrouter` |
| `stoppwort` | `stopp` | Stoppwörter, Komma-getrennt; leer = aus |

`GET /api/stimme/modelle` → `{tts: [{id, name, stimmen[], preis_je_1m_zeichen}], stt: [{id, name}]}` aus dem
OpenRouter-Modellkatalog (gefiltert auf ElevenLabs, Microsoft MAI, Google TTS, Mistral; 10 min Cache; ohne
Schlüssel leer).

### WebSocket (`docs/VERTRAEGE.md`)

Client → Server: `audio_start {rate}`, `audio_stop`, danach **Binärframes** = int16 PCM mono mit `rate`.
Server → Client: `sprachausgabe {zustand: start|ende|gestoppt, rate?, grund?}`; zwischen `start` und `ende`
**Binärframes** = int16 PCM mono 24 kHz, nur an die Verbindung mit aktiver Audio-Sitzung. `pegel` wie bisher.
`stimme {aktiv}` und `zuhoeren` funktionieren mit Browser-Quelle unverändert.

## Oberfläche

* `src/lib/audio.ts`: `BrowserAudio` – `start()` (getUserMedia, AudioContext, Worklet aus Blob-URL: Float32 →
  int16, Blöcke à 4096 Samples), `stop()`, `abspielen(pcm: ArrayBuffer)` (AudioBuffer 24 kHz, lückenlose Planung),
  `leeren()`; Ereignisse `pegel` lokal für die Orb-Animation während der Aufnahme.
* `api/socket.ts`: `sendeBinaer(daten)`, `onBinaer(daten)`; `ws.binaryType = 'arraybuffer'`.
* Umschalter „Audio im Browser“ (Composer neben dem Mikrofon; localStorage `jarvis.audioBrowser`; Standard an bei
  Touch-Geräten oder wenn `Status.plattform` fehlt). Ist er an, startet der Mikrofon-Knopf die Browser-Aufnahme
  und sendet `audio_start`, dann `stimme {aktiv: true}`; aus → `audio_stop`, `stimme {aktiv: false}`.
  Leertaste (Push-to-talk) sendet weiterhin `zuhoeren`.
* Einstellungen → Stimme: Sprachausgabe-Auswahl mit „OpenRouter (Cloud, streamt)“, Modellauswahl aus
  `/api/stimme/modelle` mit Stimmenliste, Spracherkennung „OpenRouter (Whisper)“, Feld „Stoppwort“, Knopf
  „Probe sprechen“ (ruft `/api/stimme/probe`). Hinweis mit Preis je Minute (aus `preis_je_1m_zeichen` · 900).
* Reducer: `sprachausgabe` setzt `spricht`/`bereit`-unabhängig ein Feld `sprachausgabe: 'laeuft' | null` und bei
  `gestoppt` einen Hinweis „Ausgabe gestoppt (Stoppwort)“.

## Tests

* `tests/stimme/test_sprecher.py`: Satzstrom (Grenzen, Abkürzungen, Zahlen, Rest), Sprecher mit Fake-Synthese
  (Reihenfolge, Vorauslesen max. 2, Fehler eines Satzes, `stoppen` leert), `OpenRouterTTS` mit `MockTransport`
  (PCM-Chunks, Content-Type-Rate, 401 → StimmFehler), `BrowserZiel` (Rahmen ≤ 9600 Bytes, Ereignisse),
  `BrowserQuelle` (48-kHz-Eingabe → 1280er-Rahmen).
* `tests/stimme/test_dienst_stimme.py` (bestehende Dienst-Tests erweitern): Stoppwort bricht Ausgabe ab und sendet
  `sprachausgabe gestoppt`; Weckwort-Barge-in unverändert; `quelle_setzen` wechselt die Quelle.
* `tests/test_agent.py`: Deltas gehen an den Sprecher, `abschliessen` am Ende, `stoppen` bei Abbruch.
* `tests/test_server.py`: `audio_start` + Binärframes erreichen die Browser-Quelle, Ausgabe kommt als Binärframes
  an genau diese Verbindung; `POST /api/stimme/probe` ohne Schlüssel → 400; `GET /api/stimme/modelle` mit Mock.
* Oberfläche: `audio.test.ts` (Worklet-Nachrichten → int16, Wiedergabeplanung mit Fake-AudioContext),
  `stimme.test.tsx` (Umschalter, Mikrofon-Knopf sendet `audio_start`+`stimme`, Einstellungen: Auswahl, Stoppwort,
  Probe-Knopf).

## Doku

`docs/VERTRAEGE.md` (Ereignisse, Binärframes, Einstellungen, Endpunkte), `README.md`/`README.de.md` (Stimme über
OpenRouter, Stoppwort, Browser-Audio), `docs/STAND.md`, `docs/PROTOKOLL.md`, `CLAUDE.md` (Aufbau `stimme/sprecher.py`).
