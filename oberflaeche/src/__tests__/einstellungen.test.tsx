import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EinstellungenAnsicht, ttsOptionen } from '../views/Settings';

interface Aufruf { methode: string; pfad: string; body: unknown }

function fetchAttrappe(aufrufe: Aufruf[]) {
  let eigene: { id: string; name?: string; api_base: string; schluessel?: string | null }[] = [];
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const pfad = String(input);
    const methode = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    aufrufe.push({ methode, pfad, body });
    const json = (d: unknown) => new Response(JSON.stringify(d), { status: 200, headers: { 'Content-Type': 'application/json' } });
    if (pfad.startsWith('/api/modelle') && methode === 'GET') {
      const q = new URL(pfad, 'http://x').searchParams;
      const anbieter = [
        { id: 'ollama', name: 'Ollama (lokal)', schluessel: null, verfuegbar: true, lokal: true, eigen: false },
        { id: 'openai', name: 'OpenAI', schluessel: 'OPENAI_API_KEY', verfuegbar: true, lokal: false, eigen: false },
        { id: 'openrouter', name: 'OpenRouter', schluessel: 'OPENROUTER_API_KEY', verfuegbar: false, lokal: false, eigen: false },
        ...(eigene.map((e) => ({ id: e.id, name: e.name ?? e.id, schluessel: e.schluessel ?? null, verfuegbar: true, lokal: false, eigen: true }))),
      ];
      const alle = [
        { id: 'ollama/qwen2.5:7b', name: 'Qwen 2.5 7B', lokal: true, verfuegbar: true, anbieter: 'ollama', live: true },
        { id: 'openai/gpt-4o', name: 'GPT-4o', lokal: false, verfuegbar: true, anbieter: 'openai' },
        { id: 'openrouter/google/gemma-4-31b-it:free', name: 'Gemma 4 (free)', lokal: false, verfuegbar: false, anbieter: 'openrouter', kostenlos: true, werkzeuge: true, live: true },
        { id: 'openrouter/deepseek/deepseek-v4.1-flash', name: 'DeepSeek V4.1 Flash', lokal: false, verfuegbar: false, anbieter: 'openrouter', kostenlos: false, live: true },
        ...eigene.map((e) => ({ id: `${e.id}/llama`, name: 'llama', lokal: false, verfuegbar: true, anbieter: e.id })),
      ];
      const gewaehlt = q.get('anbieter');
      return json({ aktuell: 'ollama/qwen2.5:7b', anbieter, vorschlaege: gewaehlt ? alle.filter((v) => v.anbieter === gewaehlt) : alle });
    }
    if (pfad === '/api/einstellungen' && methode === 'PUT' && body && typeof body === 'object' && 'anbieter_eigene' in body) {
      eigene = (body as { anbieter_eigene: typeof eigene }).anbieter_eigene;
      return json({ anbieter_eigene: eigene });
    }
    if (pfad === '/api/einstellungen' && methode === 'GET')
      return json({ modell: 'ollama/qwen2.5:7b', anbieter_eigene: eigene, persona: 'Du bist Jarvis …', anrede: 'Sir', anrede_verwenden: true, stimme: { aktiv: true, weckwort: 'hey_jarvis', schwelle: 0.5, stt: 'lokal', tts: 'say', tts_stimme: 'Anna' } });
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
      stimme: {
        aktiv: false, weckwort: 'hey_jarvis', weckwort_engine: 'auto', schwelle: 0.5, stt: 'cloud', stt_openrouter_modell: 'openai/whisper-large-v3',
        tts: 'aus', tts_openrouter_modell: 'elevenlabs/eleven-flash-v2.5', tts_stimme: 'Anna', stoppwort: 'stopp',
      },
      anrede_verwenden: false,
      anrede: 'Chefin',
    });
    // Die Persona (Systemprompt) wird nie überschrieben.
    expect(put?.body).not.toHaveProperty('persona');
  });

  it('Modell wechseln per PUT /api/modelle (Liste und freie ID)', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    // Anbieter des aktiven Modells (Ollama) ist vorausgewählt und zeigt nur seine Modelle
    const leiste = await screen.findByRole('radiogroup', { name: 'Anbieter' });
    expect(within(leiste).getByRole('radio', { name: /Ollama/ })).toHaveAttribute('aria-checked', 'true');
    expect(await screen.findByText('Qwen 2.5 7B')).toBeInTheDocument();
    expect(screen.queryByText('GPT-4o')).not.toBeInTheDocument();
    expect(screen.getByText('Qwen 2.5 7B').closest('button')).toHaveTextContent('lokal');

    await u.click(within(leiste).getByRole('radio', { name: /OpenAI/ }));
    await waitFor(() => expect(aufrufe.some((a) => a.pfad === '/api/modelle?anbieter=openai')).toBe(true));
    await u.click(await screen.findByRole('radio', { name: /GPT-4o/ }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/modelle', body: { modell: 'openai/gpt-4o' } }));
    await u.type(screen.getByLabelText('Eigene Modell-ID'), 'ollama/llama3.1:8b');
    await u.click(screen.getByRole('button', { name: 'Übernehmen' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/modelle', body: { modell: 'ollama/llama3.1:8b' } }));
  });

  it('Anbieterwahl: Schlüsselstatus, kostenlose Modelle, Schlüssel speichern lädt Liste neu', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    const leiste = await screen.findByRole('radiogroup', { name: 'Anbieter' });
    const openrouter = within(leiste).getByRole('radio', { name: /OpenRouter/ });
    expect(openrouter).toHaveAttribute('title', 'Schlüssel fehlt');
    await u.click(openrouter);
    const gemma = await screen.findByRole('radio', { name: /Gemma 4/ });
    expect(gemma).toHaveTextContent('kostenlos');
    expect(gemma).toHaveTextContent('Werkzeuge');
    expect(gemma).toHaveTextContent('Schlüssel fehlt');
    expect(screen.getByRole('radio', { name: /DeepSeek V4.1/ })).not.toHaveTextContent('kostenlos');
    expect(screen.getByText('Liste vom Anbieter')).toBeInTheDocument();
    // Schlüsselfeld für den gewählten Anbieter direkt im Modell-Abschnitt
    const feld = document.getElementById('m-OPENROUTER_API_KEY') as HTMLInputElement;
    expect(feld).toHaveAttribute('type', 'password');
    await u.type(feld, 'or-123');
    await u.click(within(feld.closest('form')!).getByRole('button', { name: /Speichern/ }));
    await waitFor(() =>
      expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/geheimnisse/OPENROUTER_API_KEY', body: { wert: 'or-123' } }),
    );
    await waitFor(() => expect(aufrufe.some((a) => a.pfad === '/api/modelle?anbieter=openrouter&neu=1')).toBe(true));
    await u.click(screen.getByRole('button', { name: /Modelle neu laden/ }));
    await waitFor(() => expect(aufrufe.filter((a) => a.pfad === '/api/modelle?anbieter=openrouter&neu=1').length).toBe(2));
  });

  it('Eigenen Anbieter anlegen (PUT /api/einstellungen + Schlüssel) und entfernen', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    await screen.findByRole('radiogroup', { name: 'Anbieter' });
    await u.click(screen.getByRole('button', { name: /Anbieter hinzufügen/ }));
    await u.type(screen.getByLabelText('Name'), 'LM Studio');
    expect(screen.getByText('lm-studio')).toBeInTheDocument();
    await u.type(screen.getByLabelText(/Basis-URL/), 'http://127.0.0.1:1234/v1');
    await u.type(screen.getByLabelText(/API-Schlüssel \(optional/), 'geheim');
    await u.click(screen.getByRole('button', { name: 'Anlegen' }));
    await waitFor(() =>
      expect(aufrufe).toContainEqual({
        methode: 'PUT',
        pfad: '/api/einstellungen',
        body: { anbieter_eigene: [{ id: 'lm-studio', name: 'LM Studio', api_base: 'http://127.0.0.1:1234/v1', schluessel: 'LM_STUDIO_API_KEY' }] },
      }),
    );
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/geheimnisse/LM_STUDIO_API_KEY', body: { wert: 'geheim' } }));
    const leiste = screen.getByRole('radiogroup', { name: 'Anbieter' });
    const chip = await within(leiste).findByRole('radio', { name: /LM Studio/ });
    await waitFor(() => expect(chip).toHaveAttribute('aria-checked', 'true'));
    expect(await screen.findByRole('radio', { name: /lm-studio\/llama/ })).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: /Anbieter entfernen/ }));
    await u.click(screen.getByRole('button', { name: 'Ja, entfernen' }));
    await waitFor(() => expect(aufrufe).toContainEqual({ methode: 'PUT', pfad: '/api/einstellungen', body: { anbieter_eigene: [] } }));
    await waitFor(() => expect(within(leiste).queryByRole('radio', { name: /LM Studio/ })).not.toBeInTheDocument());
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
    expect(ttsOptionen('mac', 'auto').map(([w]) => w)).toEqual(['auto', 'openrouter', 'say', 'cloud', 'aus']);
    expect(ttsOptionen('windows', 'auto').map(([w]) => w)).toEqual(['auto', 'openrouter', 'sapi', 'cloud', 'aus']);
    expect(ttsOptionen('linux', 'auto').map(([w]) => w)).toEqual(['auto', 'openrouter', 'piper', 'cloud', 'aus']);
    expect(ttsOptionen(undefined, 'say').map(([w]) => w)).toEqual(['auto', 'openrouter', 'say', 'cloud', 'aus']);
    // gespeicherter Wert, der nicht zur Plattform passt, bleibt sichtbar
    expect(ttsOptionen('linux', 'espeak').map(([w]) => w)).toEqual(['auto', 'openrouter', 'piper', 'espeak', 'cloud', 'aus']);
  });
});
