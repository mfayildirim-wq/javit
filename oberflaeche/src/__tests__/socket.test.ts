import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { JarvisSocket, backoff, istServerEvent, type SocketLike } from '../api/socket';

class FakeSocket implements SocketLike {
  static alle: FakeSocket[] = [];
  readyState = 0;
  onopen: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  gesendet: string[] = [];
  constructor(public url: string) {
    FakeSocket.alle.push(this);
  }
  send(d: string) {
    this.gesendet.push(d);
  }
  close() {
    this.readyState = 3;
  }
  oeffnen() {
    this.readyState = 1;
    this.onopen?.({});
  }
  schliessen() {
    this.readyState = 3;
    this.onclose?.({});
  }
}

describe('Reconnect-Logik', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.alle = [];
  });
  afterEach(() => vi.useRealTimers());

  const erzeugen = () => {
    const status = vi.fn();
    const events = vi.fn();
    const s = new JarvisSocket({
      url: 'ws://test/ws',
      onEvent: events,
      onStatus: status,
      factory: (u) => new FakeSocket(u),
      minVerzoegerung: 500,
      maxVerzoegerung: 4000,
    });
    return { s, status, events };
  };

  it('backoff wächst exponentiell und ist gedeckelt', () => {
    expect([0, 1, 2, 3, 4, 5].map((v) => backoff(v, 500, 4000))).toEqual([500, 1000, 2000, 4000, 4000, 4000]);
  });

  it('verbindet nach Abbruch mit wachsender Wartezeit neu und setzt nach Erfolg zurück', () => {
    const { s, status } = erzeugen();
    s.start();
    expect(FakeSocket.alle).toHaveLength(1);
    expect(status).toHaveBeenLastCalledWith('verbinde', 0);

    FakeSocket.alle[0]!.schliessen(); // Kern nicht erreichbar
    expect(status).toHaveBeenLastCalledWith('getrennt', 1);
    vi.advanceTimersByTime(499);
    expect(FakeSocket.alle).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.alle).toHaveLength(2);

    FakeSocket.alle[1]!.schliessen();
    vi.advanceTimersByTime(999);
    expect(FakeSocket.alle).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.alle).toHaveLength(3);

    FakeSocket.alle[2]!.schliessen();
    vi.advanceTimersByTime(2000);
    expect(FakeSocket.alle).toHaveLength(4);

    FakeSocket.alle[3]!.oeffnen();
    expect(status).toHaveBeenLastCalledWith('offen', 0);
    expect(s.versuche).toBe(0);

    // Nach erfolgreicher Verbindung beginnt das Backoff wieder bei 500 ms
    FakeSocket.alle[3]!.schliessen();
    vi.advanceTimersByTime(500);
    expect(FakeSocket.alle).toHaveLength(5);
    s.stop();
  });

  it('Wartezeit bleibt am Deckel', () => {
    const { s } = erzeugen();
    s.start();
    for (let i = 0; i < 6; i++) {
      FakeSocket.alle.at(-1)!.schliessen();
      vi.advanceTimersByTime(4000);
    }
    expect(FakeSocket.alle).toHaveLength(7);
    s.stop();
  });

  it('stop() beendet die Wiederverbindung', () => {
    const { s } = erzeugen();
    s.start();
    FakeSocket.alle[0]!.schliessen();
    s.stop();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.alle).toHaveLength(1);
  });

  it('leitet nur gültige Events weiter und sendet nur bei offener Verbindung', () => {
    const { s, events } = erzeugen();
    s.start();
    const ws = FakeSocket.alle[0]!;
    expect(s.senden({ typ: 'abbrechen' })).toBe(false);
    ws.oeffnen();
    ws.onmessage?.({ data: JSON.stringify({ typ: 'zustand', zustand: 'denkt' }) });
    ws.onmessage?.({ data: '{kaputt' });
    ws.onmessage?.({ data: JSON.stringify({ typ: 'unbekannt' }) });
    expect(events).toHaveBeenCalledTimes(1);
    expect(events).toHaveBeenCalledWith({ typ: 'zustand', zustand: 'denkt' });
    expect(s.senden({ typ: 'nachricht', text: 'Hallo', sprechen: false })).toBe(true);
    expect(JSON.parse(ws.gesendet[0]!)).toEqual({ typ: 'nachricht', text: 'Hallo', sprechen: false });
    s.stop();
  });

  it('istServerEvent erkennt Typen', () => {
    expect(istServerEvent({ typ: 'pegel', wert: 1 })).toBe(true);
    expect(istServerEvent({ typ: 'nope' })).toBe(false);
    expect(istServerEvent(null)).toBe(false);
  });
});
