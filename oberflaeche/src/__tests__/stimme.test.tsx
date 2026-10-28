import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ClientNachricht } from '../api/types';
import { Composer } from '../components/Composer';
import { anfangsZustand, reduzieren } from '../state/reducer';
import { useJarvis } from '../state/store';

const status = { version: '1', modell: 'x', stimme: { aktiv: false, weckwort: 'javit', hoert: false }, integrationen: 0, werkzeuge: 0 };

describe('Audio im Browser', () => {
  let gesendet: ClientNachricht[];
  let gestartet: number;
  let gestoppt: number;
  beforeEach(() => {
    gesendet = [];
    gestartet = 0;
    gestoppt = 0;
    useJarvis.setState({
      ...anfangsZustand,
      status,
      verbindung: 'offen',
      audioBrowser: false,
      sender: (n) => {
        gesendet.push(n);
        return true;
      },
      audioStarten: async () => {
        gestartet += 1;
        return 48000;
      },
      audioStoppen: () => {
        gestoppt += 1;
      },
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it('Umschalter merkt sich die Wahl, Mikrofon-Knopf sendet audio_start und stimme', async () => {
    const u = userEvent.setup();
    render(<Composer />);
    const umschalter = screen.getByRole('button', { name: 'Audio im Browser einschalten' });
    expect(umschalter).toHaveAttribute('aria-pressed', 'false');
    await u.click(umschalter);
    expect(useJarvis.getState().audioBrowser).toBe(true);
    expect(localStorage.getItem('jarvis.audioBrowser')).toBe('1');
    await u.click(screen.getByRole('button', { name: 'Mikrofon einschalten' }));
    await waitFor(() => expect(gesendet).toEqual([{ typ: 'audio_start', rate: 48000 }, { typ: 'stimme', aktiv: true }]));
    expect(gestartet).toBe(1);
    // Solange das Mikrofon an ist, lässt sich die Quelle nicht umschalten
    expect(screen.getByRole('button', { name: 'Audio im Browser ausschalten' })).toBeDisabled();
    await u.click(screen.getByRole('button', { name: 'Mikrofon ausschalten' }));
    await waitFor(() => expect(gesendet.slice(2)).toEqual([{ typ: 'audio_stop' }, { typ: 'stimme', aktiv: false }]));
    expect(gestoppt).toBe(1);
  });

  it('ohne Browser-Mikrofon kommt ein Hinweis und nichts wird gesendet', async () => {
    const u = userEvent.setup();
    useJarvis.setState({ audioBrowser: true, audioStarten: async () => null });
    render(<Composer />);
    await u.click(screen.getByRole('button', { name: 'Mikrofon einschalten' }));
    await waitFor(() => expect(useJarvis.getState().hinweise.map((h) => h.text)).toEqual([expect.stringContaining('Mikrofon im Browser nicht verfügbar')]));
    expect(gesendet).toEqual([]);
  });

  it('ohne Browser-Audio bleibt der alte Weg (nur stimme)', async () => {
    const u = userEvent.setup();
    render(<Composer />);
    await u.click(screen.getByRole('button', { name: 'Mikrofon einschalten' }));
    await waitFor(() => expect(gesendet).toEqual([{ typ: 'stimme', aktiv: true }]));
    expect(gestartet).toBe(0);
  });
});

describe('Reducer sprachausgabe', () => {
  it('setzt das Laufen und meldet das Stoppwort als Hinweis', () => {
    const laeuft = reduzieren(anfangsZustand, { typ: 'sprachausgabe', zustand: 'start', rate: 24000 });
    expect(laeuft.sprachausgabe).toBe(true);
    const ende = reduzieren(laeuft, { typ: 'sprachausgabe', zustand: 'ende' });
    expect(ende.sprachausgabe).toBe(false);
    const gestoppt = reduzieren(laeuft, { typ: 'sprachausgabe', zustand: 'gestoppt', grund: 'stoppwort' });
    expect(gestoppt.sprachausgabe).toBe(false);
    expect(gestoppt.hinweise.map((h) => h.text)).toEqual(['Sprachausgabe gestoppt (Stoppwort).']);
  });
});

describe('Einstellungen → Stimme (OpenRouter, Stoppwort, Probe)', () => {
  it('zeigt Modelle und Stimmen, speichert Stoppwort und spricht eine Probe', async () => {
    const aufrufe: { methode: string; pfad: string; body: unknown }[] = [];
    let einstellungen: Record<string, unknown> = {
      modell: 'ollama/x', anbieter_eigene: [], verzeichnisse_eigene: [],
      stimme: { aktiv: false, weckwort: 'javit', schwelle: 0.5, stt: 'auto', tts: 'openrouter', tts_stimme: '', tts_openrouter_modell: 'elevenlabs/eleven-flash-v2.5', stoppwort: 'stopp' },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
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
      if (pfad === '/api/stimme/modelle')
        return json({
          tts: [
            { id: 'elevenlabs/eleven-flash-v2.5', name: 'ElevenLabs Flash', stimmen: ['daniel', 'sarah'], preis_je_1m_zeichen: 40, standard_stimme: 'daniel' },
            { id: 'microsoft/mai-voice-2.1-flash', name: 'MAI Voice Flash', stimmen: ['de-DE-Klaus:MAI-Voice-2.1-Flash'], preis_je_1m_zeichen: 15, standard_stimme: 'de-DE-Klaus:MAI-Voice-2.1-Flash' },
          ],
          stt: [{ id: 'openai/whisper-large-v3', name: 'Whisper large v3' }],
          fehler: null,
        });
      if (pfad === '/api/stimme/probe') return json({ ok: true, art: 'openrouter', modell: 'elevenlabs/eleven-flash-v2.5', stimme: 'sarah', ziel: 'lautsprecher' });
      if (pfad.startsWith('/api/modelle')) return json({ aktuell: 'ollama/x', anbieter: [], vorschlaege: [] });
      if (pfad === '/api/gedaechtnis') return json([]);
      if (pfad === '/api/unterhaltungen') return json([]);
      if (pfad === '/api/status') return json({ ...status, plattform: 'mac' });
      return json({ ok: true });
    }));
    const u = userEvent.setup();
    const { EinstellungenAnsicht } = await import('../views/Settings');
    render(<EinstellungenAnsicht />);
    await u.click(await screen.findByRole('tab', { name: 'Stimme' }));
    const modell = await screen.findByLabelText('Stimme (OpenRouter)');
    await waitFor(() => expect(within(modell).getAllByRole('option')).toHaveLength(2));
    expect(screen.getByText(/ca\. 3,6 Cent je Minute/)).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText('Stimme', { selector: 'input, select' }), 'sarah');
    await u.selectOptions(modell, 'microsoft/mai-voice-2.1-flash');
    expect((screen.getByLabelText('Stimme', { selector: 'input, select' }) as HTMLSelectElement).value).toBe(''); // Modellwechsel setzt die Stimme zurück
    expect(screen.getByText(/ca\. 1,4 Cent je Minute/)).toBeInTheDocument();
    await u.clear(screen.getByLabelText('Stoppwort'));
    await u.type(screen.getByLabelText('Stoppwort'), 'stopp, halt');
    await u.click(screen.getByRole('button', { name: 'Probe sprechen' }));
    await screen.findByText(/Probe gesprochen \(openrouter, elevenlabs\/eleven-flash-v2.5, Stimme „sarah“, am Rechner\)/);
    const put = aufrufe.find((a) => a.methode === 'PUT' && a.pfad === '/api/einstellungen');
    expect(put?.body).toMatchObject({ stimme: { tts: 'openrouter', tts_openrouter_modell: 'microsoft/mai-voice-2.1-flash', tts_stimme: '', stoppwort: 'stopp, halt', stt: 'auto', stt_openrouter_modell: 'openai/whisper-large-v3' } });
    expect(aufrufe.some((a) => a.methode === 'POST' && a.pfad === '/api/stimme/probe')).toBe(true);
    vi.unstubAllGlobals();
  });
});
