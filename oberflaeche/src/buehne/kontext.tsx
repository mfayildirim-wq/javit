// Darstellungskontext einer Fläche und Hilfen für Bausteine (Werte, Kinder, Aktionen, Bindungen).
import { createContext, useContext, type ReactNode } from 'react';
import type { BuehnenKomponente } from '../api/types';
import { useJarvis } from '../state/store';
import { aktionAusloesen } from './aktionen';
import { istBindung, pfadAufloesen, textAufloesen, wertAufloesen, zeigerLesen, type BindeKontext } from './binder';
import { BAUSTEINE } from './register';
import { useBuehne } from './store';

export const MAX_TIEFE = 12;
export const MAX_LISTE = 500;

export interface FlaechenDaten {
  surfaceId: string;
  komponenten: Record<string, BuehnenKomponente>;
  daten: Record<string, unknown>;
  /** Vorschau (Einstellungen): keine Aktionen, keine Nachrichten an den Kern. */
  vorschau: boolean;
}

export const FlaechenKontext = createContext<FlaechenDaten>({ surfaceId: '', komponenten: {}, daten: {}, vorschau: true });

/** Rendert die Komponente `id` mit Datenbasis `basis`. */
export function Knoten({ id, basis, tiefe }: { id: string; basis: string; tiefe: number }) {
  const { komponenten } = useContext(FlaechenKontext);
  const k = komponenten[id];
  if (!k || tiefe > MAX_TIEFE) return null;
  const Baustein = BAUSTEINE[k.component];
  if (!Baustein) return null;
  return <Baustein k={k} basis={basis} tiefe={tiefe} />;
}

function istObjekt(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x);
}

/** Kinder-Angabe: Liste von IDs oder Template `{path, componentId}` (je Element relative Basis). */
export function kinderListe(kinder: unknown, basis: string, daten: unknown): { id: string; basis: string; schluessel: string }[] {
  if (Array.isArray(kinder)) return kinder.filter((x): x is string => typeof x === 'string').map((id, i) => ({ id, basis, schluessel: `${id}-${i}` }));
  if (istObjekt(kinder) && typeof kinder.path === 'string' && typeof kinder.componentId === 'string') {
    const pfad = pfadAufloesen(kinder.path, basis);
    const quelle = zeigerLesen(daten, pfad);
    const praefix = pfad === '/' ? '' : pfad;
    const schluessel = Array.isArray(quelle) ? quelle.map((_, i) => String(i)) : istObjekt(quelle) ? Object.keys(quelle) : [];
    return schluessel.slice(0, MAX_LISTE).map((s) => ({
      id: kinder.componentId as string,
      basis: `${praefix}/${s.replace(/~/g, '~0').replace(/\//g, '~1')}`,
      schluessel: s,
    }));
  }
  return [];
}

export function useBaustein(k: BuehnenKomponente, basis: string, tiefe: number) {
  const f = useContext(FlaechenKontext);
  const ctx: BindeKontext = { daten: f.daten, basis };
  const kindKnoten = (id: string, b = basis, key?: string): ReactNode => <Knoten key={key ?? id} id={id} basis={b} tiefe={tiefe + 1} />;
  return {
    ctx,
    vorschau: f.vorschau,
    surfaceId: f.surfaceId,
    /** Eigenschaft aufgelöst (Literal, Bindung, Funktion). */
    w: (name: string): unknown => wertAufloesen(k[name], ctx),
    /** Eigenschaft als Text. */
    t: (name: string): string => textAufloesen(k[name], ctx),
    kind: (id: unknown): ReactNode => (typeof id === 'string' ? kindKnoten(id) : null),
    kinder: (): ReactNode[] => kinderListe(k.children, basis, f.daten).map((x) => kindKnoten(x.id, x.basis, x.schluessel)),
    /** Aktion auslösen (in der Vorschau ohne Wirkung). */
    ausloesen: (aktion: unknown, zusatz?: Record<string, unknown>, b: string = basis): boolean =>
      f.vorschau ? false : aktionAusloesen(aktion, { surfaceId: f.surfaceId, quelle: k.id, ctx: { daten: f.daten, basis: b }, zusatz }),
    /** Gebundener Wert einer Eingabe-Eigenschaft (`{path}`) mit absolutem Pfad. */
    bindung: (name: string): { pfad: string | null; wert: unknown } => {
      const roh = k[name];
      if (istBindung(roh)) {
        const pfad = pfadAufloesen(roh.path, basis);
        return { pfad, wert: zeigerLesen(f.daten, pfad) };
      }
      return { pfad: null, wert: wertAufloesen(roh, ctx) };
    },
    /** Lokal in das Datenmodell schreiben. */
    setzen: (pfad: string | null, wert: unknown) => {
      if (pfad && !f.vorschau) useBuehne.getState().datenSetzen(f.surfaceId, pfad, wert);
    },
    /** Wert an den Kern melden (zweiseitige Bindung). */
    melden: (pfad: string | null, wert: unknown) => {
      if (pfad && !f.vorschau) useJarvis.getState().senden({ typ: 'buehne_daten', surfaceId: f.surfaceId, path: pfad, value: wert });
    },
  };
}

export type BausteinHilfen = ReturnType<typeof useBaustein>;
