import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IntegrationsAnsicht } from '../views/Integrations';
import { EinstellungenAnsicht } from '../views/Settings';

interface Aufruf { methode: string; pfad: string; body: unknown }

const notionKatalog = {
  id: 'notion', name: 'Notion', beschreibung: 'Seiten und Datenbanken', kategorie: 'Produktivität', icon: 'notebook', art: 'mcp_http', benoetigt: [], hinweis: 'Offiziell',
  oauth: 'entdeckung', vertrauen: 'offiziell', quelle: 'https://developers.notion.com/docs/mcp', einrichtung: [],
};
const quellen = [
  { id: 'mcp-registry', name: 'MCP-Registry (offiziell)', url: 'https://registry.modelcontextprotocol.io', eigen: false },
  { id: 'smithery', name: 'Smithery', url: 'https://registry.smithery.ai', eigen: false },
];
const exa = {
  quelle: 'smithery', kennung: 'exa', name: 'Exa Search', beschreibung: 'Websuche.', webseite: 'https://exa.ai', repository: null, herausgeber: 'Smithery-Konto exa',
  verifiziert: true, nutzungen: 9181, art: 'mcp_http', laufzeit: 'fern', oauth: true, felder: [], warnungen: [], installierbar: true, vollstaendig: false,
};
const dateien = {
  quelle: 'mcp-registry', kennung: 'io.github.foo/dateien', name: 'dateien', beschreibung: 'Dateien lesen.', webseite: 'https://foo.example', repository: null,
  herausgeber: 'GitHub-Konto foo', verifiziert: false, nutzungen: null, art: 'mcp_stdio', laufzeit: 'npx', oauth: false,
  felder: [
    { name: 'ORDNER', titel: 'Freigegebener Ordner', geheim: false, optional: false, beschreibung: 'Freigegebener Ordner' },
    { name: 'FOO_API_KEY', titel: 'API-Schlüssel von foo.example', geheim: true, optional: false, beschreibung: 'API-Schlüssel von foo.example' },
    { name: 'FOO_LOG', titel: 'Log-Level', geheim: false, optional: true, beschreibung: 'Log-Level', standard: 'info' },
  ],
  warnungen: ['Lokaler Server: Javit führt das Paket „@foo/mcp-dateien“ mit npx auf diesem Rechner aus. Nur installieren, wenn du dem Herausgeber vertraust.'],
  installierbar: true, vollstaendig: true,
};
const docker = { ...dateien, kennung: 'com.firma/docker-only', name: 'docker-only', felder: [], laufzeit: null, art: null, installierbar: false, warnungen: ['Nur als oci verfügbar (Docker-Image/MCPB-Paket) – wird nicht unterstützt.'] };

function fetchAttrappe(aufrufe: Aufruf[]) {
  let eigene: { id: string; name: string; url: string }[] = [];
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const pfad = String(input);
    const methode = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    aufrufe.push({ methode, pfad, body });
    const json = (d: unknown, status = 200) => new Response(JSON.stringify(d), { status, headers: { 'Content-Type': 'application/json' } });
    if (pfad === '/api/integrationen' && methode === 'GET') return json([]);
    if (pfad === '/api/integrationen/katalog') return json([notionKatalog]);
    if (pfad === '/api/verzeichnisse' && methode === 'GET') return json([...quellen, ...eigene.map((e) => ({ ...e, eigen: true }))]);
    if (pfad.startsWith('/api/verzeichnisse/suche?')) {
      const q = new URL(pfad, 'http://x').searchParams;
      if (q.get('q') === 'notion') return json({ treffer: [exa, dateien, docker], fehler: { smithery: 'HTTP 500' } });
      return json({ treffer: [], fehler: {} });
    }
    if (pfad === '/api/verzeichnisse/smithery/exa') return json({ ...exa, vollstaendig: true, warnungen: ['Der Server wird von Smithery gehostet.'] });
    if (pfad === '/api/verzeichnisse/mcp-registry/io.github.foo%2Fdateien' || pfad === '/api/verzeichnisse/mcp-registry/io.github.foo/dateien') return json(dateien);
    if (pfad === '/api/verzeichnisse/installieren' && methode === 'POST') {
      const b = body as { kennung: string; werte?: Record<string, string> };
      if (b.kennung === 'io.github.foo/dateien' && !b.werte?.FOO_API_KEY)
        return json({ detail: 'Für dateien fehlen noch: API-Schlüssel (FOO_API_KEY).', fehlend: [{ name: 'FOO_API_KEY', titel: 'API-Schlüssel', geheim: true }] }, 400);
      return json({ id: 'dateien', name: 'dateien', art: 'mcp_stdio', status: 'verbunden', werkzeuge: 4 });
    }
    if (pfad === '/api/einstellungen' && methode === 'PUT' && body && typeof body === 'object' && 'verzeichnisse_eigene' in body) {
      eigene = (body as { verzeichnisse_eigene: typeof eigene }).verzeichnisse_eigene;
      return json({ verzeichnisse_eigene: eigene });
    }
    if (pfad === '/api/einstellungen' && methode === 'GET') return json({ modell: 'ollama/x', verzeichnisse_eigene: eigene, anbieter_eigene: [], stimme: { aktiv: false } });
    if (pfad.startsWith('/api/modelle')) return json({ aktuell: 'ollama/x', anbieter: [], vorschlaege: [] });
    if (pfad === '/api/gedaechtnis') return json([]);
    if (pfad === '/api/status') return json({ version: '1', modell: 'x', stimme: { aktiv: false, weckwort: 'javit', hoert: false }, integrationen: 0, werkzeuge: 0 });
    return json({ ok: true });
  });
}

describe('Verzeichnissuche', () => {
  let aufrufe: Aufruf[];
  beforeEach(() => {
    aufrufe = [];
    vi.stubGlobal('fetch', fetchAttrappe(aufrufe));
  });
  afterEach(() => vi.unstubAllGlobals());

  it('zeigt Katalogtreffer, Verzeichnis-Treffer mit Chips und nicht erreichbare Quellen', async () => {
    const u = userEvent.setup();
    render(<IntegrationsAnsicht />);
    await u.click(await screen.findByRole('tab', { name: /Suchen/ }));
    await u.type(screen.getByLabelText('Verzeichnisse durchsuchen'), 'notion{Enter}');
    const katalog = await screen.findByRole('region', { name: 'Im Katalog' });
    expect(within(katalog).getByText('Notion')).toBeInTheDocument();
    expect(within(katalog).getByText('Offiziell')).toBeInTheDocument();
    const liste = await screen.findByRole('region', { name: 'Treffer aus Verzeichnissen' });
    const exaZeile = within(liste).getByRole('button', { name: 'Exa Search öffnen' });
    expect(exaZeile).toHaveTextContent('Verifiziert');
    expect(exaZeile).toHaveTextContent('Smithery');
    expect(exaZeile).toHaveTextContent('Fern');
    expect(exaZeile).toHaveTextContent('Anmeldung im Browser');
    expect(exaZeile).toHaveTextContent('9.181 Nutzungen');
    const dateienZeile = within(liste).getByRole('button', { name: 'dateien öffnen' });
    expect(dateienZeile).toHaveTextContent('GitHub-Konto foo');
    expect(dateienZeile).toHaveTextContent('Lokal (npx)');
    expect(within(liste).getByRole('button', { name: 'docker-only öffnen' })).toHaveTextContent('nicht installierbar');
    expect(screen.getByText(/Smithery nicht erreichbar: HTTP 500/)).toBeInTheDocument();
    expect(aufrufe.find((a) => a.pfad.startsWith('/api/verzeichnisse/suche'))?.pfad).toBe('/api/verzeichnisse/suche?q=notion&limit=8');
  });

  it('Detail: Warnung, Felder, fehlende Pflichtfelder, Installation über POST /api/verzeichnisse/installieren', async () => {
    const u = userEvent.setup();
    render(<IntegrationsAnsicht />);
    await u.click(await screen.findByRole('tab', { name: /Suchen/ }));
    await u.type(screen.getByLabelText('Verzeichnisse durchsuchen'), 'notion{Enter}');
    await u.click(await screen.findByRole('button', { name: 'dateien öffnen' }));
    expect(await screen.findByText(/Von Dritten veröffentlicht/)).toBeInTheDocument();
    expect(screen.getByText(/Lokale Server führen fremden Code/)).toBeInTheDocument();
    expect(screen.getByText(/führt das Paket/)).toBeInTheDocument();
    const formular = screen.getByRole('form', { name: 'dateien installieren' });
    expect(within(formular).getByLabelText('API-Schlüssel von foo.example')).toHaveAttribute('type', 'password');
    expect(within(formular).getByLabelText('Log-Level (optional)')).toHaveAttribute('placeholder', 'info');
    await u.click(within(formular).getByRole('button', { name: 'dateien installieren' }));
    expect(await screen.findByText(/Bitte ausfüllen: Freigegebener Ordner, API-Schlüssel/)).toBeInTheDocument();
    await u.type(within(formular).getByLabelText('Freigegebener Ordner'), '~/Dokumente');
    await u.type(within(formular).getByLabelText('API-Schlüssel von foo.example'), 'k-1');
    await u.click(within(formular).getByRole('button', { name: 'dateien installieren' }));
    await screen.findByText(/dateien hinzugefügt – 4 Werkzeuge bereit/);
    expect(aufrufe).toContainEqual({
      methode: 'POST',
      pfad: '/api/verzeichnisse/installieren',
      body: { quelle: 'mcp-registry', kennung: 'io.github.foo/dateien', werte: { ORDNER: '~/Dokumente', FOO_API_KEY: 'k-1' } },
    });
  });

  it('Smithery-Treffer lädt Details nach und zeigt den OAuth-Hinweis', async () => {
    const u = userEvent.setup();
    render(<IntegrationsAnsicht />);
    await u.click(await screen.findByRole('tab', { name: /Suchen/ }));
    await u.type(screen.getByLabelText('Verzeichnisse durchsuchen'), 'notion{Enter}');
    await u.click(await screen.findByRole('button', { name: 'Exa Search öffnen' }));
    expect(await screen.findByText(/Der Server wird von Smithery gehostet/)).toBeInTheDocument();
    expect(screen.getByText(/beim Verbinden öffnet sich die Anmeldung im Browser/)).toBeInTheDocument();
    expect(screen.queryByText(/Von Dritten veröffentlicht/)).not.toBeInTheDocument();
    expect(aufrufe.some((a) => a.pfad === '/api/verzeichnisse/smithery/exa')).toBe(true);
  });

  it('Einstellungen: eigene Registry anlegen und entfernen', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    const liste = await screen.findByRole('list', { name: 'Eigene Verzeichnisse' });
    expect(within(liste).getAllByText('eingebaut')).toHaveLength(2);
    await u.click(screen.getByRole('button', { name: 'Registry hinzufügen' }));
    await u.type(screen.getByLabelText('Name'), 'Firmen Registry');
    await u.type(screen.getByLabelText('Basis-URL (https)'), 'https://registry.firma.test');
    await u.click(screen.getByRole('button', { name: 'Anlegen' }));
    await waitFor(() =>
      expect(aufrufe).toContainEqual({
        methode: 'PUT',
        pfad: '/api/einstellungen',
        body: { verzeichnisse_eigene: [{ id: 'firmen-registry', name: 'Firmen Registry', url: 'https://registry.firma.test' }] },
      }),
    );
    await u.click(await screen.findByRole('button', { name: 'Firmen Registry entfernen' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/einstellungen', body: { verzeichnisse_eigene: [] } }));
  });
});
