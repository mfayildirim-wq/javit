// Eigener Store der Bühne (getrennt vom globalen useJarvis): Flächen, Stile, aktive Fläche, Höhe.
// verarbeiten() setzt die A2UI-Nachrichten des Ereignisses `buehne` um.
import { create } from 'zustand';
import type { A2uiNachricht, BuehnenKomponente, Flaeche, Stil } from '../api/types';
import { zeigerLoeschen, zeigerSetzen } from './binder';

export const HOEHE_SCHLUESSEL = 'jarvis.buehne.hoehe';
export const HOEHE_STANDARD = 0.45;
export const HOEHE_MIN = 0.2;
export const HOEHE_MAX = 0.8;
export const MAX_KOMPONENTEN = 300;
export const STANDARD_STIL_ID = 'javit-dunkel';

export interface FlaechenZustand {
  surfaceId: string;
  titel: string;
  catalogId: string;
  stil: string;
  vorlage: string | null;
  /** Sichtbare Komponenten (erst, wenn `root` angekommen ist). */
  komponenten: Record<string, BuehnenKomponente>;
  /** Gepufferte Komponenten, solange `root` fehlt (Streaming). */
  puffer: BuehnenKomponente[];
  daten: Record<string, unknown>;
}

export interface BuehnenZustand {
  flaechen: Record<string, FlaechenZustand>;
  /** Reihenfolge der Reiter. */
  reihenfolge: string[];
  aktiv: string | null;
  stile: Record<string, Stil>;
  /** Anteil der Mitte (0.2–0.8). */
  hoehe: number;
  eingeklappt: boolean;

  verarbeiten: (n: A2uiNachricht) => void;
  datenSetzen: (surfaceId: string, pfad: string, wert: unknown) => void;
  ausServer: (flaechen: Flaeche[], stile: Stil[]) => void;
  stileSetzen: (stile: Stil[]) => void;
  stilSetzen: (surfaceId: string, stilId: string) => void;
  vorlageSetzen: (surfaceId: string, vorlage: string | null) => void;
  aktivSetzen: (surfaceId: string) => void;
  flaecheEntfernen: (surfaceId: string) => void;
  hoeheSetzen: (h: number) => void;
  setEingeklappt: (an: boolean) => void;
  zuruecksetzen: () => void;
}

export function hoeheBegrenzen(h: number): number {
  if (!Number.isFinite(h)) return HOEHE_STANDARD;
  return Math.round(Math.min(HOEHE_MAX, Math.max(HOEHE_MIN, h)) * 1000) / 1000;
}

export function hoeheLaden(): number {
  try {
    const roh = localStorage.getItem(HOEHE_SCHLUESSEL);
    const h = roh === null ? NaN : Number(roh);
    return Number.isFinite(h) ? hoeheBegrenzen(h) : HOEHE_STANDARD;
  } catch {
    return HOEHE_STANDARD;
  }
}

function istKomponente(x: unknown): x is BuehnenKomponente {
  return typeof x === 'object' && x !== null && typeof (x as BuehnenKomponente).id === 'string' && typeof (x as BuehnenKomponente).component === 'string';
}

function alsObjekt(x: unknown): Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x) ? (x as Record<string, unknown>) : {};
}

function neueFlaeche(surfaceId: string, teil: Partial<FlaechenZustand> = {}): FlaechenZustand {
  return { surfaceId, titel: surfaceId, catalogId: 'jarvis:buehne/1', stil: STANDARD_STIL_ID, vorlage: null, komponenten: {}, puffer: [], daten: {}, ...teil };
}

/** Neue Komponenten einarbeiten: ohne `root` puffern, sonst Puffer + neue übernehmen (max. 300). */
function komponentenEinarbeiten(f: FlaechenZustand, neue: BuehnenKomponente[]): FlaechenZustand {
  const gueltig = neue.filter(istKomponente);
  const hatRoot = 'root' in f.komponenten || [...f.puffer, ...gueltig].some((k) => k.id === 'root');
  if (!hatRoot) return { ...f, puffer: [...f.puffer, ...gueltig].slice(-MAX_KOMPONENTEN) };
  const komponenten = { ...f.komponenten };
  for (const k of [...f.puffer, ...gueltig]) {
    if (!(k.id in komponenten) && Object.keys(komponenten).length >= MAX_KOMPONENTEN) continue;
    komponenten[k.id] = k;
  }
  return { ...f, komponenten, puffer: [] };
}

const leer = () => ({ flaechen: {}, reihenfolge: [] as string[], aktiv: null, stile: {} as Record<string, Stil>, eingeklappt: false });

export const useBuehne = create<BuehnenZustand>()((set, get) => ({
  ...leer(),
  hoehe: hoeheLaden(),

  verarbeiten: (n) => {
    if (!n || typeof n !== 'object') return;
    const { flaechen, reihenfolge } = get();
    if (n.stil && typeof n.stil.id === 'string') {
      const stil = n.stil;
      set((s) => ({ stile: { ...s.stile, [stil.id]: stil } }));
    }
    if (n.createSurface?.surfaceId) {
      const c = n.createSurface;
      const alt = flaechen[c.surfaceId];
      const f = { ...(alt ?? neueFlaeche(c.surfaceId)) };
      if (c.titel) f.titel = c.titel;
      if (c.catalogId) f.catalogId = c.catalogId;
      if (typeof c.theme?.stil === 'string') f.stil = c.theme.stil;
      if (c.vorlage !== undefined) f.vorlage = c.vorlage ?? null;
      set({
        flaechen: { ...flaechen, [c.surfaceId]: f },
        reihenfolge: alt ? reihenfolge : [...reihenfolge, c.surfaceId],
        aktiv: c.surfaceId,
      });
    }
    if (n.updateComponents?.surfaceId) {
      const u = n.updateComponents;
      const s = get();
      const alt = s.flaechen[u.surfaceId];
      const f = komponentenEinarbeiten(alt ?? neueFlaeche(u.surfaceId), Array.isArray(u.components) ? u.components : []);
      set({
        flaechen: { ...s.flaechen, [u.surfaceId]: f },
        reihenfolge: alt ? s.reihenfolge : [...s.reihenfolge, u.surfaceId],
        aktiv: s.aktiv ?? u.surfaceId,
      });
    }
    if (n.updateDataModel?.surfaceId) {
      const u = n.updateDataModel;
      const s = get();
      const alt = s.flaechen[u.surfaceId] ?? neueFlaeche(u.surfaceId);
      const pfad = u.path || '/';
      const hatWert = 'value' in u && u.value !== undefined;
      const daten = alsObjekt(hatWert ? zeigerSetzen(alt.daten, pfad, u.value) : zeigerLoeschen(alt.daten, pfad));
      set({
        flaechen: { ...s.flaechen, [u.surfaceId]: { ...alt, daten } },
        reihenfolge: s.reihenfolge.includes(u.surfaceId) ? s.reihenfolge : [...s.reihenfolge, u.surfaceId],
        aktiv: s.aktiv ?? u.surfaceId,
      });
    }
    if (n.deleteSurface?.surfaceId) get().flaecheEntfernen(n.deleteSurface.surfaceId);
  },

  datenSetzen: (surfaceId, pfad, wert) =>
    set((s) => {
      const f = s.flaechen[surfaceId];
      if (!f) return s;
      return { flaechen: { ...s.flaechen, [surfaceId]: { ...f, daten: alsObjekt(zeigerSetzen(f.daten, pfad, wert)) } } };
    }),

  ausServer: (liste, stile) => {
    const flaechen: Record<string, FlaechenZustand> = {};
    const reihenfolge: string[] = [];
    for (const fl of Array.isArray(liste) ? liste : []) {
      if (!fl || typeof fl.surfaceId !== 'string') continue;
      const roh = neueFlaeche(fl.surfaceId, {
        titel: fl.titel || fl.surfaceId,
        catalogId: fl.catalogId || 'jarvis:buehne/1',
        stil: fl.stil || STANDARD_STIL_ID,
        vorlage: fl.vorlage ?? null,
        daten: alsObjekt(fl.daten),
      });
      flaechen[fl.surfaceId] = komponentenEinarbeiten(roh, (Array.isArray(fl.components) ? fl.components : []) as BuehnenKomponente[]);
      reihenfolge.push(fl.surfaceId);
    }
    const aktiv = get().aktiv;
    set({ flaechen, reihenfolge, aktiv: aktiv && flaechen[aktiv] ? aktiv : (reihenfolge[0] ?? null) });
    get().stileSetzen(stile);
  },

  stileSetzen: (stile) => {
    if (!Array.isArray(stile)) return;
    set((s) => {
      const neu = { ...s.stile };
      for (const st of stile) if (st && typeof st.id === 'string') neu[st.id] = st;
      return { stile: neu };
    });
  },

  stilSetzen: (surfaceId, stil) =>
    set((s) => {
      const f = s.flaechen[surfaceId];
      return f ? { flaechen: { ...s.flaechen, [surfaceId]: { ...f, stil } } } : s;
    }),

  vorlageSetzen: (surfaceId, vorlage) =>
    set((s) => {
      const f = s.flaechen[surfaceId];
      return f ? { flaechen: { ...s.flaechen, [surfaceId]: { ...f, vorlage } } } : s;
    }),

  aktivSetzen: (surfaceId) => set((s) => (s.flaechen[surfaceId] ? { aktiv: surfaceId } : s)),

  flaecheEntfernen: (surfaceId) =>
    set((s) => {
      if (!s.flaechen[surfaceId]) return s;
      const flaechen = { ...s.flaechen };
      delete flaechen[surfaceId];
      const index = s.reihenfolge.indexOf(surfaceId);
      const reihenfolge = s.reihenfolge.filter((id) => id !== surfaceId);
      const aktiv = s.aktiv === surfaceId ? (reihenfolge[Math.max(0, index - 1)] ?? null) : s.aktiv;
      return { flaechen, reihenfolge, aktiv };
    }),

  hoeheSetzen: (h) => {
    const hoehe = hoeheBegrenzen(h);
    try {
      localStorage.setItem(HOEHE_SCHLUESSEL, String(hoehe));
    } catch {
      /* egal */
    }
    set({ hoehe });
  },

  setEingeklappt: (eingeklappt) => set({ eingeklappt }),

  zuruecksetzen: () => set({ ...leer(), hoehe: hoeheLaden() }),
}));
