import { render, screen, waitFor } from '@testing-library/react';
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
