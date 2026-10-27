import type { Status } from '../api/types';

/** Standardname des Assistenten (Kern: jarvis/konfig.py STANDARD_NAME). */
export const STANDARD_NAME = 'Javit';

/** Name aus /api/status (optionales Feld `name`), sonst der Standard. */
export function assistentName(status: Pick<Status, 'name'> | null | undefined): string {
  const n = typeof status?.name === 'string' ? status.name.trim() : '';
  return n || STANDARD_NAME;
}

/** Anzeige des (ersten) Weckworts: „hey_jarvis“ → „Hey Jarvis“, „javit, hey javit“ → „Javit“. */
export function weckwortAnzeige(weckwort: string | boolean | null | undefined, name: string = STANDARD_NAME): string {
  if (typeof weckwort !== 'string' || !weckwort.trim()) return name;
  const erstes = weckwort.split(/[,;]/)[0]!.trim();
  const datei = erstes.match(/([^/\\]+)\.(onnx|tflite)$/i);
  const text = (datei ? datei[1]! : erstes).replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!text) return name;
  return text
    .split(' ')
    .map((w) => w.charAt(0).toLocaleUpperCase('de-DE') + w.slice(1))
    .join(' ');
}
