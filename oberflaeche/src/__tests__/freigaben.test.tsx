import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EinstellungenAnsicht } from '../views/Settings';
import { IntegrationDetail } from '../views/IntegrationDetail';

interface Aufruf { methode: string; pfad: string; body: unknown }

function fetchAttrappe(aufrufe: Aufruf[]) {
  let einstellungen: Record<string, unknown> = { modell: 'ollama/x', anbieter_eigene: [], verzeichnisse_eigene: [], freigabe_technisch: false, freigabe_fachlich: 'aendern', stimme: { aktiv: false } };
  let bereich = 'fachlich';
  const details = () => ({
    id: 'gg', name: 'GG Immobilien', art: 'mcp_http', status: 'verbunden', werkzeuge: 2, bereich,
    konfig: { befehl: null, url: 'https://gg.test/mcp', kopfzeilen: {}, umgebung: {}, auth: null, rest: null, geheimnisse: [], risiko_standard: 'aendern', werkzeug_risiko: {}, aktiv: true, hinzugefuegt: '' },
    werkzeug_liste: [], protokoll: [],
  });
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const pfad = String(input);
    const methode = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    aufrufe.push({ methode, pfad, body });
    const json = (d: unknown) => new Response(JSON.stringify(d), { status: 200, headers: { 'Content-Type': 'application/json' } });
    if (pfad === '/api/einstellungen' && methode === 'PUT') {
      einstellungen = { ...einstellungen, ...(body as object) };
      return json(einstellungen);
    }
    if (pfad === '/api/einstellungen') return json(einstellungen);
    if (pfad === '/api/integrationen/gg/bereich' && methode === 'PUT') {
      bereich = (body as { bereich: string }).bereich;
      return json(details());
    }
    if (pfad === '/api/integrationen/gg') return json(details());
    if (pfad.startsWith('/api/modelle')) return json({ aktuell: 'ollama/x', anbieter: [], vorschlaege: [] });
    if (pfad === '/api/gedaechtnis') return json([]);
    if (pfad === '/api/status') return json({ version: '1', modell: 'x', stimme: { aktiv: false, weckwort: 'javit', hoert: false }, integrationen: 0, werkzeuge: 0 });
    return json({ ok: true });
  });
}

describe('Freigaben nach Bereich', () => {
  let aufrufe: Aufruf[];
  beforeEach(() => {
    aufrufe = [];
    vi.stubGlobal('fetch', fetchAttrappe(aufrufe));
  });
  afterEach(() => vi.unstubAllGlobals());

  it('Einstellungen: technische Freigaben einschalten und fachliche Stufe wählen', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    await u.click(await screen.findByRole('tab', { name: 'Freigaben' }));
    const schalter = await screen.findByRole('switch', { name: /Technische Aktionen bestätigen/ });
    expect(schalter).not.toBeChecked();
    await u.click(schalter);
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/einstellungen', body: { freigabe_technisch: true } }));
    const gruppe = screen.getByRole('radiogroup', { name: 'Fachliche Aktionen bestätigen' });
    expect(within(gruppe).getByRole('radio', { name: 'Ab Ändern' })).toHaveAttribute('aria-checked', 'true');
    await u.click(within(gruppe).getByRole('radio', { name: 'Nur Kritisches' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/einstellungen', body: { freigabe_fachlich: 'kritisch' } }));
    expect(within(gruppe).getByRole('radio', { name: 'Nur Kritisches' })).toHaveAttribute('aria-checked', 'true');
  });

  it('Detailseite: Bereich einer Integration umstellen', async () => {
    const u = userEvent.setup();
    render(<IntegrationDetail id="gg" onZurueck={() => undefined} onGeaendert={() => undefined} />);
    const gruppe = await screen.findByRole('radiogroup', { name: 'Bereich' });
    expect(within(gruppe).getByRole('radio', { name: 'Fachlich' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText(/Alles außer Lesen legt/)).toBeInTheDocument();
    await u.click(within(gruppe).getByRole('radio', { name: 'Technisch' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/integrationen/gg/bereich', body: { bereich: 'technisch' } }));
    expect(await screen.findByText(/ohne Rückfrage/)).toBeInTheDocument();
    expect(within(gruppe).getByRole('radio', { name: 'Technisch' })).toHaveAttribute('aria-checked', 'true');
  });
});
