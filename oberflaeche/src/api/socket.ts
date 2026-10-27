import { SERVER_EVENT_TYPEN, type ClientNachricht, type ServerEvent } from './types';

export type VerbindungsStatus = 'verbinde' | 'offen' | 'getrennt';

/** Minimale WebSocket-Schnittstelle, damit Tests eine Attrappe einsetzen können. */
export interface SocketLike {
  readyState: number;
  onopen: ((ev: unknown) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  send(daten: string): void;
  close(): void;
}
export type SocketFactory = (url: string) => SocketLike;

export interface SocketOptionen {
  url: string;
  onEvent: (ev: ServerEvent) => void;
  onStatus: (status: VerbindungsStatus, versuche: number) => void;
  factory?: SocketFactory;
  /** Erste Wartezeit vor Wiederverbindung (ms). */
  minVerzoegerung?: number;
  /** Obergrenze der Wartezeit (ms). */
  maxVerzoegerung?: number;
}

const OFFEN = 1;

/** Exponentielles Backoff: min, 2·min, 4·min … gedeckelt bei max. */
export function backoff(versuch: number, min: number, max: number): number {
  return Math.min(max, min * 2 ** Math.max(0, versuch));
}

export function istServerEvent(x: unknown): x is ServerEvent {
  if (typeof x !== 'object' || x === null) return false;
  const typ = (x as { typ?: unknown }).typ;
  return typeof typ === 'string' && (SERVER_EVENT_TYPEN as readonly string[]).includes(typ);
}

export class JarvisSocket {
  private ws: SocketLike | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private fehlversuche = 0;
  private beendet = false;
  private readonly opt: Required<Omit<SocketOptionen, 'factory'>> & { factory: SocketFactory };

  constructor(opt: SocketOptionen) {
    this.opt = {
      minVerzoegerung: 500,
      maxVerzoegerung: 8000,
      factory: (url) => new WebSocket(url) as unknown as SocketLike,
      ...opt,
    };
  }

  get versuche(): number {
    return this.fehlversuche;
  }

  start(): void {
    this.beendet = false;
    this.verbinden();
  }

  stop(): void {
    this.beendet = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      ws.onopen = null;
      try {
        ws.close();
      } catch {
        /* egal */
      }
    }
  }

  /** Sendet eine Nachricht. Liefert false, wenn keine Verbindung besteht. */
  senden(n: ClientNachricht): boolean {
    if (!this.ws || this.ws.readyState !== OFFEN) return false;
    this.ws.send(JSON.stringify(n));
    return true;
  }

  private verbinden(): void {
    if (this.beendet) return;
    this.opt.onStatus('verbinde', this.fehlversuche);
    let ws: SocketLike;
    try {
      ws = this.opt.factory(this.opt.url);
    } catch {
      this.planen();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.fehlversuche = 0;
      this.opt.onStatus('offen', 0);
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return;
      let daten: unknown;
      try {
        daten = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (istServerEvent(daten)) this.opt.onEvent(daten);
    };
    ws.onerror = () => {
      /* onclose folgt */
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.planen();
    };
  }

  private planen(): void {
    if (this.beendet) return;
    const warte = backoff(this.fehlversuche, this.opt.minVerzoegerung, this.opt.maxVerzoegerung);
    this.fehlversuche += 1;
    this.opt.onStatus('getrennt', this.fehlversuche);
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.verbinden();
    }, warte);
  }
}

export function wsUrl(loc: Pick<Location, 'protocol' | 'host'> = window.location): string {
  const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${loc.host}/ws`;
}
