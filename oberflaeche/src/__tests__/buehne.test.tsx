import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Konsole } from '../components/Konsole';
import { useBuehne } from '../buehne/store';
import { useJarvis } from '../state/store';
import { anfangsZustand } from '../state/reducer';
import { STANDARD_STIL } from '../buehne/stile';
import type { Stil } from '../api/types';

interface Aufruf { methode: string; pfad: string; body: unknown }

const PAPIER: Stil = { ...STANDARD_STIL, id: 'papier', name: 'Papier', werte: { ...STANDARD_STIL.werte, schema: 'hell' } };

function fetchAttrappe(aufrufe: Aufruf[]) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const pfad = String(input);
    const methode = init?.method ?? 'GET';
    aufrufe.push({ methode, pfad, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const json = (d: unknown) => new Response(JSON.stringify(d), { status: 200, headers: { 'Content-Type': 'application/json' } });
    if (pfad === '/api/buehne/stile') return json([STANDARD_STIL, PAPIER]);
    if (pfad === '/api/buehne' && methode === 'GET')
      return json({ flaechen: [{ surfaceId: 'gg-liste', titel: 'GG', catalogId: 'jarvis:buehne/1', stil: 'javit-dunkel', components: [], daten: {}, vorlage: 'gg-liste' }], stile: [], zuordnung: {} });
    return json({ ok: true });
  });
}

function flaecheAnlegen(surfaceId: string, titel: string, text: string, vorlage?: string) {
  const b = useBuehne.getState();
  b.verarbeiten({ version: 'v0.9.1', createSurface: { surfaceId, titel, theme: { stil: 'javit-dunkel' }, ...(vorlage ? { vorlage } : {}) } });
  b.verarbeiten({ version: 'v0.9.1', updateComponents: { surfaceId, components: [{ id: 'root', component: 'Text', text }] } });
}

describe('Bühne in der Konsole', () => {
  let aufrufe: Aufruf[];
  beforeEach(() => {
    aufrufe = [];
    localStorage.clear();
    vi.stubGlobal('fetch', fetchAttrappe(aufrufe));
    useBuehne.getState().zuruecksetzen();
    useJarvis.setState({ ...anfangsZustand, verbindung: 'offen', sender: () => true });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('ohne Flächen keine Bühne, Orb in voller Größe', () => {
    const { container } = render(<Konsole aktiv={false} />);
    expect(screen.queryByRole('region', { name: 'Bühne' })).toBeNull();
    expect(container.querySelector('.orb-buehne')).not.toHaveClass('klein');
  });

  it('Reiter je Fläche, Wechsel und kleiner Orb', async () => {
    const u = userEvent.setup();
    act(() => {
      flaecheAnlegen('immobilien', 'Immobilien', 'Liste der Objekte');
      flaecheAnlegen('wetter', 'Wetter', 'Sonnig, 21 Grad');
    });
    const { container } = render(<Konsole aktiv={false} />);
    const buehne = screen.getByRole('region', { name: 'Bühne' });
    const reiter = within(buehne).getAllByRole('tab');
    expect(reiter.map((r) => r.textContent)).toEqual(['Immobilien', 'Wetter']);
    expect(within(buehne).getByRole('tab', { name: 'Wetter' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Sonnig, 21 Grad')).toBeInTheDocument();
    await u.click(within(buehne).getByRole('tab', { name: 'Immobilien' }));
    expect(screen.getByText('Liste der Objekte')).toBeInTheDocument();
    expect(screen.queryByText('Sonnig, 21 Grad')).toBeNull();
    expect(container.querySelector('.orb-buehne')).toHaveClass('klein');
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('Schließen entfernt die Fläche und meldet es dem Kern', async () => {
    const u = userEvent.setup();
    act(() => {
      flaecheAnlegen('immobilien', 'Immobilien', 'A');
      flaecheAnlegen('wetter', 'Wetter', 'B');
    });
    render(<Konsole aktiv={false} />);
    await u.click(screen.getByRole('button', { name: 'Fläche „Wetter“ schließen' }));
    expect(screen.queryByRole('tab', { name: 'Wetter' })).toBeNull();
    expect(aufrufe).toContainEqual({ methode: 'DELETE', pfad: '/api/buehne/flaechen/wetter', body: undefined });
    await u.click(screen.getByRole('button', { name: 'Fläche „Immobilien“ schließen' }));
    expect(screen.queryByRole('region', { name: 'Bühne' })).toBeNull();
  });

  it('Stil-Menü: mit Vorlage per PUT, ohne Vorlage nur lokal', async () => {
    const u = userEvent.setup();
    act(() => flaecheAnlegen('immobilien', 'Immobilien', 'A', 'immobilienliste'));
    const { container } = render(<Konsole aktiv={false} />);
    const menue = await screen.findByRole('combobox', { name: 'Stil der Fläche' });
    await waitFor(() => expect(within(menue).getByRole('option', { name: 'Papier' })).toBeInTheDocument());
    await u.selectOptions(menue, 'papier');
    expect(useBuehne.getState().flaechen.immobilien?.stil).toBe('papier');
    expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/buehne/vorlagen/immobilienliste', body: { stil: 'papier' } });
    expect(container.querySelector('.buehne-flaeche')).toHaveAttribute('data-schema', 'hell');

    act(() => flaecheAnlegen('frei', 'Frei', 'B'));
    await u.selectOptions(screen.getByRole('combobox', { name: 'Stil der Fläche' }), 'papier');
    expect(useBuehne.getState().flaechen.frei?.stil).toBe('papier');
    expect(aufrufe.filter((a) => a.methode === 'PUT')).toHaveLength(1);

    // Vorlage nicht in createSurface genannt, aber im Stand des Kerns bekannt → PUT an diese Vorlage.
    act(() => flaecheAnlegen('gg-liste', 'GG', 'C'));
    await u.selectOptions(screen.getByRole('combobox', { name: 'Stil der Fläche' }), 'papier');
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/buehne/vorlagen/gg-liste', body: { stil: 'papier' } }));
    expect(useBuehne.getState().flaechen['gg-liste']?.vorlage).toBe('gg-liste');
  });

  it('Höhe per Tastatur und Ziehen am Teiler, gemerkt', () => {
    act(() => flaecheAnlegen('wetter', 'Wetter', 'B'));
    const { container } = render(<Konsole aktiv={false} />);
    const teiler = screen.getByRole('separator', { name: 'Höhe der Bühne' });
    expect(teiler).toHaveAttribute('aria-valuenow', '45');
    expect((container.querySelector('.buehne-oben') as HTMLElement).style.flexBasis).toBe('45%');
    fireEvent.keyDown(teiler, { key: 'ArrowDown' });
    expect(useBuehne.getState().hoehe).toBeCloseTo(0.5);
    expect(localStorage.getItem('jarvis.buehne.hoehe')).toBe('0.5');
    fireEvent.keyDown(teiler, { key: 'ArrowUp' });
    fireEvent.keyDown(teiler, { key: 'ArrowUp' });
    expect(useBuehne.getState().hoehe).toBeCloseTo(0.4);

    const konsole = container.querySelector('.konsole') as HTMLElement;
    vi.spyOn(konsole, 'getBoundingClientRect').mockReturnValue({ top: 100, height: 1000, left: 0, width: 800, bottom: 1100, right: 800, x: 0, y: 100, toJSON: () => ({}) });
    fireEvent.pointerDown(teiler, { clientY: 500, pointerId: 1 });
    fireEvent.pointerMove(window, { clientY: 700, pointerId: 1 });
    expect(useBuehne.getState().hoehe).toBeCloseTo(0.6);
    fireEvent.pointerMove(window, { clientY: 1090, pointerId: 1 });
    expect(useBuehne.getState().hoehe).toBe(0.8);
    fireEvent.pointerUp(window, { pointerId: 1 });
    fireEvent.pointerMove(window, { clientY: 300, pointerId: 1 });
    expect(useBuehne.getState().hoehe).toBe(0.8);
    expect(localStorage.getItem('jarvis.buehne.hoehe')).toBe('0.8');
  });

  it('einklappen blendet den Inhalt aus, Reiter bleiben', async () => {
    const u = userEvent.setup();
    act(() => flaecheAnlegen('wetter', 'Wetter', 'Sonnig'));
    render(<Konsole aktiv={false} />);
    await u.click(screen.getByRole('button', { name: 'Bühne einklappen' }));
    expect(screen.queryByText('Sonnig')).toBeNull();
    expect(screen.getByRole('tab', { name: 'Wetter' })).toBeInTheDocument();
    expect(screen.queryByRole('separator', { name: 'Höhe der Bühne' })).toBeNull();
    await u.click(screen.getByRole('button', { name: 'Bühne ausklappen' }));
    expect(screen.getByText('Sonnig')).toBeInTheDocument();
  });
});
