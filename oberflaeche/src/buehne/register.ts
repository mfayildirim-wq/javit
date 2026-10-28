// Komponentenregister der Bühne (Katalog jarvis:buehne/1). Befüllt von ./komponenten/index.ts.
import type { ComponentType } from 'react';
import type { BuehnenKomponente } from '../api/types';

export interface BausteinProps {
  k: BuehnenKomponente;
  /** Absoluter Pfad des Datenkontexts (im Listen-Template das Element, sonst ""). */
  basis: string;
  tiefe: number;
}

export const BAUSTEINE: Record<string, ComponentType<BausteinProps>> = {};

export function registrieren(bausteine: Record<string, ComponentType<BausteinProps>>): void {
  Object.assign(BAUSTEINE, bausteine);
}
