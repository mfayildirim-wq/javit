// Bühne im Mock-Kern: Beispielflächen (Immobilien, Posteingang, Wetter), Stile aus dem Kern-Paket,
// Vorlagen/Rezepte im Speicher. Eingebunden von mock-server.mjs.
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const V = 'v0.9.1';
const KATALOG = 'jarvis:buehne/1';
const STIL_ORDNER = join(dirname(fileURLToPath(import.meta.url)), '..', 'kern', 'jarvis', 'buehne', 'stile');

function stileLaden() {
  try {
    return readdirSync(STIL_ORDNER)
      .filter((d) => d.endsWith('.json'))
      .map((d) => ({ ...JSON.parse(readFileSync(join(STIL_ORDNER, d), 'utf8')), eigen: false }));
  } catch {
    return [];
  }
}

const stile = stileLaden();
let zuordnung = { 'gg-immobilien': 'papier' };

const IMMOBILIEN = {
  surfaceId: 'immobilienliste', titel: 'Immobilien', catalogId: KATALOG, stil: 'javit-dunkel', vorlage: 'immobilienliste',
  components: [
    { id: 'root', component: 'Column', children: ['kopf', 'kacheln'] },
    { id: 'kopf', component: 'Row', children: ['titel', 'anzahl'], justify: 'spaceBetween', align: 'center' },
    { id: 'titel', component: 'Text', text: 'Aktuelle Immobilien', variant: 'h3' },
    { id: 'anzahl', component: 'Badge', text: { call: 'formatString', args: { value: '${/anzahl} Objekte' } }, ton: 'info' },
    { id: 'kacheln', component: 'Grid', spalten: 3, children: { path: '/immobilien', componentId: 'kachel' } },
    { id: 'kachel', component: 'Card', child: 'kachel_inhalt' },
    { id: 'kachel_inhalt', component: 'Column', children: ['k_kopf', 'k_ort', 'k_preis', 'k_knoepfe'], gap: 8 },
    { id: 'k_kopf', component: 'Row', children: ['k_titel', 'k_status'], justify: 'spaceBetween' },
    { id: 'k_titel', component: 'Text', text: { path: 'titel' }, variant: 'h5' },
    { id: 'k_status', component: 'Badge', text: { path: 'status' }, ton: 'ok' },
    { id: 'k_ort', component: 'Karte', adresse: { path: 'adresse' } },
    { id: 'k_preis', component: 'Kennzahl', wert: { call: 'formatCurrency', args: { value: { path: 'preis' }, currency: 'EUR', maximumFractionDigits: 0 } }, label: { call: 'formatString', args: { value: '${zimmer} Zimmer · ${flaeche} m²' } } },
    { id: 'k_knoepfe', component: 'Row', children: ['k_expose', 'k_notiz'], wrap: true },
    { id: 'k_expose', component: 'Button', text: 'Exposé', icon: 'open_in_new', variant: 'primary', action: { functionCall: { call: 'openUrl', args: { url: { path: 'link' } } } } },
    { id: 'k_notiz', component: 'Button', text: 'Notiz', icon: 'edit', action: { event: { name: 'notiz_anlegen', context: { objekt_id: { path: 'id' } } } } },
  ],
  daten: {
    anzahl: 3,
    immobilien: [
      { id: 'hafenweg-3', titel: 'Hafenweg 3', status: 'neu', adresse: 'Hafenweg 3, 20457 Hamburg', preis: 425000, zimmer: 3, flaeche: 92, link: 'https://example.org/expose/hafenweg-3' },
      { id: 'elbchaussee-12', titel: 'Elbchaussee 12', status: 'reserviert', adresse: 'Elbchaussee 12, 22763 Hamburg', preis: 1250000, zimmer: 5, flaeche: 168, link: 'https://example.org/expose/elbchaussee-12' },
      { id: 'lindenallee-7', titel: 'Lindenallee 7', status: 'neu', adresse: 'Lindenallee 7, 70176 Stuttgart', preis: 389000, zimmer: 2, flaeche: 64, link: 'https://example.org/expose/lindenallee-7' },
    ],
  },
};

const POSTEINGANG = {
  surfaceId: 'posteingang', titel: 'Posteingang', catalogId: KATALOG, stil: 'neutral', vorlage: 'posteingang',
  components: [
    { id: 'root', component: 'Column', children: ['kopf', 'tabelle'] },
    { id: 'kopf', component: 'Row', children: ['ungelesen', 'wichtig'], gap: 32 },
    { id: 'ungelesen', component: 'Kennzahl', wert: { path: '/ungelesen' }, label: 'ungelesen' },
    { id: 'wichtig', component: 'Kennzahl', wert: { path: '/wichtig' }, label: 'wichtig', trend: 1 },
    { id: 'tabelle', component: 'Tabelle', zeilen: { path: '/mails' }, spalten: [{ titel: 'Von', path: 'von' }, { titel: 'Betreff', path: 'betreff' }, { titel: 'Zeit', path: 'zeit', format: 'datum' }, { titel: 'Status', path: 'status', format: 'badge' }], zeilenAktion: { event: { name: 'mail_oeffnen', context: { id: { path: 'id' } } } } },
  ],
  daten: {
    ungelesen: 5, wichtig: 2,
    mails: [
      { id: 'm1', von: 'Lea Schulz', betreff: 'Abendessen Freitag?', zeit: '2026-10-28T17:42:00', status: 'wichtig' },
      { id: 'm2', von: 'GG Immobilien', betreff: 'Neues Objekt: Hafenweg 3', zeit: '2026-10-28T15:10:00', status: 'neu' },
      { id: 'm3', von: 'Stadtwerke', betreff: 'Ihre Abschlagszahlung', zeit: '2026-10-28T09:03:00', status: 'neu' },
    ],
  },
};

const WETTER = {
  surfaceId: 'wetter', titel: 'Wetter Stuttgart', catalogId: KATALOG, stil: 'material-hell', vorlage: 'wetter',
  components: [
    { id: 'root', component: 'Row', children: ['links', 'verlauf'], wrap: true, gap: 24 },
    { id: 'links', component: 'Column', children: ['kopf', 'werte'] },
    { id: 'kopf', component: 'Row', children: ['symbol', 'temp'], align: 'center' },
    { id: 'symbol', component: 'Icon', name: 'sunny', ton: 'warn' },
    { id: 'temp', component: 'Kennzahl', wert: { path: '/temperatur' }, einheit: '°C', label: 'Stuttgart, sonnig' },
    { id: 'werte', component: 'Row', children: ['wind', 'regen'], gap: 24 },
    { id: 'wind', component: 'Kennzahl', wert: 12, einheit: 'km/h', label: 'Wind' },
    { id: 'regen', component: 'Fortschritt', wert: 0.1, label: 'Regenrisiko' },
    { id: 'verlauf', component: 'Diagramm', typ: 'linie', titel: 'Nächste Tage', serien: [{ name: 'Höchstwert °C', path: '/vorhersage' }] },
  ],
  daten: { temperatur: 14, vorhersage: [{ x: 'Do', y: 14 }, { x: 'Fr', y: 12 }, { x: 'Sa', y: 9 }, { x: 'So', y: 11 }, { x: 'Mo', y: 13 }] },
};

let flaechen = [];
const vorlagen = [
  { id: 'immobilienliste', name: 'Immobilienliste', zweck: 'Aktuelle Objekte aus GG als Kacheln', version: 3, versionen: 3, protokollVersion: V, katalogId: KATALOG, datenquelle: { werkzeug: 'gg-immobilien__read_collection', argumente: {}, abbildung: { '/immobilien': '/items' } }, aktionen: { notiz_anlegen: 'gg-notiz', makler_kontaktieren: 'makler' }, stil: null, signatur: { werkzeug: 'gg-immobilien__read_collection', schluessel: ['id', 'preis'] }, erstellt: '2026-10-28T10:00:00', geaendert: '2026-10-28T12:30:00' },
  { id: 'posteingang', name: 'Posteingang', zweck: 'Ungelesene Mails mit Absender, Betreff, Zeit', version: 1, versionen: 1, protokollVersion: V, katalogId: KATALOG, datenquelle: { werkzeug: 'gmail__suchen', argumente: { q: 'is:unread' }, abbildung: { '/mails': '/messages' } }, aktionen: { mail_oeffnen: '' }, stil: 'neutral', signatur: { werkzeug: 'gmail__suchen', schluessel: ['id'] }, erstellt: '2026-10-28T11:00:00', geaendert: '2026-10-28T11:00:00' },
  { id: 'wetter', name: 'Wetter', zweck: 'Temperatur, Wind und Vorhersage eines Orts', version: 1, versionen: 1, protokollVersion: V, katalogId: KATALOG, datenquelle: { werkzeug: 'wetter__vorhersage', argumente: { ort: 'Stuttgart' }, abbildung: {} }, aktionen: {}, stil: 'material-hell', signatur: { werkzeug: 'wetter__vorhersage', schluessel: ['temperatur'] }, erstellt: '2026-10-28T09:00:00', geaendert: '2026-10-28T09:00:00' },
];
const WETTER_STUTTGART = { id: 'wetter-stuttgart', titel: 'Wetter Stuttgart', vorlage: 'wetter', werkzeug: 'wetter__vorhersage', argumente: { ort: 'Stuttgart' }, zaehler: 5, zuletzt: '2026-10-28T18:00:00' };
const WETTER_FRANKFURT = { id: 'wetter-frankfurt', titel: 'Wetter Frankfurt', vorlage: 'wetter', werkzeug: 'wetter__vorhersage', argumente: { ort: 'Frankfurt' }, zaehler: 2, zuletzt: '2026-10-27T08:30:00' };
const POST_UNGELESEN = { id: 'posteingang-ungelesen', titel: 'Posteingang', vorlage: 'posteingang', werkzeug: 'gmail__suchen', argumente: { q: 'is:unread' }, zaehler: 3, zuletzt: '2026-10-28T11:00:00' };
const schnellaktionen = [WETTER_STUTTGART, POST_UNGELESEN, WETTER_FRANKFURT];
const varianten = { wetter: [WETTER_STUTTGART, WETTER_FRANKFURT] };

let rezepte = [
  { id: 'gg-notiz', name: 'notiz_anlegen', art: 'werkzeug', werkzeug: 'gg-immobilien__add_note', argumentAbbildung: { entity_id: 'context.objekt_id' }, risiko: 'aendern', vorlage: 'immobilienliste' },
  { id: 'makler', name: 'makler_kontaktieren', art: 'agent', auftrag: 'Entwurf an den Makler schreiben', risiko: 'kritisch', vorlage: 'immobilienliste' },
  { id: 'gg-detail', name: 'details', art: 'zeigen', werkzeug: 'gg-immobilien__read_item', argumentAbbildung: { entity_id: 'context.objekt_id' }, titel: 'Objekt {objekt_id}', vorlageZiel: 'immobilie-detail', risiko: 'lesen', vorlage: 'immobilienliste' },
];

/** Nachrichten für das Szenario „buehne“ (alle drei Flächen nacheinander). */
export function buehneSzenario() {
  flaechen = [IMMOBILIEN, POSTEINGANG, WETTER];
  return flaechen.flatMap((f) => [
    { typ: 'buehne', nachricht: { version: V, createSurface: { surfaceId: f.surfaceId, catalogId: KATALOG, theme: { stil: f.stil }, titel: f.titel } } },
    { typ: 'buehne', nachricht: { version: V, updateComponents: { surfaceId: f.surfaceId, components: f.components } } },
    { typ: 'buehne', nachricht: { version: V, updateDataModel: { surfaceId: f.surfaceId, path: '/', value: f.daten } } },
  ]).concat([{ typ: 'buehne', nachricht: { version: V, aktionen: { schnell: schnellaktionen, varianten } } }]);
}

/** REST /api/buehne…; gibt [status, daten] oder null (nicht zuständig) zurück. */
export async function buehneAnfrage(p, m, lesen) {
  if (!p.startsWith('/api/buehne')) return null;
  const teil = p.slice('/api/buehne'.length).split('/').filter(Boolean).map(decodeURIComponent);
  if (teil.length === 0 && m === 'GET') {
    // MOCK_BUEHNE_ERSTE=wetter|posteingang: diese Fläche zuerst (für Screenshots).
    const erste = process.env.MOCK_BUEHNE_ERSTE;
    const sortiert = erste ? [...flaechen].sort((a, b) => Number(b.surfaceId === erste) - Number(a.surfaceId === erste)) : flaechen;
    return [200, { flaechen: sortiert, stile, zuordnung, schnellaktionen, varianten }];
  }
  const [art, id, zusatz] = teil;
  if (art === 'vorlagen') {
    if (!id && m === 'GET') return [200, vorlagen];
    const v = vorlagen.find((x) => x.id === id);
    if (!v) return [404, { detail: 'Vorlage nicht gefunden' }];
    if (m === 'GET') return [200, v];
    if (m === 'PUT') return [200, Object.assign(v, await lesen())];
    if (m === 'POST' && zusatz === 'zurueck') return [200, Object.assign(v, { version: Math.max(1, v.version - 1) })];
    if (m === 'DELETE') {
      vorlagen.splice(vorlagen.indexOf(v), 1);
      return [200, { geloescht: true }];
    }
  }
  if (art === 'rezepte') {
    if (!id && m === 'GET') return [200, rezepte];
    if (m === 'DELETE') {
      rezepte = rezepte.filter((r) => r.id !== id);
      return [200, { geloescht: true }];
    }
  }
  if (art === 'stile') {
    if (!id && m === 'GET') return [200, stile];
    if (!id && m === 'POST') {
      const b = await lesen();
      const basis = stile.find((s) => s.id === 'javit-dunkel') ?? stile[0];
      const neu = { ...basis, id: `eigen-${Date.now()}`, name: b.name, quelle: { art: b.quelle?.art ?? 'werte', wert: b.quelle?.wert }, werte: b.quelle?.werte ?? basis.werte, eigen: true };
      stile.push(neu);
      return [200, neu];
    }
    const s = stile.find((x) => x.id === id);
    if (!s) return [404, { detail: 'Stil nicht gefunden' }];
    if (m === 'PUT') {
      const b = await lesen();
      if (s.eigen) return [200, Object.assign(s, b)];
      const kopie = { ...s, ...b, id: `${s.id}-eigen`, eigen: true, quelle: { art: 'werte' } };
      const alt = stile.findIndex((x) => x.id === kopie.id);
      if (alt >= 0) stile[alt] = kopie;
      else stile.push(kopie);
      return [200, kopie];
    }
    if (m === 'DELETE') {
      if (!s.eigen) return [400, { detail: 'Vordefinierte Stile können nicht gelöscht werden' }];
      stile.splice(stile.indexOf(s), 1);
      return [200, { geloescht: true }];
    }
  }
  if (art === 'zuordnung' && m === 'PUT') {
    const b = await lesen();
    zuordnung = Object.fromEntries(Object.entries(b).filter(([, v]) => v));
    return [200, zuordnung];
  }
  if (art === 'aktion' && m === 'POST') return [200, { ok: true }];
  if (art === 'erneut' && m === 'POST') {
    const b = await lesen();
    const f = flaechen.find((x) => x.vorlage === b.vorlage);
    if (!f) return [404, { detail: 'Vorlage nicht gefunden' }];
    return [200, { surfaceId: f.surfaceId, titel: b.titel ?? f.titel, vorlage: b.vorlage, anzahl: 0 }];
  }
  if (art === 'flaechen' && m === 'DELETE') {
    flaechen = flaechen.filter((f) => f.surfaceId !== id);
    return [200, { geschlossen: true }];
  }
  return [404, { detail: 'Nicht gefunden' }];
}
