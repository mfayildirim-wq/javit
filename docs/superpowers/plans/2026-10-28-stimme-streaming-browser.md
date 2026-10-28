# Flüssige Stimme – Umsetzungsplan

> **Für ausführende Agenten:** Aufgaben nacheinander mit `superpowers:executing-plans`; je Aufgabe erst Test
> (rot), dann Code (grün), dann Commit. Spezifikation:
> `docs/superpowers/specs/2026-10-28-stimme-streaming-browser-design.md`.

**Ziel:** Javit spricht satzweise, sobald das Modell den ersten Satz hat (OpenRouter-PCM-Strom, ElevenLabs),
hört auf ein Stoppwort und kann Mikrofon und Lautsprecher des Browsers nutzen.

**Architektur:** Neues Modul `stimme/sprecher.py` (Satzstrom, OpenRouterTTS, Ausgabeziele Lautsprecher/Browser,
Sprecher-Warteschlange). `StimmDienst` nutzt den Sprecher für alle Ausgaben, erkennt das Stoppwort im Modus
SPRICHT und kann Quelle/Ziel auf den Browser umschalten. Der Agent speist Text-Deltas in den Sprecher.
Server/WebSocket transportieren Binärframes; die Oberfläche kapselt Aufnahme/Wiedergabe in `lib/audio.ts`.

**Technik:** Python 3.12, httpx (Streaming), sounddevice (optional), Vosk, FastAPI-WebSocket (Binär),
Web Audio API (AudioWorklet), React/zustand, vitest.

Befehle: Kern `cd kern && ~/.jarvis/venv/bin/python -m pytest -q <datei>`; Oberfläche
`cd oberflaeche && npm run typecheck && npx vitest run && npm run build`.

---

### Aufgabe 1: Satzstrom, OpenRouterTTS, Ausgabeziele, Sprecher
**Dateien:** Neu `kern/jarvis/stimme/sprecher.py`; Test `kern/tests/stimme/test_sprecher.py` (neu).
- [ ] Tests: Satzstrom (Grenzen, „z. B.“, „3.5“, Rest, erster Satz ab 12 Zeichen, kurze Sätze verschmelzen);
  OpenRouterTTS mit MockTransport (Chunks, Rate aus Content-Type, Stereo→Mono, 401 → StimmFehler);
  Sprecher mit Fake-Synthese und Fake-Ziel (Reihenfolge, max. 2 voraus, Fehler überspringt Satz, stoppen leert);
  BrowserZiel (Frames ≤ 9600 Bytes, Ereignisse start/ende/gestoppt, ende wartet Spieldauer – mit Fake-Clock);
  BrowserQuelle (48 kHz → 1280er-Rahmen).
- [ ] Umsetzen laut Spezifikation; `LautsprecherZiel` mit sounddevice, Fallback WAV + Abspieler.
- [ ] Grün, Commit „Stimme: Sprecher mit Satzstrom, OpenRouter-PCM-Strom, Ausgabeziele“.

### Aufgabe 2: Einstellungen und Fabriken
**Dateien:** `kern/jarvis/konfig.py`, `kern/jarvis/stimme/einstellungen.py`, `kern/jarvis/stimme/tts.py`
(`tts_art`, `erzeuge_tts`), `kern/jarvis/stimme/stt.py` (`erzeuge_stt`, `OpenRouterSTT`); Tests
`kern/tests/stimme/test_sprecher.py` (Teil 2), `tests/stimme/test_stt.py` falls vorhanden.
- [ ] Tests: `tts_art` auto → openrouter nur mit Schlüssel in `os.environ`; `erzeuge_tts` liefert OpenRouterTTS
  mit Standardstimme je Modell; `stt` auto; `OpenRouterSTT.erkennen` mit MockTransport; `stoppwort`-Normalisierung.
- [ ] Umsetzen; Grün; Commit „Stimme: Einstellungen openrouter/stoppwort, Fabriken“.

### Aufgabe 3: StimmDienst – Sprecher, Stoppwort, Quelle/Ziel
**Dateien:** `kern/jarvis/stimme/dienst.py`; Tests `kern/tests/stimme/test_dienst*.py`.
- [ ] Tests: `sprechen(text)` läuft über den Sprecher (Fake-Ziel bekommt PCM, Zustand spricht→bereit);
  `sprecher_beginnen` + `einspeisen` + `abschliessen`; Stoppwort-Detektor (Fake) im Modus SPRICHT stoppt und
  sendet `sprachausgabe gestoppt`; `quelle_setzen` wechselt Quelle; `ausgabe_setzen` Browser.
- [ ] Umsetzen; bestehende Dienst-Tests grün; Commit.

### Aufgabe 4: Agent und Anwendung streamen ins Sprechen
**Dateien:** `kern/jarvis/agent.py`, `kern/jarvis/anwendung.py`; Tests `kern/tests/test_agent.py`,
`kern/tests/test_server.py`.
- [ ] Tests: Fake-Sprecher erhält Deltas in Reihenfolge, `abschliessen` am Ende, `stoppen` bei Abbruch;
  `anfrage(sprechen=True)` ohne Stimmmodul nutzt weiterhin `_vorlesen_ohne_stimmdienst`.
- [ ] Umsetzen (`Agent.sprecher`-Fabrik, `_schleife`, `Jarvis.sprecher()`), Grün, Commit.

### Aufgabe 5: WebSocket-Binärframes, Browser-Sitzung, Probe und Modelle
**Dateien:** `kern/jarvis/server.py`, `kern/jarvis/anwendung.py`; Tests `kern/tests/test_server.py`.
- [ ] Tests: `audio_start` + Binärframes → BrowserQuelle (Fake-Dienst zählt Rahmen); Ausgabe-Binärframes nur an
  diese Verbindung; Trennen beendet Sitzung; `POST /api/stimme/probe` 400 ohne Schlüssel;
  `GET /api/stimme/modelle` mit Mock-Transport.
- [ ] Umsetzen (`ws.receive()` statt `receive_json`, Binär-Sender je Verbindung), Grün, Commit.

### Aufgabe 6: Oberfläche – Audio, Socket, Umschalter
**Dateien:** `src/lib/audio.ts` (neu), `src/api/socket.ts`, `src/api/types.ts`, `src/state/reducer.ts`,
`src/state/store.ts`, `src/state/verbindung.ts`, `src/components/Composer.tsx`; Tests `src/__tests__/audio.test.ts`,
`src/__tests__/stimme.test.tsx`.
- [ ] Tests: int16-Umwandlung, Wiedergabeplanung (Fake-AudioContext), Socket-Binär rein/raus, Umschalter +
  Mikrofon-Knopf senden `audio_start`/`stimme`, Reducer `sprachausgabe gestoppt` → Hinweis.
- [ ] Umsetzen, `npm run typecheck && npx vitest run && npm run build`, Commit.

### Aufgabe 7: Einstellungen-Oberfläche (Stimme)
**Dateien:** `src/views/Settings.tsx`, `src/api/rest.ts`, `src/api/types.ts`; Test `src/__tests__/stimme.test.tsx`.
- [ ] Tests: Auswahl „OpenRouter“, Modelle/Stimmen aus `/api/stimme/modelle`, Stoppwort speichern, Probe-Knopf.
- [ ] Umsetzen, Grün, Commit.

### Aufgabe 8: Doku, Gesamtlauf, Live-Prüfung
- [ ] `docs/VERTRAEGE.md`, READMEs, `docs/STAND.md`, `docs/PROTOKOLL.md`, `CLAUDE.md`.
- [ ] Gesamte Kern-Suite, Oberfläche komplett, Live am Mac: Probe über Lautsprecher (ElevenLabs), Stoppwort,
  Browser-Audio in Chrome (Mikrofon-Freigabe durch den Nutzer).
- [ ] Caches aufräumen, Commit, Push.
