// Kleine Hilfen für Bausteine: erlaubte Werte, Ton-Klassen, Abstände.
import type { CSSProperties } from 'react';

export function wahl<T extends string>(wert: unknown, erlaubt: readonly T[], standard: T): T {
  return typeof wert === 'string' && (erlaubt as readonly string[]).includes(wert) ? (wert as T) : standard;
}

const TOENE = ['normal', 'neutral', 'dezent', 'ok', 'warn', 'fehler', 'info'] as const;

/** Klasse `b-ton-…` nur für bekannte Töne. */
export function tonKlasse(ton: unknown, standard = ''): string {
  const t = wahl(ton, TOENE, '' as (typeof TOENE)[number]);
  return t ? `b-ton-${t}` : standard;
}

/** Abstand aus `gap` (Zahl, 0–64 px); sonst Stilabstand per CSS. */
export function abstandStil(gap: unknown): CSSProperties | undefined {
  return typeof gap === 'number' && Number.isFinite(gap) ? { gap: `${Math.min(64, Math.max(0, gap))}px` } : undefined;
}

export function klassen(...teile: (string | false | null | undefined)[]): string {
  return teile.filter(Boolean).join(' ');
}
