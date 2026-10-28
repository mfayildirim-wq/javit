import { beforeEach, describe, expect, it } from 'vitest';
import { HOEHE_STANDARD, hoeheLaden, useBuehne } from '../buehne/store';
import type { A2uiNachricht, Stil } from '../api/types';
import { STANDARD_STIL } from '../buehne/stile';

const V = 'v0.9.1';
const n = (x: Omit<A2uiNachricht, 'version'>): A2uiNachricht => ({ version: V, ...x });
const s = () => useBuehne.getState();

describe('Bühnen-Store', () => {
  beforeEach(() => {
    localStorage.clear();
    useBuehne.getState().zuruecksetzen();
  });

  it('createSurface legt eine Fläche an und macht sie aktiv', () => {
    s().verarbeiten(n({ createSurface: { surfaceId: 'immobilien', catalogId: 'jarvis:buehne/1', theme: { stil: 'papier' }, titel: 'Immobilien' } }));
    s().verarbeiten(n({ createSurface: { surfaceId: 'wetter', titel: 'Wetter' } }));
    expect(s().reihenfolge).toEqual(['immobilien', 'wetter']);
    expect(s().aktiv).toBe('wetter');
    expect(s().flaechen.immobilien).toMatchObject({ titel: 'Immobilien', stil: 'papier', catalogId: 'jarvis:buehne/1', daten: {} });
    expect(s().flaechen.wetter?.stil).toBe('javit-dunkel');
  });

  it('puffert Komponenten, bis root vorhanden ist', () => {
    s().verarbeiten(n({ createSurface: { surfaceId: 'f', titel: 'F' } }));
    s().verarbeiten(n({ updateComponents: { surfaceId: 'f', components: [{ id: 'titel', component: 'Text', text: 'Hallo' }] } }));
    expect(s().flaechen.f?.komponenten).toEqual({});
    expect(s().flaechen.f?.puffer).toHaveLength(1);
    s().verarbeiten(n({ updateComponents: { surfaceId: 'f', components: [{ id: 'root', component: 'Column', children: ['titel'] }] } }));
    expect(Object.keys(s().flaechen.f?.komponenten ?? {}).sort()).toEqual(['root', 'titel']);
    expect(s().flaechen.f?.puffer).toHaveLength(0);
    // Danach direkte Aktualisierung einzelner Komponenten
    s().verarbeiten(n({ updateComponents: { surfaceId: 'f', components: [{ id: 'titel', component: 'Text', text: 'Neu' }] } }));
    expect(s().flaechen.f?.komponenten.titel?.text).toBe('Neu');
  });

  it('updateComponents ohne createSurface legt die Fläche an', () => {
    s().verarbeiten(n({ updateComponents: { surfaceId: 'x', components: [{ id: 'root', component: 'Text', text: 'a' }] } }));
    expect(s().flaechen.x?.titel).toBe('x');
  });

  it('updateDataModel: "/" ersetzt alles, Pfad setzt, ohne value löscht', () => {
    s().verarbeiten(n({ createSurface: { surfaceId: 'f', titel: 'F' } }));
    s().verarbeiten(n({ updateDataModel: { surfaceId: 'f', path: '/', value: { a: 1, liste: [{ x: 1 }] } } }));
    expect(s().flaechen.f?.daten).toEqual({ a: 1, liste: [{ x: 1 }] });
    s().verarbeiten(n({ updateDataModel: { surfaceId: 'f', path: '/liste/0/x', value: 5 } }));
    expect(s().flaechen.f?.daten).toEqual({ a: 1, liste: [{ x: 5 }] });
    s().verarbeiten(n({ updateDataModel: { surfaceId: 'f', path: '/a' } }));
    expect(s().flaechen.f?.daten).toEqual({ liste: [{ x: 5 }] });
    s().verarbeiten(n({ updateDataModel: { surfaceId: 'f', path: '/', value: 'kein Objekt' } }));
    expect(s().flaechen.f?.daten).toEqual({});
  });

  it('deleteSurface entfernt die Fläche und wählt eine andere aktive', () => {
    s().verarbeiten(n({ createSurface: { surfaceId: 'a', titel: 'A' } }));
    s().verarbeiten(n({ createSurface: { surfaceId: 'b', titel: 'B' } }));
    s().verarbeiten(n({ deleteSurface: { surfaceId: 'b' } }));
    expect(s().flaechen.b).toBeUndefined();
    expect(s().reihenfolge).toEqual(['a']);
    expect(s().aktiv).toBe('a');
    s().verarbeiten(n({ deleteSurface: { surfaceId: 'a' } }));
    expect(s().aktiv).toBeNull();
  });

  it('stil-Nachricht ergänzt die Stile', () => {
    const papier: Stil = { ...STANDARD_STIL, id: 'papier', name: 'Papier' };
    s().verarbeiten(n({ stil: papier }));
    expect(s().stile.papier?.name).toBe('Papier');
  });

  it('datenSetzen schreibt lokal in das Datenmodell', () => {
    s().verarbeiten(n({ createSurface: { surfaceId: 'f', titel: 'F' } }));
    s().datenSetzen('f', '/filter/suche', 'Hamburg');
    expect(s().flaechen.f?.daten).toEqual({ filter: { suche: 'Hamburg' } });
    s().datenSetzen('gibtsnicht', '/x', 1);
    expect(s().flaechen.gibtsnicht).toBeUndefined();
  });

  it('ausServer übernimmt Flächen und Stile von GET /api/buehne', () => {
    s().ausServer(
      [{ surfaceId: 'mails', titel: 'Posteingang', catalogId: 'jarvis:buehne/1', stil: 'neutral', components: [{ id: 'root', component: 'Text', text: 'x' }], daten: { n: 1 }, vorlage: 'posteingang' }],
      [{ ...STANDARD_STIL, id: 'neutral', name: 'Neutral' }],
    );
    expect(s().reihenfolge).toEqual(['mails']);
    expect(s().aktiv).toBe('mails');
    expect(s().flaechen.mails).toMatchObject({ titel: 'Posteingang', stil: 'neutral', vorlage: 'posteingang', daten: { n: 1 } });
    expect(s().flaechen.mails?.komponenten.root?.component).toBe('Text');
    expect(s().stile.neutral?.name).toBe('Neutral');
  });

  it('Höhe wird begrenzt und in localStorage gemerkt', () => {
    expect(hoeheLaden()).toBe(HOEHE_STANDARD);
    s().hoeheSetzen(0.95);
    expect(s().hoehe).toBe(0.8);
    expect(localStorage.getItem('jarvis.buehne.hoehe')).toBe('0.8');
    s().hoeheSetzen(0.1);
    expect(s().hoehe).toBe(0.2);
    localStorage.setItem('jarvis.buehne.hoehe', 'unsinn');
    expect(hoeheLaden()).toBe(0.45);
    localStorage.setItem('jarvis.buehne.hoehe', '0.6');
    expect(hoeheLaden()).toBe(0.6);
  });

  it('stilSetzen und flaecheEntfernen wirken lokal', () => {
    s().verarbeiten(n({ createSurface: { surfaceId: 'f', titel: 'F' } }));
    s().stilSetzen('f', 'kontrast');
    expect(s().flaechen.f?.stil).toBe('kontrast');
    s().flaecheEntfernen('f');
    expect(s().reihenfolge).toEqual([]);
  });
});
