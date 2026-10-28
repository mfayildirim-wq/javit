import { render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApprovalDialog } from '../components/ApprovalDialog';
import { Boot } from '../components/Boot';
import { Composer } from '../components/Composer';
import { Konsole } from '../components/Konsole';
import { Marke } from '../components/TopBar';
import { ActivityPanel } from '../components/ActivityPanel';
import { EinstellungenAnsicht } from '../views/Settings';
import { useFenstertitel, useJarvis } from '../state/store';
import { anfangsZustand } from '../state/reducer';
import { assistentName, weckwortAnzeige } from '../lib/name';
import type { Status } from '../api/types';

function status(teil: Partial<Status> = {}): Status {
  return { version: '1', modell: 'x', stimme: { aktiv: true, weckwort: 'javit', hoert: false }, integrationen: 0, werkzeuge: 0, ...teil };
}

function setzen(s: Status | null) {
  useJarvis.setState({ ...anfangsZustand, verbindung: 'offen', status: s, sender: () => true });
}

describe('Name des Assistenten', () => {
  beforeEach(() => setzen(status({ name: 'Javit' })));

  it('Standard „Javit“, wenn der Kern (noch) keinen Namen liefert', () => {
    expect(assistentName(null)).toBe('Javit');
    expect(assistentName({ name: '  ' })).toBe('Javit');
    expect(assistentName({ name: 'Friday' })).toBe('Friday');
  });

  it('Weckwort-Anzeige', () => {
    expect(weckwortAnzeige('javit')).toBe('Javit');
    expect(weckwortAnzeige('javit, hey javit')).toBe('Javit');
    expect(weckwortAnzeige('hey_jarvis')).toBe('Hey Jarvis');
    expect(weckwortAnzeige('~/.jarvis/modelle/openwakeword/javit.onnx')).toBe('Javit');
    expect(weckwortAnzeige(true, 'Friday')).toBe('Friday');
  });

  it('Fenstertitel, Kopfzeile, Boot-Animation', () => {
    renderHook(() => useFenstertitel());
    expect(document.title).toBe('Javit');
    render(<Marke />);
    expect(screen.getByLabelText('Javit')).toHaveTextContent('Javit');
    const { container } = render(<Boot onFertig={() => {}} />);
    expect(container.querySelector('.boot-wort')).toHaveTextContent('Javit');
  });

  it('Name folgt /api/status (auch im Titel)', async () => {
    const { rerender } = render(<Marke />);
    renderHook(() => useFenstertitel());
    setzen(status({ name: 'Friday' }));
    rerender(<Marke />);
    await waitFor(() => expect(document.title).toBe('Friday'));
    expect(screen.getByLabelText('Friday')).toBeInTheDocument();
  });

  it('Platzhalter, Mikrofon-Hinweis, Leerzustände und Zustandszeile', () => {
    render(<Konsole aktiv={false} />);
    expect(screen.getByPlaceholderText('Nachricht an Javit …')).toBeInTheDocument();
    expect(screen.getByLabelText('Nachricht an Javit')).toBeInTheDocument();
    expect(screen.getByTitle('Mikrofon an – „Javit“ aktiv')).toBeInTheDocument();
    expect(screen.getByText('Guten Tag, hier ist Javit. Womit kann ich helfen?')).toBeInTheDocument();
    expect(screen.getByText('Sagen Sie „Javit“ oder tippen Sie unten')).toBeInTheDocument();
    render(<ActivityPanel />);
    expect(screen.getByText(/sobald Javit etwas für Sie erledigt/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Jarvis/);
  });

  it('Freigabe-Dialog fragt „Darf Javit das ausführen?“', () => {
    useJarvis.getState().verarbeiten({
      typ: 'freigabe_noetig', id: 'f1', werkzeug: 'shell_ausfuehren', argumente: {}, grund: 'Test', risiko: 'kritisch',
    });
    render(<ApprovalDialog />);
    expect(screen.getByRole('heading', { name: 'Darf Javit das ausführen?' })).toBeInTheDocument();
  });

  it('anderer Name und anderes Weckwort', () => {
    setzen(status({ name: 'Friday', stimme: { aktiv: true, weckwort: 'hey_jarvis', hoert: false } }));
    render(<Composer />);
    expect(screen.getByPlaceholderText('Nachricht an Friday …')).toBeInTheDocument();
    expect(screen.getByTitle('Mikrofon an – „Hey Jarvis“ aktiv')).toBeInTheDocument();
  });
});

describe('Einstellungen: Name und Weckwort', () => {
  const aufrufe: { methode: string; pfad: string; body: unknown }[] = [];
  beforeEach(() => {
    aufrufe.length = 0;
    setzen(status({ name: 'Javit' }));
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const pfad = String(input);
        const methode = init?.method ?? 'GET';
        aufrufe.push({ methode, pfad, body: init?.body ? JSON.parse(String(init.body)) : undefined });
        const json = (d: unknown) => new Response(JSON.stringify(d), { status: 200, headers: { 'Content-Type': 'application/json' } });
        if (pfad === '/api/einstellungen' && methode === 'GET')
          return json({ name: 'Javit', anrede: 'Sir', anrede_verwenden: true, stimme: { aktiv: true, weckwort: 'javit', weckwort_engine: 'auto', schwelle: 0.5, stt: 'lokal', tts: 'auto' } });
        if (pfad === '/api/modelle') return json({ aktuell: 'x', vorschlaege: [] });
        if (pfad === '/api/gedaechtnis') return json([]);
        if (pfad === '/api/status') return json(status({ name: 'Friday' }));
        return json({ ok: true });
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it('speichert name, stimme.weckwort und weckwort_engine', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    await u.click(await screen.findByRole('tab', { name: 'Stimme' }));
    const name = await screen.findByLabelText('Name des Assistenten');
    expect(name).toHaveValue('Javit');
    expect(screen.getByLabelText('Weckwort')).toHaveValue('javit');
    expect(screen.getByText('Weckwort „Javit“, Spracherkennung und Sprachausgabe.')).toBeInTheDocument();

    await u.clear(name);
    await u.type(name, 'Friday');
    await u.clear(screen.getByLabelText('Weckwort'));
    await u.type(screen.getByLabelText('Weckwort'), 'javit, hey javit');
    await u.click(within(screen.getByRole('radiogroup', { name: 'Weckwort-Erkennung' })).getByRole('radio', { name: 'Vosk (freies Wort)' }));
    expect(screen.getByRole('switch', { name: /Friday antwortet förmlich/ })).toBeInTheDocument();
    await u.click(screen.getByRole('button', { name: 'Einstellungen speichern' }));

    await screen.findByText('Einstellungen gespeichert.');
    const put = aufrufe.find((a) => a.methode === 'PUT' && a.pfad === '/api/einstellungen');
    expect(put?.body).toMatchObject({ name: 'Friday', stimme: { weckwort: 'javit, hey javit', weckwort_engine: 'vosk', aktiv: true } });
    // Status wird neu geladen → Kopfzeile/Titel zeigen den neuen Namen
    await waitFor(() => expect(useJarvis.getState().status?.name).toBe('Friday'));
  });

  it('leerer Name wird als Standard „Javit“ gespeichert', async () => {
    const u = userEvent.setup();
    render(<EinstellungenAnsicht />);
    await u.click(await screen.findByRole('tab', { name: 'Stimme' }));
    await u.clear(await screen.findByLabelText('Name des Assistenten'));
    await u.click(screen.getByRole('button', { name: 'Einstellungen speichern' }));
    await screen.findByText('Einstellungen gespeichert.');
    expect(aufrufe.find((a) => a.methode === 'PUT')?.body).toMatchObject({ name: 'Javit' });
  });
});
