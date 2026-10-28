// Stilwerte → CSS-Variablen (--b-*) am Flächen-Container, Kontrast nach WCAG 2.x.
// Stile sind reine Werte: Farben nur als Hex, Schriftnamen ohne CSS-Steuerzeichen.
import type { CSSProperties } from 'react';
import type { Stil, StilWerte } from '../api/types';

/** Werte von „javit-dunkel“ (Standard, falls ein Stil fehlt). */
export const STANDARD_WERTE: StilWerte = {
  schema: 'dunkel',
  farben: {
    primaer: '#7fe8ff',
    akzent: '#ffb86b',
    hintergrund: '#04080f',
    flaeche: '#0b1624',
    text: '#e2fbff',
    dezent: '#8aa4b8',
    ok: '#5de4a0',
    warn: '#ffc857',
    fehler: '#ff6b6b',
  },
  schrift: { familie: 'Sora Variable, system-ui, sans-serif', basisgroesse: 14 },
  rundung: 10,
  abstand: 12,
  dichte: 'normal',
  schatten: 'weich',
};

export const STANDARD_STIL: Stil = {
  id: 'javit-dunkel',
  name: 'Javit dunkel',
  quelle: { art: 'vordefiniert', wert: 'javit-dunkel' },
  werte: STANDARD_WERTE,
  vorlieben: { liste: 'kacheln', bildgroesse: 'mittel', kennzahlenOben: true },
};

export const FARB_NAMEN: { schluessel: keyof StilWerte['farben']; titel: string }[] = [
  { schluessel: 'primaer', titel: 'Primär' },
  { schluessel: 'akzent', titel: 'Akzent' },
  { schluessel: 'hintergrund', titel: 'Hintergrund' },
  { schluessel: 'flaeche', titel: 'Fläche' },
  { schluessel: 'text', titel: 'Text' },
  { schluessel: 'dezent', titel: 'Dezent' },
  { schluessel: 'ok', titel: 'OK' },
  { schluessel: 'warn', titel: 'Warnung' },
  { schluessel: 'fehler', titel: 'Fehler' },
];

const DICHTE: Record<StilWerte['dichte'], number> = { dicht: 0.75, normal: 1, luftig: 1.3 };
const SCHATTEN: Record<StilWerte['schatten'], string> = {
  keiner: 'none',
  weich: '0 4px 18px rgba(0, 0, 0, 0.22)',
  stark: '0 10px 32px rgba(0, 0, 0, 0.45)',
};

export function istHex(x: unknown): x is string {
  return typeof x === 'string' && /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(x.trim());
}

/** „#abc“ → „#aabbcc“ (für `<input type="color">`); ungültig → null. */
export function hexLang(hex: string): string | null {
  if (!istHex(hex)) return null;
  const h = hex.trim().slice(1).toLowerCase();
  if (h.length === 3) return '#' + [...h].map((c) => c + c).join('');
  return '#' + h.slice(0, 6);
}

function zahlIn(x: unknown, min: number, max: number, standard: number): number {
  return typeof x === 'number' && Number.isFinite(x) ? Math.min(max, Math.max(min, x)) : standard;
}

function schriftSaeubern(familie: unknown): string {
  if (typeof familie !== 'string') return STANDARD_WERTE.schrift.familie;
  const s = familie.replace(/[;{}<>\\()@:]/g, '').replace(/\s+/g, ' ').trim().slice(0, 160);
  return s || STANDARD_WERTE.schrift.familie;
}

/** CSS-Variablen für den Container `.buehne-flaeche`. */
export function stilVariablen(werte: StilWerte | undefined | null): Record<string, string> {
  const w = werte ?? STANDARD_WERTE;
  const farben = (w.farben ?? {}) as Partial<StilWerte['farben']>;
  const v: Record<string, string> = {};
  for (const { schluessel } of FARB_NAMEN) {
    const f = farben[schluessel];
    v[`--b-${schluessel}`] = istHex(f) ? f.trim() : STANDARD_WERTE.farben[schluessel];
  }
  v['--b-schrift'] = schriftSaeubern(w.schrift?.familie);
  v['--b-basis'] = `${zahlIn(w.schrift?.basisgroesse, 10, 22, 14)}px`;
  v['--b-rundung'] = `${zahlIn(w.rundung, 0, 32, 10)}px`;
  v['--b-abstand'] = `${zahlIn(w.abstand, 2, 40, 12)}px`;
  v['--b-dichte'] = String(DICHTE[w.dichte] ?? 1);
  v['--b-schatten'] = SCHATTEN[w.schatten] ?? SCHATTEN.weich;
  return v;
}

export function stilStil(werte: StilWerte | undefined | null): CSSProperties {
  return stilVariablen(werte) as CSSProperties;
}

/** Werte des Stils `id` aus der Sammlung; unbekannt → Standard. */
export function stilWerte(id: string | null | undefined, stile: Record<string, Stil>): StilWerte {
  return (id && stile[id]?.werte) || stile['javit-dunkel']?.werte || STANDARD_WERTE;
}

function kanal(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

/** Relative Leuchtdichte nach WCAG. */
export function leuchtdichte(hex: string): number {
  const h = hexLang(hex);
  if (!h) return 0;
  const r = parseInt(h.slice(1, 3), 16);
  const g = parseInt(h.slice(3, 5), 16);
  const b = parseInt(h.slice(5, 7), 16);
  return 0.2126 * kanal(r) + 0.7152 * kanal(g) + 0.0722 * kanal(b);
}

/** Kontrastverhältnis 1…21 (WCAG AA: ≥ 4,5 für normalen Text). */
export function kontrast(hexA: string, hexB: string): number {
  const a = leuchtdichte(hexA);
  const b = leuchtdichte(hexB);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
