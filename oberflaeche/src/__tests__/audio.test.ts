import { describe, expect, it } from 'vitest';
import {
  BrowserAudio,
  float32ZuInt16,
  pcmPegel,
  workletQuelltext,
  type AudioContextLike,
  type BufferSourceLike,
  type WorkletLike,
} from '../lib/audio';

class FakeSource implements BufferSourceLike {
  buffer = null;
  gestartet: number | null = null;
  gestoppt = false;
  onended: (() => void) | null = null;
  connect() {
    return undefined;
  }
  start(zeit?: number) {
    this.gestartet = zeit ?? 0;
  }
  stop() {
    this.gestoppt = true;
    this.onended?.();
  }
}

function fakeContext(rate = 48000) {
  const quellen: FakeSource[] = [];
  const puffer: { kanaele: number; laenge: number; rate: number }[] = [];
  const ctx: AudioContextLike & { quellen: FakeSource[]; puffer: typeof puffer; resumed: number } = {
    sampleRate: rate,
    currentTime: 10,
    destination: {},
    state: 'suspended',
    resumed: 0,
    quellen,
    puffer,
    async resume() {
      this.resumed += 1;
      this.state = 'running';
    },
    async close() {
      this.state = 'closed';
    },
    createBuffer(kanaele, laenge, r) {
      puffer.push({ kanaele, laenge, rate: r });
      const daten = new Float32Array(laenge);
      return { getChannelData: () => daten, duration: laenge / r };
    },
    createBufferSource() {
      const q = new FakeSource();
      quellen.push(q);
      return q;
    },
    createMediaStreamSource() {
      return { connect: () => undefined, disconnect: () => undefined };
    },
  };
  return ctx;
}

class FakeKnoten implements WorkletLike {
  port: { onmessage: ((ev: { data: unknown }) => void) | null } = { onmessage: null };
  verbunden = 0;
  getrennt = 0;
  connect() {
    this.verbunden += 1;
    return undefined;
  }
  disconnect() {
    this.getrennt += 1;
  }
}

function fakeStream() {
  const tracks = [{ gestoppt: 0, stop() { this.gestoppt += 1; } }];
  return { getTracks: () => tracks, tracks } as unknown as MediaStream & { tracks: typeof tracks };
}

describe('Audio-Helfer', () => {
  it('float32ZuInt16 begrenzt und skaliert', () => {
    expect(Array.from(float32ZuInt16(new Float32Array([0, 1, -1, 2, -2, 0.5])))).toEqual([0, 32767, -32768, 32767, -32768, 16384]);
  });

  it('pcmPegel liegt zwischen 0 und 1 und steigt mit der Lautstärke', () => {
    const leise = new Int16Array([10, -10, 10, -10]);
    const laut = new Int16Array([20000, -20000, 20000, -20000]);
    expect(pcmPegel(new Int16Array(0))).toBe(0);
    expect(pcmPegel(leise)).toBeLessThan(pcmPegel(laut));
    expect(pcmPegel(laut)).toBeLessThanOrEqual(1);
  });

  it('Worklet-Quelltext registriert den Prozessor mit Blockgröße', () => {
    const q = workletQuelltext(2048);
    expect(q).toContain("registerProcessor('javit-aufnahme'");
    expect(q).toContain('new Float32Array(2048)');
  });
});

describe('BrowserAudio', () => {
  it('start öffnet Mikrofon, sendet int16-Blöcke und meldet den Pegel; stop räumt auf', async () => {
    const ctx = fakeContext(44100);
    const knoten = new FakeKnoten();
    const strom = fakeStream();
    const gesendet: ArrayBuffer[] = [];
    const pegel: number[] = [];
    const audio = new BrowserAudio({
      senden: (d) => {
        gesendet.push(d);
        return true;
      },
      onPegel: (w) => pegel.push(w),
      fabrik: () => ctx,
      medien: async () => strom,
      knoten: async () => knoten,
    });
    expect(await audio.start()).toBe(44100);
    expect(audio.aktiv && ctx.resumed === 1 && knoten.verbunden === 0).toBe(true);
    const block = new Int16Array([1000, -1000, 1000, -1000]).buffer;
    knoten.port.onmessage?.({ data: block });
    knoten.port.onmessage?.({ data: 'kein Puffer' });
    expect(gesendet).toEqual([block]);
    expect(pegel).toHaveLength(1);
    expect(await audio.start()).toBe(44100); // zweiter Start ändert nichts
    audio.stop();
    expect(audio.aktiv).toBe(false);
    expect(knoten.getrennt).toBe(1);
    expect(strom.tracks[0]!.gestoppt).toBe(1);
  });

  it('abspielen plant Blöcke lückenlos, leeren stoppt alles', () => {
    const ctx = fakeContext();
    const audio = new BrowserAudio({ senden: () => true, fabrik: () => ctx });
    audio.abspielen(new Int16Array(2400).buffer); // 0,1 s bei 24 kHz
    audio.abspielen(new Int16Array(4800).buffer); // 0,2 s
    audio.abspielen(new ArrayBuffer(0)); // leer → ignoriert
    expect(ctx.puffer).toEqual([
      { kanaele: 1, laenge: 2400, rate: 24000 },
      { kanaele: 1, laenge: 4800, rate: 24000 },
    ]);
    expect(ctx.quellen.map((q) => q.gestartet)).toEqual([10.05, 10.15]);
    expect(audio.rest).toBeCloseTo(0.35, 5);
    audio.leeren();
    expect(ctx.quellen.every((q) => q.gestoppt)).toBe(true);
    expect(audio.rest).toBe(0);
    // Nach dem Leeren beginnt die Planung wieder bei „jetzt“
    audio.abspielen(new Int16Array(2400).buffer);
    expect(ctx.quellen[2]!.gestartet).toBe(10.05);
  });
});
