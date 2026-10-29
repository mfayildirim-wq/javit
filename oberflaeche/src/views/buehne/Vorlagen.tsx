// Einstellungen → Bühne → Vorlagen: Liste, umbenennen, Stil, Version zurück, löschen, Rezepte.
import { useEffect, useState, type FormEvent } from 'react';
import { Pencil, RotateCcw, Trash2 } from 'lucide-react';
import { api } from '../../api/rest';
import type { Rezept, Stil, Vorlage } from '../../api/types';
import { Abschnitt } from '../EinstellungsBausteine';

/** Lesbare Kurzform eines Rezepts (hinter dem Aktionsnamen). */
export function rezeptText(r: Rezept): string {
  if (r.art === 'werkzeug') return ` → Werkzeug ${r.werkzeug ?? ''}`;
  if (r.art === 'zeigen') return ` → Zeigen: ${r.werkzeug ?? '–'} → ${r.titel || r.vorlageZiel || 'neue Fläche'}`;
  return ` → Auftrag: ${r.auftrag ?? ''}`;
}

function VorlageEintrag({ v, rezepte, stile, neuLaden, fehler }: { v: Vorlage; rezepte: Rezept[]; stile: Stil[]; neuLaden: () => void; fehler: (t: string) => void }) {
  const [umbenennen, setUmbenennen] = useState(false);
  const [name, setName] = useState(v.name);
  const [loeschen, setLoeschen] = useState(false);
  const aufruf = (p: Promise<unknown>) => p.then(neuLaden, (e: Error) => fehler(e.message));

  const speichern = (e: FormEvent) => {
    e.preventDefault();
    const neu = name.trim();
    if (!neu || neu === v.name) return setUmbenennen(false);
    setUmbenennen(false);
    void aufruf(api.buehneVorlageAendern(v.id, { name: neu }));
  };
  const aktionen = Object.entries(v.aktionen ?? {});
  return (
    <li className="vorlage" aria-label={v.name}>
      <div className="vorlage-kopf">
        {umbenennen ? (
          <form onSubmit={speichern} className="feld-reihe">
            <input aria-label="Neuer Name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            <button type="submit" className="knopf klein">Speichern</button>
          </form>
        ) : (
          <strong>{v.name}</strong>
        )}
        <span className="marke-chip">Version {v.version}{v.versionen ? ` / ${v.versionen}` : ''}</span>
      </div>
      {v.zweck && <p className="vorlage-zweck">{v.zweck}</p>}
      <p className="feld-hilfe">
        Datenquelle: <code>{v.datenquelle?.werkzeug ?? '–'}</code>
      </p>
      {aktionen.length > 0 && (
        <ul className="vorlage-aktionen" aria-label="Aktionen">
          {aktionen.map(([aktion, rezeptId]) => {
            const r = rezepte.find((x) => x.id === rezeptId || x.name === aktion);
            return (
              <li key={aktion}>
                <code>{aktion}</code>
                <span className="feld-hilfe">{r ? rezeptText(r) : ' → noch kein Rezept'}</span>
                {r && (
                  <button type="button" className="icon-knopf" aria-label={`Rezept „${aktion}“ löschen`} onClick={() => void aufruf(api.buehneRezeptLoeschen(r.id))}>
                    <Trash2 size={13} aria-hidden="true" />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <div className="feld-reihe vorlage-knoepfe">
        <select aria-label={`Stil der Vorlage „${v.name}“`} value={v.stil ?? ''} onChange={(e) => void aufruf(api.buehneVorlageAendern(v.id, { stil: e.target.value || null }))}>
          <option value="">Stil der Integration</option>
          {stile.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <button type="button" className="knopf klein" onClick={() => setUmbenennen(true)}>
          <Pencil size={13} aria-hidden="true" /> Umbenennen
        </button>
        <button type="button" className="knopf klein" disabled={(v.versionen ?? v.version) < 2} onClick={() => void aufruf(api.buehneVorlageZurueck(v.id))}>
          <RotateCcw size={13} aria-hidden="true" /> Version zurück
        </button>
        {loeschen ? (
          <button type="button" className="knopf klein gefahr" onClick={() => void aufruf(api.buehneVorlageLoeschen(v.id))}>Wirklich löschen</button>
        ) : (
          <button type="button" className="knopf klein leise" aria-label="Vorlage löschen" onClick={() => setLoeschen(true)}>
            <Trash2 size={13} aria-hidden="true" /> Löschen
          </button>
        )}
      </div>
    </li>
  );
}

export function Vorlagen({ stile }: { stile: Stil[] }) {
  const [vorlagen, setVorlagen] = useState<Vorlage[] | null>(null);
  const [rezepte, setRezepte] = useState<Rezept[]>([]);
  const [fehler, setFehler] = useState<string | null>(null);
  const laden = () => {
    Promise.all([api.buehneVorlagen(), api.buehneRezepte()]).then(
      ([v, r]) => {
        setVorlagen(v);
        setRezepte(r);
      },
      (e: Error) => setFehler(e.message),
    );
  };
  useEffect(laden, []);
  return (
    <Abschnitt id="buehne-vorlagen" titel="Vorlagen" text="Oberflächen, die der Assistent einmal gebaut hat und mit neuen Daten wiederverwendet. Gelten in allen Unterhaltungen.">
      {vorlagen === null && !fehler && <p className="feld-hilfe">Lade …</p>}
      {vorlagen?.length === 0 && <p className="feld-hilfe">Noch keine Vorlagen – sie entstehen, wenn der Assistent etwas auf der Bühne zeigt.</p>}
      {vorlagen && vorlagen.length > 0 && (
        <ul className="vorlagen-liste">
          {vorlagen.map((v) => (
            <VorlageEintrag key={`${v.id}-${v.version}-${v.name}`} v={v} rezepte={rezepte.filter((r) => r.vorlage === v.id)} stile={stile} neuLaden={laden} fehler={setFehler} />
          ))}
        </ul>
      )}
      {fehler && <p className="formular-fehler">{fehler}</p>}
    </Abschnitt>
  );
}
