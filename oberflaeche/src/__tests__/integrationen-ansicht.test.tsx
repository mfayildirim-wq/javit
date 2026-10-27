import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IntegrationsAnsicht } from '../views/Integrations';
import { useJarvis } from '../state/store';

interface Aufruf { methode: string; pfad: string; body: unknown }

const gmailKatalog = {
  id: 'gmail', name: 'Gmail', beschreibung: 'E-Mails', kategorie: 'Kommunikation', icon: 'mail', art: 'mcp_stdio', benoetigt: [], hinweis: 'Einmalig …',
  webseite: 'https://example.org/gmail',
  einrichtung: [
    { titel: 'Gmail API aktivieren', text: 'In der Konsole …', link: 'https://console.example', datei: null, befehl: null },
    { titel: 'OAuth-Datei ablegen', text: 'Hochladen', link: null, datei: '~/.gmail-mcp/gcp-oauth.keys.json', befehl: null },
    { titel: 'Bei Google anmelden', text: 'Browser öffnet sich', link: null, datei: null, befehl: 'npx -y gmail auth' },
  ],
};
const dateisystemKatalog = {
  id: 'dateisystem', name: 'Dateisystem', beschreibung: 'Dateien', kategorie: 'System', icon: 'folder-open', art: 'mcp_stdio',
  benoetigt: [{ name: 'VERZEICHNIS', titel: 'Freigegebener Ordner', geheim: false, typ: 'ordner', standard: '~/Documents' }], hinweis: 'Nur der Ordner', einrichtung: [],
};

const notionKatalog = {
  id: 'notion', name: 'Notion', beschreibung: 'Seiten', kategorie: 'Produktivität', icon: 'notebook', art: 'mcp_http', benoetigt: [], hinweis: 'Offiziell',
  oauth: 'entdeckung', vertrauen: 'offiziell', quelle: 'https://developers.notion.com/docs/mcp', einrichtung: [],
};
const googleFelder = [
  { name: 'GOOGLE_OAUTH_CLIENT_ID', titel: 'OAuth-Client-ID', geheim: false },
  { name: 'GOOGLE_OAUTH_CLIENT_SECRET', titel: 'OAuth-Client-Secret', geheim: true },
];
const googleKatalog = [
  { id: 'google-gmail', name: 'Gmail', beschreibung: 'E-Mails', kategorie: 'Google Workspace', icon: 'mail', art: 'mcp_http', benoetigt: googleFelder, hinweis: 'Google', oauth: 'manuell', vertrauen: 'offiziell', quelle: 'https://developers.google.com/workspace/guides/configure-mcp-servers', gruppe: 'google-workspace', einrichtung: [] },
  { id: 'google-kalender', name: 'Google Kalender', beschreibung: 'Termine', kategorie: 'Google Workspace', icon: 'calendar', art: 'mcp_http', benoetigt: googleFelder, hinweis: 'Google', oauth: 'manuell', vertrauen: 'offiziell', quelle: 'https://developers.google.com/workspace/guides/configure-mcp-servers', gruppe: 'google-workspace', einrichtung: [] },
  { id: 'google-drive', name: 'Google Drive', beschreibung: 'Dateien', kategorie: 'Google Workspace', icon: 'hard-drive', art: 'mcp_http', benoetigt: googleFelder, hinweis: 'Google', oauth: 'manuell', vertrauen: 'offiziell', quelle: 'https://developers.google.com/workspace/guides/configure-mcp-servers', gruppe: 'google-workspace', einrichtung: [] },
];

function fetchAttrappe(aufrufe: Aufruf[]) {
  let dateiDa = false;
  const einrichtung = () => gmailKatalog.einrichtung.map((s, i) => ({ ...s, erfuellt: i === 1 ? dateiDa : null }));
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const pfad = String(input);
    const methode = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    aufrufe.push({ methode, pfad, body });
    const json = (d: unknown, status = 200) => new Response(JSON.stringify(d), { status, headers: { 'Content-Type': 'application/json' } });
    if (pfad === '/api/integrationen' && methode === 'GET')
      return json([
        { id: 'gmail', name: 'Gmail', art: 'mcp_stdio', status: 'fehler', werkzeuge: 0, fehler: 'Server meldet: OAuth keys file not found' },
        { id: 'dateisystem', name: 'Dateisystem', art: 'mcp_stdio', status: 'verbunden', werkzeuge: 14 },
        { id: 'notion', name: 'Notion', art: 'mcp_http', status: 'verbunden', werkzeuge: 3 },
      ]);
    if (pfad === '/api/integrationen/katalog' && methode === 'GET') return json([gmailKatalog, dateisystemKatalog, notionKatalog, ...googleKatalog]);
    if (pfad === '/api/integrationen/katalog/gmail' && methode === 'GET') return json({ ...gmailKatalog, einrichtung: einrichtung(), installiert: true });
    if (pfad === '/api/integrationen/katalog/gmail/einrichtung/1/datei' && methode === 'POST') {
      dateiDa = true;
      return json({ pfad: '/Users/x/.gmail-mcp/gcp-oauth.keys.json', erfuellt: true, einrichtung: einrichtung() });
    }
    if (pfad === '/api/integrationen/katalog/gmail/einrichtung/2/stand') return json({ status: 'nie', rueckgabe: null, ausgabe: [], sekunden: 0 });
    if (pfad === '/api/integrationen/katalog/gmail/einrichtung/2/ausfuehren' && methode === 'POST')
      return json({ status: 'laeuft', rueckgabe: null, ausgabe: ['$ npx -y gmail auth'], sekunden: 0 });
    if (pfad === '/api/integrationen/gmail' && methode === 'GET')
      return json({
        id: 'gmail', name: 'Gmail', art: 'mcp_stdio', status: 'fehler', werkzeuge: 0, fehler: 'Server meldet: OAuth keys file not found',
        katalog: { id: 'gmail', name: 'Gmail', hinweis: 'Einmalig …', webseite: 'https://example.org/gmail', benoetigt: [], einrichtung: einrichtung() },
        werte: {},
        konfig: { befehl: ['npx', '-y', 'gmail'], url: null, kopfzeilen: {}, umgebung: {}, auth: null, rest: null, geheimnisse: [], risiko_standard: 'aendern', werkzeug_risiko: {}, aktiv: true, hinzugefuegt: '2026-10-27T10:00:00' },
        werkzeug_liste: [],
        protokoll: ['Error: OAuth keys file not found'],
      });
    if (pfad === '/api/integrationen/notion' && methode === 'GET')
      return json({
        id: 'notion', name: 'Notion', art: 'mcp_http', status: 'verbunden', werkzeuge: 3, oauth: { modus: 'entdeckung', angemeldet: true },
        katalog: { id: 'notion', name: 'Notion', hinweis: 'Offiziell', webseite: null, benoetigt: [], einrichtung: [] }, werte: {},
        konfig: { befehl: null, url: 'https://mcp.notion.com/mcp', kopfzeilen: {}, umgebung: {}, auth: null, rest: null, geheimnisse: [], risiko_standard: 'aendern', werkzeug_risiko: {}, aktiv: true, hinzugefuegt: '' },
        werkzeug_liste: [], protokoll: [],
      });
    if (pfad === '/api/integrationen/notion/abmelden' && methode === 'POST') return json({ id: 'notion', name: 'Notion', art: 'mcp_http', status: 'aus', werkzeuge: 0 });
    if (pfad === '/api/integrationen/dateisystem' && methode === 'GET')
      return json({
        id: 'dateisystem', name: 'Dateisystem', art: 'mcp_stdio', status: 'verbunden', werkzeuge: 1,
        katalog: { id: 'dateisystem', name: 'Dateisystem', hinweis: 'Nur der Ordner', webseite: null, benoetigt: dateisystemKatalog.benoetigt, einrichtung: [] },
        werte: { VERZEICHNIS: '~/Documents' },
        konfig: { befehl: ['npx', '-y', 'fs', '${VERZEICHNIS}'], url: null, kopfzeilen: {}, umgebung: { VERZEICHNIS: '~/Documents' }, auth: null, rest: null, geheimnisse: [], risiko_standard: 'aendern', werkzeug_risiko: {}, aktiv: true, hinzugefuegt: '2026-10-27T10:00:00' },
        werkzeug_liste: [{ name: 'dateisystem__read_file', beschreibung: 'Liest eine Datei', risiko: 'lesen' }],
        protokoll: [],
      });
    if (pfad === '/api/integrationen/dateisystem' && methode === 'PUT')
      return json({ id: 'dateisystem', name: 'Dateisystem', art: 'mcp_stdio', status: 'verbunden', werkzeuge: 1, werte: (body as { werte: Record<string, string> }).werte, konfig: { befehl: ['npx'], kopfzeilen: {}, umgebung: (body as { werte: Record<string, string> }).werte, geheimnisse: [], risiko_standard: 'aendern', werkzeug_risiko: {}, aktiv: true, hinzugefuegt: '' }, katalog: { id: 'dateisystem', name: 'Dateisystem', benoetigt: dateisystemKatalog.benoetigt, einrichtung: [] }, werkzeug_liste: [], protokoll: [] });
    if (pfad === '/api/integrationen' && methode === 'POST') {
      const b = body as { name?: string; katalog?: string };
      return json({ id: (b.name ?? b.katalog ?? 'x').toLowerCase(), name: b.name ?? b.katalog, art: 'mcp_stdio', status: 'verbunden', werkzeuge: 2 });
    }
    if (pfad === '/api/status') return json({ version: '1', modell: 'x', stimme: { aktiv: false, weckwort: 'javit', hoert: false }, integrationen: 2, werkzeuge: 0 });
    return json({ ok: true });
  });
}

describe('Integrationen: Detailseite, Einrichtung, Bearbeiten, Hinzufügen', () => {
  let aufrufe: Aufruf[];
  beforeEach(() => {
    aufrufe = [];
    vi.stubGlobal('fetch', fetchAttrappe(aufrufe));
    useJarvis.setState({ ansicht: 'integrationen', sender: () => true });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('zeigt bei Fehler Grund, Einrichtungs-Checkliste mit Upload und Ausführen sowie Hilfe durch den Assistenten', async () => {
    const u = userEvent.setup();
    render(<IntegrationsAnsicht />);
    await u.click(await screen.findByRole('button', { name: 'Gmail öffnen' }));
    const kasten = await screen.findByRole('alert');
    expect(kasten).toHaveTextContent('OAuth keys file not found');
    const einrichtung = screen.getByRole('region', { name: 'Einrichtung' });
    expect(within(einrichtung).getByText(/1\. Gmail API aktivieren/)).toBeInTheDocument();
    expect(within(einrichtung).getByRole('link', { name: /Öffnen/ })).toHaveAttribute('href', 'https://console.example');
    expect(screen.getByText('1 Schritt offen')).toBeInTheDocument();

    // Datei hochladen → POST …/datei mit Base64, danach Schritt erledigt
    const datei = new File(['{"installed":{}}'], 'gcp-oauth.keys.json', { type: 'application/json' });
    await u.upload(screen.getByLabelText('Datei für Schritt 2 auswählen'), datei);
    await waitFor(() => expect(aufrufe.some((a) => a.pfad === '/api/integrationen/katalog/gmail/einrichtung/1/datei' && a.methode === 'POST')).toBe(true));
    const upload = aufrufe.find((a) => a.pfad.endsWith('/einrichtung/1/datei'))!;
    expect(atob((upload.body as { inhalt_base64: string }).inhalt_base64)).toBe('{"installed":{}}');
    expect(await screen.findByText('Alle prüfbaren Schritte erledigt')).toBeInTheDocument();

    // Befehl ausführen → POST …/ausfuehren
    await u.click(screen.getByRole('button', { name: 'Ausführen' }));
    await waitFor(() => expect(aufrufe.some((a) => a.pfad === '/api/integrationen/katalog/gmail/einrichtung/2/ausfuehren')).toBe(true));
    expect(await screen.findByRole('button', { name: 'Läuft …' })).toBeDisabled();

    // Hilfe durch den Assistenten: Nachricht in die Konsole
    await u.click(screen.getByRole('button', { name: /um Hilfe bitten/ }));
    expect(useJarvis.getState().ansicht).toBe('konsole');
    expect(useJarvis.getState().nachrichten.at(-1)?.text).toMatch(/Hilf mir, die Integration „Gmail“ einzurichten/);
  });

  it('bearbeitet eine Katalog-Integration per PUT mit vorbelegten Werten', async () => {
    const u = userEvent.setup();
    render(<IntegrationsAnsicht />);
    await u.click(await screen.findByRole('button', { name: 'Dateisystem öffnen' }));
    expect(await screen.findByText('dateisystem__read_file')).toBeInTheDocument();
    expect(screen.getByText('~/Documents')).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: /Bearbeiten/ }));
    const feld = screen.getByLabelText('Freigegebener Ordner');
    expect(feld).toHaveValue('~/Documents');
    await u.clear(feld);
    await u.type(feld, 'Documents/*');
    await u.click(screen.getByRole('button', { name: 'Speichern und neu verbinden' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Platzhalter wie * sind nicht erlaubt');
    await u.clear(feld);
    await u.type(feld, '~/Desktop');
    await u.click(screen.getByRole('button', { name: 'Speichern und neu verbinden' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/integrationen/dateisystem', body: { katalog: 'dateisystem', werte: { VERZEICHNIS: '~/Desktop' } } }));
    expect(await screen.findByText('~/Desktop')).toBeInTheDocument();
  });

  it('Plus-Knopf öffnet Hinzufügen; JSON-Import legt mehrere Integrationen an; Katalogformular belegt Standardwert vor', async () => {
    const u = userEvent.setup();
    render(<IntegrationsAnsicht />);
    await screen.findByRole('button', { name: 'Gmail öffnen' });
    await u.click(screen.getByRole('button', { name: 'Integration hinzufügen' }));
    await u.click(screen.getByRole('tab', { name: /JSON einfügen/ }));
    const json = JSON.stringify({ mcpServers: { notion: { command: 'npx', args: ['-y', '@notionhq/notion-mcp-server'], env: { NOTION_TOKEN: 'ntn_x' } }, remote: { type: 'http', url: 'https://mcp.example.org/mcp', headers: { Authorization: 'Bearer t' } } } });
    await u.click(screen.getByLabelText('JSON-Konfiguration'));
    await u.paste(json);
    const vorschau = await screen.findByRole('list', { name: 'Erkannte Server' });
    expect(within(vorschau).getAllByRole('listitem')).toHaveLength(2);
    await u.click(screen.getByRole('button', { name: '2 Integrationen hinzufügen' }));
    await waitFor(() =>
      expect(aufrufe).toContainEqual({ methode: 'POST', pfad: '/api/integrationen', body: { name: 'notion', mcp_befehl: 'npx -y @notionhq/notion-mcp-server', umgebung: { NOTION_TOKEN: 'ntn_x' } } }),
    );
    expect(aufrufe).toContainEqual({ methode: 'POST', pfad: '/api/integrationen', body: { name: 'remote', mcp_url: 'https://mcp.example.org/mcp', kopfzeilen: { Authorization: 'Bearer t' } } });

    await u.click(screen.getByRole('button', { name: 'Integration hinzufügen' }));
    await u.click(screen.getByRole('tab', { name: /Katalog/ }));
    await u.click(screen.getByRole('button', { name: /Dateisystem/ }));
    expect(await screen.findByLabelText('Freigegebener Ordner')).toHaveValue('~/Documents');
    expect(screen.getByText(/keine Platzhalter/)).toBeInTheDocument();
  });

  it('Katalog: Herkunfts-Chips, Google-Workspace-Gruppe legt gewählte Dienste mit gemeinsamen Werten an', async () => {
    const u = userEvent.setup();
    render(<IntegrationsAnsicht />);
    await screen.findByRole('button', { name: 'Gmail öffnen' });
    await u.click(screen.getByRole('button', { name: 'Integration hinzufügen' }));
    const notion = await screen.findByRole('button', { name: /Notion/ });
    expect(notion).toHaveTextContent('Offiziell');
    expect(notion).toHaveTextContent('Anmeldung im Browser');
    expect(screen.getByRole('button', { name: /Dateisystem/ })).toHaveTextContent('Community');
    expect(screen.queryByRole('button', { name: /^Google Drive/ })).not.toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: 'Google Workspace öffnen' }));
    expect(screen.getByRole('checkbox', { name: /Gmail/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /Google Drive/ })).not.toBeChecked();
    await u.click(screen.getByRole('checkbox', { name: /Google Kalender/ }));
    await u.type(screen.getByLabelText('OAuth-Client-ID'), 'cid.apps');
    await u.type(screen.getByLabelText('OAuth-Client-Secret'), 'cs-1');
    await u.click(screen.getByRole('button', { name: '1 Dienst hinzufügen' }));
    await waitFor(() =>
      expect(aufrufe).toContainEqual({ methode: 'POST', pfad: '/api/integrationen', body: { katalog: 'google-gmail', werte: { GOOGLE_OAUTH_CLIENT_ID: 'cid.apps', GOOGLE_OAUTH_CLIENT_SECRET: 'cs-1' } } }),
    );
    expect(aufrufe.filter((a) => a.pfad === '/api/integrationen' && a.methode === 'POST')).toHaveLength(1);
  });

  it('OAuth-Hinweis mit Anmeldelink und Abmelden auf der Detailseite', async () => {
    const u = userEvent.setup();
    render(<IntegrationsAnsicht />);
    await screen.findByRole('button', { name: 'Notion öffnen' });
    useJarvis.getState().verarbeiten({ typ: 'oauth_anmeldung', integration: 'notion', url: 'https://mcp.notion.com/authorize?state=abc' });
    const link = await screen.findByRole('link', { name: 'Anmeldeseite öffnen' });
    expect(link).toHaveAttribute('href', 'https://mcp.notion.com/authorize?state=abc');
    useJarvis.getState().verarbeiten({ typ: 'integration_geaendert', integration: { id: 'notion', status: 'verbunden' } });
    await waitFor(() => expect(screen.queryByRole('link', { name: 'Anmeldeseite öffnen' })).not.toBeInTheDocument());
    await u.click(screen.getByRole('button', { name: 'Notion öffnen' }));
    expect(await screen.findByText('angemeldet')).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: /Abmelden/ }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'POST', pfad: '/api/integrationen/notion/abmelden', body: undefined }));
  });
});
