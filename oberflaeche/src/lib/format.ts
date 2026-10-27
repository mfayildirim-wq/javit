import type { Zustand } from '../api/types';

export const ZUSTAND_TEXT: Record<Zustand, string> = {
  bereit: 'Bereit',
  hoert: 'Ich höre zu',
  denkt: 'Denke nach',
  arbeitet: 'Arbeite',
  spricht: 'Spreche',
};

export function dauer(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0).replace('.', ',')} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m} min ${s} s`;
}

export function alsText(wert: unknown, einruecken = 2): string {
  if (wert === null || wert === undefined) return '';
  if (typeof wert === 'string') return wert;
  try {
    return JSON.stringify(wert, null, einruecken);
  } catch {
    return String(wert);
  }
}

/** Kurze einzeilige Vorschau der Argumente, z. B. `query: "Miles Davis", limit: 5`. */
export function argumenteKurz(arg: unknown, max = 70): string {
  let text: string;
  if (arg && typeof arg === 'object' && !Array.isArray(arg)) {
    text = Object.entries(arg as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${typeof v === 'string' ? `"${v}"` : JSON.stringify(v)}`)
      .join(', ');
  } else {
    text = alsText(arg, 0);
  }
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

const uhrFormat = new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const zeitKurz = new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const datumFormat = new Intl.DateTimeFormat('de-DE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

export const uhrzeit = (d: Date) => uhrFormat.format(d);
export const zeitpunkt = (ms: number) => zeitKurz.format(new Date(ms));
export const datum = (d: Date) => datumFormat.format(d);

/** Kalenderwoche nach ISO 8601. */
export function kalenderwoche(d: Date): number {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const tag = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - tag);
  const jahresAnfang = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t.getTime() - jahresAnfang.getTime()) / 86_400_000 + 1) / 7);
}

export function modellAnbieter(id: string): string {
  const p = id.split('/')[0] ?? '';
  const namen: Record<string, string> = {
    ollama: 'Ollama',
    anthropic: 'Anthropic',
    openai: 'OpenAI',
    gemini: 'Google Gemini',
    groq: 'Groq',
    mistral: 'Mistral',
    openrouter: 'OpenRouter',
    deepseek: 'DeepSeek',
    moonshot: 'Kimi (Moonshot)',
    zai: 'GLM (Z.AI)',
    opencode: 'OpenCode',
    xai: 'xAI (Grok)',
  };
  return namen[p] ?? (p || 'Modell');
}

export function modellKurz(id: string): string {
  const i = id.indexOf('/');
  return i >= 0 ? id.slice(i + 1) : id;
}
