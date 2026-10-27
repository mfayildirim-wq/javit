import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EinstellungenAnsicht, ttsOptionen } from '../views/Settings';

interface Aufruf { methode: string; pfad: string; body: unknown }

function fetchAttrappe(aufrufe: Aufruf[]) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const pfad = String(input);
    const methode = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    aufrufe.push({ methode, pfad, body });
    const json = (d: unknown) => new Response(JSON.stringify(d), { status: 200, headers: { 'Content-Type': 'application/json' } });
    if (pfad === '/api/modelle' && methode === 'GET')
      return json({
        aktuell: 'ollama/qwen2.5:7b',
        vorschlaege: [
          { id: 'ollama/qwen2.5:7b', name: 'Qwen 2.5 7B', lokal: true, verfuegbar: true },
          { id: 'openai/gpt-4o', name: 'GPT-4o', lokal: false, verfuegbar: true },
        ],
      });
    if (pfad === '/api/einstellungen' && methode === 'GET')
      return json({ modell: 'ollama/qwen2.5:7b', persona: 'Du bist Jarvis …', anrede: 'Sir', anrede_verwenden: true, stimme: { aktiv: true, weckwort: 'hey_jarvis', schwelle: 0.5, stt: 'lokal', tts: 'say', tts_stimme: 'Anna' } });
    if (pfad === '/api/gedaechtnis' && methode === 'GET') return json([{ id: 'm1', text: 'Mag Jazz' }]);
    if (pfad === '/api/status') return json({ version: '1', modell: 'x', stimme: { aktiv: false, weckwort: 'hey_jarvis', hoert: false }, integrationen: 0, werkzeuge: 0 });
    return json({ ok: true });
  });
}

describe('Einstellungen speichern', () => {
  let aufrufe: Aufruf[];
  beforeEach(() => {
    aufrufe = [];
    vi.stubGlobal('fetch', fetchAttrappe(aufrufe));
  });
  afterEach(() => vi.unstubAllGlobals());

  it('Stimme und Persona per PUT /api/einstellungen als Teilupdate', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    const speichern = await screen.findByRole('button', { name: 'Einstellungen speichern' });
    expect(speichern).toBeDisabled();

    await u.click(screen.getByRole('switch', { name: /Mit „Sir“ ansprechen/ }));
    await u.click(screen.getByRole('switch', { name: /Mit „Sir“ ansprechen/ }));
    await u.clear(screen.getByLabelText('Anrede'));
    await u.type(screen.getByLabelText('Anrede'), 'Chefin');
    await u.click(screen.getByRole('switch', { name: /Mit „Chefin“ ansprechen/ }));
    await u.click(within(screen.getByRole('radiogroup', { name: 'Spracherkennung' })).getByRole('radio', { name: 'Cloud' }));
    await u.click(within(screen.getByRole('radiogroup', { name: 'Sprachausgabe' })).getByRole('radio', { name: 'Aus' }));
    await u.click(screen.getByRole('switch', { name: /Sprachsteuerung aktiv/ }));
    expect(speichern).toBeEnabled();
    await u.click(speichern);

    await screen.findByText('Einstellungen gespeichert.');
    const put = aufrufe.find((a) => a.methode === 'PUT' && a.pfad === '/api/einstellungen');
    expect(put?.body).toEqual({
      name: 'Javit',
      stimme: { aktiv: false, weckwort: 'hey_jarvis', weckwort_engine: 'auto', schwelle: 0.5, stt: 'cloud', tts: 'aus', tts_stimme: 'Anna' },
      anrede_verwenden: false,
      anrede: 'Chefin',
    });
    // Die Persona (Systemprompt) wird nie überschrieben.
    expect(put?.body).not.toHaveProperty('persona');
  });

  it('Modell wechseln per PUT /api/modelle (Liste und freie ID)', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    await u.click(await screen.findByRole('radio', { name: /GPT-4o/ }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/modelle', body: { modell: 'openai/gpt-4o' } }));
    await u.type(screen.getByLabelText('Eigene Modell-ID'), 'ollama/llama3.1:8b');
    await u.click(screen.getByRole('button', { name: 'Übernehmen' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/modelle', body: { modell: 'ollama/llama3.1:8b' } }));
    expect(screen.getByText('Qwen 2.5 7B').closest('button')).toHaveTextContent('lokal');
  });

  it('API-Schlüssel per PUT /api/geheimnisse/{name}', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    const feld = await screen.findByLabelText(/Anthropic \(Claude\)/);
    expect(feld).toHaveAttribute('type', 'password');
    await u.type(feld, 'sk-ant-123');
    const zeile = feld.closest('form')!;
    await u.click(within(zeile).getByRole('button', { name: /Speichern/ }));
    await waitFor(() =>
      expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/geheimnisse/ANTHROPIC_API_KEY', body: { wert: 'sk-ant-123' } }),
    );
    expect(await within(zeile).findByRole('button', { name: /Gespeichert/ })).toBeInTheDocument();
    expect(feld).toHaveValue('');
  });

  it('Gedächtnis ansehen und löschen (mit Bestätigung)', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    expect(await screen.findByText('Mag Jazz')).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: /Gedächtnis löschen/ }));
    await u.click(screen.getByRole('button', { name: 'Ja, löschen' }));
    await waitFor(() => expect(aufrufe.some((a) => a.methode === 'DELETE' && a.pfad === '/api/gedaechtnis')).toBe(true));
  });
});

describe('ttsOptionen', () => {
  it('zeigt je Plattform die passende lokale Stimme', () => {
    expect(ttsOptionen('mac', 'auto').map(([w]) => w)).toEqual(['auto', 'say', 'cloud', 'aus']);
    expect(ttsOptionen('windows', 'auto').map(([w]) => w)).toEqual(['auto', 'sapi', 'cloud', 'aus']);
    expect(ttsOptionen('linux', 'auto').map(([w]) => w)).toEqual(['auto', 'piper', 'cloud', 'aus']);
    expect(ttsOptionen(undefined, 'say').map(([w]) => w)).toEqual(['auto', 'say', 'cloud', 'aus']);
    // gespeicherter Wert, der nicht zur Plattform passt, bleibt sichtbar
    expect(ttsOptionen('linux', 'espeak').map(([w]) => w)).toEqual(['auto', 'piper', 'espeak', 'cloud', 'aus']);
  });
});
