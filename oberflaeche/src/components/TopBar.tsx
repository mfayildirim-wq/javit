import type { JSX } from 'react';
import { Command, LayoutGrid, MessageSquarePlus, Plug, Settings } from 'lucide-react';
import { useJarvis, useName, type Ansicht } from '../state/store';
import { neueUnterhaltung } from '../state/verbindung';

const TABS: { id: Ansicht; titel: string; icon: JSX.Element }[] = [
  { id: 'konsole', titel: 'Konsole', icon: <LayoutGrid size={17} aria-hidden="true" /> },
  { id: 'integrationen', titel: 'Integrationen', icon: <Plug size={17} aria-hidden="true" /> },
  { id: 'einstellungen', titel: 'Einstellungen', icon: <Settings size={17} aria-hidden="true" /> },
];

/** Marke (Symbol + Name) mit dem Titel der aktuellen Unterhaltung – oben im linken Bereich. */
export function Marke() {
  const name = useName();
  const ansicht = useJarvis((s) => s.ansicht);
  const unterhaltung = useJarvis((s) => s.unterhaltung);
  return (
    <div className="marke-block">
      <div className="marke" aria-label={name}>
        <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
          <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="1.2" strokeDasharray="6 2.4" />
          <circle cx="16" cy="16" r="7.5" fill="none" stroke="currentColor" strokeWidth="1" opacity=".55" />
          <circle cx="16" cy="16" r="3" fill="currentColor" />
        </svg>
        <span className="marke-wort">{name}</span>
      </div>
      {unterhaltung && ansicht === 'konsole' && (
        <span className="unterhaltung-titel" title="Aktuelle Unterhaltung">{unterhaltung.titel}</span>
      )}
    </div>
  );
}

/** Symbolleiste: Ansichten, neue Unterhaltung, Befehlspalette, Verbindungsstatus – oben im rechten Bereich
 * (auf schmalen Bildschirmen als Zeile über der Konsole). */
export function Werkzeugleiste({ mobil = false }: { mobil?: boolean }) {
  const ansicht = useJarvis((s) => s.ansicht);
  const setAnsicht = useJarvis((s) => s.setAnsicht);
  const setPalette = useJarvis((s) => s.setPalette);
  const verbindung = useJarvis((s) => s.verbindung);
  const name = useName();
  const mac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
  const verbText = verbindung === 'offen' ? 'Kern verbunden' : verbindung === 'verbinde' ? 'Verbinde …' : 'Kern getrennt';

  return (
    <div className={`werkzeugleiste ${mobil ? 'mobil' : ''}`} role="toolbar" aria-label="Ansichten und Befehle">
      {mobil && (
        <span className="marke marke-klein" aria-label={name}>
          <svg viewBox="0 0 32 32" width="20" height="20" aria-hidden="true">
            <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="1.2" strokeDasharray="6 2.4" />
            <circle cx="16" cy="16" r="3" fill="currentColor" />
          </svg>
        </span>
      )}
      <nav className="reiter reiter-icons" role="tablist" aria-label="Ansicht">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={ansicht === t.id}
            aria-label={t.titel}
            title={t.titel}
            className="reiter-knopf icon"
            onClick={() => setAnsicht(t.id)}
          >
            {t.icon}
          </button>
        ))}
      </nav>
      <button className="symbol-knopf" onClick={() => void neueUnterhaltung()} aria-label="Neue Unterhaltung" title="Neue Unterhaltung (Alt+N)">
        <MessageSquarePlus size={16} aria-hidden="true" />
      </button>
      <button className="symbol-knopf" onClick={() => setPalette(true)} aria-label="Befehlspalette öffnen" title={`Befehle (${mac ? '⌘' : 'Strg'} K)`}>
        <Command size={15} aria-hidden="true" />
      </button>
      <span className={`verbindung verbindung-${verbindung} nur-punkt`} role="status" aria-live="polite" title={verbText}>
        <span className="verbindung-punkt" aria-hidden="true" />
        <span className="sr-only">{verbText}</span>
      </span>
    </div>
  );
}

/** Rückwärtskompatibel: frühere Kopfzeile – jetzt nur noch die mobile Symbolleiste. */
export function TopBar() {
  return <Werkzeugleiste mobil />;
}
