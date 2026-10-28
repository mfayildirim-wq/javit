// Einstellungen → Bühne → Stile: vordefinierte und eigene, Vorschau, Bearbeiten, Löschen.
import { useState } from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { api } from '../../api/rest';
import type { Stil } from '../../api/types';
import { Abschnitt } from '../EinstellungsBausteine';
import { StilEditor } from './StilEditor';
import { StilVorschau } from './StilVorschau';

export function istEigenerStil(s: Stil): boolean {
  return s.eigen === true || (s.eigen === undefined && s.quelle?.art !== 'vordefiniert');
}

export function StileListe({ stile, neuLaden }: { stile: Stil[]; neuLaden: () => void }) {
  const [bearbeiten, setBearbeiten] = useState<Stil | null>(null);
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);

  const loeschen = (s: Stil) => {
    setFehler(null);
    api.buehneStilLoeschen(s.id).then(
      () => {
        setMeldung(`Stil „${s.name}“ gelöscht.`);
        neuLaden();
      },
      (e: Error) => setFehler(e.message),
    );
  };

  return (
    <Abschnitt id="buehne-stile" titel="Stile" text="Farben, Schrift und Abstände der Flächen. Vordefinierte Stile bleiben unverändert – Änderungen werden als Kopie gespeichert.">
      {bearbeiten && (
        <StilEditor
          key={bearbeiten.id}
          stil={bearbeiten}
          onFertig={(m) => {
            setBearbeiten(null);
            if (m) {
              setMeldung(m);
              neuLaden();
            }
          }}
        />
      )}
      {meldung && <p className="ok-text" role="status">{meldung}</p>}
      <ul className="stile-liste">
        {stile.map((s) => (
          <li key={s.id} aria-label={s.name} className="stil-eintrag">
            <div className="stil-eintrag-kopf">
              <strong>{s.name}</strong>
              <span className={`marke-chip ${istEigenerStil(s) ? 'quelle' : ''}`}>{istEigenerStil(s) ? 'eigen' : 'vordefiniert'}</span>
            </div>
            {s.beschreibung && <p className="feld-hilfe">{s.beschreibung}</p>}
            <StilVorschau werte={s.werte} name={s.name} />
            <div className="feld-reihe">
              <button type="button" className="knopf klein" onClick={() => { setMeldung(null); setBearbeiten(s); }}>
                <Pencil size={13} aria-hidden="true" /> Bearbeiten
              </button>
              {istEigenerStil(s) && (
                <button type="button" className="knopf klein leise" onClick={() => loeschen(s)}>
                  <Trash2 size={13} aria-hidden="true" /> Löschen
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </Abschnitt>
  );
}
