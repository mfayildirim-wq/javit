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
    const v = (werte[f.name] ?? f.standard ?? '').trim();
    if (!v) {
      if (f.optional) continue;
      return { ok: false, fehler: `„${f.titel}“ fehlt.` };
    }
    if ((f.typ === 'ordner' || f.typ === 'datei') && /[*?]/.test(v)) return { ok: false, fehler: `„${f.titel}“: Platzhalter wie * sind nicht erlaubt – bitte einen Pfad angeben (z. B. ~/Documents).` };
    sauber[f.name] = v;
  }
  return { ok: true, body: { katalog: eintrag.id, werte: sauber } };
}

/** Importiert MCP-Server aus einer JSON-Konfiguration im Format von Claude Desktop / Claude Code
 * (`{"mcpServers": {"name": {"command","args","env"} | {"type":"http","url","headers"}}}`); auch ein
 * einzelner Server-Eintrag ohne Hülle wird angenommen. */
export function mcpJsonParsen(text: string): { ok: true; eintraege: IntegrationAnlegen[] } | { ok: false; fehler: string } {
  let daten: unknown;
  try {
    daten = JSON.parse(text);
  } catch {
    return { ok: false, fehler: 'Kein gültiges JSON. Erwartet wird z. B. {"mcpServers": {"name": {"command": "npx", "args": ["-y", "paket"]}}}' };
  }
  if (!daten || typeof daten !== 'object') return { ok: false, fehler: 'JSON muss ein Objekt sein.' };
  const o = daten as Record<string, unknown>;
  let server: Record<string, unknown>;
  if (o.mcpServers && typeof o.mcpServers === 'object') server = o.mcpServers as Record<string, unknown>;
  else if (o.servers && typeof o.servers === 'object') server = o.servers as Record<string, unknown>;
  else if ('command' in o || 'url' in o) server = { [typeof o.name === 'string' && o.name ? o.name : 'Server']: o };
  else server = o;
  const eintraege: IntegrationAnlegen[] = [];
  for (const [name, roh] of Object.entries(server)) {
    if (!roh || typeof roh !== 'object') continue;
    const s = roh as Record<string, unknown>;
    const strMap = (v: unknown): Record<string, string> =>
      v && typeof v === 'object' ? Object.fromEntries(Object.entries(v as Record<string, unknown>).map(([k, w]) => [k, String(w)])) : {};
    if (typeof s.url === 'string' && s.url) {
      if (!istUrl(s.url)) return { ok: false, fehler: `„${name}“: URL ist ungültig.` };
      eintraege.push({ name, mcp_url: s.url, kopfzeilen: strMap(s.headers) });
    } else if (typeof s.command === 'string' && s.command) {
      const args = Array.isArray(s.args) ? s.args.map(String) : [];
      const befehl = [s.command, ...args].map((a) => (/\s/.test(a) ? JSON.stringify(a) : a)).join(' ');
      eintraege.push({ name, mcp_befehl: befehl, umgebung: strMap(s.env) });
    } else {
      return { ok: false, fehler: `„${name}“: weder command noch url gefunden.` };
    }
  }
  if (eintraege.length === 0) return { ok: false, fehler: 'Keine Server in der JSON gefunden.' };
  return { ok: true, eintraege };
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
