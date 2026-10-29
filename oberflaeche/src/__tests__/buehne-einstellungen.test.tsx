import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BuehneEinstellungen } from '../views/BuehneEinstellungen';
import { EinstellungenAnsicht } from '../views/Settings';
import { STANDARD_STIL } from '../buehne/stile';
import { useBuehne } from '../buehne/store';
import type { Rezept, Stil, Vorlage } from '../api/types';

interface Aufruf { methode: string; pfad: string; body: unknown }

const EIGEN: Stil = { ...STANDARD_STIL, id: 'mein-stil', name: 'Mein Stil', quelle: { art: 'werte' }, eigen: true };
const VORDEF: Stil = { ...STANDARD_STIL, eigen: false };
const VORLAGE: Vorlage = {
  id: 'immobilienliste', name: 'Immobilienliste', zweck: 'Aktuelle Objekte aus GG', version: 2, versionen: 2, protokollVersion: 'v0.9.1', katalogId: 'jarvis:buehne/1',
  datenquelle: { werkzeug: 'gg__read_collection', argumente: {}, abbildung: { '/immobilien': '/items' } },
  aktionen: { notiz_anlegen: 'gg-notiz', details: 'gg-detail' }, stil: null, signatur: { werkzeug: 'gg__read_collection', schluessel: ['id'] }, erstellt: '2026-10-28T10:00:00', geaendert: '2026-10-28T11:00:00',
};
const ZEIGEN: Rezept = { id: 'gg-detail', name: 'details', art: 'zeigen', werkzeug: 'gg__read_item', titel: 'Objekt {objekt_id}', risiko: 'lesen', vorlage: 'immobilienliste' };
const REZEPT: Rezept = { id: 'gg-notiz', name: 'notiz_anlegen', art: 'werkzeug', werkzeug: 'gg__add_note', risiko: 'aendern', vorlage: 'immobilienliste' };

function fetchAttrappe(aufrufe: Aufruf[]) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const pfad = String(input);
    const methode = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    aufrufe.push({ methode, pfad, body });
    const json = (d: unknown) => new Response(JSON.stringify(d), { status: 200, headers: { 'Content-Type': 'application/json' } });
    if (methode === 'GET') {
      if (pfad.startsWith('/api/modelle')) return json({ aktuell: 'ollama/x', vorschlaege: [], anbieter: [] });
      if (pfad === '/api/buehne/vorlagen') return json([VORLAGE]);
      if (pfad === '/api/buehne/rezepte') return json([REZEPT, ZEIGEN]);
      if (pfad === '/api/buehne/stile') return json([VORDEF, EIGEN]);
      if (pfad === '/api/buehne') return json({ flaechen: [], stile: [VORDEF, EIGEN], zuordnung: { gg: 'mein-stil' } });
      if (pfad === '/api/integrationen')
        return json([
          { id: 'gg', name: 'GG Immobilien', art: 'mcp', status: 'verbunden', werkzeuge: 4 },
          { id: 'gmail', name: 'Gmail', art: 'mcp', status: 'verbunden', werkzeuge: 6 },
        ]);
    }
    if (pfad === '/api/buehne/stile' && methode === 'POST') return json({ ...EIGEN, id: 'neu', name: body.name, quelle: body.quelle });
    if (pfad.startsWith('/api/buehne/stile/') && methode === 'PUT') return json({ ...VORDEF, id: 'javit-dunkel-eigen', eigen: true, ...body });
    if (pfad === '/api/buehne/zuordnung') return json(Object.fromEntries(Object.entries(body as Record<string, string | null>).filter(([, v]) => v)));
    if (pfad.startsWith('/api/buehne/vorlagen/') && methode === 'PUT') return json({ ...VORLAGE, ...body });
    if (pfad.endsWith('/zurueck')) return json({ ...VORLAGE, version: 1 });
    return json({ geloescht: true });
  });
}

describe('Einstellungen → Bühne', () => {
  let aufrufe: Aufruf[];
  beforeEach(() => {
    aufrufe = [];
    localStorage.clear();
    useBuehne.getState().zuruecksetzen();
    vi.stubGlobal('fetch', fetchAttrappe(aufrufe));
  });
  afterEach(() => vi.unstubAllGlobals());

  it('ist als Reiter erreichbar', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    await u.click(screen.getByRole('tab', { name: 'Bühne' }));
    expect(await screen.findByRole('heading', { name: 'Vorlagen' })).toBeInTheDocument();
  });

  it('Vorlagen: Anzeige, umbenennen, Stil, Version zurück, Rezepte und löschen', async () => {
    const u = userEvent.setup();
    render(<BuehneEinstellungen />);
    const eintrag = await screen.findByRole('listitem', { name: 'Immobilienliste' });
    expect(within(eintrag).getByText('Aktuelle Objekte aus GG')).toBeInTheDocument();
    expect(within(eintrag).getByText('gg__read_collection')).toBeInTheDocument();
    expect(within(eintrag).getByText(/Version 2/)).toBeInTheDocument();
    expect(within(eintrag).getByText('notiz_anlegen')).toBeInTheDocument();
    expect(within(eintrag).getByText(/gg__add_note/)).toBeInTheDocument();
    expect(within(eintrag).getByText('→ Zeigen: gg__read_item → Objekt {objekt_id}', { normalizer: (t) => t.trim() })).toBeInTheDocument();

    await u.click(within(eintrag).getByRole('button', { name: 'Umbenennen' }));
    const feld = within(eintrag).getByLabelText('Neuer Name');
    await u.clear(feld);
    await u.type(feld, 'Objekte{Enter}');
    expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/buehne/vorlagen/immobilienliste', body: { name: 'Objekte' } });

    const stilWahl = await screen.findByRole('combobox', { name: /Stil der Vorlage/ });
    await waitFor(() => expect(within(stilWahl).getByRole('option', { name: 'Mein Stil' })).toBeInTheDocument());
    await u.selectOptions(stilWahl, 'mein-stil');
    expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/buehne/vorlagen/immobilienliste', body: { stil: 'mein-stil' } });

    await u.click(screen.getByRole('button', { name: 'Version zurück' }));
    expect(aufrufe).toContainEqual({ methode: 'POST', pfad: '/api/buehne/vorlagen/immobilienliste/zurueck', body: undefined });

    await u.click(screen.getByRole('button', { name: 'Rezept „notiz_anlegen“ löschen' }));
    expect(aufrufe).toContainEqual({ methode: 'DELETE', pfad: '/api/buehne/rezepte/gg-notiz', body: undefined });

    await u.click(screen.getByRole('button', { name: 'Vorlage löschen' }));
    expect(aufrufe.some((a) => a.methode === 'DELETE' && a.pfad.startsWith('/api/buehne/vorlagen/'))).toBe(false);
    await u.click(screen.getByRole('button', { name: 'Wirklich löschen' }));
    expect(aufrufe).toContainEqual({ methode: 'DELETE', pfad: '/api/buehne/vorlagen/immobilienliste', body: undefined });
  });

  it('Stil bearbeiten: Farbwähler und Hex, Kontrastprüfung, Speichern per PUT', async () => {
    const u = userEvent.setup();
    render(<BuehneEinstellungen />);
    const eintrag = await screen.findByRole('listitem', { name: 'Javit dunkel' });
    expect(within(eintrag).getByText('vordefiniert')).toBeInTheDocument();
    expect(within(eintrag).queryByRole('button', { name: 'Löschen' })).toBeNull();
    expect(within(eintrag).getByLabelText('Vorschau Javit dunkel')).toBeInTheDocument();
    await u.click(within(eintrag).getByRole('button', { name: 'Bearbeiten' }));

    const editor = screen.getByRole('form', { name: 'Stil bearbeiten' });
    const hex = within(editor).getByLabelText('Primär (Hex)');
    await u.clear(hex);
    await u.type(hex, '#123456');
    expect(within(editor).getByLabelText('Primär (Farbwähler)')).toHaveValue('#123456');
    expect(within(editor).getByText(/Kontrast Text\/Hintergrund/)).toBeInTheDocument();
    expect(within(editor).queryByText(/unter 4,5/)).toBeNull();

    const textHex = within(editor).getByLabelText('Text (Hex)');
    await u.clear(textHex);
    await u.type(textHex, '#101820');
    expect(within(editor).getByText(/unter 4,5/)).toBeInTheDocument();
    await u.clear(textHex);
    await u.type(textHex, '#e2fbff');

    await u.click(within(within(editor).getByRole('radiogroup', { name: 'Dichte' })).getByRole('radio', { name: 'Dicht' }));
    await u.click(within(editor).getByRole('button', { name: 'Als Kopie speichern' }));
    const put = aufrufe.find((a) => a.methode === 'PUT' && a.pfad === '/api/buehne/stile/javit-dunkel');
    expect(put?.body).toMatchObject({ name: 'Javit dunkel', werte: { dichte: 'dicht', farben: { primaer: '#123456', text: '#e2fbff' } } });
    expect(await screen.findByText('Stil „Javit dunkel“ gespeichert.')).toBeInTheDocument();
  });

  it('Eigenen Stil als neuen speichern und löschen', async () => {
    const u = userEvent.setup();
    render(<BuehneEinstellungen />);
    const eintrag = await screen.findByRole('listitem', { name: 'Mein Stil' });
    await u.click(within(eintrag).getByRole('button', { name: 'Bearbeiten' }));
    const editor = screen.getByRole('form', { name: 'Stil bearbeiten' });
    await u.clear(within(editor).getByLabelText('Name'));
    await u.type(within(editor).getByLabelText('Name'), 'Kopie');
    await u.click(within(editor).getByRole('button', { name: 'Als neuen Stil speichern' }));
    const post = aufrufe.find((a) => a.methode === 'POST' && a.pfad === '/api/buehne/stile');
    expect(post?.body).toMatchObject({ name: 'Kopie', quelle: { art: 'werte', werte: { schema: 'dunkel' } } });

    await u.click(within(await screen.findByRole('listitem', { name: 'Mein Stil' })).getByRole('button', { name: 'Löschen' }));
    expect(aufrufe).toContainEqual({ methode: 'DELETE', pfad: '/api/buehne/stile/mein-stil', body: undefined });
  });

  it('Stil aus URL ableiten, aus Klassen und aus einer Datei', async () => {
    const u = userEvent.setup();
    render(<BuehneEinstellungen />);
    const form = await screen.findByRole('form', { name: 'Stil ableiten' });
    await u.type(within(form).getByLabelText('Name des Stils'), 'GG Immo');
    await u.type(within(form).getByLabelText('Adresse (https)'), 'https://gg-immobilienhandel-test.vercel.app');
    await u.click(within(form).getByRole('button', { name: 'Stil ableiten' }));
    expect(aufrufe).toContainEqual({ methode: 'POST', pfad: '/api/buehne/stile', body: { name: 'GG Immo', quelle: { art: 'url', wert: 'https://gg-immobilienhandel-test.vercel.app' } } });
    expect(await within(form).findByText(/„GG Immo“ angelegt/)).toBeInTheDocument();

    await u.click(within(within(form).getByRole('radiogroup', { name: 'Quelle' })).getByRole('radio', { name: 'Klassen einfügen' }));
    await u.type(within(form).getByLabelText('Name des Stils'), 'Tailwind');
    await u.type(within(form).getByLabelText('Klassen oder CSS'), '.btn-primary {{ color: #0055ff }');
    await u.click(within(form).getByRole('button', { name: 'Stil ableiten' }));
    expect(aufrufe.filter((a) => a.methode === 'POST').at(-1)?.body).toEqual({ name: 'Tailwind', quelle: { art: 'klassen', wert: '.btn-primary { color: #0055ff }' } });

    await u.click(within(within(form).getByRole('radiogroup', { name: 'Quelle' })).getByRole('radio', { name: 'Datei hochladen' }));
    await u.type(within(form).getByLabelText('Name des Stils'), 'Datei');
    await u.upload(within(form).getByLabelText('Datei'), new File([':root { --primary: #ff0000 }'], 'stil.css', { type: 'text/css' }));
    await u.click(within(form).getByRole('button', { name: 'Stil ableiten' }));
    await waitFor(() => expect(aufrufe.filter((a) => a.methode === 'POST').at(-1)?.body).toMatchObject({ name: 'Datei', quelle: { art: 'datei', wert: 'stil.css' } }));
    const quelle = (aufrufe.filter((a) => a.methode === 'POST').at(-1)?.body as { quelle: { inhalt_base64: string } }).quelle;
    expect(atob(quelle.inhalt_base64)).toBe(':root { --primary: #ff0000 }');
  });

  it('Zuordnung Integration → Stil per PUT', async () => {
    const u = userEvent.setup();
    render(<BuehneEinstellungen />);
    const gg = await screen.findByRole('combobox', { name: 'Stil der Integration „GG Immobilien“' });
    await waitFor(() => expect(gg).toHaveValue('mein-stil'));
    await u.selectOptions(screen.getByRole('combobox', { name: 'Stil der Integration „Gmail“' }), 'javit-dunkel');
    expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/buehne/zuordnung', body: { gg: 'mein-stil', gmail: 'javit-dunkel' } });
    await u.selectOptions(gg, '');
    expect(aufrufe.at(-1)).toEqual({ methode: 'PUT', pfad: '/api/buehne/zuordnung', body: { gg: null, gmail: 'javit-dunkel' } });
  });
});
