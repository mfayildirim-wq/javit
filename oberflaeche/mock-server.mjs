#!/usr/bin/env node
// Mock des Kerns (Assistent „Javit“) für Entwicklung und Screenshots.
// REST unter /api, WebSocket unter /ws – gemäß docs/VERTRAEGE.md.
// Zusätzlich Steuer-Endpunkte für Tests: POST /mock/szenario/<name>
//   (bereit | hoert | denkt | arbeitet | spricht | freigabe | gespraech | buehne | reset)
//
// Start: npm run mock   (Port 8765, oder PORT=…)

import http from 'node:http';
import { WebSocketServer } from 'ws';
import { buehneAnfrage, buehneSzenario } from './mock-buehne.mjs';

const PORT = Number(process.env.PORT ?? 8765);
const HOST = process.env.HOST ?? '127.0.0.1';

// ------------------------------------------------------------------ Daten

const modelle = {
  aktuell: 'anthropic/claude-sonnet-5-5',
  vorschlaege: [
    { id: 'ollama/qwen2.5:7b', name: 'Qwen 2.5 7B', lokal: true, verfuegbar: true },
    { id: 'ollama/llama3.1:8b', name: 'Llama 3.1 8B', lokal: true, verfuegbar: true },
    { id: 'ollama/mistral-nemo', name: 'Mistral Nemo', lokal: true, verfuegbar: false },
    { id: 'anthropic/claude-sonnet-5-5', name: 'Claude Sonnet 5.5', lokal: false, verfuegbar: true },
    { id: 'openai/gpt-6.1-sol', name: 'GPT-6.1 Sol', lokal: false, verfuegbar: true },
    { id: 'gemini/gemini-3.8-flash', name: 'Gemini 3.8 Flash', lokal: false, verfuegbar: false },
    { id: 'groq/llama-3.3-70b-versatile', name: 'Llama 3.3 70B (Groq)', lokal: false, verfuegbar: false },
  ],
};

let einstellungen = {
  name: 'Javit',
  modell: modelle.aktuell,
  persona: 'Du bist {name}, der persönliche KI-Assistent …',
  anrede: 'Sir',
  anrede_verwenden: true,
  stimme: { aktiv: true, weckwort: 'javit', weckwort_engine: 'auto', schwelle: 0.5, stt: 'lokal', tts: 'say', tts_stimme: 'Anna' },
};

const katalog = [
  { id: 'spotify', name: 'Spotify', beschreibung: 'Musik abspielen, suchen, Playlists steuern', kategorie: 'Musik', icon: 'music', art: 'mcp_stdio',
    benoetigt: [ { name: 'SPOTIFY_CLIENT_ID', titel: 'Client ID', geheim: false }, { name: 'SPOTIFY_CLIENT_SECRET', titel: 'Client Secret', geheim: true } ],
    hinweis: 'Schlüssel unter developer.spotify.com → Dashboard → App anlegen. Redirect-URI: http://127.0.0.1:8765/callback' },
  { id: 'github', name: 'GitHub', beschreibung: 'Issues, Pull Requests und Repositories verwalten', kategorie: 'Entwicklung', icon: 'github', art: 'mcp_stdio',
    benoetigt: [ { name: 'GITHUB_TOKEN', titel: 'Personal Access Token', geheim: true } ], hinweis: 'Token unter github.com/settings/tokens erzeugen (fine-grained).' },
  { id: 'kalender', name: 'Kalender', beschreibung: 'Termine aus dem macOS-Kalender lesen und anlegen', kategorie: 'Organisation', icon: 'calendar', art: 'eingebaut', benoetigt: [] },
  { id: 'erinnerungen', name: 'Erinnerungen', beschreibung: 'Aufgaben in der Erinnerungen-App verwalten', kategorie: 'Organisation', icon: 'list-todo', art: 'eingebaut', benoetigt: [] },
  { id: 'notion', name: 'Notion', beschreibung: 'Seiten und Datenbanken durchsuchen und bearbeiten', kategorie: 'Organisation', icon: 'notion', art: 'mcp_stdio',
    benoetigt: [ { name: 'NOTION_TOKEN', titel: 'Integration Token', geheim: true } ] },
  { id: 'browser', name: 'Browser', beschreibung: 'Webseiten öffnen, klicken und ausfüllen (Playwright)', kategorie: 'Web', icon: 'globe', art: 'mcp_stdio', benoetigt: [] },
  { id: 'brave-suche', name: 'Brave Suche', beschreibung: 'Websuche mit aktuellen Ergebnissen', kategorie: 'Web', icon: 'search', art: 'mcp_stdio',
    benoetigt: [ { name: 'BRAVE_API_KEY', titel: 'API-Schlüssel', geheim: true } ] },
  { id: 'home-assistant', name: 'Home Assistant', beschreibung: 'Licht, Heizung und Szenen im Smart Home steuern', kategorie: 'Zuhause', icon: 'home', art: 'mcp_http',
    benoetigt: [ { name: 'HA_URL', titel: 'Adresse', geheim: false }, { name: 'HA_TOKEN', titel: 'Langzeit-Token', geheim: true } ] },
  { id: 'slack', name: 'Slack', beschreibung: 'Nachrichten lesen und in Kanälen schreiben', kategorie: 'Kommunikation', icon: 'slack', art: 'mcp_stdio',
    benoetigt: [ { name: 'SLACK_BOT_TOKEN', titel: 'Bot-Token', geheim: true }, { name: 'SLACK_TEAM_ID', titel: 'Team-ID', geheim: false } ] },
  { id: 'mail', name: 'Mail', beschreibung: 'E-Mails in Apple Mail suchen, lesen und entwerfen', kategorie: 'Kommunikation', icon: 'mail', art: 'eingebaut', benoetigt: [] },
  { id: 'wetter', name: 'Wetter', beschreibung: 'Vorhersage über Open-Meteo, ohne Schlüssel', kategorie: 'Web', icon: 'cloud-sun', art: 'rest', benoetigt: [] },
  { id: 'dateisystem', name: 'Dateien', beschreibung: 'Dateien in freigegebenen Ordnern lesen und schreiben', kategorie: 'System', icon: 'folder', art: 'mcp_stdio', benoetigt: [] },
  { id: 'todoist', name: 'Todoist', beschreibung: 'Aufgaben und Projekte verwalten', kategorie: 'Organisation', icon: 'list-todo', art: 'openapi',
    benoetigt: [ { name: 'TODOIST_TOKEN', titel: 'API-Token', geheim: true } ] },
  { id: 'youtube', name: 'YouTube', beschreibung: 'Videos suchen und Transkripte abrufen', kategorie: 'Musik', icon: 'youtube', art: 'mcp_stdio', benoetigt: [] },
  { id: 'postgres', name: 'PostgreSQL', beschreibung: 'Datenbank abfragen (nur lesend)', kategorie: 'Entwicklung', icon: 'database', art: 'mcp_stdio',
    benoetigt: [ { name: 'DATABASE_URL', titel: 'Verbindungs-URL', geheim: true } ] },
];

let integrationen = [
  { id: 'spotify', name: 'Spotify', art: 'mcp_stdio', status: 'verbunden', werkzeuge: 12 },
  { id: 'kalender', name: 'Kalender', art: 'eingebaut', status: 'verbunden', werkzeuge: 4 },
  { id: 'browser', name: 'Browser', art: 'mcp_stdio', status: 'verbunden', werkzeuge: 9 },
  { id: 'wetter', name: 'Wetter', art: 'rest', status: 'verbunden', werkzeuge: 1 },
  { id: 'home-assistant', name: 'Home Assistant', art: 'mcp_http', status: 'fehler', werkzeuge: 0, fehler: 'Verbindung abgelehnt: homeassistant.local:8123' },
];

const werkzeugeBasis = [
  ['app_oeffnen', 'Programm starten', 'mac', null, 'aendern'],
  ['lautstaerke_setzen', 'Systemlautstärke setzen', 'mac', null, 'aendern'],
  ['shell_ausfuehren', 'Shell-Befehl ausführen', 'mac', null, 'kritisch'],
  ['datei_loeschen', 'Datei in den Papierkorb legen', 'mac', null, 'kritisch'],
  ['web_suche', 'Im Web suchen', 'web', null, 'lesen'],
  ['webseite_lesen', 'Webseite als Text lesen', 'web', null, 'lesen'],
  ['spotify_suchen', 'Titel suchen', 'mcp', 'spotify', 'lesen'],
  ['spotify_abspielen', 'Wiedergabe starten', 'mcp', 'spotify', 'aendern'],
  ['kalender_termine', 'Termine lesen', 'eingebaut', 'kalender', 'lesen'],
  ['kalender_anlegen', 'Termin anlegen', 'eingebaut', 'kalender', 'aendern'],
  ['wetter_abrufen', 'Wetter abrufen', 'rest', 'wetter', 'lesen'],
  ['mail_senden', 'E-Mail senden', 'eingebaut', null, 'kritisch'],
];
const werkzeuge = () => [
  ...werkzeugeBasis.map(([name, beschreibung, quelle, integration, risiko]) => ({ name, beschreibung, quelle, integration, risiko })),
  ...Array.from({ length: 14 }, (_, i) => ({ name: `browser_aktion_${i}`, beschreibung: 'Browser', quelle: 'mcp', integration: 'browser', risiko: i % 4 === 0 ? 'aendern' : 'lesen' })),
];

let gedaechtnis = [
  { id: 1, text: 'Bevorzugt Jazz am Abend, besonders Miles Davis und Bill Evans.', zeit: '2026-10-20T19:12:00Z' },
  { id: 2, text: 'Arbeitet meist von 9 bis 17 Uhr im Büro in Hamburg.', zeit: '2026-10-21T08:30:00Z' },
  { id: 3, text: 'Mag kurze Antworten ohne Smalltalk.', zeit: '2026-10-24T12:05:00Z' },
];

const verlauf = [];

// ------------------------------------------------------------------ REST

function senden(res, status, daten) {
  const body = daten === undefined ? '' : JSON.stringify(daten);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(body);
}

function lesen(req) {
  return new Promise((ok) => {
    let d = '';
    req.on('data', (c) => (d += c));
    req.on('end', () => {
      try {
        ok(d ? JSON.parse(d) : {});
      } catch {
        ok({});
      }
    });
  });
}

function slug(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || `int-${Date.now()}`;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://${req.headers.host}`);
  const p = url.pathname;
  const m = req.method ?? 'GET';
  await warte(60 + Math.random() * 120);

  if (p === '/api/status' && m === 'GET')
    return senden(res, 200, {
      version: '0.1.0-mock',
      name: einstellungen.name,
      modell: modelle.aktuell,
      stimme: { aktiv: einstellungen.stimme.aktiv, weckwort: einstellungen.stimme.weckwort, hoert: kern.zustand === 'hoert', engine: 'vosk' },
      integrationen: integrationen.filter((i) => i.status === 'verbunden').length,
      werkzeuge: werkzeuge().length,
      zustand: kern.zustand,
    });
  if (p === '/api/modelle' && m === 'GET') return senden(res, 200, modelle);
  if (p === '/api/modelle' && m === 'PUT') {
    const b = await lesen(req);
    if (!b.modell) return senden(res, 422, { detail: 'modell fehlt' });
    modelle.aktuell = b.modell;
    einstellungen.modell = b.modell;
    return senden(res, 200, { modell: b.modell });
  }
  if (p === '/api/einstellungen' && m === 'GET') return senden(res, 200, einstellungen);
  if (p === '/api/einstellungen' && m === 'PUT') {
    const b = await lesen(req);
    einstellungen = {
      ...einstellungen,
      ...b,
      stimme: { ...einstellungen.stimme, ...(b.stimme ?? {}) },
    };
    console.log('[mock] Einstellungen:', JSON.stringify(b));
    return senden(res, 200, einstellungen);
  }
  if (p.startsWith('/api/geheimnisse/') && m === 'PUT') {
    const b = await lesen(req);
    console.log('[mock] Geheimnis gesetzt:', decodeURIComponent(p.split('/').pop()), '(', String(b.wert ?? '').length, 'Zeichen )');
    return senden(res, 200, { ok: true });
  }
  if (p === '/api/werkzeuge' && m === 'GET') return senden(res, 200, werkzeuge());
  if (p === '/api/integrationen' && m === 'GET') return senden(res, 200, integrationen);
  if (p === '/api/integrationen/katalog' && m === 'GET') return senden(res, 200, katalog);
  if (p === '/api/integrationen' && m === 'POST') {
    const b = await lesen(req);
    console.log('[mock] Integration anlegen:', JSON.stringify(b));
    await warte(500);
    let neu;
    if (b.katalog) {
      const k = katalog.find((x) => x.id === b.katalog);
      if (!k) return senden(res, 404, { detail: `Unbekannter Katalogeintrag: ${b.katalog}` });
      neu = { id: k.id, name: k.name, art: k.art, status: 'verbunden', werkzeuge: 3 + Math.floor(Math.random() * 8) };
    } else if (b.mcp_befehl) neu = { id: slug(b.name), name: b.name, art: 'mcp_stdio', status: 'verbunden', werkzeuge: 5 };
    else if (b.mcp_url) neu = { id: slug(b.name), name: b.name, art: 'mcp_http', status: 'verbunden', werkzeuge: 4 };
    else if (b.openapi_url) neu = { id: slug(b.name), name: b.name, art: 'openapi', status: 'verbunden', werkzeuge: 19 };
    else if (Array.isArray(b.rest)) neu = { id: slug(b.name), name: b.name, art: 'rest', status: 'verbunden', werkzeuge: b.rest.length };
    else return senden(res, 422, { detail: 'Unbekannte Form' });
    integrationen = [...integrationen.filter((i) => i.id !== neu.id), neu];
    rundruf({ typ: 'integration_geaendert', integration: neu });
    return senden(res, 200, neu);
  }
  const intMatch = p.match(/^\/api\/integrationen\/([^/]+)(\/neu-verbinden)?$/);
  if (intMatch && intMatch[1] !== 'katalog') {
    const id = decodeURIComponent(intMatch[1]);
    const i = integrationen.find((x) => x.id === id);
    if (!i) return senden(res, 404, { detail: 'Nicht gefunden' });
    if (m === 'DELETE' && !intMatch[2]) {
      integrationen = integrationen.filter((x) => x.id !== id);
      rundruf({ typ: 'integration_geaendert', integration: { id, entfernt: true } });
      return senden(res, 200, { ok: true });
    }
    if (m === 'POST' && intMatch[2]) {
      await warte(700);
      Object.assign(i, { status: 'verbunden', fehler: undefined, werkzeuge: i.werkzeuge || 6 });
      rundruf({ typ: 'integration_geaendert', integration: i });
      return senden(res, 200, i);
    }
  }
  if (p === '/api/verlauf' && m === 'GET') return senden(res, 200, verlauf.slice(-Number(url.searchParams.get('limit') ?? 20)));
  if (p === '/api/gedaechtnis' && m === 'GET') return senden(res, 200, gedaechtnis);
  if (p === '/api/gedaechtnis' && m === 'DELETE') {
    gedaechtnis = [];
    return senden(res, 200, { ok: true });
  }

  const b = await buehneAnfrage(p, m, () => lesen(req));
  if (b) return senden(res, b[0], b[1]);

  // Steuerung für Screenshots/Tests
  const sz = p.match(/^\/mock\/szenario\/([a-z_]+)$/);
  if (sz && m === 'POST') {
    szenario(sz[1]);
    return senden(res, 200, { ok: true, szenario: sz[1] });
  }
  senden(res, 404, { detail: 'Nicht gefunden' });
});

// ------------------------------------------------------------------ WebSocket

const wss = new WebSocketServer({ server, path: '/ws' });
const kern = { zustand: 'bereit', laeufe: 0, timer: new Set(), intervalle: new Set(), freigaben: new Map() };

function rundruf(ev) {
  const s = JSON.stringify(ev);
  for (const c of wss.clients) if (c.readyState === 1) c.send(s);
}
function zustand(z) {
  kern.zustand = z;
  rundruf({ typ: 'zustand', zustand: z });
}
function warte(ms) {
  return new Promise((ok) => {
    const t = setTimeout(() => {
      kern.timer.delete(t);
      ok();
    }, ms);
    kern.timer.add(t);
  });
}
function pegelStarten(stark = 1) {
  let t = 0;
  const iv = setInterval(() => {
    t += 1;
    const w = Math.max(0, Math.min(1, (0.25 + 0.55 * Math.abs(Math.sin(t / 3)) + Math.random() * 0.25) * stark));
    rundruf({ typ: 'pegel', wert: Number(w.toFixed(3)) });
  }, 66);
  kern.intervalle.add(iv);
  return () => {
    clearInterval(iv);
    kern.intervalle.delete(iv);
    rundruf({ typ: 'pegel', wert: 0 });
  };
}
function allesStoppen() {
  kern.laeufe += 1;
  for (const t of kern.timer) clearTimeout(t);
  kern.timer.clear();
  for (const i of kern.intervalle) clearInterval(i);
  kern.intervalle.clear();
  for (const [, f] of kern.freigaben) f(false);
  kern.freigaben.clear();
}

let zaehler = 0;
const nid = (p) => `${p}-${Date.now().toString(36)}-${(zaehler++).toString(36)}`;

async function streamen(text, lauf, sprechen) {
  const id = nid('a');
  rundruf({ typ: 'antwort_start', id });
  const stop = sprechen ? pegelStarten(0.9) : null;
  if (sprechen) zustand('spricht');
  const teile = text.match(/\S+\s*/g) ?? [];
  for (const t of teile) {
    if (lauf !== kern.laeufe) return;
    rundruf({ typ: 'antwort_text', id, delta: t });
    await warte(28 + Math.random() * 50);
  }
  if (lauf !== kern.laeufe) return;
  rundruf({ typ: 'antwort_ende', id, text });
  verlauf.push({ id: verlauf.length + 1, rolle: 'jarvis', inhalt: text, zeit: new Date().toISOString() });
  if (sprechen) {
    await warte(900);
    stop?.();
  }
}

async function werkzeug(name, argumente, integration, dauerMs, ergebnis, ok = true) {
  const id = nid('w');
  rundruf({ typ: 'werkzeug_start', id, name, argumente, integration });
  await warte(dauerMs);
  rundruf({ typ: 'werkzeug_ende', id, ok, ergebnis });
  return id;
}

function freigabeAnfragen(werkzeugName, argumente, grund, risiko = 'kritisch') {
  const id = nid('f');
  rundruf({ typ: 'freigabe_noetig', id, werkzeug: werkzeugName, argumente, grund, risiko });
  return new Promise((ok) => {
    kern.freigaben.set(id, ok);
    const t = setTimeout(() => {
      kern.freigaben.delete(id);
      ok(false);
    }, 120_000);
    kern.timer.add(t);
  });
}

const sir = () => (einstellungen.anrede_verwenden ? `, ${einstellungen.anrede || 'Sir'}` : '');

async function bearbeiten(text, sprechen) {
  allesStoppen();
  const lauf = kern.laeufe;
  verlauf.push({ id: verlauf.length + 1, rolle: 'nutzer', inhalt: text, zeit: new Date().toISOString() });
  zustand('denkt');
  await warte(700 + Math.random() * 500);
  if (lauf !== kern.laeufe) return;
  const t = text.toLowerCase();

  if (/wetter|regen|temperatur/.test(t)) {
    zustand('arbeitet');
    await werkzeug('wetter_abrufen', { latitude: 53.55, longitude: 9.99, current_weather: true }, 'wetter', 900,
      { temperatur: 11.4, wind_kmh: 18, wettercode: 3, beschreibung: 'bedeckt' });
    if (lauf !== kern.laeufe) return;
    zustand('denkt');
    await warte(500);
    return fertig(lauf, sprechen,
      `In Hamburg sind es gerade **11 °C** bei bedecktem Himmel${sir()}. Der Wind kommt mit etwa 18 km/h aus Südwest.\n\nFür heute Abend ist kein Regen gemeldet – ein Schirm ist nicht nötig.`);
  }
  if (/musik|spiel|jazz|song|lied/.test(t)) {
    zustand('arbeitet');
    await werkzeug('spotify_suchen', { query: 'Miles Davis Kind of Blue', typ: 'album', limit: 5 }, 'spotify', 800,
      [{ id: '1weenld61qoidwYuZ1GESA', name: 'Kind Of Blue', artist: 'Miles Davis' }]);
    if (lauf !== kern.laeufe) return;
    await werkzeug('spotify_abspielen', { uri: 'spotify:album:1weenld61qoidwYuZ1GESA', geraet: 'MacBook Pro' }, 'spotify', 600, { ok: true });
    if (lauf !== kern.laeufe) return;
    return fertig(lauf, sprechen, `Ich spiele *Kind of Blue* von Miles Davis auf dem MacBook${sir()}.`);
  }
  if (/lösch|loesch|räum|download|shell|terminal/.test(t)) {
    zustand('arbeitet');
    await werkzeug('dateien_auflisten', { pfad: '~/Downloads', muster: '*.dmg' }, null, 500, ['Firefox 131.dmg', 'Zoom.pkg.dmg', 'Docker.dmg']);
    if (lauf !== kern.laeufe) return;
    const erlaubt = await freigabeAnfragen('shell_ausfuehren', { befehl: 'rm ~/Downloads/*.dmg', arbeitsverzeichnis: '~' },
      'Löscht 3 Installationsdateien (1,8 GB) dauerhaft aus dem Downloads-Ordner.');
    if (lauf !== kern.laeufe) return;
    if (!erlaubt) return fertig(lauf, sprechen, `Verstanden${sir()}, ich lasse die Dateien unangetastet.`);
    await werkzeug('shell_ausfuehren', { befehl: 'rm ~/Downloads/*.dmg' }, null, 700, 'exit 0');
    return fertig(lauf, sprechen, `Erledigt${sir()}. Drei Installationsdateien entfernt, **1,8 GB** wieder frei.`);
  }
  if (/fehler|kaputt/.test(t)) {
    zustand('arbeitet');
    await werkzeug('kalender_termine', { von: 'heute', bis: 'morgen' }, 'kalender', 700, 'Zugriff auf Kalender verweigert (macOS-Datenschutz)', false);
    return fertig(lauf, sprechen, 'Ich habe keinen Zugriff auf den Kalender. Bitte unter *Systemeinstellungen → Datenschutz → Kalender* freigeben.');
  }
  return fertig(lauf, sprechen,
    `Gern${sir()}. Ich bin ein Mock des Kerns – probieren Sie „Wie ist das Wetter?“, „Spiel etwas Jazz“ oder „Räum meine Downloads auf“.\n\n- Werkzeuge erscheinen rechts in der Aktivität\n- Kritische Aktionen brauchen Ihre Freigabe`);
}

async function fertig(lauf, sprechen, text) {
  if (lauf !== kern.laeufe) return;
  await streamen(text, lauf, sprechen && einstellungen.stimme.tts !== 'aus');
  if (lauf !== kern.laeufe) return;
  zustand('bereit');
}

async function zuhoeren(satz = 'Wie ist das Wetter in Hamburg?') {
  allesStoppen();
  const lauf = kern.laeufe;
  zustand('hoert');
  const stop = pegelStarten();
  const woerter = satz.split(' ');
  for (let i = 1; i <= woerter.length; i++) {
    await warte(260);
    if (lauf !== kern.laeufe) return stop();
    rundruf({ typ: 'transkript', text: woerter.slice(0, i).join(' '), final: false });
  }
  await warte(500);
  stop();
  if (lauf !== kern.laeufe) return;
  rundruf({ typ: 'transkript', text: satz, final: true });
  void bearbeiten(satz, true);
}

wss.on('connection', (ws) => {
  ws.send(JSON.stringify({ typ: 'zustand', zustand: kern.zustand }));
  ws.on('message', (roh) => {
    let n;
    try {
      n = JSON.parse(String(roh));
    } catch {
      return ws.send(JSON.stringify({ typ: 'fehler', text: 'Ungültiges JSON' }));
    }
    console.log('[mock] ←', JSON.stringify(n));
    switch (n.typ) {
      case 'nachricht':
        if (typeof n.text !== 'string' || !n.text.trim()) return ws.send(JSON.stringify({ typ: 'fehler', text: 'Leere Nachricht' }));
        void bearbeiten(n.text, Boolean(n.sprechen));
        break;
      case 'freigabe': {
        const f = kern.freigaben.get(n.id);
        if (f) {
          kern.freigaben.delete(n.id);
          f(Boolean(n.erlaubt));
        }
        break;
      }
      case 'buehne_aktion':
      case 'buehne_daten':
        break; // im Mock nur protokolliert
      case 'abbrechen':
        allesStoppen();
        zustand('bereit');
        break;
      case 'stimme':
        einstellungen.stimme.aktiv = Boolean(n.aktiv);
        if (n.aktiv && kern.zustand === 'bereit') void zuhoeren();
        break;
      default:
        ws.send(JSON.stringify({ typ: 'fehler', text: `Unbekannter Typ: ${n.typ}` }));
    }
  });
});

// ------------------------------------------------------------------ Szenarien (für Screenshots)

async function szenario(name) {
  allesStoppen();
  const lauf = kern.laeufe;
  switch (name) {
    case 'reset':
    case 'bereit':
      zustand('bereit');
      break;
    case 'hoert': {
      rundruf({ typ: 'transkript', text: '', final: false });
      zustand('hoert');
      pegelStarten();
      const satz = 'Javit, wie wird das Wetter morgen früh in Hamburg';
      const w = satz.split(' ');
      for (let i = 1; i <= w.length && lauf === kern.laeufe; i++) {
        rundruf({ typ: 'transkript', text: w.slice(0, i).join(' '), final: false });
        await warte(180);
      }
      break; // bleibt im Zuhören, Pegel läuft weiter
    }
    case 'buehne':
      for (const n of buehneSzenario()) rundruf(n);
      break;
    case 'gespraech': {
      rundruf({ typ: 'transkript', text: 'Wie ist das Wetter in Hamburg?', final: true });
      const id = nid('a');
      const text = `In Hamburg sind es gerade **11 °C** bei bedecktem Himmel${sir()}. Der Wind kommt mit etwa 18 km/h aus Südwest.\n\nFür heute Abend ist kein Regen gemeldet – ein Schirm ist nicht nötig.`;
      rundruf({ typ: 'antwort_start', id });
      rundruf({ typ: 'antwort_ende', id, text });
      zustand('bereit');
      break;
    }
    case 'denkt':
    case 'arbeitet': {
      rundruf({ typ: 'transkript', text: 'Spiel etwas Ruhiges von Miles Davis und dimm das Licht im Wohnzimmer', final: true });
      zustand('denkt');
      await werkzeug('kalender_termine', { von: 'heute 18:00', bis: 'heute 23:59' }, 'kalender', 30, [{ titel: 'Abendessen mit Lea', beginn: '19:30' }]);
      await werkzeug('spotify_suchen', { query: 'Miles Davis', stimmung: 'ruhig', limit: 5 }, 'spotify', 40,
        [{ name: 'Kind Of Blue', artist: 'Miles Davis' }, { name: "'Round About Midnight", artist: 'Miles Davis' }]);
      await werkzeug('licht_dimmen', { raum: 'Wohnzimmer', helligkeit: 30 }, 'home-assistant', 30, 'Home Assistant nicht erreichbar (Zeitüberschreitung nach 5 s)', false);
      if (name === 'arbeitet') zustand('arbeitet');
      rundruf({ typ: 'werkzeug_start', id: nid('w'), name: 'spotify_abspielen', argumente: { uri: 'spotify:album:1weenld61qoidwYuZ1GESA', geraet: 'MacBook Pro', lautstaerke: 35 }, integration: 'spotify' });
      if (name === 'denkt') zustand('denkt');
      break;
    }
    case 'spricht': {
      zustand('spricht');
      pegelStarten(0.9);
      break;
    }
    case 'freigabe': {
      rundruf({ typ: 'transkript', text: 'Räum meinen Downloads-Ordner auf', final: true });
      zustand('arbeitet');
      await werkzeug('dateien_auflisten', { pfad: '~/Downloads', muster: '*.dmg' }, null, 30, ['Firefox 131.dmg', 'Zoom.pkg.dmg', 'Docker.dmg']);
      freigabeAnfragen('shell_ausfuehren', { befehl: 'rm ~/Downloads/*.dmg', arbeitsverzeichnis: '~' },
        'Löscht 3 Installationsdateien (1,8 GB) dauerhaft aus dem Downloads-Ordner.');
      break;
    }
    default:
      rundruf({ typ: 'fehler', text: `Unbekanntes Szenario: ${name}` });
  }
}

server.listen(PORT, HOST, () => {
  console.log(`[mock] Jarvis-Kern-Mock läuft auf http://${HOST}:${PORT}  (REST /api, WebSocket /ws)`);
});
