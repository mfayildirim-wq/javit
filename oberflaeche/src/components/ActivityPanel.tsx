import { useEffect, useState } from 'react';
import { Check, LoaderCircle, X } from 'lucide-react';
import { useJarvis, useName } from '../state/store';
import type { WerkzeugAufruf } from '../state/reducer';
import { alsText, argumenteKurz, dauer, zeitpunkt } from '../lib/format';

function LaufzeitAnzeige({ start, ende }: { start: number; ende: number | null }) {
  const [jetzt, setJetzt] = useState(() => Date.now());
  useEffect(() => {
    if (ende !== null) return;
    const t = setInterval(() => setJetzt(Date.now()), 100);
    return () => clearInterval(t);
  }, [ende]);
  return <span className="ereignis-dauer">{dauer((ende ?? jetzt) - start)}</span>;
}

function Eintrag({ w }: { w: WerkzeugAufruf }) {
  const zustand = w.ende === null ? 'laeuft' : w.ok ? 'ok' : 'fehler';
  const argText = alsText(w.argumente);
  const ergText = alsText(w.ergebnis);
  return (
    <li className={`ereignis e-${zustand}`}>
      <span className="ereignis-knoten" aria-hidden="true">
        {zustand === 'laeuft' ? (
          <LoaderCircle size={12} className="dreht" />
        ) : zustand === 'ok' ? (
          <Check size={12} />
        ) : (
          <X size={12} />
        )}
      </span>
      <div className="ereignis-kopf">
        <span className="ereignis-name">{w.name}</span>
        <LaufzeitAnzeige start={w.start} ende={w.ende} />
      </div>
      <div className="ereignis-meta">
        {w.integration ? <span className="chip">{w.integration}</span> : <span className="chip leise">eingebaut</span>}
        <span className="ereignis-zeit">{zeitpunkt(w.start)}</span>
        <span className="sr-only">
          {zustand === 'laeuft' ? 'läuft' : zustand === 'ok' ? 'erfolgreich' : 'fehlgeschlagen'}
        </span>
      </div>
      {argText && (
        <details className="ereignis-details">
          <summary>
            <span className="details-label">Argumente</span>
            <span className="details-vorschau">{argumenteKurz(w.argumente, 48)}</span>
          </summary>
          <pre>{argText}</pre>
        </details>
      )}
      {w.ende !== null && ergText && (
        <details className={`ereignis-details ${w.ok ? '' : 'fehler'}`} open={!w.ok}>
          <summary>
            <span className="details-label">{w.ok ? 'Ergebnis' : 'Fehler'}</span>
            <span className="details-vorschau">{argumenteKurz(w.ergebnis, 48)}</span>
          </summary>
          <pre>{ergText}</pre>
        </details>
      )}
    </li>
  );
}

export function ActivityPanel() {
  const werkzeuge = useJarvis((s) => s.werkzeuge);
  const verarbeiten = useJarvis((s) => s.verarbeiten);
  const name = useName();
  const laufend = werkzeuge.filter((w) => w.ende === null).length;
  const liste = [...werkzeuge].reverse();

  return (
    <aside className="leiste leiste-rechts" aria-label="Aktivität">
      <div className="leiste-kopfzeile">
        <h2 className="leiste-titel">Aktivität</h2>
        <span className="leiste-zahl">{laufend > 0 ? `${laufend} laufen` : `${werkzeuge.length} Aufrufe`}</span>
        {werkzeuge.length > 0 && laufend === 0 && (
          <button className="text-knopf" onClick={() => verarbeiten({ typ: 'lokal_aktivitaet_leeren' })}>
            Leeren
          </button>
        )}
      </div>
      {liste.length === 0 ? (
        <div className="leer">
          <p>Hier erscheinen Werkzeugaufrufe, sobald {name} etwas für Sie erledigt.</p>
          <p className="gedaempft">Beispiel: „Wie wird das Wetter morgen in Berlin?“</p>
        </div>
      ) : (
        <ol className="zeitleiste" aria-live="polite">
          {liste.map((w) => (
            <Eintrag key={w.id} w={w} />
          ))}
        </ol>
      )}
    </aside>
  );
}
