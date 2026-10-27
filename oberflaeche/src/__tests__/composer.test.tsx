import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { Composer } from '../components/Composer';
import { useJarvis } from '../state/store';
import { anfangsZustand } from '../state/reducer';
import type { ClientNachricht } from '../api/types';

describe('Eingabezeile', () => {
  let gesendet: ClientNachricht[];
  beforeEach(() => {
    gesendet = [];
    useJarvis.setState({
      ...anfangsZustand,
      verbindung: 'offen',
      vorlesen: true,
      status: { version: '1', modell: 'x', stimme: { aktiv: false, weckwort: 'hey_jarvis', hoert: false }, integrationen: 0, werkzeuge: 0 },
      sender: (n) => {
        gesendet.push(n);
        return true;
      },
    });
  });

  it('Enter sendet die Nachricht inkl. Vorlese-Wunsch und zeigt sie an', async () => {
    const u = userEvent.setup();
    render(<Composer />);
    await u.type(screen.getByLabelText('Nachricht an Javit'), 'Spiel etwas Jazz{Enter}');
    expect(gesendet).toEqual([{ typ: 'nachricht', text: 'Spiel etwas Jazz', sprechen: true }]);
    expect(useJarvis.getState().nachrichten.at(-1)).toMatchObject({ rolle: 'nutzer', text: 'Spiel etwas Jazz' });
    expect(screen.getByLabelText('Nachricht an Javit')).toHaveValue('');
  });

  it('Mikrofon-Knopf schaltet die Stimme, Abbrechen erscheint während der Arbeit', async () => {
    const u = userEvent.setup();
    render(<Composer />);
    await u.click(screen.getByRole('button', { name: 'Mikrofon einschalten' }));
    expect(gesendet).toContainEqual({ typ: 'stimme', aktiv: true });
    useJarvis.getState().verarbeiten({ typ: 'zustand', zustand: 'denkt' });
    await u.click(await screen.findByRole('button', { name: /Abbrechen/ }));
    expect(gesendet).toContainEqual({ typ: 'abbrechen' });
  });
});
