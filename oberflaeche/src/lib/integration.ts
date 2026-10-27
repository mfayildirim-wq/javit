import type { IntegrationAnlegen, KatalogEintrag, RestEndpunkt } from '../api/types';

export interface Paar { schluessel: string; wert: string }

export type Ergebnis = { ok: true; body: IntegrationAnlegen } | { ok: false; fehler: string };

export function paareZuObjekt(paare: Paar[]): Record<string, string> {
  const o: Record<string, string> = {};
  for (const p of paare) {
    const k = p.schluessel.trim();
    if (k) o[k] = p.wert;
  }
  return o;
}

function istUrl(s: string): boolean {
  try {
    const u = new URL(s);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

/** Leitet aus einem Befehl wie `npx -y @scope/server-foo` einen lesbaren Namen ab. */
export function nameAusBefehl(befehl: string): string {
  const teile = befehl.trim().split(/\s+/).filter((t) => t && !t.startsWith('-'));
  const paket = teile[1] ?? teile[0] ?? '';
  const basis = (paket.split('/').pop() ?? paket).replace(/@[^@]*$/, '');
  const ohne = basis.replace(/^(mcp-server-|server-)/, '').replace(/(-mcp|-server|-mcp-server)$/, '');
  if (!ohne) return '';
  return ohne
    .split(/[-_]/)
    .filter(Boolean)
    .map((w) => w[0]!.toUpperCase() + w.slice(1))
    .join(' ');
}

export function nameAusUrl(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, '').replace(/^api\./, '');
    const erster = host.split('.')[0] ?? host;
    return erster ? erster[0]!.toUpperCase() + erster.slice(1) : '';
  } catch {
    return '';
  }
}

export function katalogBody(eintrag: KatalogEintrag, werte: Record<string, string>): Ergebnis {
  const sauber: Record<string, string> = {};
  for (const f of eintrag.benoetigt) {
    const v = (werte[f.name] ?? '').trim();
    if (!v) return { ok: false, fehler: `„${f.titel}“ fehlt.` };
    sauber[f.name] = v;
  }
  return { ok: true, body: { katalog: eintrag.id, werte: sauber } };
}

export function mcpBefehlBody(name: string, befehl: string, umgebung: Paar[]): Ergebnis {
  const b = befehl.trim();
  if (!b) return { ok: false, fehler: 'Befehl fehlt, z. B. npx -y @modelcontextprotocol/server-everything' };
  const n = name.trim() || nameAusBefehl(b);
  if (!n) return { ok: false, fehler: 'Name fehlt.' };
  return { ok: true, body: { name: n, mcp_befehl: b, umgebung: paareZuObjekt(umgebung) } };
}

export function mcpUrlBody(name: string, url: string, kopfzeilen: Paar[]): Ergebnis {
  const u = url.trim();
  if (!istUrl(u)) return { ok: false, fehler: 'Bitte eine gültige http(s)-URL angeben.' };
  const n = name.trim() || nameAusUrl(u);
  if (!n) return { ok: false, fehler: 'Name fehlt.' };
  return { ok: true, body: { name: n, mcp_url: u, kopfzeilen: paareZuObjekt(kopfzeilen) } };
}

export type AuthArt = 'keine' | 'bearer' | 'basic' | 'api_key';

export function openapiBody(name: string, url: string, authArt: AuthArt, authWert: string): Ergebnis {
  const u = url.trim();
  if (!istUrl(u)) return { ok: false, fehler: 'Bitte die URL der OpenAPI-Beschreibung angeben.' };
  const n = name.trim() || nameAusUrl(u);
  if (!n) return { ok: false, fehler: 'Name fehlt.' };
  if (authArt === 'keine') return { ok: true, body: { name: n, openapi_url: u } };
  if (!authWert.trim()) return { ok: false, fehler: 'Wert für die Anmeldung fehlt.' };
  return { ok: true, body: { name: n, openapi_url: u, auth: { art: authArt, wert: authWert.trim() } } };
}

export interface RestParamZeile { name: string; typ: 'text' | 'zahl' | 'bool' }
export interface RestEntwurf {
  name: string;
  methode: string;
  url: string;
  beschreibung: string;
  parameter: RestParamZeile[];
}

export const REST_METHODEN = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const;

function werkzeugName(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/[äöüß]/g, (c) => ({ ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss' })[c] ?? c)
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

export function restBody(name: string, endpunkte: RestEntwurf[]): Ergebnis {
  const n = name.trim();
  if (!n) return { ok: false, fehler: 'Name der Integration fehlt.' };
  if (endpunkte.length === 0) return { ok: false, fehler: 'Mindestens einen Endpunkt angeben.' };
  const rest: RestEndpunkt[] = [];
  for (const [i, e] of endpunkte.entries()) {
    const u = e.url.trim();
    if (!istUrl(u)) return { ok: false, fehler: `Endpunkt ${i + 1}: URL ist ungültig.` };
    const wn = werkzeugName(e.name) || werkzeugName(`${n}_${i + 1}`);
    const parameter: Record<string, string> = {};
    for (const p of e.parameter) {
      const pn = p.name.trim();
      if (pn) parameter[pn] = p.typ;
    }
    rest.push({
      name: wn,
      methode: (e.methode || 'GET').toUpperCase(),
      url: u,
      parameter,
      beschreibung: e.beschreibung.trim() || `${e.methode.toUpperCase()} ${u}`,
    });
  }
  return { ok: true, body: { name: n, rest } };
}
