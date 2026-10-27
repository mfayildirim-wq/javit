# Javit – Oberfläche

React + TypeScript (strict) + Vite. Futuristische HUD-Oberfläche für den Kern des Assistenten (Name aus `/api/status`, Standard „Javit“) mit
animiertem Reaktor-Orb, Live-Transkript, Werkzeug-Zeitleiste, Freigabe-Dialog,
Integrationen und Einstellungen. Der Kern liefert den Build (`dist/`) unter `/` aus.

Schnittstellen: siehe `../docs/VERTRAEGE.md` (REST `/api`, WebSocket `/ws`).

## Start

```bash
npm install
npm run mock        # Mock-Kern auf http://127.0.0.1:8765 (REST + WebSocket)
npm run dev         # Vite auf http://127.0.0.1:5173, Proxy /api und /ws → 8765
```

Mit dem echten Kern entfällt `npm run mock` – einfach `jarvis start` und `npm run dev`.

| Skript | Zweck |
|---|---|
| `npm run dev` | Entwicklungsserver mit Proxy auf den Kern (Port 8765) |
| `npm run build` | Typprüfung + Produktions-Build nach `dist/` (base `/`) |
| `npm run preview` | Build lokal ansehen (Port 4173, ebenfalls mit Proxy) |
| `npm test` | Vitest + Testing Library (jsdom) |
| `npm run typecheck` | `tsc` ohne Ausgabe |
| `npm run mock` | Mock-Kern (`mock-server.mjs`) |

## Mock-Kern

`mock-server.mjs` simuliert alle REST-Endpunkte und WebSocket-Events realistisch:

- Nachrichten mit „Wetter“, „Musik/Jazz/Spiel“, „Räum … Downloads auf“ (mit Freigabe) oder „Fehler“
  lösen passende Werkzeugketten, gestreamte Antworten und Zustandswechsel aus.
- `stimme: {aktiv: true}` startet eine simulierte Spracheingabe mit Pegel und Zwischen-Transkripten.
- `abbrechen` stoppt alles, `freigabe` beantwortet offene Anfragen.
- Für Screenshots/Tests: `POST /mock/szenario/<name>` mit
  `bereit | hoert | denkt | arbeitet | spricht | freigabe | gespraech | reset`.

Screenshots aller Zustände (Mock und `npm run preview` müssen laufen, Python-Playwright nötig):

```bash
python3 scripts/screenshots.py /tmp/jarvis-ui
```

## Bedienung

| Kürzel | Wirkung |
|---|---|
| Enter | Nachricht senden |
| Leertaste halten (außerhalb von Eingabefeldern) | Stimme einmal aktivieren (war das Mikrofon aus, wird es nach der Runde wieder ausgeschaltet) |
| Esc | Freigabe ablehnen, sonst laufende Arbeit abbrechen, sonst zurück zur Konsole |
| Cmd/Strg + K | Befehlspalette (Ansichten, Mikrofon, Vorlesen, Modellwechsel, „Javit fragen“ – mit dem eingestellten Namen) |

Die Boot-Animation (≤ 1,4 s) lässt sich per Klick oder Taste überspringen und erscheint pro Sitzung einmal.

## Aufbau

```
src/
  api/types.ts        Typen für alle REST-Antworten und WS-Events (VERTRAEGE.md)
  api/socket.ts       WebSocket-Client mit exponentiellem Reconnect (0,5 s … 8 s)
  api/rest.ts         fetch-Wrapper für /api
  state/reducer.ts    reiner Event-Reducer (Server-Events + lokale Aktionen)
  state/store.ts      zustand-Store, Senden, Freigabe, Abbrechen, Ansicht
  state/verbindung.ts Hook: Verbindung, Status-Abfrage, Verlauf laden
  components/         Orb (Canvas), Konsole, Eingabe, Systeme, Aktivität,
                      Freigabe-Dialog, Befehlspalette, Hinweise, Boot
  views/              Integrationen (Installiert, Katalog, Eigene), Einstellungen
  lib/                Integrations-Bodies, Formatierung, Icons, Tastenkürzel
  styles/app.css      Design-Tokens und gesamtes Styling
```

### Gestaltung

- Tiefes Blau-Schwarz (`#02060c`/`#040a13`), ein einziger Akzent Eis-Cyan (`#7fe8ff`);
  Orange/Rot nur für Freigaben und Fehler, Grün nur für „verbunden/ok“.
- Schriften lokal gebündelt über `@fontsource`: **Sora** (Text, Uhr, Antworten) und
  **JetBrains Mono** (Werkzeugnamen, Daten). Keine Anfragen an Google Fonts.
- Reaktor-Orb: Canvas 2D, ein `requestAnimationFrame`-Loop, liest den Store direkt
  (kein React-Render pro Frame), pausiert im Hintergrund-Tab und hinter anderen Ansichten.
  Zustände: *bereit* atmet, *hoert* pulsiert mit `pegel`, *denkt* dreht schnell,
  *arbeitet* zeigt Orbit-Punkte, *spricht* zeigt eine Wellenform im Kern; bei offener
  Freigabe färbt er sich orange, ohne Kern wird er gedimmt.
- `prefers-reduced-motion`: Orb zeichnet nur bei Zustandsänderungen, CSS-Animationen aus.
- Markdown in Antworten über `react-markdown` ohne rohes HTML (`skipHtml`), kein
  `dangerouslySetInnerHTML`.

### Annahmen (wo VERTRAEGE.md offen ist)

- `GET/PUT /api/einstellungen` folgt `kern/jarvis/konfig.py`: gesendet wird nur das Teilupdate
  `{stimme: {aktiv, schwelle, stt, tts, tts_stimme}, anrede_verwenden, anrede}` – die Persona
  (Systemprompt, Feld `persona`) wird nie verändert.
- `GET /api/status` darf zusätzlich `zustand` liefern; nach (Wieder-)Verbindung übernimmt der Orb ihn.
- `GET /api/gedaechtnis`: Liste `[{id, zeit, text}]` (auch `{erinnerungen: [...]}` wird akzeptiert);
  `DELETE /api/gedaechtnis` ohne `id` löscht alles.
- `GET /api/verlauf`: Liste `[{id, zeit, rolle: "nutzer"|"jarvis", inhalt}]` (`text` statt `inhalt` geht auch).
- OpenAPI-Auth: `auth.art` ∈ `bearer | api_key | basic`, bei „Keine“ entfällt `auth`.
- REST-Parametertypen: `text | zahl | bool`.
- Getippte Nachrichten zeigt die Oberfläche sofort an; ein `transkript` mit `final: true`
  und identischem Text innerhalb von 10 s wird nicht doppelt angezeigt.
- `freigabe_noetig.id` kann der ID eines Werkzeugaufrufs entsprechen; ein `werkzeug_ende`
  mit derselben ID schließt den Dialog. Nach 120 s ohne Antwort sendet die Oberfläche
  `{typ: "freigabe", id, erlaubt: false}`.
