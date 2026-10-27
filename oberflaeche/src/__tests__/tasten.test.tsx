import { fireEvent, render } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { useTastenkuerzel } from '../lib/tasten';
import { useJarvis } from '../state/store';
import { anfangsZustand } from '../state/reducer';
import type { ClientNachricht } from '../api/types';

function Huelle() {
  useTastenkuerzel();
  return <div>Konsole</div>;
}

describe('Leertaste (Push-to-talk)', () => {
  let gesendet: ClientNachricht[];
  beforeEach(() => {
    gesendet = [];
    useJarvis.setState({
      ...anfangsZustand,
      verbindung: 'offen',
      ansicht: 'konsole',
      status: { version: '1', modell: 'x', stimme: { aktiv: false, weckwort: 'hey_jarvis', hoert: false }, integrationen: 0, werkzeuge: 0 },
      sender: (n) => {
        gesendet.push(n);
        return true;
      },
    });
  });

  it('sendet beim Drücken genau einmal „zuhoeren“ und schaltet die Stimme nicht um', () => {
    render(<Huelle />);
    fireEvent.keyDown(document.body, { code: 'Space', key: ' ' });
    fireEvent.keyDown(document.body, { code: 'Space', key: ' ', repeat: true });
    expect(document.documentElement.dataset.ptt).toBe('1');
    fireEvent.keyUp(document.body, { code: 'Space', key: ' ' });
    expect(document.documentElement.dataset.ptt).toBeUndefined();
    expect(gesendet).toEqual([{ typ: 'zuhoeren' }]);
    expect(gesendet.some((n) => n.typ === 'stimme')).toBe(false);
  });

  it('ignoriert die Leertaste in Eingabefeldern und bei offener Freigabe', () => {
    render(
      <>
        <Huelle />
        <input aria-label="feld" />
      </>,
    );
    const feld = document.querySelector('input')!;
    fireEvent.keyDown(feld, { code: 'Space', key: ' ' });
    useJarvis.setState({ freigaben: [{ id: 'f1', werkzeug: 'shell', argumente: {}, grund: 'x', risiko: 'kritisch' }] as never });
    fireEvent.keyDown(document.body, { code: 'Space', key: ' ' });
    expect(gesendet).toEqual([]);
  });
});
