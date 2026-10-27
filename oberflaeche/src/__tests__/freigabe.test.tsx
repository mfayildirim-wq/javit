import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApprovalDialog, FREIGABE_SEKUNDEN } from '../components/ApprovalDialog';
import { useJarvis } from '../state/store';
import { anfangsZustand } from '../state/reducer';
import type { ClientNachricht } from '../api/types';

describe('Freigabe-Dialog', () => {
  let gesendet: ClientNachricht[];

  beforeEach(() => {
    gesendet = [];
    useJarvis.setState({
      ...anfangsZustand,
      sender: (n) => {
        gesendet.push(n);
        return true;
      },
    });
    useJarvis.getState().verarbeiten({
      typ: 'freigabe_noetig',
      id: 'f-42',
      werkzeug: 'shell_ausfuehren',
      argumente: { befehl: 'rm ~/Downloads/*.dmg' },
      grund: 'Löscht 3 Dateien dauerhaft.',
      risiko: 'kritisch',
    });
  });
  afterEach(() => vi.useRealTimers());

  it('zeigt Werkzeug, Grund, Argumente und Risiko', () => {
    render(<ApprovalDialog />);
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByText('shell_ausfuehren')).toBeInTheDocument();
    expect(screen.getByText('Löscht 3 Dateien dauerhaft.')).toBeInTheDocument();
    expect(screen.getByText(/rm ~\/Downloads/)).toBeInTheDocument();
    expect(screen.getByText('Kritische Aktion')).toBeInTheDocument();
    expect(screen.getByRole('timer')).toHaveTextContent(String(FREIGABE_SEKUNDEN));
  });

  it('„Erlauben“ sendet {typ: freigabe, id, erlaubt: true} und schließt', () => {
    render(<ApprovalDialog />);
    fireEvent.click(screen.getByRole('button', { name: 'Erlauben' }));
    expect(gesendet).toEqual([{ typ: 'freigabe', id: 'f-42', erlaubt: true }]);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('„Ablehnen“ sendet erlaubt: false und ist vorausgewählt', () => {
    render(<ApprovalDialog />);
    const ablehnen = screen.getByRole('button', { name: /Ablehnen/ });
    expect(ablehnen).toHaveFocus();
    fireEvent.click(ablehnen);
    expect(gesendet).toEqual([{ typ: 'freigabe', id: 'f-42', erlaubt: false }]);
  });

  it('lehnt nach Ablauf des Countdowns automatisch ab', () => {
    vi.useFakeTimers({ now: Date.now() });
    // Zeitstempel der Anfrage auf "jetzt" der Fake-Uhr setzen
    useJarvis.setState((s) => ({ freigaben: s.freigaben.map((f) => ({ ...f, empfangen: Date.now() })) }));
    render(<ApprovalDialog />);
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByRole('timer')).toHaveTextContent('60');
    expect(gesendet).toHaveLength(0);
    act(() => {
      vi.advanceTimersByTime(60_500);
    });
    expect(gesendet).toEqual([{ typ: 'freigabe', id: 'f-42', erlaubt: false }]);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('zeigt die nächste Anfrage, wenn mehrere warten', () => {
    useJarvis.getState().verarbeiten({ typ: 'freigabe_noetig', id: 'f-43', werkzeug: 'mail_senden', argumente: {}, grund: 'Sendet Mail', risiko: 'aendern' });
    render(<ApprovalDialog />);
    expect(screen.getByText(/1 weitere Anfrage wartet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erlauben' }));
    expect(screen.getByText('mail_senden')).toBeInTheDocument();
    expect(screen.getByText('Ändert Daten')).toBeInTheDocument();
  });

  it('übernimmt die Wartezeit des Kerns (timeout) für den Countdown', () => {
    useJarvis.getState().verarbeiten({
      typ: 'freigabe_noetig',
      id: 'f-42',
      werkzeug: 'shell_ausfuehren',
      argumente: {},
      grund: 'x',
      risiko: 'kritisch',
      timeout: 45,
    });
    render(<ApprovalDialog />);
    expect(screen.getByRole('timer')).toHaveTextContent('45');
  });
});
