import { describe, expect, it } from 'vitest';
import {
  formatDate,
  formatString,
  istHttps,
  istSichereBildUrl,
  pfadAufloesen,
  pluralize,
  wertAufloesen,
  zeigerLesen,
  zeigerLoeschen,
  zeigerSetzen,
  zeigerTeile,
} from '../buehne/binder';
import { kontrast, stilVariablen, STANDARD_WERTE } from '../buehne/stile';

const daten = {
  user: { name: 'Fatih' },
  'a/b': { 'm~n': 7 },
  immobilien: [
    { id: 'hafenweg-3', titel: 'Hafenweg 3', preis: 425000, zeit: '2026-10-28T14:05:00' },
    { id: 'elbchaussee', titel: 'Elbchaussee', preis: 1250000.5 },
  ],
  anzahl: 2,
};

describe('JSON-Pointer (RFC 6901)', () => {
  it('zerlegt Pfade inklusive ~0 und ~1', () => {
    expect(zeigerTeile('/')).toEqual([]);
    expect(zeigerTeile('')).toEqual([]);
    expect(zeigerTeile('/a~1b/m~0n')).toEqual(['a/b', 'm~n']);
  });

  it('liest verschachtelte Werte und Array-Indizes', () => {
    expect(zeigerLesen(daten, '/user/name')).toBe('Fatih');
    expect(zeigerLesen(daten, '/a~1b/m~0n')).toBe(7);
    expect(zeigerLesen(daten, '/immobilien/1/titel')).toBe('Elbchaussee');
    expect(zeigerLesen(daten, '/immobilien/9/titel')).toBeUndefined();
    expect(zeigerLesen(daten, '/')).toBe(daten);
  });

  it('setzt unveränderlich und legt Zwischenstufen an', () => {
    const neu = zeigerSetzen(daten, '/filter/suche', 'Hamburg') as Record<string, unknown>;
    expect(neu).not.toBe(daten);
    expect(zeigerLesen(neu, '/filter/suche')).toBe('Hamburg');
    expect((daten as Record<string, unknown>).filter).toBeUndefined();
    const liste = zeigerSetzen(daten, '/immobilien/0/preis', 1) as typeof daten;
    expect(liste.immobilien[0]?.preis).toBe(1);
    expect(daten.immobilien[0]?.preis).toBe(425000);
    expect(liste.immobilien[1]).toBe(daten.immobilien[1]);
    expect(zeigerSetzen(daten, '/', { x: 1 })).toEqual({ x: 1 });
  });

  it('löscht Schlüssel und Array-Elemente', () => {
    const ohne = zeigerLoeschen(daten, '/user/name') as typeof daten;
    expect(ohne.user).toEqual({});
    const kuerzer = zeigerLoeschen(daten, '/immobilien/0') as typeof daten;
    expect(kuerzer.immobilien).toHaveLength(1);
    expect(zeigerLoeschen(daten, '/')).toEqual({});
  });

  it('löst relative Pfade gegen die Basis des Templates auf', () => {
    expect(pfadAufloesen('titel', '/immobilien/1')).toBe('/immobilien/1/titel');
    expect(pfadAufloesen('/anzahl', '/immobilien/1')).toBe('/anzahl');
    expect(pfadAufloesen('.', '/immobilien/1')).toBe('/immobilien/1');
    expect(pfadAufloesen('titel', '')).toBe('/titel');
  });
});

describe('Werte und Client-Funktionen', () => {
  const ctx = { daten, basis: '/immobilien/0' };

  it('Literale bleiben, Bindungen werden gelesen (relativ und absolut)', () => {
    expect(wertAufloesen('Text', ctx)).toBe('Text');
    expect(wertAufloesen(3, ctx)).toBe(3);
    expect(wertAufloesen({ path: 'titel' }, ctx)).toBe('Hafenweg 3');
    expect(wertAufloesen({ path: '/user/name' }, ctx)).toBe('Fatih');
  });

  it('formatString interpoliert ${…} absolut und relativ', () => {
    expect(formatString('${/user/name}, ${/anzahl} Treffer – ${titel}', ctx)).toBe('Fatih, 2 Treffer – Hafenweg 3');
    expect(formatString('Fehlt: ${/gibtsnicht}.', ctx)).toBe('Fehlt: .');
    expect(wertAufloesen({ call: 'formatString', args: { value: 'Hallo ${/user/name}' } }, ctx)).toBe('Hallo Fatih');
  });

  it('formatNumber und formatCurrency nutzen de-DE', () => {
    expect(wertAufloesen({ call: 'formatNumber', args: { value: 1234.567, maximumFractionDigits: 1 } }, ctx)).toBe('1.234,6');
    const preis = wertAufloesen({ call: 'formatCurrency', args: { value: { path: 'preis' }, currency: 'EUR' } }, ctx) as string;
    expect(preis.replace(/\s/g, ' ')).toBe('425.000,00 €');
  });

  it('formatDate mit Muster und ungültigem Datum', () => {
    expect(formatDate('2026-10-28T14:05:00', 'dd.MM.yyyy HH:mm')).toBe('28.10.2026 14:05');
    expect(formatDate('2026-03-04T09:07:00', 'd.M.yy')).toBe('4.3.26');
    expect(formatDate('2026-10-28T14:05:00', 'EEEE, d. MMMM yyyy')).toBe('Mittwoch, 28. Oktober 2026');
    expect(formatDate('kein Datum', 'dd.MM.yyyy')).toBe('kein Datum');
    expect(wertAufloesen({ call: 'formatDate', args: { value: { path: 'zeit' }, pattern: 'HH:mm' } }, ctx)).toBe('14:05');
  });

  it('pluralize wählt die Form nach Anzahl', () => {
    expect(pluralize(1, { one: 'Objekt', other: 'Objekte' })).toBe('Objekt');
    expect(pluralize(2, { one: 'Objekt', other: 'Objekte' })).toBe('Objekte');
    expect(pluralize(0, { zero: 'keine', one: 'Objekt', other: 'Objekte' })).toBe('keine');
    expect(wertAufloesen({ call: 'pluralize', args: { count: { path: '/anzahl' }, one: 'Treffer', other: 'Treffern' } }, ctx)).toBe('Treffern');
  });

  it('Sicherheitsprüfungen für URLs', () => {
    expect(istHttps('https://example.org')).toBe(true);
    expect(istHttps('http://example.org')).toBe(false);
    expect(istHttps('javascript:alert(1)')).toBe(false);
    expect(istSichereBildUrl('data:image/png;base64,AAAA')).toBe(true);
    expect(istSichereBildUrl('data:text/html;base64,AAAA')).toBe(false);
    expect(istSichereBildUrl('http://bild.example/a.png')).toBe(false);
  });
});

describe('Stile', () => {
  it('Stilwerte werden zu --b-*-Variablen', () => {
    const v = stilVariablen(STANDARD_WERTE);
    expect(v['--b-primaer']).toBe('#7fe8ff');
    expect(v['--b-basis']).toBe('14px');
    expect(v['--b-rundung']).toBe('10px');
    expect(v['--b-abstand']).toBe('12px');
    expect(v['--b-dichte']).toBe('1');
    expect(v['--b-schatten']).not.toBe('none');
    for (const n of ['akzent', 'hintergrund', 'flaeche', 'text', 'dezent', 'ok', 'warn', 'fehler', 'schrift']) expect(v[`--b-${n}`]).toBeTruthy();
  });

  it('verwirft ungültige Farben und gefährliche Schriftangaben', () => {
    const v = stilVariablen({
      ...STANDARD_WERTE,
      farben: { ...STANDARD_WERTE.farben, primaer: 'red; background:url(x)' },
      schrift: { familie: 'Arial; } body { display:none', basisgroesse: 99 },
      dichte: 'dicht',
      schatten: 'keiner',
    });
    expect(v['--b-primaer']).toBe(STANDARD_WERTE.farben.primaer);
    expect(v['--b-schrift']).not.toMatch(/[;{}]/);
    expect(v['--b-basis']).toBe('22px');
    expect(Number(v['--b-dichte'])).toBeLessThan(1);
    expect(v['--b-schatten']).toBe('none');
  });

  it('Kontrast nach WCAG', () => {
    expect(kontrast('#000000', '#ffffff')).toBeCloseTo(21, 1);
    expect(kontrast('#fff', '#fff')).toBeCloseTo(1, 5);
    expect(kontrast('#777777', '#ffffff')).toBeCloseTo(4.48, 1);
  });
});
