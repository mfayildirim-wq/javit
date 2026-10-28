import { describe, expect, it } from 'vitest';
import { anfangsZustand, reduzieren, type Aktion, type KernZustand } from '../state/reducer';
import { SERVER_EVENT_TYPEN, type ServerEvent } from '../api/types';

const lauf = (aktionen: Aktion[], start: KernZustand = anfangsZustand, t0 = 1_000_000) =>
  aktionen.reduce((s, a, i) => reduzieren(s, a, t0 + i * 100), start);

describe('Event-Reducer', () => {
  it('zustand: setzt den Orb-Zustand und nullt den Pegel außerhalb von hoert/spricht', () => {
    let s = lauf([{ typ: 'zustand', zustand: 'hoert' }, { typ: 'pegel', wert: 0.7 }]);
    expect(s.zustand).toBe('hoert');
    expect(s.pegel).toBeCloseTo(0.7);
    s = reduzieren(s, { typ: 'zustand', zustand: 'denkt' });
    expect(s.zustand).toBe('denkt');
    expect(s.pegel).toBe(0);
  });

  it('pegel: wird auf 0..1 begrenzt, ungültige Werte werden 0', () => {
    expect(reduzieren(anfangsZustand, { typ: 'pegel', wert: 1.8 }).pegel).toBe(1);
    expect(reduzieren(anfangsZustand, { typ: 'pegel', wert: -2 }).pegel).toBe(0);
    expect(reduzieren(anfangsZustand, { typ: 'pegel', wert: Number.NaN }).pegel).toBe(0);
  });

  it('transkript: Zwischenstände live, final wird Nutzernachricht', () => {
    let s = lauf([
      { typ: 'zustand', zustand: 'hoert' },
      { typ: 'transkript', text: 'Wie ist', final: false },
      { typ: 'transkript', text: 'Wie ist das Wetter', final: false },
    ]);
    expect(s.transkript).toBe('Wie ist das Wetter');
    expect(s.nachrichten).toHaveLength(0);
    s = reduzieren(s, { typ: 'transkript', text: 'Wie ist das Wetter?', final: true });
    expect(s.transkript).toBe('');
    expect(s.nachrichten).toHaveLength(1);
    expect(s.nachrichten[0]).toMatchObject({ rolle: 'nutzer', text: 'Wie ist das Wetter?' });
  });

  it('transkript final doppelt nicht eine soeben getippte Nachricht', () => {
    const s = lauf([
      { typ: 'lokal_gesendet', text: 'Hallo Jarvis' },
      { typ: 'transkript', text: 'Hallo Jarvis', final: true },
    ]);
    expect(s.nachrichten).toHaveLength(1);
  });

  it('antwort_start/antwort_text/antwort_ende: streamt in eine Nachricht', () => {
    let s = lauf([
      { typ: 'antwort_start', id: 'a1' },
      { typ: 'antwort_text', id: 'a1', delta: 'Guten ' },
      { typ: 'antwort_text', id: 'a1', delta: 'Abend' },
    ]);
    expect(s.aktiveAntwort).toBe('a1');
    expect(s.nachrichten).toEqual([expect.objectContaining({ id: 'a1', rolle: 'jarvis', text: 'Guten Abend', fertig: false })]);
    s = reduzieren(s, { typ: 'antwort_ende', id: 'a1', text: 'Guten Abend, Sir.' });
    expect(s.aktiveAntwort).toBeNull();
    expect(s.nachrichten[0]).toMatchObject({ text: 'Guten Abend, Sir.', fertig: true });
  });

  it('antwort_text ohne antwort_start legt die Nachricht trotzdem an', () => {
    const s = reduzieren(anfangsZustand, { typ: 'antwort_text', id: 'x', delta: 'Hi' });
    expect(s.nachrichten[0]).toMatchObject({ id: 'x', text: 'Hi', fertig: false });
  });

  it('antwort_ende mit leerem Text behält den gestreamten Text', () => {
    const s = lauf([
      { typ: 'antwort_start', id: 'a' },
      { typ: 'antwort_text', id: 'a', delta: 'Fertig.' },
      { typ: 'antwort_ende', id: 'a', text: '' },
    ]);
    expect(s.nachrichten[0]?.text).toBe('Fertig.');
  });

  it('werkzeug_start/werkzeug_ende: Zeitleiste mit Dauer, Ergebnis und Fehler', () => {
    const s = lauf([
      { typ: 'werkzeug_start', id: 'w1', name: 'spotify_suchen', argumente: { query: 'Jazz' }, integration: 'spotify' },
      { typ: 'werkzeug_start', id: 'w2', name: 'shell', argumente: { befehl: 'ls' } },
      { typ: 'werkzeug_ende', id: 'w1', ok: true, ergebnis: [{ name: 'Kind of Blue' }] },
      { typ: 'werkzeug_ende', id: 'w2', ok: false, ergebnis: 'Zugriff verweigert' },
    ]);
    expect(s.werkzeuge).toHaveLength(2);
    const [w1, w2] = s.werkzeuge;
    expect(w1).toMatchObject({ name: 'spotify_suchen', integration: 'spotify', ok: true });
    expect(w1!.ende! - w1!.start).toBe(200);
    expect(w2).toMatchObject({ integration: null, ok: false, ergebnis: 'Zugriff verweigert' });
  });

  it('freigabe_noetig: reiht Anfragen ein; werkzeug_ende mit gleicher id räumt sie ab', () => {
    let s = lauf([
      { typ: 'freigabe_noetig', id: 'f1', werkzeug: 'shell_ausfuehren', argumente: { befehl: 'rm x' }, grund: 'Löscht x', risiko: 'kritisch' },
      { typ: 'freigabe_noetig', id: 'f2', werkzeug: 'mail_senden', argumente: {}, grund: 'Sendet', risiko: 'kritisch' },
    ]);
    expect(s.freigaben.map((f) => f.id)).toEqual(['f1', 'f2']);
    expect(s.freigaben[0]?.empfangen).toBe(1_000_000);
    s = reduzieren(s, { typ: 'werkzeug_ende', id: 'f1', ok: false, ergebnis: 'abgelehnt' });
    expect(s.freigaben.map((f) => f.id)).toEqual(['f2']);
    s = reduzieren(s, { typ: 'lokal_freigabe_erledigt', id: 'f2' });
    expect(s.freigaben).toHaveLength(0);
  });

  it('integration_geaendert: erhöht den Stand', () => {
    const s = lauf([{ typ: 'integration_geaendert', integration: { id: 'spotify' } }, { typ: 'integration_geaendert', integration: {} }]);
    expect(s.integrationsStand).toBe(2);
  });

  it('fehler: erzeugt Hinweis und schließt laufende Antwort', () => {
    const s = lauf([
      { typ: 'antwort_start', id: 'a' },
      { typ: 'fehler', text: 'Modell nicht erreichbar' },
    ]);
    expect(s.hinweise.at(-1)?.text).toBe('Modell nicht erreichbar');
    expect(s.aktiveAntwort).toBeNull();
    expect(s.nachrichten[0]?.fertig).toBe(true);
  });

  it('lokal_abgebrochen: beendet laufende Werkzeuge und Freigaben', () => {
    const s = lauf([
      { typ: 'werkzeug_start', id: 'w', name: 'x', argumente: {} },
      { typ: 'freigabe_noetig', id: 'f', werkzeug: 'x', argumente: {}, grund: '', risiko: 'kritisch' },
      { typ: 'lokal_abgebrochen' },
    ]);
    expect(s.freigaben).toHaveLength(0);
    expect(s.werkzeuge[0]).toMatchObject({ ok: false, ergebnis: 'abgebrochen' });
    expect(s.werkzeuge[0]?.ende).not.toBeNull();
  });

  it('deckt jeden Server-Event-Typ aus VERTRAEGE.md ab', () => {
    const beispiele: Record<ServerEvent['typ'], ServerEvent> = {
      zustand: { typ: 'zustand', zustand: 'spricht' },
      pegel: { typ: 'pegel', wert: 0.4 },
      transkript: { typ: 'transkript', text: 'a', final: false },
      antwort_start: { typ: 'antwort_start', id: '1' },
      antwort_text: { typ: 'antwort_text', id: '1', delta: 'x' },
      antwort_ende: { typ: 'antwort_ende', id: '1', text: 'x' },
      werkzeug_start: { typ: 'werkzeug_start', id: 'w', name: 'n', argumente: {} },
      werkzeug_ende: { typ: 'werkzeug_ende', id: 'w', ok: true, ergebnis: null },
      freigabe_noetig: { typ: 'freigabe_noetig', id: 'f', werkzeug: 'n', argumente: {}, grund: 'g', risiko: 'kritisch' },
      integration_geaendert: { typ: 'integration_geaendert', integration: {} },
      oauth_anmeldung: { typ: 'oauth_anmeldung', integration: 'notion', url: 'https://as.example/authorize?state=x' },
      fehler: { typ: 'fehler', text: 'x' },
      unterhaltung: { typ: 'unterhaltung', id: 2, titel: 'Neu', grund: 'neu' },
      sprachausgabe: { typ: 'sprachausgabe', zustand: 'start', rate: 24000 },
      buehne: { typ: 'buehne', nachricht: { version: 'v0.9.1', deleteSurface: { surfaceId: 'x' } } },
    };
    for (const typ of SERVER_EVENT_TYPEN) {
      const vorher = anfangsZustand;
      const nachher = reduzieren(vorher, beispiele[typ]);
      expect(nachher, typ).not.toBe(vorher);
    }
  });
});

describe('oauth_anmeldung', () => {
  it('merkt die laufende Anmeldung und räumt sie auf, sobald die Integration einen Endzustand meldet', () => {
    let s = reduzieren(anfangsZustand, { typ: 'oauth_anmeldung', integration: 'notion', url: 'https://as.example/authorize?state=x' }, 5);
    expect(s.oauthAnmeldung).toEqual({ integration: 'notion', url: 'https://as.example/authorize?state=x', zeit: 5 });
    s = reduzieren(s, { typ: 'integration_geaendert', integration: { id: 'notion', status: 'verbindet' } });
    expect(s.oauthAnmeldung).not.toBeNull();
    s = reduzieren(s, { typ: 'integration_geaendert', integration: { id: 'andere', status: 'verbunden' } });
    expect(s.oauthAnmeldung).not.toBeNull();
    s = reduzieren(s, { typ: 'integration_geaendert', integration: { id: 'notion', status: 'verbunden' } });
    expect(s.oauthAnmeldung).toBeNull();
    s = reduzieren(reduzieren(s, { typ: 'oauth_anmeldung', integration: 'n', url: 'u' }), { typ: 'lokal_oauth_weg' });
    expect(s.oauthAnmeldung).toBeNull();
  });
});
