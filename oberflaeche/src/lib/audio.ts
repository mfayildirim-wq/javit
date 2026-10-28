/**
 * Audio im Browser: Mikrofon aufnehmen (AudioWorklet → int16-Blöcke an den Kern) und PCM-Strom des Kerns
 * (int16, 24 kHz) lückenlos abspielen. Für Tests sind AudioContext, Mikrofon und Worklet-Knoten austauschbar.
 */

export interface AudioQuelleLike {
  connect(ziel: unknown): unknown;
  disconnect(): void;
}

export interface WorkletLike {
  port: { onmessage: ((ev: { data: unknown }) => void) | null };
  connect(ziel: unknown): unknown;
  disconnect(): void;
}

export interface AudioBufferLike {
  getChannelData(kanal: number): Float32Array;
  duration: number;
}

export interface BufferSourceLike {
  buffer: AudioBufferLike | null;
  connect(ziel: unknown): unknown;
  start(zeit?: number): void;
  stop(zeit?: number): void;
  onended: (() => void) | null;
}

export interface AudioContextLike {
  sampleRate: number;
  currentTime: number;
  destination: unknown;
  state: string;
  resume(): Promise<void>;
  close(): Promise<void>;
  createBuffer(kanaele: number, laenge: number, rate: number): AudioBufferLike;
  createBufferSource(): BufferSourceLike;
  createMediaStreamSource(strom: MediaStream): AudioQuelleLike;
  audioWorklet?: { addModule(url: string): Promise<void> };
}

export interface BrowserAudioOptionen {
  /** Sendet einen int16-Block an den Kern; false, wenn keine Verbindung besteht. */
  senden: (daten: ArrayBuffer) => boolean;
  onPegel?: (wert: number) => void;
  fabrik?: () => AudioContextLike;
  medien?: () => Promise<MediaStream>;
  knoten?: (ctx: AudioContextLike, name: string) => Promise<WorkletLike>;
  /** Blockgröße der Aufnahme in Samples (Standard 4096 ≈ 85 ms bei 48 kHz). */
  blockgroesse?: number;
}

export const WORKLET_NAME = 'javit-aufnahme';
export const AUSGABE_RATE = 24000;

/** Float32 (−1..1) → int16 mit Begrenzung. */
export function float32ZuInt16(f: Float32Array): Int16Array {
  const out = new Int16Array(f.length);
  for (let i = 0; i < f.length; i += 1) {
    const x = Math.max(-1, Math.min(1, f[i] ?? 0));
    out[i] = x < 0 ? Math.round(x * 32768) : Math.round(x * 32767);
  }
  return out;
}

/** Pegel 0..1 eines int16-Blocks (wie im Kern: −60 dBFS … −12 dBFS). */
export function pcmPegel(daten: Int16Array): number {
  if (daten.length === 0) return 0;
  let summe = 0;
  for (let i = 0; i < daten.length; i += 1) {
    const x = (daten[i] ?? 0) / 32768;
    summe += x * x;
  }
  const rms = Math.sqrt(summe / daten.length);
  const db = rms > 1e-9 ? 20 * Math.log10(rms) : -120;
  return Math.max(0, Math.min(1, (db + 60) / 48));
}

/** Worklet-Prozessor: sammelt Mono-Samples und sendet int16-Blöcke an den Hauptthread. */
export function workletQuelltext(blockgroesse: number): string {
  return `
class JavitAufnahme extends AudioWorkletProcessor {
  constructor() { super(); this.puffer = new Float32Array(${blockgroesse}); this.gefuellt = 0; }
  process(eingaben) {
    const kanal = eingaben[0] && eingaben[0][0];
    if (!kanal) return true;
    for (let i = 0; i < kanal.length; i += 1) {
      this.puffer[this.gefuellt++] = kanal[i];
      if (this.gefuellt === this.puffer.length) {
        const out = new Int16Array(this.puffer.length);
        for (let k = 0; k < out.length; k += 1) {
          const x = Math.max(-1, Math.min(1, this.puffer[k]));
          out[k] = x < 0 ? Math.round(x * 32768) : Math.round(x * 32767);
        }
        this.port.postMessage(out.buffer, [out.buffer]);
        this.gefuellt = 0;
      }
    }
    return true;
  }
}
registerProcessor('${WORKLET_NAME}', JavitAufnahme);
`;
}

async function standardKnoten(ctx: AudioContextLike, name: string, blockgroesse: number): Promise<WorkletLike> {
  if (!ctx.audioWorklet) throw new Error('AudioWorklet wird von diesem Browser nicht unterstützt.');
  const url = URL.createObjectURL(new Blob([workletQuelltext(blockgroesse)], { type: 'application/javascript' }));
  try {
    await ctx.audioWorklet.addModule(url);
  } finally {
    URL.revokeObjectURL(url);
  }
  const Knoten = (globalThis as unknown as { AudioWorkletNode: new (c: unknown, n: string) => WorkletLike }).AudioWorkletNode;
  return new Knoten(ctx, name);
}

export class BrowserAudio {
  private ctx: AudioContextLike | null = null;
  private strom: MediaStream | null = null;
  private quelle: AudioQuelleLike | null = null;
  private knoten: WorkletLike | null = null;
  private naechsteZeit = 0;
  private laufende = new Set<BufferSourceLike>();
  private readonly opt: BrowserAudioOptionen;

  constructor(opt: BrowserAudioOptionen) {
    this.opt = opt;
  }

  get aktiv(): boolean {
    return this.strom !== null;
  }

  /** Abtastrate des Geräts (nach `start`), sonst 0. */
  get rate(): number {
    return this.ctx?.sampleRate ?? 0;
  }

  private kontext(): AudioContextLike {
    if (this.ctx) return this.ctx;
    const fabrik = this.opt.fabrik ?? (() => {
      const Ctx = (globalThis as unknown as { AudioContext?: new () => AudioContextLike; webkitAudioContext?: new () => AudioContextLike });
      const Klasse = Ctx.AudioContext ?? Ctx.webkitAudioContext;
      if (!Klasse) throw new Error('Web Audio wird von diesem Browser nicht unterstützt.');
      return new Klasse();
    });
    this.ctx = fabrik();
    return this.ctx;
  }

  /** Mikrofon öffnen und Blöcke an den Kern senden; liefert die Abtastrate der Aufnahme. */
  async start(): Promise<number> {
    if (this.strom) return this.rate;
    const ctx = this.kontext();
    if (ctx.state === 'suspended') await ctx.resume();
    const medien = this.opt.medien ?? (() =>
      navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false }));
    const strom = await medien();
    const blockgroesse = this.opt.blockgroesse ?? 4096;
    const knoten = await (this.opt.knoten ? this.opt.knoten(ctx, WORKLET_NAME) : standardKnoten(ctx, WORKLET_NAME, blockgroesse));
    knoten.port.onmessage = (ev) => {
      const daten = ev.data;
      if (!(daten instanceof ArrayBuffer)) return;
      if (this.opt.onPegel) this.opt.onPegel(pcmPegel(new Int16Array(daten)));
      this.opt.senden(daten);
    };
    const quelle = ctx.createMediaStreamSource(strom);
    quelle.connect(knoten);
    this.strom = strom;
    this.quelle = quelle;
    this.knoten = knoten;
    return ctx.sampleRate;
  }

  /** Aufnahme beenden (Wiedergabe bleibt möglich). */
  stop(): void {
    this.knoten?.disconnect();
    this.quelle?.disconnect();
    this.strom?.getTracks().forEach((t) => t.stop());
    this.knoten = null;
    this.quelle = null;
    this.strom = null;
  }

  /** PCM-Block des Kerns (int16 mono) lückenlos an die laufende Wiedergabe anhängen. */
  abspielen(pcm: ArrayBuffer, rate = AUSGABE_RATE): void {
    const n = Math.floor(pcm.byteLength / 2);
    if (n === 0) return;
    const ctx = this.kontext();
    if (ctx.state === 'suspended') void ctx.resume();
    const werte = new Int16Array(pcm, 0, n);
    const puffer = ctx.createBuffer(1, n, rate);
    const kanal = puffer.getChannelData(0);
    for (let i = 0; i < n; i += 1) kanal[i] = (werte[i] ?? 0) / 32768;
    const quelle = ctx.createBufferSource();
    quelle.buffer = puffer;
    quelle.connect(ctx.destination);
    const start = Math.max(ctx.currentTime + 0.05, this.naechsteZeit);
    quelle.onended = () => this.laufende.delete(quelle);
    this.laufende.add(quelle);
    quelle.start(start);
    this.naechsteZeit = start + n / rate;
  }

  /** Wiedergabe sofort abbrechen (Stoppwort, Abbruch). */
  leeren(): void {
    for (const q of this.laufende) {
      try {
        q.stop();
      } catch {
        /* schon zu Ende */
      }
    }
    this.laufende.clear();
    this.naechsteZeit = 0;
  }

  /** Sekunden, die noch abgespielt werden. */
  get rest(): number {
    const ctx = this.ctx;
    if (!ctx) return 0;
    return Math.max(0, this.naechsteZeit - ctx.currentTime);
  }
}
