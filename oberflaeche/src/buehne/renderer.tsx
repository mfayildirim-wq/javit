// Renderer der Bühne: Fläche aus dem Store (bzw. statisch für Vorschauen) mit Stil-Variablen.
import type { BuehnenKomponente, StilWerte } from '../api/types';
import './komponenten';
import { FlaechenKontext, Knoten } from './kontext';
import { stilStil, stilWerte } from './stile';
import { useBuehne } from './store';

export { aktionAusloesen } from './aktionen';

export interface FlaechenAnsichtProps {
  surfaceId: string;
  komponenten: Record<string, BuehnenKomponente>;
  daten: Record<string, unknown>;
  werte: StilWerte;
  vorschau?: boolean;
  titel?: string;
}

/** Stellt eine Fläche dar (ab `root`); ohne `root` ein Aufbau-Hinweis. */
export function FlaechenAnsicht({ surfaceId, komponenten, daten, werte, vorschau = false, titel }: FlaechenAnsichtProps) {
  return (
    <div className="buehne-flaeche" data-schema={werte.schema === 'hell' ? 'hell' : 'dunkel'} style={stilStil(werte)} aria-label={titel}>
      <FlaechenKontext.Provider value={{ surfaceId, komponenten, daten, vorschau }}>
        {komponenten.root ? <Knoten id="root" basis="" tiefe={0} /> : <p className="b-aufbau">Fläche wird aufgebaut …</p>}
      </FlaechenKontext.Provider>
    </div>
  );
}

/** Fläche aus dem Bühnen-Store. */
export function Flaeche({ surfaceId }: { surfaceId: string }) {
  const f = useBuehne((s) => s.flaechen[surfaceId]);
  const stile = useBuehne((s) => s.stile);
  if (!f) return null;
  return <FlaechenAnsicht surfaceId={surfaceId} komponenten={f.komponenten} daten={f.daten} werte={stilWerte(f.stil, stile)} titel={f.titel} />;
}
