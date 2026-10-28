// Datenbindung der Bühne: JSON-Pointer (RFC 6901), relative Pfade im Listen-Template,
// Client-Funktionen des Katalogs jarvis:buehne/1 (formatString, formatNumber, formatCurrency,
// formatDate, pluralize) und URL-Prüfungen. Reine Funktionen ohne React.

export type Daten = unknown;

/** Datenkontext beim Auflösen: ganzes Datenmodell + Basis (absoluter Pfad) für relative Pfade. */
export interface BindeKontext {
  daten: Daten;
  basis: string;
}

const SPRACHE = 'de-DE';

/** „/a~1b/m~0n“ → ["a/b", "m~n"]; „/“ und „“ bezeichnen das ganze Dokument. */
export function zeigerTeile(pfad: string): string[] {
  if (!pfad || pfad === '/') return [];
  const ohne = pfad.startsWith('/') ? pfad.slice(1) : pfad;
  return ohne.split('/').map((t) => t.replace(/~1/g, '/').replace(/~0/g, '~'));
}

export function zeigerAusTeilen(teile: (string | number)[]): string {
  return teile.length === 0 ? '/' : '/' + teile.map((t) => String(t).replace(/~/g, '~0').replace(/\//g, '~1')).join('/');
}

function istObjekt(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x);
}

/** Wert unter dem Pfad oder `undefined`. */
export function zeigerLesen(daten: Daten, pfad: string): unknown {
  let aktuell: unknown = daten;
  for (const t of zeigerTeile(pfad)) {
    if (Array.isArray(aktuell)) aktuell = /^\d+$/.test(t) ? aktuell[Number(t)] : undefined;
    else if (istObjekt(aktuell)) aktuell = Object.prototype.hasOwnProperty.call(aktuell, t) ? aktuell[t] : undefined;
    else return undefined;
    if (aktuell === undefined) return undefined;
  }
  return aktuell;
}

// Schlüssel, die Prototypen verändern könnten, werden nie geschrieben.
const VERBOTEN = new Set(['__proto__', 'constructor', 'prototype']);

function setzenRek(knoten: unknown, teile: string[], wert: unknown, loeschen: boolean): unknown {
  const [kopf, ...rest] = teile;
  if (kopf === undefined) return wert;
  if (VERBOTEN.has(kopf)) return knoten;
  if (Array.isArray(knoten)) {
    const index = kopf === '-' ? knoten.length : /^\d+$/.test(kopf) ? Number(kopf) : -1;
    if (index < 0) return knoten;
    const kopie = [...knoten];
    if (rest.length === 0 && loeschen) {
      if (index < kopie.length) kopie.splice(index, 1);
      return kopie;
    }
    kopie[index] = setzenRek(kopie[index], rest, wert, loeschen);
    return kopie;
  }
  const basis: Record<string, unknown> = istObjekt(knoten) ? { ...knoten } : {};
  if (rest.length === 0 && loeschen) {
    delete basis[kopf];
    return basis;
  }
  const naechstes = basis[kopf];
  // Fehlende Zwischenstufe: Array, wenn der nächste Schlüssel ein Index ist.
  const zwischen = naechstes === undefined && rest.length > 0 && /^(\d+|-)$/.test(rest[0] ?? '') ? [] : naechstes;
  basis[kopf] = setzenRek(zwischen, rest, wert, loeschen);
  return basis;
}

/** Setzt unveränderlich (neue Objekte entlang des Pfads), legt Zwischenstufen an. */
export function zeigerSetzen(daten: Daten, pfad: string, wert: unknown): unknown {
  return setzenRek(daten, zeigerTeile(pfad), wert, false);
}

/** Entfernt den Pfad; „/“ leert das ganze Modell. */
export function zeigerLoeschen(daten: Daten, pfad: string): unknown {
  const teile = zeigerTeile(pfad);
  if (teile.length === 0) return {};
  return setzenRek(daten, teile, undefined, true);
}

/** Absoluter Pfad: „/x“ bleibt, „x“ hängt an die Basis an, „.“/„“ = Basis selbst. */
export function pfadAufloesen(pfad: string, basis: string): string {
  if (pfad.startsWith('/')) return pfad;
  const b = basis === '/' ? '' : basis.replace(/\/$/, '');
  if (pfad === '' || pfad === '.') return b || '/';
  return `${b}/${pfad.replace(/^\.\//, '')}`;
}

export function istBindung(x: unknown): x is { path: string } {
  return istObjekt(x) && typeof x.path === 'string' && Object.keys(x).length === 1;
}

function istAufruf(x: unknown): x is { call: string; args: Record<string, unknown> } {
  return istObjekt(x) && typeof x.call === 'string' && istObjekt(x.args);
}

/** Literal, Bindung `{path}` oder Funktionsaufruf `{call, args}` auflösen. */
export function wertAufloesen(wert: unknown, ctx: BindeKontext): unknown {
  if (istBindung(wert)) return zeigerLesen(ctx.daten, pfadAufloesen(wert.path, ctx.basis));
  if (istAufruf(wert)) return funktionAufrufen(wert.call, wert.args, ctx);
  return wert;
}

/** Wie {@link wertAufloesen}, aber immer als anzeigbarer Text. */
export function textAufloesen(wert: unknown, ctx: BindeKontext): string {
  return alsText(wertAufloesen(wert, ctx));
}

export function alsText(v: unknown): string {
  if (v === undefined || v === null) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number') return Number.isFinite(v) ? v.toLocaleString(SPRACHE) : '';
  if (typeof v === 'boolean') return v ? 'ja' : 'nein';
  try {
    return JSON.stringify(v);
  } catch {
    return '';
  }
}

export function alsZahl(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function funktionAufrufen(name: string, rohArgs: Record<string, unknown>, ctx: BindeKontext): unknown {
  // formatString darf seine Vorlage nicht vorab auflösen (enthält ${…}).
  if (name === 'formatString') {
    const vorlage = wertAufloesen(rohArgs.value, ctx);
    return formatString(typeof vorlage === 'string' ? vorlage : alsText(vorlage), ctx);
  }
  const args: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(rohArgs)) args[k] = wertAufloesen(v, ctx);
  switch (name) {
    case 'formatNumber':
      return formatNumber(args.value, args);
    case 'formatCurrency':
      return formatCurrency(args.value, typeof args.currency === 'string' ? args.currency : 'EUR', args);
    case 'formatDate':
      return formatDate(args.value, typeof args.pattern === 'string' ? args.pattern : undefined);
    case 'pluralize':
      return pluralize(alsZahl(args.count ?? args.value) ?? 0, args);
    default:
      return '';
  }
}

/** „${/user/name}, ${anzahl} Treffer“ – Pfade absolut oder relativ zur Basis. */
export function formatString(vorlage: string, ctx: BindeKontext): string {
  return vorlage.replace(/\$\{([^}]*)\}/g, (_, pfad: string) => alsText(zeigerLesen(ctx.daten, pfadAufloesen(pfad.trim(), ctx.basis))));
}

function stellen(x: unknown): number | undefined {
  const n = alsZahl(x);
  return n === null ? undefined : Math.min(20, Math.max(0, Math.round(n)));
}

export function formatNumber(wert: unknown, opt: Record<string, unknown> = {}): string {
  const n = alsZahl(wert);
  if (n === null) return alsText(wert);
  const min = stellen(opt.minimumFractionDigits);
  const max = stellen(opt.maximumFractionDigits);
  return new Intl.NumberFormat(SPRACHE, {
    minimumFractionDigits: min !== undefined && max !== undefined ? Math.min(min, max) : min,
    maximumFractionDigits: max,
    useGrouping: opt.useGrouping === false ? false : undefined,
  }).format(n);
}

export function formatCurrency(wert: unknown, waehrung = 'EUR', opt: Record<string, unknown> = {}): string {
  const n = alsZahl(wert);
  if (n === null) return alsText(wert);
  try {
    return new Intl.NumberFormat(SPRACHE, { style: 'currency', currency: waehrung, maximumFractionDigits: stellen(opt.maximumFractionDigits) }).format(n);
  } catch {
    return `${formatNumber(n)} ${waehrung}`;
  }
}

function datumAus(wert: unknown): Date | null {
  if (wert instanceof Date) return Number.isNaN(wert.getTime()) ? null : wert;
  if (typeof wert === 'number') return new Date(wert);
  if (typeof wert !== 'string' || !wert.trim()) return null;
  const d = new Date(wert);
  return Number.isNaN(d.getTime()) ? null : d;
}

const zwei = (n: number) => String(n).padStart(2, '0');

/** Muster nach Unicode-Art (yyyy, yy, MMMM, MMM, MM, M, dd, d, EEEE, EEE, HH, H, mm, ss); ohne Muster Intl-Standard. */
export function formatDate(wert: unknown, muster?: string): string {
  const d = datumAus(wert);
  if (!d) return alsText(wert);
  if (!muster) return new Intl.DateTimeFormat(SPRACHE, { dateStyle: 'medium', timeStyle: 'short' }).format(d);
  const teile: Record<string, () => string> = {
    yyyy: () => String(d.getFullYear()),
    yy: () => zwei(d.getFullYear() % 100),
    MMMM: () => new Intl.DateTimeFormat(SPRACHE, { month: 'long' }).format(d),
    MMM: () => new Intl.DateTimeFormat(SPRACHE, { month: 'short' }).format(d),
    MM: () => zwei(d.getMonth() + 1),
    M: () => String(d.getMonth() + 1),
    dd: () => zwei(d.getDate()),
    d: () => String(d.getDate()),
    EEEE: () => new Intl.DateTimeFormat(SPRACHE, { weekday: 'long' }).format(d),
    EEE: () => new Intl.DateTimeFormat(SPRACHE, { weekday: 'short' }).format(d),
    HH: () => zwei(d.getHours()),
    H: () => String(d.getHours()),
    mm: () => zwei(d.getMinutes()),
    ss: () => zwei(d.getSeconds()),
  };
  // Längste Token zuerst; Text in '…' bleibt wörtlich.
  return muster.replace(/'([^']*)'|yyyy|yy|MMMM|MMM|MM|M|dd|d|EEEE|EEE|HH|H|mm|ss/g, (treffer, woertlich?: string) =>
    woertlich !== undefined ? woertlich : (teile[treffer]?.() ?? treffer),
  );
}

/** Form nach Anzahl: zero (optional, bei 0), one, other (Intl.PluralRules de-DE). */
export function pluralize(anzahl: number, formen: Record<string, unknown>): string {
  if (anzahl === 0 && typeof formen.zero === 'string') return formen.zero;
  const kategorie = new Intl.PluralRules(SPRACHE).select(anzahl);
  const form = formen[kategorie] ?? formen.other ?? formen.one;
  return typeof form === 'string' ? form : '';
}

export function istHttps(url: unknown): url is string {
  if (typeof url !== 'string') return false;
  try {
    return new URL(url).protocol === 'https:';
  } catch {
    return false;
  }
}

export function istSichereBildUrl(url: unknown): url is string {
  if (typeof url !== 'string') return false;
  return istHttps(url) || /^data:image\/(png|jpe?g|gif|webp|avif|svg\+xml);base64,[A-Za-z0-9+/=\s]+$/i.test(url);
}
