import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { anfangsZustand, reduzieren, type KernZustand } from '../state/reducer';
import { useJarvis } from '../state/store';
import { EinstellungenAnsicht } from '../views/Settings';
import { TopBar } from '../components/TopBar';

interface Aufruf { methode: string; pfad: string; body: unknown }

const unterhaltungen = [
  { id: 3, titel: 'Neue Unterhaltung', titel_fest: false, erstellt: '2026-10-28T09:00:00', aktualisiert: '2026-10-28T09:00:00', zusammenfassung: null, nachbereitet: null, nachrichten: 0, aktuell: true },
  { id: 2, titel: 'Reise nach Rom', titel_fest: false, erstellt: '2026-10-27T10:00:00', aktualisiert: '2026-10-27T11:30:00', zusammenfassung: 'Reise nach Rom im Mai geplant.', nachbereitet: '2026-10-28T09:00:00', nachrichten: 8, aktuell: false },
];

function fetchAttrappe(aufrufe: Aufruf[]) {
  let liste = [...unterhaltungen];
  let automatisch = true;
  const romVerlauf = [{ rolle: 'nutzer', inhalt: 'Rom im Mai?', zeit: '2026-10-27T10:00:00' }, { rolle: 'jarvis', inhalt: 'Sehr schön.', zeit: '2026-10-27T10:00:05' }];
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const pfad = String(input);
    const methode = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    aufrufe.push({ methode, pfad, body });
    const json = (d: unknown, status = 200) => new Response(JSON.stringify(d), { status, headers: { 'Content-Type': 'application/json' } });
    if (pfad === '/api/unterhaltungen' && methode === 'GET') return json(liste);
    if (pfad === '/api/unterhaltungen' && methode === 'POST') {
      const neu = { ...unterhaltungen[0]!, id: 9, titel: (body as { titel?: string })?.titel ?? 'Neue Unterhaltung', aktuell: true };
      liste = [neu, ...liste.map((u) => ({ ...u, aktuell: false }))];
      return json(neu);
    }
    if (pfad === '/api/unterhaltungen/2/aktivieren') {
      liste = liste.map((u) => ({ ...u, aktuell: u.id === 2 }));
      return json(liste.find((u) => u.id === 2));
    }
    if (pfad === '/api/unterhaltungen/2' && methode === 'PUT') {
      liste = liste.map((u) => (u.id === 2 ? { ...u, titel: (body as { titel: string }).titel, titel_fest: true } : u));
      return json(liste.find((u) => u.id === 2));
    }
    if (pfad === '/api/unterhaltungen/2' && methode === 'DELETE') {
      liste = liste.filter((u) => u.id !== 2);
      return json({ geloescht: true, aktuell: liste[0] });
    }
    if (pfad === '/api/unterhaltungen/2/verlauf') return json(romVerlauf);
    // /api/verlauf liefert die aktuelle Unterhaltung des Kerns
    if (pfad.startsWith('/api/verlauf')) return json(liste.find((u) => u.aktuell)?.id === 2 ? romVerlauf : []);
    if (pfad === '/api/gedaechtnis' && methode === 'GET') return json([{ id: 1, text: 'Der Nutzer mag Italien.', zeit: '2026-10-27T11:30:00', quelle: 'auto' }, { id: 2, text: 'Trinkt Espresso.', zeit: '2026-10-20T08:00:00', quelle: 'nutzer' }]);
    if (pfad.startsWith('/api/gedaechtnis?id=') && methode === 'DELETE') return json({ geloescht: 1 });
    if (pfad === '/api/einstellungen' && methode === 'PUT') {
      automatisch = (body as { gedaechtnis_automatisch: boolean }).gedaechtnis_automatisch;
      return json({ gedaechtnis_automatisch: automatisch });
    }
    if (pfad === '/api/einstellungen') return json({ modell: 'ollama/x', anbieter_eigene: [], verzeichnisse_eigene: [], gedaechtnis_automatisch: automatisch, stimme: { aktiv: false } });
    if (pfad.startsWith('/api/modelle')) return json({ aktuell: 'ollama/x', anbieter: [], vorschlaege: [] });
    if (pfad === '/api/status') return json({ version: '1', modell: 'x', stimme: { aktiv: false, weckwort: 'javit', hoert: false }, integrationen: 0, werkzeuge: 0, unterhaltung: { id: 3, titel: 'Neue Unterhaltung' } });
    return json({ ok: true });
  });
}

describe('Unterhaltungen – Reducer', () => {
  it('Wechsel leert die Konsole, Titeländerung nicht', () => {
    const s: KernZustand = {
      ...anfangsZustand,
      unterhaltung: { id: 1, titel: 'Alt' },
      nachrichten: [{ id: 'n1', rolle: 'nutzer', text: 'hallo', fertig: true, zeit: 1 }],
      aktiveAntwort: 'a1',
    };
    const t = reduzieren(s, { typ: 'unterhaltung', id: 1, titel: 'Alt mit Titel', grund: 'titel' });
    expect(t.nachrichten).toHaveLength(1);
    expect(t.unterhaltung).toEqual({ id: 1, titel: 'Alt mit Titel' });
    const w = reduzieren(s, { typ: 'unterhaltung', id: 2, titel: 'Neu', grund: 'neu' });
    expect(w.nachrichten).toEqual([]);
    expect(w.aktiveAntwort).toBeNull();
    expect(w.unterhaltung).toEqual({ id: 2, titel: 'Neu' });
    // Danach darf der geladene Verlauf die leere Konsole füllen
    const v = reduzieren(w, { typ: 'lokal_verlauf', nachrichten: [{ id: 'v1', rolle: 'jarvis', text: 'x', fertig: true, zeit: 2 }] });
    expect(v.nachrichten).toHaveLength(1);
    const l = reduzieren(anfangsZustand, { typ: 'lokal_unterhaltung', id: 5, titel: 'Fünf' });
    expect(l.unterhaltung).toEqual({ id: 5, titel: 'Fünf' });
  });
});

describe('Unterhaltungen – Oberfläche', () => {
  let aufrufe: Aufruf[];
  beforeEach(() => {
    aufrufe = [];
    vi.stubGlobal('fetch', fetchAttrappe(aufrufe));
    useJarvis.setState({ ...anfangsZustand, ansicht: 'konsole', unterhaltung: { id: 3, titel: 'Neue Unterhaltung' } });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('Kopfzeile: Titel und Knopf „Neue Unterhaltung“ legt per POST an', async () => {
    const u = userEvent.setup();
    render(<TopBar />);
    expect(screen.getByTitle('Aktuelle Unterhaltung')).toHaveTextContent('Neue Unterhaltung');
    await u.click(screen.getByRole('button', { name: 'Neue Unterhaltung' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'POST', pfad: '/api/unterhaltungen', body: {} }));
    await waitFor(() => expect(useJarvis.getState().unterhaltung?.id).toBe(9));
  });

  it('Einstellungen: Liste, Öffnen, Umbenennen, Löschen', async () => {
    const u = userEvent.setup();
    useJarvis.setState({ ansicht: 'einstellungen' });
    render(<EinstellungenAnsicht />);
    const liste = await screen.findByRole('list', { name: 'Unterhaltungen' });
    const rom = within(liste).getByRole('button', { name: 'Reise nach Rom öffnen' });
    expect(rom).toHaveTextContent('8 Nachrichten');
    expect(rom).toHaveTextContent('Reise nach Rom im Mai geplant.');
    expect(within(liste).getByRole('button', { name: 'Neue Unterhaltung öffnen' })).toHaveTextContent('aktuell');

    await u.click(within(liste).getByRole('button', { name: 'Reise nach Rom umbenennen' }));
    const feld = screen.getByLabelText('Neuer Titel');
    await u.clear(feld);
    await u.type(feld, 'Rom im Mai{Enter}');
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/unterhaltungen/2', body: { titel: 'Rom im Mai' } }));
    await screen.findByRole('button', { name: 'Rom im Mai öffnen' });

    await u.click(screen.getByRole('button', { name: 'Rom im Mai öffnen' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'POST', pfad: '/api/unterhaltungen/2/aktivieren', body: undefined }));
    await waitFor(() => expect(useJarvis.getState().ansicht).toBe('konsole'));
    expect(useJarvis.getState().unterhaltung).toEqual({ id: 2, titel: 'Rom im Mai' });
    await waitFor(() => expect(useJarvis.getState().nachrichten.map((n) => n.text)).toEqual(['Rom im Mai?', 'Sehr schön.']));

    await u.click(screen.getByRole('button', { name: 'Rom im Mai löschen' }));
    await u.click(screen.getByRole('button', { name: 'Ja, löschen' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'DELETE', pfad: '/api/unterhaltungen/2', body: undefined }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Rom im Mai öffnen' })).not.toBeInTheDocument());
  });

  it('Gedächtnis: Herkunft, einzeln löschen, automatisch merken umschalten', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    const eintrag = (await screen.findByText('Der Nutzer mag Italien.')).closest('li')!;
    expect(within(eintrag).getByText('automatisch')).toBeInTheDocument();
    expect(screen.getByText('Trinkt Espresso.').closest('li')!).toHaveTextContent('von Ihnen');
    await u.click(within(eintrag).getByRole('button', { name: 'Erinnerung löschen: Der Nutzer mag Italien.' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'DELETE', pfad: '/api/gedaechtnis?id=1', body: undefined }));
    const schalter = await screen.findByRole('switch', { name: /Automatisch merken/ });
    expect(schalter).toBeChecked();
    await u.click(schalter);
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/einstellungen', body: { gedaechtnis_automatisch: false } }));
  });
});
