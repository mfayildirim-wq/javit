import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  KatalogFormular,
  McpBefehlFormular,
  McpUrlFormular,
  OpenApiFormular,
  RestFormular,
} from '../views/Formulare';
import { katalogBody, mcpBefehlBody, mcpJsonParsen, mcpUrlBody, nameAusBefehl, openapiBody, restBody } from '../lib/integration';
import type { KatalogEintrag } from '../api/types';

const spotify: KatalogEintrag = {
  id: 'spotify',
  name: 'Spotify',
  beschreibung: 'Musik',
  kategorie: 'Musik',
  icon: 'music',
  art: 'mcp_stdio',
  benoetigt: [
    { name: 'SPOTIFY_CLIENT_ID', titel: 'Client ID', geheim: false },
    { name: 'SPOTIFY_CLIENT_SECRET', titel: 'Client Secret', geheim: true },
  ],
};

describe('POST-Bodies (reine Funktionen)', () => {
  it('katalog mit Standardwert, optionalen Feldern und Pfadprüfung', () => {
    const fs: KatalogEintrag = { ...spotify, id: 'dateisystem', name: 'Dateisystem', benoetigt: [{ name: 'VERZEICHNIS', titel: 'Ordner', geheim: false, typ: 'ordner', standard: '~/Documents' }, { name: 'OPT', titel: 'Opt', geheim: false, optional: true }] };
    expect(katalogBody(fs, {})).toEqual({ ok: true, body: { katalog: 'dateisystem', werte: { VERZEICHNIS: '~/Documents' } } });
    expect(katalogBody(fs, { VERZEICHNIS: 'Documents/*' })).toMatchObject({ ok: false });
  });
  it('mcpJsonParsen: Claude-Format mit Befehl und URL, einzelner Server, Fehler', () => {
    const r = mcpJsonParsen('{"mcpServers": {"a": {"command": "npx", "args": ["-y", "p q"], "env": {"K": 1}}, "b": {"type": "http", "url": "https://x.org/mcp", "headers": {"Authorization": "Bearer t"}}}}');
    expect(r).toEqual({ ok: true, eintraege: [{ name: 'a', mcp_befehl: 'npx -y "p q"', umgebung: { K: '1' } }, { name: 'b', mcp_url: 'https://x.org/mcp', kopfzeilen: { Authorization: 'Bearer t' } }] });
    expect(mcpJsonParsen('{"command": "uvx", "args": ["mcp-server-fetch"]}')).toEqual({ ok: true, eintraege: [{ name: 'Server', mcp_befehl: 'uvx mcp-server-fetch', umgebung: {} }] });
    expect(mcpJsonParsen('kein json')).toMatchObject({ ok: false });
    expect(mcpJsonParsen('{"mcpServers": {"x": {"foo": 1}}}')).toMatchObject({ ok: false, fehler: expect.stringContaining('weder command noch url') });
    expect(mcpJsonParsen('{"mcpServers": {}}')).toMatchObject({ ok: false });
    expect(mcpJsonParsen('{"mcpServers": {"x": {"url": "nix"}}}')).toMatchObject({ ok: false });
  });
  it('katalog', () => {
    expect(katalogBody(spotify, { SPOTIFY_CLIENT_ID: ' abc ', SPOTIFY_CLIENT_SECRET: 'geheim', FREMD: 'x' })).toEqual({
      ok: true,
      body: { katalog: 'spotify', werte: { SPOTIFY_CLIENT_ID: 'abc', SPOTIFY_CLIENT_SECRET: 'geheim' } },
    });
    expect(katalogBody(spotify, { SPOTIFY_CLIENT_ID: 'abc' }).ok).toBe(false);
  });
  it('mcp_befehl mit abgeleitetem Namen', () => {
    expect(nameAusBefehl('npx -y @modelcontextprotocol/server-everything')).toBe('Everything');
    expect(nameAusBefehl('uvx mcp-server-fetch')).toBe('Fetch');
    expect(mcpBefehlBody('', 'npx -y @modelcontextprotocol/server-everything', [{ schluessel: 'A', wert: '1' }, { schluessel: ' ', wert: 'x' }])).toEqual({
      ok: true,
      body: { name: 'Everything', mcp_befehl: 'npx -y @modelcontextprotocol/server-everything', umgebung: { A: '1' } },
    });
    expect(mcpBefehlBody('X', '  ', []).ok).toBe(false);
  });
  it('mcp_url', () => {
    expect(mcpUrlBody('Home Assistant', 'http://homeassistant.local:8123/mcp', [{ schluessel: 'Authorization', wert: 'Bearer t' }])).toEqual({
      ok: true,
      body: { name: 'Home Assistant', mcp_url: 'http://homeassistant.local:8123/mcp', kopfzeilen: { Authorization: 'Bearer t' } },
    });
    expect(mcpUrlBody('x', 'keine-url', []).ok).toBe(false);
  });
  it('openapi_url mit und ohne Auth', () => {
    const url = 'https://petstore3.swagger.io/api/v3/openapi.json';
    expect(openapiBody('Petstore', url, 'keine', '')).toEqual({ ok: true, body: { name: 'Petstore', openapi_url: url } });
    expect(openapiBody('Petstore', url, 'bearer', 'tok')).toEqual({
      ok: true,
      body: { name: 'Petstore', openapi_url: url, auth: { art: 'bearer', wert: 'tok' } },
    });
    expect(openapiBody('', url, 'keine', '')).toMatchObject({ ok: true, body: { name: 'Petstore3' } });
  });
  it('rest', () => {
    expect(
      restBody('Wetter', [
        {
          name: 'Wetter abrufen',
          methode: 'get',
          url: 'https://api.open-meteo.com/v1/forecast',
          beschreibung: 'Aktuelles Wetter',
          parameter: [
            { name: 'latitude', typ: 'zahl' },
            { name: 'longitude', typ: 'zahl' },
            { name: '', typ: 'text' },
          ],
        },
      ]),
    ).toEqual({
      ok: true,
      body: {
        name: 'Wetter',
        rest: [
          {
            name: 'wetter_abrufen',
            methode: 'GET',
            url: 'https://api.open-meteo.com/v1/forecast',
            parameter: { latitude: 'zahl', longitude: 'zahl' },
            beschreibung: 'Aktuelles Wetter',
          },
        ],
      },
    });
  });
});

describe('Integrationsformulare senden korrekte Bodies', () => {
  it('Katalog-Formular (geheime Felder als Passwortfeld)', async () => {
    const u = userEvent.setup();
    const anlegen = vi.fn().mockResolvedValue(undefined);
    render(<KatalogFormular eintrag={spotify} onAnlegen={anlegen} />);
    const secret = screen.getByLabelText('Client Secret');
    expect(secret).toHaveAttribute('type', 'password');
    expect(screen.getByLabelText('Client ID')).toHaveAttribute('type', 'text');
    await u.type(screen.getByLabelText('Client ID'), 'id123');
    await u.click(screen.getByRole('button', { name: 'Spotify hinzufügen' }));
    expect(anlegen).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Client Secret');
    await u.type(secret, 's3cr3t');
    await u.click(screen.getByRole('button', { name: 'Spotify hinzufügen' }));
    expect(anlegen).toHaveBeenCalledWith({ katalog: 'spotify', werte: { SPOTIFY_CLIENT_ID: 'id123', SPOTIFY_CLIENT_SECRET: 's3cr3t' } });
  });

  it('MCP-Befehl', async () => {
    const u = userEvent.setup();
    const anlegen = vi.fn().mockResolvedValue(undefined);
    render(<McpBefehlFormular onAnlegen={anlegen} />);
    await u.type(screen.getByLabelText('Befehl'), 'npx -y @modelcontextprotocol/server-everything');
    await u.type(screen.getByLabelText('Name'), 'Mein Tool');
    await u.click(screen.getByRole('button', { name: /Variable hinzufügen/ }));
    await u.type(screen.getByLabelText('Variable 1'), 'API_KEY');
    await u.type(screen.getByLabelText('Wert 1'), 'xyz');
    await u.click(screen.getByRole('button', { name: 'Integration hinzufügen' }));
    expect(anlegen).toHaveBeenCalledWith({ name: 'Mein Tool', mcp_befehl: 'npx -y @modelcontextprotocol/server-everything', umgebung: { API_KEY: 'xyz' } });
  });

  it('MCP-URL mit Kopfzeilen', async () => {
    const u = userEvent.setup();
    const anlegen = vi.fn().mockResolvedValue(undefined);
    render(<McpUrlFormular onAnlegen={anlegen} />);
    await u.type(screen.getByLabelText('URL des MCP-Servers'), 'http://homeassistant.local:8123/mcp');
    await u.type(screen.getByLabelText('Name'), 'Home Assistant');
    await u.click(screen.getByRole('button', { name: /Kopfzeile hinzufügen/ }));
    await u.type(screen.getByLabelText('Kopfzeile 1'), 'Authorization');
    await u.type(screen.getByLabelText('Wert 1'), 'Bearer abc');
    await u.click(screen.getByRole('button', { name: 'Integration hinzufügen' }));
    expect(anlegen).toHaveBeenCalledWith({
      name: 'Home Assistant',
      mcp_url: 'http://homeassistant.local:8123/mcp',
      kopfzeilen: { Authorization: 'Bearer abc' },
    });
  });

  it('OpenAPI-URL mit Bearer-Auth', async () => {
    const u = userEvent.setup();
    const anlegen = vi.fn().mockResolvedValue(undefined);
    render(<OpenApiFormular onAnlegen={anlegen} />);
    await u.type(screen.getByLabelText('URL der OpenAPI-Beschreibung'), 'https://petstore3.swagger.io/api/v3/openapi.json');
    await u.type(screen.getByLabelText('Name'), 'Petstore');
    await u.selectOptions(screen.getByLabelText('Anmeldung'), 'bearer');
    await u.type(screen.getByLabelText('Token / Schlüssel'), 'tok');
    await u.click(screen.getByRole('button', { name: 'Integration hinzufügen' }));
    expect(anlegen).toHaveBeenCalledWith({
      name: 'Petstore',
      openapi_url: 'https://petstore3.swagger.io/api/v3/openapi.json',
      auth: { art: 'bearer', wert: 'tok' },
    });
  });

  it('REST-Endpunkt mit Parametern', async () => {
    const u = userEvent.setup();
    const anlegen = vi.fn().mockResolvedValue(undefined);
    render(<RestFormular onAnlegen={anlegen} />);
    await u.type(screen.getByLabelText('Name der Integration'), 'Wetter');
    await u.type(screen.getByLabelText('Werkzeugname'), 'wetter_abrufen');
    await u.type(screen.getByLabelText('URL'), 'https://api.open-meteo.com/v1/forecast');
    await u.type(screen.getByLabelText('Beschreibung für das Modell'), 'Aktuelles Wetter');
    await u.click(screen.getByRole('button', { name: /Parameter hinzufügen/ }));
    await u.type(screen.getByLabelText('Parameter 1 Name'), 'latitude');
    await u.selectOptions(screen.getByLabelText('Parameter 1 Typ'), 'zahl');
    await u.click(screen.getByRole('button', { name: /Parameter hinzufügen/ }));
    await u.type(screen.getByLabelText('Parameter 2 Name'), 'current_weather');
    await u.click(screen.getByRole('button', { name: 'Integration hinzufügen' }));
    expect(anlegen).toHaveBeenCalledWith({
      name: 'Wetter',
      rest: [
        {
          name: 'wetter_abrufen',
          methode: 'GET',
          url: 'https://api.open-meteo.com/v1/forecast',
          parameter: { latitude: 'zahl', current_weather: 'text' },
          beschreibung: 'Aktuelles Wetter',
        },
      ],
    });
  });

  it('zeigt Serverfehler im Formular an', async () => {
    const u = userEvent.setup();
    const anlegen = vi.fn().mockRejectedValue(new Error('npx nicht gefunden'));
    render(<McpBefehlFormular onAnlegen={anlegen} />);
    await u.type(screen.getByLabelText('Befehl'), 'npx -y paket');
    await u.click(screen.getByRole('button', { name: 'Integration hinzufügen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('npx nicht gefunden');
  });
});
