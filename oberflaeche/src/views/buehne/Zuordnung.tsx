// Zuordnung Integration → Stil (PUT /api/buehne/zuordnung mit der vollständigen Zuordnung {integration: stilId}).
import { useEffect, useState } from 'react';
import { api } from '../../api/rest';
import type { Integration, Stil } from '../../api/types';
import { Abschnitt } from '../EinstellungsBausteine';

export function Zuordnung({ stile, zuordnung, setZuordnung }: { stile: Stil[]; zuordnung: Record<string, string>; setZuordnung: (z: Record<string, string>) => void }) {
  const [integrationen, setIntegrationen] = useState<Integration[] | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  useEffect(() => {
    api.integrationen().then(setIntegrationen, (e: Error) => setFehler(e.message));
  }, []);

  const setzen = (id: string, stil: string) => {
    setFehler(null);
    // Vollständige Zuordnung senden: der Kern ersetzt sie als Ganzes (null = Standard).
    const neu: Record<string, string | null> = { ...zuordnung, [id]: stil || null };
    setZuordnung(Object.fromEntries(Object.entries(neu).filter((e): e is [string, string] => !!e[1])));
    api.buehneZuordnung(neu).then(
      (z) => {
        if (z && typeof z === 'object' && !Array.isArray(z)) setZuordnung(z);
      },
      (e: Error) => setFehler(e.message),
    );
  };

  return (
    <Abschnitt id="buehne-zuordnung" titel="Stil je Integration" text="Flächen einer Integration erscheinen in diesem Stil, solange die Vorlage keinen eigenen festlegt.">
      {integrationen === null && !fehler && <p className="feld-hilfe">Lade …</p>}
      {integrationen?.length === 0 && <p className="feld-hilfe">Noch keine Integrationen eingerichtet.</p>}
      {integrationen && integrationen.length > 0 && (
        <ul className="zuordnung-liste">
          {integrationen.map((i) => (
            <li key={i.id} className="zuordnung-zeile">
              <span>{i.name}</span>
              <select aria-label={`Stil der Integration „${i.name}“`} value={zuordnung[i.id] ?? ''} onChange={(e) => setzen(i.id, e.target.value)}>
                <option value="">Standard</option>
                {stile.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </li>
          ))}
        </ul>
      )}
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </Abschnitt>
  );
}
