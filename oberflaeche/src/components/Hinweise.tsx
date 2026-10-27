import { useEffect, useState } from 'react';
import { TriangleAlert, Unplug, X } from 'lucide-react';
import { useJarvis } from '../state/store';

/** Hinweis, wenn der Kern länger als ~1,5 s nicht erreichbar ist. */
export function VerbindungsHinweis() {
  const verbindung = useJarvis((s) => s.verbindung);
  const seit = useJarvis((s) => s.getrenntSeit);
  const versuche = useJarvis((s) => s.verbindungsVersuche);
  const [jetzt, setJetzt] = useState(() => Date.now());

  useEffect(() => {
    if (verbindung === 'offen') return;
    const t = setInterval(() => setJetzt(Date.now()), 500);
    return () => clearInterval(t);
  }, [verbindung]);

  if (verbindung === 'offen' || seit === null || jetzt - seit < 1500 || versuche === 0) return null;
  return (
    <div className="kern-weg" role="alert">
      <Unplug size={18} aria-hidden="true" />
      <div>
        <strong>Kern nicht erreichbar</strong>
        <span>
          Im Terminal <code>javit start</code> ausführen. Neuer Versuch läuft automatisch ({versuche}).
        </span>
      </div>
    </div>
  );
}

export function Hinweise() {
  const hinweise = useJarvis((s) => s.hinweise);
  const verarbeiten = useJarvis((s) => s.verarbeiten);

  useEffect(() => {
    if (hinweise.length === 0) return;
    const timer = hinweise.map((h) =>
      setTimeout(() => verarbeiten({ typ: 'lokal_hinweis_weg', id: h.id }), Math.max(0, h.zeit + 7000 - Date.now())),
    );
    return () => timer.forEach(clearTimeout);
  }, [hinweise, verarbeiten]);

  if (hinweise.length === 0) return null;
  return (
    <div className="hinweise" aria-live="assertive">
      {hinweise.map((h) => (
        <div key={h.id} className="hinweis" role="alert">
          <TriangleAlert size={16} aria-hidden="true" />
          <span>{h.text}</span>
          <button aria-label="Hinweis schließen" onClick={() => verarbeiten({ typ: 'lokal_hinweis_weg', id: h.id })}>
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
